r"""Data quality for RQ1/H1: what standardization actually improves.

H1 predicts that Silver improves type consistency, code validity and schema
conformance over Bronze, and reduces missing values, duplicates and parsing
failures. Six metrics, one interface applied unchanged to both layers.

The hard part is not computing rates. It is making sure the rates compare the
same thing, because Bronze and Silver do not even use the same column names —
Bronze has ``거래금액`` holding ``"120,000"``, Silver has ``price_krw`` holding
``1200000000``. A :class:`QualitySpec` states, in one layer's vocabulary, which
column plays which role and how a value in it is to be read. Everything else is
computed identically for both.

Two ways this measurement could manufacture H1, and what stops each
---------------------------------------------------------------------

**Reading Bronze naively.** ``pd.to_numeric("120,000")`` fails, and if that
counted as a parsing failure, H1 would be measuring how hostile we chose to be
to Bronze rather than anything about the data. So a Bronze spec passes the same
interpretation the Silver *build* declares — ``kpx.metrics.roles.INTERPRETERS``,
keyed by the cast in the contract — and Bronze is credited with every value the
build could read. What remains a failure is a value the pipeline could not parse
either.

**Improving a rate by dropping rows.** A Silver build that deletes rows with
nulls reports a better missing rate for a reason that has nothing to do with
standardization. Two things make that visible rather than invisible:

* missing rate is reported **per required column** as well as overall, so a
  column that improved by disappearing does not hide inside an average, and
* :func:`table2` prints the **row count of each layer in the same table**, so a
  reduction bought by dropping rows is visible at the same glance as the
  reduction.

The metrics
-----------

=========================  ====================================================
``missing_rate``           missing cells / cells, over required columns
``duplicate_rate``         duplicate records / records
``type_consistency``       values that read as their declared type / values
``schema_conformance``     records where every required column is present,
                           readable and within its declared bounds
``code_validity``          code values found in the reference code list
``parsing_failure_rate``   records with at least one present-but-unreadable
                           required value
=========================  ====================================================

Comparable and diagnostic
-------------------------

All six are measured and all six are stored. They are not all evidence for H1.

A metric is **comparable** when a :class:`QualitySpec` states the same role on
both sides, so the two layers measure the same construct even though Bronze
calls it ``대여소번호`` and Silver calls it ``station_code``. Those carry the
layer-to-layer comparison.

``duplicate_rate`` is **diagnostic**, for a subtler reason. Given role-projected
frames it is computed over the same roles on both sides, so the comparison space
is no longer the problem. What remains is that it compares *stored values*:
without a key it is exact-row equality over the frame, not over what
``ColumnSpec.interpret`` made of it. Two records that mean the same thing but
spell a missing gender ``\N`` in one row and ``""`` in the other are unequal in
Bronze and equal in Silver, so canonicalization **raises** the rate by removing
the difference that kept them apart.

A rise is therefore not a regression and a fall is not an improvement; both are
questions. The number stays in the result schema because it is a real
observation that found real things — every change examined so far was the
source's own duplicates becoming visible — but each one is settled by tracing
the record pairs behind it, not by subtracting two layers.

Missing and unreadable are counted separately throughout: an absent value and a
corrupt one are different defects, and collapsing them would let a layer trade
one for the other silently.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from kpx.contract import Layer

Kind = Literal["numeric", "date", "code", "text"]

#: Kinds whose values are expected to read as a specific type. ``text`` is
#: excluded: a string that is a string is not evidence of anything.
TYPED_KINDS: frozenset[str] = frozenset({"numeric", "date", "code"})

#: Metrics where a larger number is better, which decides the sign of Table 2's
#: improvement column.
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {"type_consistency", "schema_conformance", "code_validity"}
)

#: The layer-to-layer comparison. Each one is stated as a role that both layers
#: fill, so the two sides measure the same construct under different column
#: names. ``code_validity`` belongs here whenever a reference code list exists;
#: where none does it is simply ``None`` and drops out of the table.
H1_COMPARABLE_METRICS: tuple[str, ...] = (
    "type_consistency",
    "missing_rate",
    "schema_conformance",
    "code_validity",
    "parsing_failure_rate",
)

#: Measured and stored, but not evidence for H1 on its own. See the module
#: docstring: it compares stored values rather than interpreted ones, so a
#: delta here is something to explain rather than something that settles
#: anything.
H1_DIAGNOSTIC_METRICS: tuple[str, ...] = ("duplicate_rate",)

#: Everything a :class:`QualityReport` can answer for. The result schema keeps
#: all of it — separating presentation from storage is the point.
TABLE2_METRICS: tuple[str, ...] = H1_COMPARABLE_METRICS + H1_DIAGNOSTIC_METRICS


class QualityError(ValueError):
    """Raised when a quality measurement cannot be made as specified."""


@dataclass(frozen=True)
class ColumnSpec:
    r"""One column of one layer, and how to read it.

    ``interpret`` turns a stored value into its canonical form and returns
    ``None`` — or raises — when it cannot. A Bronze spec should pass the task's
    own parser here rather than leave it to the default, so that Bronze is
    credited with everything the pipeline can actually read.

    ``null_tokens`` are the stored spellings of absence the contract declares
    (``\N`` and the like). They are read as missing rather than unreadable —
    the source said those cells are empty, and counting them as corrupt would
    blame the data for what the reader was not told.

    ``minimum`` is an **exclusive** lower bound, because the bounds H1 cares
    about are ``price > 0`` and ``area > 0``.
    """

    column: str
    role: str
    kind: Kind = "numeric"
    interpret: Callable[[Any], Any] | None = None
    minimum: float | None = None
    predicate: Callable[[Any], bool] | None = None
    required: bool = True
    null_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class QualitySpec:
    """What to measure, in one layer's vocabulary.

    ``key`` is the identity of a record for duplicate detection; without one,
    a record is its whole row. ``valid_codes`` is the reference code list —
    pinned by #6 — that ``code_validity`` checks against.
    """

    columns: tuple[ColumnSpec, ...]
    key: tuple[str, ...] = ()
    valid_codes: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not self.columns:
            raise QualityError("a quality spec must declare at least one column")
        roles = [column.role for column in self.columns]
        repeated = sorted({role for role in roles if roles.count(role) > 1})
        if repeated:
            raise QualityError(
                f"role(s) declared more than once: {', '.join(repeated)}; a role names "
                f"what a column means, and two columns cannot mean the same thing"
            )

    @property
    def required(self) -> tuple[ColumnSpec, ...]:
        return tuple(column for column in self.columns if column.required)

    def for_columns(self, frame: pd.DataFrame) -> None:
        """Raise if the frame does not carry every column the spec names."""
        missing = [column.column for column in self.columns if column.column not in frame.columns]
        if missing:
            raise QualityError(f"frame is missing specified column(s): {', '.join(missing)}")


@dataclass(frozen=True)
class QualityReport:
    """H1's six metrics for one layer, plus what they were measured over.

    ``rows`` is part of the report rather than a footnote: a missing rate is
    only comparable across layers alongside the number of rows it was computed
    over.
    """

    layer: Layer
    rows: int
    missing_rate: float
    duplicate_rate: float
    schema_conformance: float
    parsing_failure_rate: float
    type_consistency: float | None = None
    code_validity: float | None = None
    missing_by_column: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The result-schema fields this measurement fills in."""
        return {
            "missing_rate": self.missing_rate,
            "duplicate_rate": self.duplicate_rate,
            "schema_validity": self.schema_conformance,
        }

    def metric(self, name: str) -> float | None:
        if name not in TABLE2_METRICS:
            raise QualityError(f"no such quality metric: {name!r}")
        value: float | None = getattr(self, name)
        return value


