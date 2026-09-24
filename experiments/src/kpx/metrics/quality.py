r"""Data-quality metrics for RQ1, applied unchanged to Bronze and Silver.

Six metrics — type consistency, code validity, schema conformance, missing
values, duplicates and parsing failures — through one interface for both layers.
In RQ1 they are an **integrity check**, not the finding: the builder refuses a
build whose declared casts lose values, so once Bronze is read with the
contract's own parsers a successful build cannot differ from its Silver on the
comparable metrics. What standardization changed is measured cell by cell in
:mod:`kpx.metrics.pairing`, as role × transition-cause counts — that is RQ1's
primary result.

The hard part is not computing rates. It is making sure the rates compare the
same thing, because Bronze and Silver do not even use the same column names —
Bronze has ``거래금액`` holding ``"120,000"``, Silver has ``price_krw`` holding
``1200000000``. A :class:`QualitySpec` states, in one layer's vocabulary, which
column plays which role and how a value in it is to be read. Everything else is
computed identically for both.

Two ways this measurement could manufacture a layer difference, and what stops each
-----------------------------------------------------------------------------------

**Reading Bronze naively.** ``pd.to_numeric("120,000")`` fails, and if that
counted as a parsing failure, the comparison would measure how hostile we chose to be
to Bronze rather than anything about the data. So a Bronze spec passes the same
interpretation the Silver *build* declares — ``kpx.metrics.roles.INTERPRETERS``,
keyed by the cast in the contract — and Bronze is credited with every value the
build could read. What remains a failure is a value the pipeline could not parse
either.

**Changing a rate by dropping rows.** A Silver build that deletes rows with
nulls reports a lower missing rate for a reason that has nothing to do with
standardization. Two things make that visible rather than invisible:

* missing rate is reported **per required column** as well as overall, so a
  column that changed by disappearing does not hide inside an average, and
* every report carries the **row count of its layer**, and
  ``scripts/quality_spectrum.py`` stores it beside the rates, so a change bought
  by dropping rows is visible next to the change itself.

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

All six are measured and all six are stored. They are not all comparable.

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

A rise is therefore not a regression and a fall is not a gain; both are
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

#: The layer-to-layer integrity check. Each one is stated as a role that both
#: layers fill, so the two sides measure the same construct under different
#: column names. ``code_validity`` belongs here whenever a reference code list
#: exists; where none does it is simply ``None``.
INTEGRITY_METRICS: tuple[str, ...] = (
    "type_consistency",
    "missing_rate",
    "schema_conformance",
    "code_validity",
    "parsing_failure_rate",
)

#: Measured and stored, but not a layer comparison on its own. See the module
#: docstring: it compares stored values rather than interpreted ones, so a
#: delta here is something to explain rather than something that settles
#: anything.
DIAGNOSTIC_METRICS: tuple[str, ...] = ("duplicate_rate",)

#: Everything a :class:`QualityReport` can answer for. ``rq1_layer_quality``
#: stores all of it — separating presentation from storage is the point.
LAYER_QUALITY_METRICS: tuple[str, ...] = INTEGRITY_METRICS + DIAGNOSTIC_METRICS


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

    ``minimum`` is an **exclusive** lower bound, because the bounds RQ1 cares
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
    """The six metrics for one layer, plus what they were measured over.

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

    def metric(self, name: str) -> float | None:
        if name not in LAYER_QUALITY_METRICS:
            raise QualityError(f"no such quality metric: {name!r}")
        value: float | None = getattr(self, name)
        return value


def measure_quality(frame: pd.DataFrame, spec: QualitySpec, *, layer: Layer) -> QualityReport:
    """Measure the six metrics over one layer's frame."""
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
