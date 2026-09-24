"""The experiment result schema and the store that holds it.

Every **task-run** number in the paper (T1/T3, per condition) — preparation
code volume, the analytical result's digest for the equivalence gate, and T3's
join diagnostic — comes from one row of ``results/experiment_results``, so the
file has to be trustworthy on its own: a reader who never runs the pipeline sees
only this. Execution cost is not here; it comes from the timing protocol
(``scripts/_timing.py`` → ``results/timing_*``). RQ1's artifact-pair
measurements live in separate ``results/rq1_*.parquet`` tables (see the Storage
section below).

Two rules follow, and the schema exists to enforce them.

**A row must say which run produced it.** The identity fields — task, dataset,
condition, seed, source snapshot, pipeline version — are the key the contract
already defines as sufficient to replay a run. A row missing any of them is not
a weaker result, it is an unattributable one, so they are rejected rather than
stored as null.

**A metric that does not apply must be absent, not zero.** ``join_matching_rate``
belongs to the integration task (T3). Stored as ``0.0`` for T1 it would silently
enter a mean; stored as missing it cannot.
Every metric is therefore nullable, and validation distinguishes "not applicable
here" from "should have been measured and was not".

Missing-value rules
-------------------

==============  ======================================================
``identity``    always present and non-null; the row is meaningless
                without it
``measured``    non-null whenever ``status == "ok"``; a successful run
                that did not record it is a harness bug
``optional``    may be missing, meaning "not applicable to this task"
==============  ======================================================

A failed run is still recorded — ``status="failed"`` with whatever was measured
before it failed. Dropping failures would make the results file describe a more
successful experiment than the one that was run.

Storage
-------

``experiment_results.parquet`` is authoritative for **task runs**;
``experiment_results.csv`` is written beside it on every append so that the
committed results have a readable diff. RQ1 does not go through this store: it
measures an artifact pair rather than a run, and ``scripts/quality_spectrum.py``
writes its own ``rq1_*.parquet`` tables (the README's *Results* section lists
which file feeds which table). Both families are committed: they are what makes
the benchmark reproducible for a reader who does not rerun the pipeline.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from kpx.contract import CONDITIONS, Condition

Requirement = Literal["identity", "measured", "optional"]
Status = Literal["ok", "failed", "skipped"]

#: ``ok`` ran to completion; ``failed`` raised; ``skipped`` was not attempted
#: (a condition not defined for a task).
STATUSES: tuple[Status, ...] = ("ok", "failed", "skipped")

RESULTS_FILENAME = "experiment_results.parquet"


class ResultSchemaError(ValueError):
    """Raised when a result row does not satisfy the schema."""


@dataclass(frozen=True)
class Field:
    """One column of the result schema."""

    name: str
    dtype: str
    requirement: Requirement
    description: str
    minimum: float | None = None
    maximum: float | None = None


#: The schema, in the order columns are stored.
RESULT_SCHEMA: tuple[Field, ...] = (
    # -- identity: what run this row describes -----------------------------
    Field("run_id", "string", "identity", "unique id of this run"),
    Field("task", "string", "identity", "task01 | task03"),
    Field(
        "dataset", "string", "identity", "dataset(s) read, joined by '+' for multi-dataset tasks"
    ),
    Field("condition", "string", "identity", "bronze | silver | gold | monolithic"),
    Field("seed", "Int64", "identity", "0; both tasks are deterministic", minimum=0),
    Field("source_snapshot", "string", "identity", "snapshot_id the run consumed"),
    Field("pipeline_version", "string", "identity", "builder version that produced the layers"),
    Field("status", "string", "identity", "ok | failed | skipped"),
    # -- preparation code volume (RQ2) --------------------------------------
    Field("rows", "Int64", "measured", "rows in the prepared analysis input", minimum=0),
    Field("preprocessing_loc", "Int64", "measured", "LOC of prepare() and its helpers", minimum=0),
    Field("function_count", "Int64", "measured", "transformation functions used", minimum=0),
    Field(
        "transformation_steps",
        "Int64",
        "measured",
        "top-level recorded steps (diagnostic)",
        minimum=0,
    ),
    # -- equivalence gate ----------------------------------------------------
    Field("output_hash", "string", "measured", "digest of the analytical result"),
    # -- task diagnostic -----------------------------------------------------
    Field(
        "join_matching_rate",
        "Float64",
        "optional",
        "task03 only: matched join keys / total",
        minimum=0.0,
        maximum=1.0,
    ),
)

FIELDS: dict[str, Field] = {field.name: field for field in RESULT_SCHEMA}
COLUMNS: tuple[str, ...] = tuple(FIELDS)
IDENTITY_FIELDS: tuple[str, ...] = tuple(
    f.name for f in RESULT_SCHEMA if f.requirement == "identity"
)
MEASURED_FIELDS: tuple[str, ...] = tuple(
    f.name for f in RESULT_SCHEMA if f.requirement == "measured"
)


@dataclass(frozen=True)
class ResultRow:
    """One run's result.

    Optional metrics default to ``None``, which is stored as missing. A task
    with no join leaves ``join_matching_rate`` alone rather than passing ``0.0``.
    """

    run_id: str
    task: str
    dataset: str
    condition: Condition
    source_snapshot: str
    pipeline_version: str
    seed: int = 0
    status: Status = "ok"
    rows: int | None = None
    preprocessing_loc: int | None = None
    function_count: int | None = None
    transformation_steps: int | None = None
    output_hash: str | None = None
    join_matching_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def output_digest(frame: pd.DataFrame) -> str:
    """Digest an analytical result, for the equivalence gate across conditions.

    Serialized without the index, which is positional rather than part of the
    result, and without rounding: two conditions that agree only to 12
    significant digits have not produced the same result, and the gate exists to
    notice that.

    Comparable within one environment. The float repr pandas emits can change
    between pandas versions, so a hash is not a claim about other machines —
    ``pipeline_version`` and the lockfile are.
    """
    payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def empty_frame() -> pd.DataFrame:
    """An empty frame with the schema's columns and dtypes."""
    return pd.DataFrame({field.name: pd.Series(dtype=field.dtype) for field in RESULT_SCHEMA})


