"""Comparison against a published statistic, for RQ3/H3.

T1 and T3 do not have a ground truth. What they have is an **External Reference
Statistic** — a figure a public body publishes for the same region and month,
built from a different population by a different method. Agreement is evidence
that the pipeline computed what it claimed to; disagreement is not proof that it
did not. Issue #6 fixes that naming and the reason for it, and nothing here
calls the reference a ground truth.

Three metrics, because a reference supports different claims depending on what
it publishes:

=========================  ====================================================
``apd``                    absolute percentage deviation of the level, meaningful
                           only when the reference publishes absolute values
``trend_correlation``      Pearson correlation of the *changes*, which is what a
                           trend claim rests on
``direction_agreement``    share of periods where both moved the same way
=========================  ====================================================

Four ways this comparison could mislead, and what stops each
------------------------------------------------------------

**Computing a deviation against an index.** An index is a relative value on its
own base — 2021.6 = 100 — so the distance between it and a price in 만원/㎡ is
arithmetic without meaning. ``kind="index"`` leaves :attr:`apd` as ``None``
rather than returning a number that would look like a measurement.

**Correlating levels instead of changes.** Two slowly moving series of the same
quantity correlate at r ≈ 0.99 whatever their trends do, because both are
dominated by their own autocorrelation. Correlating the period-over-period
change is the comparison a trend claim actually needs, so that is what
:attr:`trend_correlation` is.

**Charging a methodology break to the pipeline.** A published series changes
when its sample is redesigned, and ours does not, because ours reads the whole
transaction record. A change spanning such a break is an artifact of the
reference. ``excluded_periods`` drops those *changes* — and only the changes;
the levels on either side are still compared, because a level is a statement
about one month and is unaffected by what happened between two.

**Rounding the pipeline against a coarser reference.** A published figure at one
decimal place is flat in a month when ours moved by 0.02. Counting that as a
disagreement would measure publication rounding, and it does not: a side that
did not move has no direction, so the pair is left out of
:attr:`direction_agreement` rather than scored against us. ``resolution`` is
therefore a diagnostic and not a filter — :attr:`below_resolution` reports how
many of our changes were finer than the reference could have printed, which is
what tells a reader whether a high agreement was earned over real movement.

Alignment is asserted, not assumed. Keys on one side and not the other are
reported rather than dropped by an inner join, because a silently shrinking
overlap is how a comparison ends up describing three districts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

__all__ = [
    "REFERENCE_KINDS",
    "ReferenceError",
    "ReferenceReport",
    "ReferenceSpec",
    "compare_to_reference",
]

#: ``level`` publishes absolute values (건수, %, 만원/㎡); ``index`` publishes a
#: relative value on its own base, against which a deviation has no meaning.
ReferenceKind = Literal["level", "index"]
REFERENCE_KINDS: tuple[ReferenceKind, ...] = ("level", "index")

#: Columns a comparison frame must carry.
REQUIRED_COLUMNS: tuple[str, ...] = ("region", "period", "value")


class ReferenceError(ValueError):
    """Raised when a reference comparison is malformed or not defensible."""


@dataclass(frozen=True)
class ReferenceSpec:
    """How one published statistic may be compared against.

    ``resolution`` is the reference's own publication precision — 0.1 for a
    percentage printed to one decimal. It is not a tolerance we chose and it
    filters nothing; it is reported so a reader can see how much of our movement
    was finer than the published figure could express.

    ``excluded_periods`` names periods whose *incoming change* is not
    attributable to either series, such as the month a sample was redesigned.
    Levels at those periods are still compared.
    """

    kind: ReferenceKind = "level"
    resolution: float = 0.0
    excluded_periods: frozenset[str] = frozenset()
    min_overlap: int = 12
    source: str = ""

    def __post_init__(self) -> None:
        if self.kind not in REFERENCE_KINDS:
            raise ReferenceError(f"unknown reference kind: {self.kind!r}")
        if self.resolution < 0:
            raise ReferenceError("resolution cannot be negative")
        if self.min_overlap < 2:
            raise ReferenceError(
                "min_overlap below 2 leaves no change to correlate; a comparison "
                "over one period is not a trend"
            )


@dataclass(frozen=True)
class ReferenceReport:
    """What a comparison found, and what it was computed over.

    The counts are not diagnostics kept to one side. A correlation over eleven
    aligned months and one over six hundred are different claims, and Table 5
    has to be able to say which one it is printing.
    """

    task: str
    kind: ReferenceKind
    aligned: int
    changes_compared: int
    apd: float | None = None
    trend_correlation: float | None = None
    direction_agreement: float | None = None
    unmatched_pipeline: tuple[str, ...] = ()
    unmatched_reference: tuple[str, ...] = ()
    excluded_changes: int = 0
    below_resolution: int = 0
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float | None]:
        """The result-schema fields this measurement fills in.

        A metric that does not apply stays ``None``. Returning ``0.0`` for an
        APD that was never defined would enter a mean as perfect agreement.
        """
        return {
            "reference_apd": self.apd,
            "reference_trend_correlation": self.trend_correlation,
            "reference_direction_agreement": self.direction_agreement,
        }


def compare_to_reference(
    pipeline: pd.DataFrame,
    reference: pd.DataFrame,
    spec: ReferenceSpec,
    *,
    task: str,
) -> ReferenceReport:
    """Compare a pipeline aggregate against a published statistic.

    Both frames are long: ``region``, ``period``, ``value``. ``period`` is an
    orderable label (``"2024-01"``), because the change metrics need the series
    in time order and a string month sorts correctly only when zero-padded.
    """
    left = _validate(pipeline, "pipeline")
    right = _validate(reference, "reference")

    merged = left.merge(right, on=["region", "period"], how="inner", suffixes=("_p", "_r"))
    if len(merged) < spec.min_overlap:
        raise ReferenceError(
            f"{task}: only {len(merged)} aligned (region, period) pairs, below the "
            f"{spec.min_overlap} this comparison requires; a metric computed over "
            f"fewer would describe the overlap, not the agreement"
        )

    changes = _changes(merged, spec)

    return ReferenceReport(
        task=task,
        kind=spec.kind,
        aligned=len(merged),
        changes_compared=len(changes),
        apd=_apd(merged, spec),
        trend_correlation=_trend_correlation(changes),
        direction_agreement=_direction_agreement(changes),
        unmatched_pipeline=_unmatched(left, right),
        unmatched_reference=_unmatched(right, left),
        excluded_changes=_excluded_count(merged, spec),
        below_resolution=_below_resolution(changes, spec),
        notes={"source": spec.source} if spec.source else {},
    )


# -- the metrics ------------------------------------------------------------


def _apd(merged: pd.DataFrame, spec: ReferenceSpec) -> float | None:
    """Mean absolute percentage deviation of the level.

    ``None`` for an index: the reference's 100 and our 만원/㎡ are not the same
    quantity, and a percentage between them would be arithmetic on unlike units.
    """
    if spec.kind == "index":
        return None

    usable = merged[merged["value_r"] != 0]
    if usable.empty:
        return None
    deviation = (usable["value_p"] - usable["value_r"]).abs() / usable["value_r"].abs()
    return float(deviation.mean() * 100)


def _trend_correlation(changes: pd.DataFrame) -> float | None:
    """Pearson correlation of the period-over-period changes.

    Undefined, and so ``None``, when either side never moved: a constant series
    has zero variance, and ``numpy`` would return ``nan`` which pandas would
    later carry into a mean as if it were a number.
    """
    if len(changes) < 2:
        return None
    left, right = changes["change_p"].to_numpy(), changes["change_r"].to_numpy()
    if np.std(left) == 0 or np.std(right) == 0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return None if math.isnan(value) else value


def _direction_agreement(changes: pd.DataFrame) -> float | None:
    """Share of changes where both series moved the same way.

    A side that did not move has no direction, so the pair is left out rather
    than scored. This is also what keeps publication rounding from being read as
    disagreement: a reference that rounds a small true move to no move records a
    change of zero, and a zero has no direction to disagree with.
    """
    directional = changes[(changes["change_p"] != 0) & (changes["change_r"] != 0)]
    if directional.empty:
        return None
    agree = np.sign(directional["change_p"]) == np.sign(directional["change_r"])
    return float(agree.mean())


# -- preparation ------------------------------------------------------------


def _validate(frame: pd.DataFrame, side: str) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ReferenceError(f"{side} frame is missing {', '.join(missing)}")
    if frame.empty:
        raise ReferenceError(f"{side} frame is empty; there is nothing to compare")

    out = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    out["region"] = out["region"].astype("string")
    out["period"] = out["period"].astype("string")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")

    duplicated = out.duplicated(subset=["region", "period"])
    if duplicated.any():
        example = out[duplicated].iloc[0]
        raise ReferenceError(
            f"{side} frame has more than one value for "
            f"({example['region']}, {example['period']}); which one is compared "
            f"would decide the result"
        )
    return out.dropna(subset=["value"])


def _changes(merged: pd.DataFrame, spec: ReferenceSpec) -> pd.DataFrame:
    """Period-over-period change on both sides, within each region.

    Changes are taken per region and in period order, so a region's first period
    contributes no change and one region's series never runs into the next.
    """
    ordered = merged.sort_values(["region", "period"])
    grouped = ordered.groupby("region", sort=False)
    ordered = ordered.assign(
        change_p=grouped["value_p"].diff(),
        change_r=grouped["value_r"].diff(),
    )
    ordered = ordered.dropna(subset=["change_p", "change_r"])
    return ordered[~ordered["period"].isin(spec.excluded_periods)]


def _excluded_count(merged: pd.DataFrame, spec: ReferenceSpec) -> int:
    if not spec.excluded_periods:
        return 0
    ordered = merged.sort_values(["region", "period"])
    grouped = ordered.groupby("region", sort=False)
    has_change = grouped["value_p"].diff().notna() & grouped["value_r"].diff().notna()
    return int((has_change & ordered["period"].isin(spec.excluded_periods)).sum())


def _below_resolution(changes: pd.DataFrame, spec: ReferenceSpec) -> int:
    """Our changes finer than the reference could have printed.

    Diagnostic, not a filter. A direction agreement computed mostly over months
    where the reference could not move is a weaker claim than the same number
    computed over months where it did.
    """
    if changes.empty or spec.resolution <= 0:
        return 0
    return int((changes["change_p"].abs() < spec.resolution).sum())


def _unmatched(left: pd.DataFrame, right: pd.DataFrame) -> tuple[str, ...]:
    """Regions present on one side and absent from the other, sorted."""
    return tuple(sorted(set(left["region"].dropna()) - set(right["region"].dropna())))
