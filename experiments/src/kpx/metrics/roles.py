"""Semantic roles: the one thing both layers must measure, however each spells it.

RQ1 compares Bronze against Silver. The comparison is only meaningful if both
sides measure the same construct, and the two layers do not agree on column
names, on column counts, or even on whether a column exists. Silver's
``ym_raw`` is Bronze's ``대여일자`` **or** ``대여년월`` depending on the
generation; Silver's ``deal_date`` is not in Bronze at all, it is built from
three parts.

The earlier plan mapped ``Bronze column -> Silver column`` from ``rename`` and
``casts`` alone. It could not express either case, and it failed quietly: a
role whose Bronze column did not exist was dropped from the Bronze spec and
kept in Silver's, so the two layers were measured over different denominators
and the tables still printed. Bike measured two required roles against three.

So a role is declared once and carries **how each layer produces it**:

============  ==================================================================
``direct``    one column, possibly under a different name (``rename``)
``coalesce``  the first of several candidate columns that has a value
``parts``     assembled from several columns (``derived``)
============  ==================================================================

:func:`project` turns a layer's frame into one column per role. After that both
layers hold the same columns, and any remaining asymmetry is a declaration bug
that :func:`assert_symmetric` raises on rather than a silent change of
denominator.

Locating a role is not the same as reading its values
-----------------------------------------------------

Projection is structural: it answers *which column holds this role here*.
Interpretation is semantic: it answers *what this value means*. Keeping them
apart is what lets the same projected frame be read two ways — once with the
interpretation the pipeline itself applies (:data:`INTERPRETERS`, keyed by the
cast the contract declares) and once as stored. The first is the H1 comparison;
the second shows what an analyst meets with no preparation at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

__all__ = [
    "CAST_KINDS",
    "INTERPRETERS",
    "Role",
    "assert_symmetric",
    "interpreter_for",
    "plan_roles",
    "project",
]

#: A declared cast decides what the metrics should expect of a value. Anything
#: the contract does not type is ``text``; see ``quality.TYPED_KINDS`` for why
#: this is not ``code``.
CAST_KINDS: dict[str, str] = {
    "int": "numeric",
    "int64": "numeric",
    "int_comma": "numeric",
    "float": "numeric",
    "float64": "numeric",
    "float_comma": "numeric",
    "date": "date",
    "datetime": "date",
}

_YEAR_MONTH_DASHED = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_YEAR_MONTH_COMPACT = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


def _numeric(value: object) -> float | None:
    text = str(value).strip()
    return float(text) if text else None


def _numeric_comma(value: object) -> float | None:
    """The whole reason this module exists.

    ``pd.to_numeric("120,000")`` fails. Counting that as a parsing failure
    measures how hostile the reader was told to be, not the data — the bias
    ``quality`` guards against. The pipeline reads it, so the measurement does.
    """
    return _numeric(str(value).replace(",", ""))


def _year_month(value: object) -> str | None:
    """``2022-07`` and ``202207`` are the same month written twice."""
    text = str(value).strip()
    if _YEAR_MONTH_DASHED.match(text):
        return text
    if _YEAR_MONTH_COMPACT.match(text):
        return f"{text[:4]}-{text[4:]}"
    return None


#: Cast name -> how the pipeline reads a value declared that way. A cast with
#: no entry is read as stored, which is what ``float``/``int`` already are.
INTERPRETERS: dict[str, Callable[[object], Any]] = {
    "int": _numeric,
    "int64": _numeric,
    "float": _numeric,
    "float64": _numeric,
    "int_comma": _numeric_comma,
    "float_comma": _numeric_comma,
    "year_month": _year_month,
}


class RoleError(ValueError):
    """Raised when a contract cannot be read as a set of comparable roles."""


@dataclass(frozen=True)
class Role:
    """One construct, and how each layer produces it."""

    name: str
    kind: str
    required: bool
    cast: str
    projection: str
    bronze: tuple[str, ...]
    silver: tuple[str, ...]

    def columns(self, layer: str) -> tuple[str, ...]:
        return self.bronze if layer == "bronze" else self.silver


def interpreter_for(role: Role) -> Callable[[object], Any] | None:
    return INTERPRETERS.get(role.cast)


def plan_roles(contract: Mapping[str, Any]) -> tuple[Role, ...]:
    """Every role the contract declares, with both layers' sources.

    Roles come from the contract only. Nothing here is per-dataset, and no
    column is chosen by hand — that was the defect this script was written to
    remove, and it would come back the moment one branch named a dataset.
    """
    rename: dict[str, str] = dict(contract.get("rename", {}))
    casts: dict[str, str] = dict(contract.get("casts", {}))
    coalesce: dict[str, tuple[str, ...]] = {
        target: tuple(candidates) for target, candidates in contract.get("coalesce", {}).items()
    }
    derived = {str(item["name"]): item for item in contract.get("derived", ())}
    required = set(contract.get("required", ()))

    # Silver name -> Bronze name, for the roles that are one column on each side.
    bronze_of = {silver: bronze for bronze, silver in rename.items()}

    roles: list[Role] = []

    def add(name: str, projection: str, bronze: tuple[str, ...], kind: str | None = None) -> None:
        cast = casts.get(name, "")
        roles.append(
            Role(
                name=name,
                kind=kind or CAST_KINDS.get(cast, "text"),
                required=name in required,
                cast=cast,
                projection=projection,
                bronze=bronze,
                silver=(name,),
            )
        )

    for bronze, silver in rename.items():
        add(silver, "direct", (bronze,))
    for target, candidates in coalesce.items():
        add(target, "coalesce", candidates)
    for name in casts:
        if name in derived or name in coalesce or name in bronze_of:
            continue
        add(name, "direct", (name,))
    for name, item in derived.items():
        kind = str(item.get("kind", ""))
        if kind != "date_parts":
            raise RoleError(
                f"derived role {name!r} has kind {kind!r}; this measurement only knows "
                "how to build 'date_parts' from a Bronze frame. Teach it the new kind "
                "rather than leaving the role out of the comparison."
            )
        parts = tuple(str(part) for part in item["columns"])
        add(name, "parts", tuple(bronze_of.get(part, part) for part in parts), kind="date")

    missing = required - {role.name for role in roles}
    if missing:
        raise RoleError(
            f"required columns {sorted(missing)} are not declared by rename, casts, "
            "coalesce or derived, so no Bronze source can be found for them"
        )
    return tuple(sorted(roles, key=lambda role: role.name))


def project(frame: pd.DataFrame, roles: Sequence[Role], *, layer: str) -> pd.DataFrame:
    """One column per role, built from whatever that layer actually holds.

    A role that this layer cannot produce is an error, not an omission. The
    whole point is that the two layers end up with the same columns; dropping
    one here is how the denominators drifted apart before.
    """
    columns: dict[str, pd.Series[Any]] = {}
    for role in roles:
        wanted = role.columns(layer)
        present = [name for name in wanted if name in frame.columns]
        if not present:
            raise RoleError(
                f"{layer} has none of {list(wanted)} for role {role.name!r}; "
                "the two layers would be measured over different roles"
            )
        if role.projection == "parts":
            if len(present) != len(wanted):
                raise RoleError(
                    f"{layer} has only {present} of {list(wanted)} for role {role.name!r}"
                )
            columns[role.name] = _join_parts(frame, present)
        elif role.projection == "coalesce":
            columns[role.name] = _coalesce(frame, present)
        else:
            columns[role.name] = frame[present[0]]
    return pd.DataFrame(columns, index=frame.index)


def assert_symmetric(bronze: pd.DataFrame, silver: pd.DataFrame, roles: Sequence[Role]) -> None:
    """Both layers measure the same roles, and the same required roles."""
    names = {role.name for role in roles}
    for layer, frame in (("bronze", bronze), ("silver", silver)):
        if set(frame.columns) != names:
            raise RoleError(
                f"{layer} projection holds {sorted(frame.columns)}, expected {sorted(names)}"
            )
    required = {role.name for role in roles if role.required}
    if not required <= names:
        raise RoleError(f"required roles {sorted(required - names)} were not projected")


# -- internals -------------------------------------------------------------


def _coalesce(frame: pd.DataFrame, present: list[str]) -> pd.Series[Any]:
    merged = frame[present[0]]
    for name in present[1:]:
        merged = merged.combine_first(frame[name])
    return merged


def _join_parts(frame: pd.DataFrame, present: list[str]) -> pd.Series[Any]:
    """``2023`` + ``1`` + ``5`` -> ``2023-01-05``, as stored, without validating.

    Zero padding is spelling, not interpretation: the parts already mean a
    year, a month and a day. Whether they form a real date is left to the
    reader, so a malformed part stays a parsing failure rather than being
    swallowed here.
    """
    widths = (4, 2, 2)
    pieces = [
        frame[name].astype("string").str.strip().str.zfill(width)
        for name, width in zip(present, widths, strict=False)
    ]
    joined = pieces[0]
    for piece in pieces[1:]:
        joined = joined + "-" + piece
    return joined
