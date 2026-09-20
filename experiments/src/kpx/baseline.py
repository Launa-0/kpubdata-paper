"""The monolithic baseline convention, and the checks that enforce it.

``monolithic`` is the control condition for RQ2 and RQ4. The claim it supports
is that a *structured, reusable* pipeline costs less to analyse against than a
*single-pass* transformation — not that Medallion cleans data better. Those are
different claims, and only the first one is being made.

That distinction is fragile in exactly one direction. A baseline written
carelessly — or written after the Medallion path, by someone who already knows
which way the result is supposed to come out — manufactures the finding. This is
the **Baseline Bias** threat, and prose promising that it did not happen is worth
very little. So the convention is enforced by two mechanical checks instead:

**Same output.** The baseline reproduces the whole pipeline in one pass, so it
must arrive at the same :class:`~kpx.contract.AnalysisInput` as the full
Medallion path. :func:`check_baseline_equivalence` runs both and compares.
A baseline that drops rows, rounds differently, or joins on a weaker key is a
broken baseline, not a slower one.

**Same transformation code.** The baseline *imports* the task's transformation
helpers rather than reimplementing them. :func:`assert_reuses_transforms` fails
if the baseline module defines a function the shared module already exports, so
"the baseline happened to parse prices a dumber way" cannot survive review.

Reuse is a deliberate choice, and it costs something: it makes the baseline
slightly *more* favourable than a realistic one-off script, because a real
analyst writing a monolithic pipeline would not have a tested helper module to
import. The alternative — inlining equivalent logic — would leave every
difference in the numbers arguable. We take the conservative error: the baseline
is handicapped in the direction that weakens our own hypothesis, and RQ2 is
measured on the *structure* of the preparation code, which reuse does not
flatter. `docs/monolithic-baseline.md` records the rationale in full.

Why the check is applied to ``monolithic`` alone: ``bronze``, ``silver`` and
``gold`` may legitimately end up with different prepared frames, because the
layers differ in data quality and that difference is precisely what RQ3
measures. Forcing all four conditions to agree would delete the H3 signal.
Only the baseline is required to match, because only the baseline claims to be
doing the same work by another route.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Sequence
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_string_dtype,
)

from kpx.contract import Condition, ConditionRunner, RunContext

#: The Medallion condition a baseline is compared against. ``monolithic`` runs
#: Source → clean → normalize → join → aggregate in one pass, which is the whole
#: pipeline — so its counterpart is the end of the Medallion path, not a stage
#: partway along it.
REFERENCE_CONDITION: Condition = "gold"

#: How many differing rows to quote in a report. Enough to debug from, few
#: enough to paste into an issue.
SAMPLE_ROWS = 3


class BaselineBiasError(AssertionError):
    """Raised when a baseline violates the equal-semantics convention.

    An :class:`AssertionError` because it is raised from conformance tests, and
    a failed baseline invalidates the comparison rather than merely reporting a
    worse number.
    """


@dataclass(frozen=True)
class Difference:
    """One way in which a baseline's prepared frame differs from the reference.

    ``kind`` is one of ``columns``, ``row_count``, ``dtype``, ``values`` or
    ``ordering``; ``column`` is set for the per-column kinds.
    """

    kind: str
    detail: str
    column: str | None = None

    def __str__(self) -> str:
        where = f" [{self.column}]" if self.column else ""
        return f"{self.kind}{where}: {self.detail}"


@dataclass(frozen=True)
class EquivalenceReport:
    """The outcome of comparing a baseline against the Medallion path."""

    task: str
    reference: Condition
    baseline: Condition
    reference_rows: int
    baseline_rows: int
    differences: tuple[Difference, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.differences

    def raise_for_status(self) -> None:
        """Raise :class:`BaselineBiasError` unless the two frames agree."""
        if not self.ok:
            raise BaselineBiasError(str(self))

    def __str__(self) -> str:
        head = (
            f"{self.task}: {self.baseline} vs {self.reference} "
            f"({self.baseline_rows:,} vs {self.reference_rows:,} rows)"
        )
        if self.ok:
            return f"{head} — equivalent"
        body = "\n".join(f"  - {difference}" for difference in self.differences)
        return f"{head} — {len(self.differences)} difference(s)\n{body}"


def compare_frames(
    reference: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    key: Sequence[str] = (),
    rtol: float = 0.0,
    atol: float = 0.0,
) -> list[Difference]:
    """Compare two prepared frames under the equal-semantics convention.

    Column order and row order are implementation detail — the analysis reads
    columns by name — so both are normalized away before comparing. Everything
    that survives that normalization is a real disagreement.

    ``key`` names the columns that identify a row. Pass it whenever the frame
    has one: sorting by an explicit key gives a stable, readable diff, and it
    catches duplicated keys that a whole-row sort would silently align. Without
    a key the rows are sorted by their full contents.

    ``rtol``/``atol`` default to exact equality. A task that relaxes them has to
    say why in the paper: the only defensible reason is that an aggregation
    legitimately sums in a different order, and the tolerance must be far below
    the effect being reported.
    """
    differences: list[Difference] = []

    missing = [c for c in reference.columns if c not in baseline.columns]
    extra = [c for c in baseline.columns if c not in reference.columns]
    if missing:
        differences.append(Difference("columns", f"baseline is missing {', '.join(missing)}"))
    if extra:
        differences.append(Difference("columns", f"baseline adds {', '.join(extra)}"))

    common = [c for c in reference.columns if c in baseline.columns]
    if not common:
        return differences

    if len(reference) != len(baseline):
        differences.append(
            Difference("row_count", f"{len(baseline):,} rows, reference has {len(reference):,}")
        )
        return differences

    missing_key = [c for c in key if c not in common]
    if missing_key:
        differences.append(
            Difference(
                "columns", f"key column(s) absent from both frames: {', '.join(missing_key)}"
            )
        )
        return differences

    sort_by = list(key) if key else common
    left = _normalize(reference[common], sort_by)
    right = _normalize(baseline[common], sort_by)

    if key:
        duplicated = int(left.duplicated(subset=list(key)).sum())
        if duplicated:
            differences.append(
                Difference("ordering", f"{duplicated:,} duplicate key(s); rows cannot be aligned")
            )
            return differences

    for column in common:
        difference = _compare_column(left[column], right[column], column, rtol=rtol, atol=atol)
        if difference is not None:
            differences.append(difference)

    return differences


def check_baseline_equivalence(
    reference: ConditionRunner,
    baseline: ConditionRunner,
    ctx: RunContext,
    *,
    key: Sequence[str] = (),
    rtol: float = 0.0,
    atol: float = 0.0,
) -> EquivalenceReport:
    """Run both conditions on the same context and compare what they prepared.

    ``ctx`` is a template: each runner is given a copy carrying its own
    condition, so both read the layer they are supposed to read from the same
    snapshot at the same pipeline version. Neither is handed an input the other
    did not have.

    Every task is required to call this from a test. See
    ``docs/monolithic-baseline.md``.
    """
    if reference.TASK != baseline.TASK:
        raise ValueError(
            f"cannot compare runners from different tasks: {reference.TASK!r} and {baseline.TASK!r}"
        )

    prepared_reference = reference.prepare(replace(ctx, condition=reference.CONDITION))
    prepared_baseline = baseline.prepare(replace(ctx, condition=baseline.CONDITION))

    return EquivalenceReport(
        task=reference.TASK,
        reference=reference.CONDITION,
        baseline=baseline.CONDITION,
        reference_rows=len(prepared_reference.frame),
        baseline_rows=len(prepared_baseline.frame),
        differences=tuple(
            compare_frames(
                prepared_reference.frame,
                prepared_baseline.frame,
                key=key,
                rtol=rtol,
                atol=atol,
            )
        ),
    )


def redefined_transforms(
    baseline_module: ModuleType, transforms_module: ModuleType
) -> tuple[str, ...]:
    """Transformation helpers the baseline reimplements instead of importing.

    A monolithic runner is free to define its own orchestration helpers — that
    is its preparation cost, and RQ2 is entitled to count it. What it may not do
    is define its own ``parse_price`` next to the shared one, because then the
    two paths no longer have the same transformation semantics and any
    difference in the numbers is unattributable.
    """
    shared = {
        name
        for name, value in vars(transforms_module).items()
        if not name.startswith("_")
        and callable(value)
        and getattr(value, "__module__", None) == transforms_module.__name__
    }
    tree = ast.parse(inspect.getsource(baseline_module))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    return tuple(sorted(shared & defined))


def assert_reuses_transforms(baseline_module: ModuleType, transforms_module: ModuleType) -> None:
    """Fail if ``baseline_module`` redefines any shared transformation helper."""
    redefined = redefined_transforms(baseline_module, transforms_module)
    if redefined:
        raise BaselineBiasError(
            f"{baseline_module.__name__} redefines {', '.join(redefined)} instead of importing "
            f"from {transforms_module.__name__}; the baseline must use the same transformation "
            f"semantics as the Medallion path"
        )


# -- internals -------------------------------------------------------------


def _normalize(frame: pd.DataFrame, sort_by: Sequence[str]) -> pd.DataFrame:
    """Sort rows and discard the index, so only contents are compared."""
    return frame.sort_values(list(sort_by), kind="stable").reset_index(drop=True)


def _dtype_kind(series: pd.Series[Any]) -> str:
    """Classify a column by what it means rather than by how it is stored."""
    if is_bool_dtype(series):
        return "boolean"
    if is_numeric_dtype(series):
        return "numeric"
    if is_datetime64_any_dtype(series):
        return "datetime"
    if is_string_dtype(series):
        return "string"
    return str(series.dtype)


def _compare_column(
    reference: pd.Series[Any],
    baseline: pd.Series[Any],
    column: str,
    *,
    rtol: float,
    atol: float,
) -> Difference | None:
    # Storage is not semantics. int64 against float64, or `str` against
    # `object`, is the same quantity held two ways — which of the two a column
    # ends up with depends on the pandas version and on which call produced it,
    # not on what the pipeline decided. A datetime against a string is a real
    # difference, so dtypes are compared by kind rather than exactly.
    reference_kind = _dtype_kind(reference)
    baseline_kind = _dtype_kind(baseline)
    if reference_kind != baseline_kind:
        return Difference(
            "dtype", f"{baseline.dtype}, reference has {reference.dtype}", column=column
        )

    if reference_kind == "numeric":
        unequal = ~np.isclose(
            reference.to_numpy(dtype="float64"),
            baseline.to_numpy(dtype="float64"),
            rtol=rtol,
            atol=atol,
            equal_nan=True,
        )
    else:
        both_missing = reference.isna().to_numpy() & baseline.isna().to_numpy()
        unequal = (reference.to_numpy() != baseline.to_numpy()) & ~both_missing

    count = int(unequal.sum())
    if not count:
        return None

    rows = np.flatnonzero(unequal)[:SAMPLE_ROWS]
    sample = ", ".join(
        f"row {row}: {baseline.iloc[row]!r} != {reference.iloc[row]!r}" for row in rows
    )
    return Difference("values", f"{count:,} of {len(reference):,} differ ({sample})", column=column)