def measure_quality(frame: pd.DataFrame, spec: QualitySpec, *, layer: Layer) -> QualityReport:
    """Measure H1's six metrics over one layer's frame."""
    if frame.empty:
        raise QualityError(
            "cannot measure the quality of an empty frame; every rate would be "
            "undefined and reporting 0.0 would claim perfection"
        )
    spec.for_columns(frame)

    readings = {column.role: _read(frame, column) for column in spec.columns}
    required = [column.role for column in spec.required]

    return QualityReport(
        layer=layer,
        rows=len(frame),
        missing_rate=_missing_rate(readings, required),
        missing_by_column=_missing_by_column(spec, readings),
        duplicate_rate=duplicate_rate(frame, spec.key),
        schema_conformance=_schema_conformance(spec, readings),
        parsing_failure_rate=_parsing_failure_rate(readings, required),
        type_consistency=_type_consistency(spec, readings),
        code_validity=_code_validity(spec, readings),
    )


def duplicate_rate(frame: pd.DataFrame, key: tuple[str, ...] = ()) -> float:
    """Records that repeat an earlier record, over records.

    Without a ``key`` a record is its whole row, which is the conservative
    reading: two trades that agree on every recorded field may still be two
    genuine trades, so the number is reported as *duplicate records*, never
    silently deduplicated.

    This is a **diagnostic** metric, not a paired one. Bronze and Silver do not
    hold the same columns — Silver may coalesce aliases away or add derived
    fields — so a whole-row rate is not computed against the same yardstick on
    both sides, and narrowing the columns can raise it on its own. Read a change
    in this number by inspecting the record pairs behind it, never from the
    aggregate alone. Every such change observed so far turned out to be
    canonicalization exposing duplicates the source already held, but that is a
    finding each time, not something the rate says by itself.
    """
    if frame.empty:
        raise QualityError("cannot measure duplicates in an empty frame")
    subset = list(key) if key else None
    return float(frame.duplicated(subset=subset).mean())


