"""Source evolution stability for RQ4/H4: does the contract survive new data?

R1 asks whether the same source rebuilds to the same bytes. R2 asks a different
question — when the upstream source grows or changes, does the pipeline still
produce what it promised? **Hash equality is not expected here.** The source
changed, so the output must differ; what must not differ is the contract.

What counts as breakage, and what does not
------------------------------------------

**A column that appears is not breakage.** Public APIs add fields over time. A
pipeline that fails because the source gained a column it never asked about is
brittle in a way that has nothing to do with the layer it produces.

**A column that disappears, or changes type, is breakage.** Downstream analysis
declared it. Silently producing a table without it moves the failure to whoever
reads the table next.

**Rows that vanish are breakage too, and the quiet kind** — the build reports
success. A build whose output is empty is counted as a pipeline breakage rather
than a 100% row loss, because "the pipeline ran and produced nothing" is a
different failure from "the pipeline dropped some rows".

The reference for every comparison is the **first successful** build. A failed
build has no schema, and letting it set the baseline would make every later
build look compatible with nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

Schema = tuple[tuple[str, str], ...]

TABLE_COLUMNS = (
    "Snapshot",
    "Status",
    "Input rows",
    "Output rows",
    "Row loss",
    "Schema",
)


class StabilityError(RuntimeError):
    """Raised when stability is asked of builds that cannot answer."""


@dataclass(frozen=True)
class BuildObservation:
    """One build of one snapshot, under the same pipeline version as the others."""

    snapshot_id: str
    status: str
    input_rows: int
    output_rows: int
    schema: Schema | None

    @property
    def succeeded(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class SchemaBreakage:
    snapshot_id: str
    missing: tuple[str, ...]
    changed: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class RowLoss:
    snapshot_id: str
    input_rows: int
    output_rows: int

    @property
    def lost(self) -> int:
        return self.input_rows - self.output_rows

    @property
    def rate(self) -> float:
        return self.lost / self.input_rows if self.input_rows else 0.0


@dataclass(frozen=True)
class PipelineBreakage:
    snapshot_id: str
    reason: str


@dataclass(frozen=True)
class StabilityReport:
    builds: int
    successes: int
    schema_breakages: tuple[SchemaBreakage, ...]
    row_losses: tuple[RowLoss, ...]
    pipeline_breakages: tuple[PipelineBreakage, ...]

    @property
    def build_success_rate(self) -> float:
        return self.successes / self.builds

    @property
    def schema_compatibility(self) -> float:
        """Share of successful builds whose schema still honours the contract."""
        if not self.successes:
            return 0.0
        return 1 - len(self.schema_breakages) / self.successes

    def to_dict(self) -> dict[str, Any]:
        return {
            "builds": self.builds,
            "successes": self.successes,
            "build_success_rate": self.build_success_rate,
            "schema_compatibility": self.schema_compatibility,
            "schema_breakages": len(self.schema_breakages),
            "row_losses": len(self.row_losses),
            "pipeline_breakages": len(self.pipeline_breakages),
        }


def _compare_schema(reference: Schema, observation: BuildObservation) -> SchemaBreakage | None:
    schema = dict(observation.schema or ())
    missing = tuple(name for name, _ in reference if name not in schema)
    changed = tuple(
        (name, dtype, schema[name])
        for name, dtype in reference
        if name in schema and schema[name] != dtype
    )
    if not missing and not changed:
        return None
    return SchemaBreakage(observation.snapshot_id, missing, changed)


def measure_stability(observations: Sequence[BuildObservation]) -> StabilityReport:
    """Summarize builds of the same pipeline against evolving snapshots."""
    if not observations:
        raise StabilityError("no builds to measure")

    successful = [o for o in observations if o.succeeded]
    reference = next((o.schema for o in successful if o.schema), None)

    schema_breakages: list[SchemaBreakage] = []
    row_losses: list[RowLoss] = []
    pipeline_breakages = [
        PipelineBreakage(o.snapshot_id, f"build {o.status}")
        for o in observations
        if not o.succeeded
    ]

    for observation in successful:
        if observation.output_rows == 0:
            pipeline_breakages.append(
                PipelineBreakage(observation.snapshot_id, "build produced no rows")
            )
            continue
        if reference is not None:
            breakage = _compare_schema(reference, observation)
            if breakage is not None:
                schema_breakages.append(breakage)
        if observation.output_rows < observation.input_rows:
            row_losses.append(
                RowLoss(observation.snapshot_id, observation.input_rows, observation.output_rows)
            )

    return StabilityReport(
        builds=len(observations),
        successes=len(successful),
        schema_breakages=tuple(schema_breakages),
        row_losses=tuple(row_losses),
        pipeline_breakages=tuple(pipeline_breakages),
    )


def table_stability(observations: Sequence[BuildObservation]) -> pd.DataFrame:
    """Per-snapshot detail behind :func:`measure_stability`.

    A breaking schema names the columns it broke on. "incompatible" alone sends
    the reader back to the logs, which is where a finding goes to die.
    """
    report = measure_stability(observations)
    breakages = {b.snapshot_id: b for b in report.schema_breakages}

    rows = []
    for observation in observations:
        breakage = breakages.get(observation.snapshot_id)
        if breakage is None:
            schema = "compatible" if observation.succeeded else "—"
        else:
            parts = [f"-{name}" for name in breakage.missing]
            parts += [f"{name}: {was}→{now}" for name, was, now in breakage.changed]
            schema = ", ".join(parts)
        lost = observation.input_rows - observation.output_rows
        rows.append(
            {
                "Snapshot": observation.snapshot_id,
                "Status": observation.status,
                "Input rows": observation.input_rows,
                "Output rows": observation.output_rows,
                "Row loss": f"{lost:,}" if lost > 0 else "0",
                "Schema": schema,
            }
        )
    return pd.DataFrame(rows, columns=list(TABLE_COLUMNS))