def validate(frame: pd.DataFrame) -> pd.DataFrame:
    """Check ``frame`` against the schema and return it normalized.

    Normalized means: schema column order, schema dtypes, optional columns that
    were absent added as missing. Anything the schema cannot vouch for raises
    :class:`ResultSchemaError` rather than being stored and discovered later by
    a figure that looks wrong.
    """
    unknown = [column for column in frame.columns if column not in FIELDS]
    if unknown:
        raise ResultSchemaError(
            f"unknown result column(s): {', '.join(sorted(unknown))}; "
            f"add them to RESULT_SCHEMA rather than widening the file in place"
        )

    absent_identity = [name for name in IDENTITY_FIELDS if name not in frame.columns]
    if absent_identity:
        raise ResultSchemaError(f"missing identity column(s): {', '.join(absent_identity)}")

    normalized = frame.reindex(columns=list(COLUMNS))
    try:
        normalized = normalized.astype({field.name: field.dtype for field in RESULT_SCHEMA})
    except (TypeError, ValueError) as error:
        raise ResultSchemaError(f"result values do not fit the schema's types: {error}") from error

    if normalized.empty:
        return normalized

    _check_identity(normalized)
    _check_domains(normalized)
    _check_bounds(normalized)
    _check_measured(normalized)
    return normalized


