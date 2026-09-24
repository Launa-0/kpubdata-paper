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
    "coalesce_sources",
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

# polars does not trim before casting, and ``Int64`` refuses a decimal point
# even when the value is whole: ``"12.0"`` is null, not 12. Matching that
# matters — the claim is that the measurement reads what the pipeline reads, so
# a reader that is more generous than the build makes Bronze look better than
# the build would have found it.
# ASCII only: ``\d`` also matches full-width ``１２``, which polars refuses.
_INTEGER = re.compile(r"^[+-]?\d+$", re.ASCII)
_FLOAT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$", re.ASCII)


def _integer(value: object) -> int | None:
    text = str(value)
    return int(text) if _INTEGER.match(text) else None


def _float(value: object) -> float | None:
    text = str(value)
    return float(text) if _FLOAT.match(text) else None


def _integer_comma(value: object) -> int | None:
    """The whole reason this module exists.

    ``pd.to_numeric("120,000")`` fails. Counting that as a parsing failure
    measures how hostile the reader was told to be, not the data — the bias
    ``quality`` guards against. The pipeline strips the separators and reads it,
    so the measurement does too.
    """
    return _integer(str(value).replace(",", "").strip())


def _float_comma(value: object) -> float | None:
    return _float(str(value).replace(",", "").strip())


def _year_month(value: object) -> str | None:
    """``2022-07`` and ``202207`` are the same month written twice."""
    text = str(value).strip()
    if _YEAR_MONTH_DASHED.match(text):
        return text
    if _YEAR_MONTH_COMPACT.match(text):
        return f"{text[:4]}-{text[4:]}"
    return None


#: Cast name -> how the pipeline reads a value declared that way. A declared
#: cast that is missing here is an error, not a fallback - see
#: :func:`interpreter_for`.
INTERPRETERS: dict[str, Callable[[object], Any]] = {
    "int": _integer,
    "int64": _integer,
    "float": _float,
    "float64": _float,
    "int_comma": _integer_comma,
    "float_comma": _float_comma,
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
    null_tokens: tuple[str, ...] = ()
    zfill: int | None = None

    def columns(self, layer: str) -> tuple[str, ...]:
        return self.bronze if layer == "bronze" else self.silver


def interpreter_for(role: Role) -> Callable[[object], Any] | None:
    """How the pipeline reads this role, or an error if nobody decided.

    A declared cast with no entry here must not fall back to the default
    reader. That is how the two definitions drifted apart the first time: the
    module said Bronze gets the pipeline's interpretation, and a cast nobody
    had taught it quietly got pandas' instead. A role with no cast declared has
    nothing to interpret and reads as stored, which is a different thing.
    """
    if not role.cast:
        return None
    try:
        return INTERPRETERS[role.cast]
    except KeyError:
        raise RoleError(
            f"role {role.name!r} declares cast {role.cast!r}, which this measurement "
            "cannot read. Teach INTERPRETERS what the builder does with it rather "
            "than letting it fall back to a different definition."
        ) from None


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
    global_nulls = tuple(contract.get("null_tokens", ()))
    column_nulls = _column_null_tokens(contract)
    zfill: dict[str, int] = dict(contract.get("zfill", {}))

    # Silver name -> Bronze name, for the roles that are one column on each side.
    bronze_of = {silver: bronze for bronze, silver in rename.items()}

    roles: list[Role] = []

    def add(name: str, projection: str, bronze: tuple[str, ...], kind: str | None = None) -> None:
        cast = casts.get(name, "")
        # A column-specific null token is declared against the layer's own
        # spelling, so both spellings are consulted; the token means absent in
        # this role wherever it is written.
        tokens = dict.fromkeys(global_nulls)
        for spelling in (*bronze, name):
            tokens.update(dict.fromkeys(column_nulls.get(spelling, ())))
        roles.append(
            Role(
                name=name,
                kind=kind or CAST_KINDS.get(cast, "text"),
                required=name in required,
                cast=cast,
                projection=projection,
                bronze=bronze,
                silver=(name,),
                null_tokens=tuple(tokens),
                zfill=zfill.get(name),
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
        # Only Bronze holds the parts; Silver stores the assembled value, and
        # joining it again would turn its date into the same string as Bronze's
        # and hide the change.
        if role.projection == "parts" and layer == "bronze":
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


def coalesce_sources(frame: pd.DataFrame, roles: Sequence[Role]) -> list[dict[str, Any]]:
    """For each coalesced role, which Bronze column supplied each row's value.

    A header that changed across source generations is a schema transition, not
    a cell rewrite: the value under ``대여년월`` is the same kind of value that
    used to sit under ``대여일자``. So it is counted in rows per source column,
    beside the cell-level causes rather than in their denominator. ``source`` is
    ``None`` for rows where no candidate held a value.
    """
    counts: list[dict[str, Any]] = []
    for role in roles:
        if role.projection != "coalesce":
            continue
        remaining = pd.Series(True, index=frame.index)
        for column in role.bronze:
            if column not in frame.columns:
                continue
            supplied = remaining & frame[column].notna()
            if supplied.any():
                counts.append({"role": role.name, "source": column, "rows": int(supplied.sum())})
            remaining &= ~supplied
        if remaining.any():
            counts.append({"role": role.name, "source": None, "rows": int(remaining.sum())})
    return counts


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


def _column_null_tokens(contract: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """``column_null_tokens`` before or after the spec turns it into objects."""
    declared = contract.get("column_null_tokens", {})
    rules: dict[str, tuple[str, ...]] = {}
    for column, rule in declared.items():
        tokens = rule["tokens"] if isinstance(rule, Mapping) else rule.tokens
        rules[str(column)] = tuple(tokens)
    return rules


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