def table2(reports: Mapping[Layer, QualityReport], *, baseline: Layer = "bronze") -> pd.DataFrame:
    """Table 2 (Data Quality): Metric / per-layer values / Improvement.

    ``Improvement`` is signed so that **positive always means better**: for a
    rate where lower is better it is ``baseline - layer``, and for one where
    higher is better it is ``layer - baseline``. Without that convention a
    column of mixed-direction deltas invites the reader to misread half of it.

    The row counts are printed as the first row, so a missing rate improved by
    dropping rows is visible in the same glance as the improvement.

    Only :data:`H1_COMPARABLE_METRICS` appear here. ``duplicate_rate`` is
    reported by :func:`table2_diagnostics`, which prints no improvement column
    at all — a signed delta is exactly the reading that metric cannot support.
    """
    if baseline not in reports:
        raise QualityError(f"no report for the baseline layer {baseline!r}")

    layers = [baseline, *[layer for layer in reports if layer != baseline]]
    rows: list[dict[str, Any]] = [
        {"Metric": "rows"} | {str(layer): float(reports[layer].rows) for layer in layers}
    ]
    for name in H1_COMPARABLE_METRICS:
        values: dict[str, Any] = {str(layer): reports[layer].metric(name) for layer in layers}
        if all(value is None for value in values.values()):
            continue
        rows.append({"Metric": name} | values)

    frame = pd.DataFrame(rows)
    for layer in layers:
        if layer == baseline:
            continue
        frame[f"{layer}_improvement"] = [
            _improvement(row["Metric"], row[baseline], row[layer]) for _, row in frame.iterrows()
        ]
    return frame


def table2_diagnostics(reports: Mapping[Layer, QualityReport]) -> pd.DataFrame:
    """The diagnostic metrics, per layer, with no improvement column.

    Separate from :func:`table2` because printing them side by side under one
    heading is what invites "duplicates improved by X" — the one reading the
    measurement does not support. The values are here in full; only the
    invitation to subtract them is gone.
    """
    layers = list(reports)
    rows = [
        {"Metric": name} | {str(layer): reports[layer].metric(name) for layer in layers}
        for name in H1_DIAGNOSTIC_METRICS
    ]
    return pd.DataFrame([row for row in rows if any(v is not None for v in list(row.values())[1:])])


def figure3_data(
    reports: Mapping[Layer, QualityReport],
    *,
    metrics: tuple[str, ...] = H1_COMPARABLE_METRICS,
) -> pd.DataFrame:
    """Tidy ``(metric, layer, value)`` rows for Figure 3 (Quality Improvement).

    Long rather than wide because every plotting library wants it that way, and
    because a metric that a layer does not report is simply absent instead of
    becoming a null that has to be explained.

    Defaults to the comparable metrics. A figure puts bars next to each other
    and the reader compares them, so a diagnostic metric plotted there makes a
    claim the caller never wrote. Pass ``metrics`` to plot one deliberately.
    """
    rows = [
        {"metric": name, "layer": layer, "value": value}
        for layer, report in reports.items()
        for name in metrics
        if (value := report.metric(name)) is not None
    ]
    return pd.DataFrame(rows, columns=["metric", "layer", "value"])


# -- internals -------------------------------------------------------------


@dataclass(frozen=True)
class _Reading:
    """One column, read: what was absent, what was unreadable, what it means."""

    spec: ColumnSpec
    missing: np.ndarray[Any, Any]
    unreadable: np.ndarray[Any, Any]
    values: pd.Series[Any]


def _read(frame: pd.DataFrame, spec: ColumnSpec) -> _Reading:
    """Apply a column's interpretation, keeping absent and corrupt apart."""
    raw = frame[spec.column]
    missing = raw.isna().to_numpy()
    if spec.null_tokens:
        # The contract declares what absence looks like in this source. A reader
        # that does not know ``\N`` calls it a corrupt value, which is the same
        # hostility as not knowing that ``120,000`` is a number: it counts the
        # reader's ignorance as the data's defect.
        missing = missing | raw.isin(spec.null_tokens).to_numpy()
    interpreted = _interpret(raw, spec)
    unreadable = interpreted.isna().to_numpy() & ~missing
    return _Reading(spec=spec, missing=missing, unreadable=unreadable, values=interpreted)


