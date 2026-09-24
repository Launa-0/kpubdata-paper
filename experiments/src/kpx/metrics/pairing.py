r"""Pairing the two layers on one role: what changed, and did it still mean the same.

With both layers projected onto the same roles, the comparable metrics come out
flat — Bronze read with the contract's own parsers is as type-consistent and as
conformant as Silver, because the values are the same values. That is the honest
result, and it leaves H1 with nothing to show unless the measurement asks a
different question.

The question worth asking is not *which layer is cleaner* but **what
standardization actually did**:

``representation_change_rate``
    On the same row and the same role, does Bronze's stored spelling differ from
    Silver's? ``"120,000"`` against ``120000``, ``"3"`` against ``"00003"``.

``semantic_preservation_rate``
    Where both sides can be read at all, do they mean the same thing?

The two together say: *Silver rewrote this share of the values and changed the
meaning of none of them.* Neither number alone is worth much — a pipeline that
rewrote nothing would preserve everything, and one that rewrote everything into
nulls would also look busy.

What a change rate is not
-------------------------

``representation_change_rate`` is **not** analyst effort. One vectorised cast
rewrites a million cells; a different million cells might cost one line each.
The share of values that had to be normalised is a descriptive footprint of this
source *under the evaluated contract and role definition* — not a property of the
source alone: counting the columns ``read_as`` converts as roles moves the trades
aggregate from 0.238 to 0.450 on the same bytes. The cost of doing that
normalisation downstream is RQ2's measurement, not this one. Reading a 70%
change rate as "70% of the work" is the same category error as reading Bronze's
naive parsing failures as data corruption.

Coverage is reported, not assumed
---------------------------------

A Bronze value the contract's own parser cannot read has no meaning to preserve.
Scoring it as preserved because both sides end up ``None`` would let unreadable
input inflate the very number that is supposed to defend the pipeline. Those
cells are excluded from the preservation rate and counted in
``semantic_coverage_rate`` instead, so the claim is always "of the values that
could be read", with the remainder stated.

Counts, not just rates
----------------------

Every rate is stored with the count it came from. Roles differ in how many
values are readable, so averaging their rates would be a macro-average with the
same defect this package keeps finding elsewhere — each role voting once
regardless of size. With counts, any later aggregation can be weighted properly.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from kpx.metrics.roles import Role, interpreter_for

__all__ = [
    "RolePair",
    "aggregate",
    "assert_row_identity",
    "pair_and_classify",
    "pair_roles",
    "token",
]

#: A value that carries no meaning to compare.
_UNREADABLE = object()


@dataclass(frozen=True)
class RolePair:
    """One role, measured across the two layers, with the counts behind it."""

    role: str
    kind: str
    projection: str
    required: bool
    rows: int
    representation_changed_count: int
    semantic_comparable_count: int
    semantic_preserved_count: int

    @property
    def representation_change_rate(self) -> float:
        return self.representation_changed_count / self.rows

    @property
    def semantic_coverage_rate(self) -> float:
        return self.semantic_comparable_count / self.rows

    @property
    def semantic_preservation_rate(self) -> float | None:
        """``None`` when nothing was readable — a rate over zero values is a lie."""
        if not self.semantic_comparable_count:
            return None
        return self.semantic_preserved_count / self.semantic_comparable_count

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "representation_change_rate": self.representation_change_rate,
            "semantic_coverage_rate": self.semantic_coverage_rate,
            "semantic_preservation_rate": self.semantic_preservation_rate,
        }


def token(value: Any) -> tuple[str, Any]:
    """A value's stored representation, typed.

    ``str()`` will not do. It flattens ``1`` and ``"1"`` onto the same string
    and turns ``None`` into ``"None"``, which would hide exactly the changes
    this measurement exists to count — a cast from text to a number is the
    commonest thing standardization does.
    """
    if _is_missing(value):
        return ("null", None)
    if isinstance(value, bool | np.bool_):
        return ("bool", bool(value))
    if isinstance(value, dt.date | dt.datetime):
        return ("date", value.isoformat())
    if isinstance(value, int | np.integer):
        return ("int", int(value))
    if isinstance(value, float | np.floating):
        return ("float", float(value))
    return ("str", str(value))


#: Casts that turn text into a number — rule 8 of the transition causes.
_NUMERIC_CASTS = frozenset({"int", "int64", "float", "float64", "int_comma", "float_comma"})


def pair_roles(
    bronze: pd.DataFrame, silver: pd.DataFrame, roles: tuple[Role, ...]
) -> list[RolePair]:
    """Compare the two projections role by role, row by row.

    Both frames must already be projections of the same roles over the same
    rows; :func:`kpx.metrics.roles.assert_symmetric` is what guarantees it.
    """
    return pair_and_classify(bronze, silver, roles)[0]


def pair_and_classify(
    bronze: pd.DataFrame, silver: pd.DataFrame, roles: tuple[Role, ...]
) -> tuple[list[RolePair], list[dict[str, Any]]]:
    """:func:`pair_roles`, plus **why** each cell changed.

    A change count says how much standardization rewrote; it does not say what
    kind of rewrite it was — ``"0"`` becoming ``0``, ``"3"`` becoming
    ``"00003"`` and ``\\N`` becoming null are all "direct" roles and all one
    number. The causes are named by the rules fixed before any result was seen
    (``docs/rq1-transition-classification.md``), first match wins:

    1. same token — ``unchanged``
    2. either side unreadable — ``unreadable_lossy``
    3. different meaning — ``other:semantic_difference``
    4. assembled from parts — ``derived_field``
    5. a declared null token became null — ``null_canonicalization``
    6. ``year_month`` cast, or an uncast date — ``date_year_month_normalization``
    7. zero-padded to the declared width — ``identifier_padding``
    8. numeric cast: from text with a separator — ``numeric_formatting``,
       otherwise ``primitive_type_normalization``
    9. no cast, a source number now stored as text (``read_as``) —
       ``primitive_type_normalization``
    10. anything else — ``other``

    Rules 5 and 7 strip the Bronze value as the pre-specified rules wrote them;
    no value in the measured snapshots is affected by the strip.

    Renaming and coalescing never change a value, so they are not causes: each
    row carries the role's ``structural`` transition beside the cell counts
    instead of inside them. The causes partition every role's cells, and all
    but ``unchanged`` add up to its ``representation_changed_count``.
    """
    if len(bronze) != len(silver):
        raise ValueError(
            f"the two layers hold {len(bronze)} and {len(silver)} rows; a row-wise "
            "pairing needs the same rows on both sides"
        )
    pairs: list[RolePair] = []
    transitions: list[dict[str, Any]] = []
    for role in roles:
        left, right = bronze[role.name], silver[role.name]
        changed = _tokens(left) != _tokens(right)

        canonical = _canonicaliser(role)
        read_left, read_right = _canonical(left, canonical), _canonical(right, canonical)
        comparable = (read_left != _UNREADABLE) & (read_right != _UNREADABLE)
        same_meaning = read_left == read_right
        preserved = comparable & same_meaning

        pairs.append(
            RolePair(
                role=role.name,
                kind=role.kind,
                projection=role.projection,
                required=role.required,
                rows=len(bronze),
                representation_changed_count=int(changed.sum()),
                semantic_comparable_count=int(comparable.sum()),
                semantic_preserved_count=int(preserved.sum()),
            )
        )
        causes = _causes(role, left, right, changed, comparable, same_meaning)
        names, counts = np.unique(causes, return_counts=True)
        transitions.extend(
            {
                "role": role.name,
                "required": role.required,
                "cast": role.cast,
                "projection": role.projection,
                "structural": _structural(role),
                "category": str(name),
                "cells": int(count),
            }
            for name, count in zip(names, counts, strict=True)
        )
    return pairs, transitions


def assert_row_identity(
    bronze: pd.DataFrame, silver: pd.DataFrame, roles: tuple[Role, ...]
) -> None:
    """Row *i* on one side is the same record as row *i* on the other.

    :func:`pair_roles` pairs by position, and there is no source ordinal to
    join on. Equal length is not enough: shuffled rows have equal length too,
    and would still produce a change rate. So the required roles — identifier,
    time and main fact — must read the same on every row before anything is
    paired.

    This is a precondition, not a finding. Once it passes, the required roles'
    ``semantic_preservation_rate`` is 1.0 by construction and says nothing on
    its own; only the optional roles' preservation is still measured.
    """
    if len(bronze) != len(silver):
        raise ValueError(
            f"the two layers hold {len(bronze)} and {len(silver)} rows; a row-wise "
            "pairing needs the same rows on both sides"
        )
    keys = [role for role in roles if role.required]
    if not keys:
        raise ValueError("no required role to identify a row by")
    same = np.ones(len(bronze), dtype=bool)
    for role in keys:
        read = _canonicaliser(role)
        left = _canonical(bronze[role.name], read)
        right = _canonical(silver[role.name], read)
        same &= (left != _UNREADABLE) & (left == right)
    if not same.all():
        first = np.flatnonzero(~same)[:5].tolist()
        raise ValueError(
            f"{int((~same).sum())} of {len(same)} rows disagree on the required roles "
            f"{[role.name for role in keys]} (first positions {first}); the two layers "
            "are not in the same row order, so a positional pairing would compare "
            "different records"
        )


def aggregate(pairs: list[RolePair], *, required_only: bool = False) -> dict[str, Any]:
    """Weighted totals across roles — never a mean of the rates."""
    chosen = [pair for pair in pairs if pair.required or not required_only]
    rows = sum(pair.rows for pair in chosen)
    changed = sum(pair.representation_changed_count for pair in chosen)
    comparable = sum(pair.semantic_comparable_count for pair in chosen)
    preserved = sum(pair.semantic_preserved_count for pair in chosen)
    return {
        "scope": "required" if required_only else "all",
        "roles": len(chosen),
        "cells": rows,
        "representation_changed_count": changed,
        "representation_change_rate": changed / rows if rows else None,
        "semantic_comparable_count": comparable,
        "semantic_coverage_rate": comparable / rows if rows else None,
        "semantic_preserved_count": preserved,
        "semantic_preservation_rate": preserved / comparable if comparable else None,
    }


# -- internals -------------------------------------------------------------


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NaT:
        return True
    return isinstance(value, float) and math.isnan(value)


def _canonicaliser(role: Role) -> Any:
    """How to read one value of this role for *meaning*, the same way on both sides.

    Applied to Bronze and Silver alike. Comparing ``interpret(bronze)`` against
    Silver's stored value directly would score the pipeline's own canonical form
    as a semantic change — ``"3"`` becoming ``"00003"`` is a zero-padded
    identifier, not a different station.
    """
    interpret = interpreter_for(role)
    nulls = frozenset(role.null_tokens)

    def read(value: Any) -> Any:
        if _is_missing(value):
            return None
        # As stored, not stripped: the builder matches null tokens with ``is_in``
        # and zero-pads without trimming, so a reader that strips first credits
        # Bronze with readings the build never made.
        text = str(value)
        if text in nulls:
            return None
        if interpret is not None:
            try:
                read_value = interpret(value)
            except Exception:
                return _UNREADABLE
            return _UNREADABLE if read_value is None else read_value
        if role.kind == "date":
            stamp = pd.to_datetime(value, errors="coerce")
            return _UNREADABLE if pd.isna(stamp) else stamp.date().isoformat()
        if role.zfill:
            text = text.zfill(role.zfill)
        return text

    return read


def _causes(
    role: Role,
    left: pd.Series[Any],
    right: pd.Series[Any],
    changed: np.ndarray[Any, Any],
    comparable: np.ndarray[Any, Any],
    same_meaning: np.ndarray[Any, Any],
) -> np.ndarray[Any, Any]:
    """One cause per cell, by the pre-specified rules (see :func:`pair_and_classify`)."""
    kind_left = _over_uniques(left, lambda value: token(value)[0]).astype(str)
    kind_right = _over_uniques(right, lambda value: token(value)[0]).astype(str)
    text_left = kind_left == "str"
    nulls = frozenset(role.null_tokens)
    declared_null = _over_uniques(
        left, lambda value: isinstance(value, str) and value.strip() in nulls
    ).astype(bool)
    has_separator = _over_uniques(
        left, lambda value: isinstance(value, str) and "," in value
    ).astype(bool)

    size = len(left)
    padded = np.zeros(size, dtype=bool)
    if role.zfill:
        width = role.zfill
        expected = _over_uniques(
            left, lambda value: value.strip().zfill(width) if isinstance(value, str) else None
        )
        padded = text_left & (kind_right == "str") & (expected == right.to_numpy(dtype=object))

    def every(flag: bool) -> np.ndarray[Any, Any]:
        return np.full(size, flag)

    numeric = role.cast in _NUMERIC_CASTS
    rules = [
        (~changed, "unchanged"),
        (~comparable, "unreadable_lossy"),
        (~same_meaning, "other:semantic_difference"),
        (every(role.projection == "parts"), "derived_field"),
        ((kind_right == "null") & text_left & declared_null, "null_canonicalization"),
        (
            every(role.cast == "year_month" or (role.kind == "date" and not role.cast)),
            "date_year_month_normalization",
        ),
        (padded, "identifier_padding"),
        (every(numeric) & text_left & has_separator, "numeric_formatting"),
        (every(numeric), "primitive_type_normalization"),
        (
            every(not role.cast) & np.isin(kind_left, ["int", "float"]) & (kind_right == "str"),
            "primitive_type_normalization",
        ),
    ]
    return np.select([rule for rule, _ in rules], [name for _, name in rules], default="other")


def _structural(role: Role) -> str:
    """How the role's column itself changed — never a cell count."""
    if role.projection == "parts":
        return "derived"
    if role.projection == "coalesce":
        return "coalesce"
    return "rename" if role.bronze[0] != role.name else "same_name"


def _tokens(series: pd.Series[Any]) -> np.ndarray[Any, Any]:
    return _over_uniques(series, token)


def _canonical(series: pd.Series[Any], read: Any) -> np.ndarray[Any, Any]:
    return _over_uniques(series, read)


def _over_uniques(series: pd.Series[Any], fn: Any) -> np.ndarray[Any, Any]:
    """Parse each distinct value once, then fan it back out.

    Millions of rows hold thousands of distinct spellings. Parsing per row would
    make this measurement slower than the build it measures.

    Distinct means distinct *with its type*. ``factorize`` hashes ``1``, ``1.0``
    and ``True`` to one value, so on its own it would hand every one of them the
    spelling it met first — exactly the int/float mix this measurement counts.
    """
    values, _ = pd.factorize(series, use_na_sentinel=False)
    types, _ = pd.factorize(series.map(type), use_na_sentinel=False)
    keys = values.astype(np.int64) * (int(types.max(initial=0)) + 1) + types
    _, first_row, codes = np.unique(keys, return_index=True, return_inverse=True)
    mapped = np.empty(len(first_row), dtype=object)
    for index, row in enumerate(first_row):
        mapped[index] = fn(series.iloc[row])
    return mapped[codes]