class ResultStore:
    """Appends, reads and queries experiment results.

    Every runner writes through this rather than to its own file, so that the
    results a figure reads are the results the experiment produced.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @property
    def csv_path(self) -> Path:
        """The diffable mirror written beside the parquet file."""
        return self.path.with_suffix(".csv")

    # -- reading -----------------------------------------------------------

    def load(self) -> pd.DataFrame:
        """Every recorded row, or an empty frame if nothing has been recorded."""
        if not self.path.exists():
            return empty_frame()
        return validate(pd.read_parquet(self.path))

    def query(
        self,
        *,
        task: str | None = None,
        condition: Condition | None = None,
        dataset: str | None = None,
        status: Status | None = "ok",
    ) -> pd.DataFrame:
        """Rows matching every filter given.

        ``status`` defaults to ``"ok"`` so that a failed run cannot quietly
        reach a table or a figure. Pass ``status=None`` to see everything,
        which is what a run log wants.
        """
        frame = self.load()
        filters = {"task": task, "condition": condition, "dataset": dataset, "status": status}
        for column, value in filters.items():
            if value is not None:
                frame = frame[frame[column] == value]
        return frame.reset_index(drop=True)

    def by_condition(self, metric: str, *, task: str | None = None) -> pd.DataFrame:
        """A task × condition table of ``metric``.

        Repeated runs are averaged, and conditions
        appear in Medallion order rather than alphabetically, so ``monolithic``
        reads as the baseline it is rather than sorting between gold and silver.
        """
        if metric not in FIELDS:
            raise ResultSchemaError(f"no such metric: {metric!r}")
        frame = self.query(task=task)
        if frame.empty:
            return pd.DataFrame(index=pd.Index([], name="task"), columns=list(CONDITIONS))
        table = frame.pivot_table(index="task", columns="condition", values=metric, aggfunc="mean")
        return table.reindex(columns=[c for c in CONDITIONS if c in table.columns])

    # -- writing -----------------------------------------------------------

    def append(self, row: ResultRow | Mapping[str, Any]) -> pd.DataFrame:
        """Record one run. Returns the stored frame."""
        return self.extend([row])

    def extend(self, rows: Iterable[ResultRow | Mapping[str, Any]]) -> pd.DataFrame:
        """Record several runs at once, validating them together.

        Validation happens before anything is written, so a bad row leaves the
        results file as it was rather than half-updated.
        """
        payload = [row.to_dict() if isinstance(row, ResultRow) else dict(row) for row in rows]
        if not payload:
            return self.load()

        incoming = validate(pd.DataFrame(payload))
        existing = self.load()
        # Concatenating an empty frame is deprecated in pandas and would drop
        # the extension dtypes the schema depends on.
        merged = incoming if existing.empty else pd.concat([existing, incoming], ignore_index=True)
        combined = validate(merged)
        self._write(combined)
        return combined

    def drop_task(self, task: str) -> None:
        """Remove one task's rows so a fresh run of it can be recorded.

        Every task writes to the same file, so deleting the file to start over
        would also delete the other tasks' results.
        """
        if not self.path.exists():
            return
        frame = self.load()
        self._write(frame[frame["task"] != task].reset_index(drop=True))

    def _write(self, frame: pd.DataFrame) -> None:
        """Write both files, each replaced atomically.

        A run that dies mid-write must not leave a truncated results file: the
        experiment would have to be rerun to find out what was lost.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._replace(self.path, lambda target: frame.to_parquet(target, index=False))
        self._replace(
            self.csv_path,
            lambda target: frame.to_csv(target, index=False, lineterminator="\n"),
        )

    @staticmethod
    def _replace(target: Path, write: Any) -> None:
        temporary = target.with_name(f"{target.name}.tmp")
        write(temporary)
        os.replace(temporary, target)


def default_store(path: Path | str | None = None) -> ResultStore:
    """The store at ``experiments/results`` unless told otherwise."""
    if path is not None:
        return ResultStore(path)
    return ResultStore(Path(__file__).resolve().parents[2] / "results" / RESULTS_FILENAME)


# -- internals -------------------------------------------------------------


def _check_identity(frame: pd.DataFrame) -> None:
    for name in IDENTITY_FIELDS:
        null = frame[name].isna()
        if bool(null.any()):
            raise ResultSchemaError(
                f"{name} is null in {int(null.sum())} row(s); a result that cannot be "
                f"attributed to a run cannot be published"
            )
    duplicated = frame["run_id"][frame["run_id"].duplicated()]
    if not duplicated.empty:
        raise ResultSchemaError(
            f"duplicate run_id(s): {', '.join(sorted(set(duplicated)))}; "
            f"repeated builds of the same run need distinct ids"
        )


def _check_domains(frame: pd.DataFrame) -> None:
    _check_membership(frame, "condition", CONDITIONS)
    _check_membership(frame, "status", STATUSES)


def _check_membership(frame: pd.DataFrame, column: str, allowed: Sequence[str]) -> None:
    unexpected = set(frame[column].dropna()) - set(allowed)
    if unexpected:
        raise ResultSchemaError(
            f"unknown {column}: {', '.join(sorted(unexpected))} (expected {', '.join(allowed)})"
        )


def _check_bounds(frame: pd.DataFrame) -> None:
    for field in RESULT_SCHEMA:
        if field.minimum is None and field.maximum is None:
            continue
        values = frame[field.name].dropna()
        if field.minimum is not None and bool((values < field.minimum).any()):
            raise ResultSchemaError(f"{field.name} below its minimum of {field.minimum}")
        if field.maximum is not None and bool((values > field.maximum).any()):
            raise ResultSchemaError(f"{field.name} above its maximum of {field.maximum}")


def _check_measured(frame: pd.DataFrame) -> None:
    succeeded = frame["status"] == "ok"
    if not bool(succeeded.any()):
        return
    for name in MEASURED_FIELDS:
        missing = succeeded & frame[name].isna()
        if bool(missing.any()):
            raise ResultSchemaError(
                f"{name} is missing in {int(missing.sum())} successful run(s); "
                f"a run that completed must report what it cost"
            )