def _interpret(raw: pd.Series[Any], spec: ColumnSpec) -> pd.Series[Any]:
    if spec.interpret is not None:
        return raw.map(lambda value: _attempt(spec.interpret, value))
    if spec.kind == "numeric":
        return pd.to_numeric(raw, errors="coerce")
    if spec.kind == "date":
        return pd.to_datetime(raw, errors="coerce")
    return raw.astype("string")


def _attempt(interpret: Callable[[Any], Any] | None, value: Any) -> Any:
    """Read one value, treating a raised exception as unreadable.

    A parser that raises and a parser that returns ``None`` mean the same thing
    here, so a task need not wrap its own helpers to be measurable.
    """
    if interpret is None or value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return interpret(value)
    except Exception:
        return None


def _missing_rate(readings: Mapping[str, _Reading], required: list[str]) -> float:
    if not required:
        return 0.0
    missing = sum(int(readings[role].missing.sum()) for role in required)
    cells = sum(readings[role].missing.size for role in required)
    return missing / cells


def _missing_by_column(spec: QualitySpec, readings: Mapping[str, _Reading]) -> dict[str, float]:
    """Per column, so a column that improved by disappearing cannot hide."""
    return {column.column: float(readings[column.role].missing.mean()) for column in spec.required}


def _parsing_failure_rate(readings: Mapping[str, _Reading], required: list[str]) -> float:
    if not required:
        return 0.0
    failed = np.zeros_like(readings[required[0]].unreadable)
    for role in required:
        failed = failed | readings[role].unreadable
    return float(failed.mean())


def _type_consistency(spec: QualitySpec, readings: Mapping[str, _Reading]) -> float | None:
    """Values that read as their declared type, over values that were present.

    Missing values are out of the denominator: absence is counted by
    ``missing_rate`` and counting it twice would make the two metrics move
    together for no reason.
    """
    typed = [column for column in spec.columns if column.kind in TYPED_KINDS]
    if not typed:
        return None
    present = sum(int((~readings[c.role].missing).sum()) for c in typed)
    if present == 0:
        return None
    unreadable = sum(int(readings[c.role].unreadable.sum()) for c in typed)
    return (present - unreadable) / present


def _code_validity(spec: QualitySpec, readings: Mapping[str, _Reading]) -> float | None:
    """Code values found in the reference list.

    ``None`` when no reference list was given. A regular expression over five
    digits would accept ``99999``, so it measures format rather than validity,
    and reporting that as code validity would overstate what was checked.
    """
    codes = [column for column in spec.columns if column.kind == "code"]
    if not codes or spec.valid_codes is None:
        return None
    valid = 0
    present = 0
    for column in codes:
        reading = readings[column.role]
        values = reading.values[~reading.missing]
        present += len(values)
        valid += int(values.astype("string").isin(spec.valid_codes).sum())
    return valid / present if present else None


def _schema_conformance(spec: QualitySpec, readings: Mapping[str, _Reading]) -> float:
    """Records where every required column is present, readable and in bounds."""
    required = spec.required
    if not required:
        return 1.0
    conforms = np.ones(readings[required[0].role].missing.shape, dtype=bool)
    for column in required:
        reading = readings[column.role]
        usable = ~reading.missing & ~reading.unreadable
        conforms = conforms & usable & _within_bounds(column, reading, usable, spec)
    return float(conforms.mean())


def _within_bounds(
    column: ColumnSpec,
    reading: _Reading,
    usable: np.ndarray[Any, Any],
    spec: QualitySpec,
) -> np.ndarray[Any, Any]:
    ok = np.ones_like(usable)
    if column.minimum is not None:
        numeric = pd.to_numeric(reading.values, errors="coerce").to_numpy()
        with np.errstate(invalid="ignore"):
            ok = ok & (numeric > column.minimum)
    if column.predicate is not None:
        ok = ok & reading.values.map(lambda v: _holds(column.predicate, v)).to_numpy()
    if column.kind == "code" and spec.valid_codes is not None:
        ok = ok & reading.values.astype("string").isin(spec.valid_codes).to_numpy()
    # Rows that were unusable are already excluded by the caller's conjunction;
    # leaving them True here keeps this function about bounds alone.
    within: np.ndarray[Any, Any] = ok | ~usable
    return within


def _holds(predicate: Callable[[Any], bool] | None, value: Any) -> bool:
    if predicate is None:
        return True
    try:
        return bool(predicate(value))
    except Exception:
        return False


def _improvement(metric: str, baseline: float | None, value: float | None) -> float | None:
    """Signed so that positive always means better."""
    if metric == "rows" or baseline is None or value is None:
        return None
    return value - baseline if metric in HIGHER_IS_BETTER else baseline - value
