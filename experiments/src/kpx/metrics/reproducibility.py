"""R1 rebuild determinism (RQ3): does the same source give the same output?

The same frozen source, the same code and the same configuration should produce
byte-identical output. This module turns a set of repeated builds of the
Medallion pipeline into that verdict. It is not a comparison against the
monolithic baseline — R1 makes no claim that layering is more deterministic.

Two ways this measurement could manufacture a clean verdict, and what stops each
-------------------------------------------------------------------------------

**Counting failed builds as agreement.** A run that failed produced no output.
If nine of ten builds fail and the tenth succeeds, there is exactly one digest —
which is not evidence of determinism but evidence that there was nothing to
compare. Equality is computed over successful builds only, and a verdict needs
**at least two** of them; below that the verdict is ``None``, not ``True``.

**Hiding a low success rate behind a clean equality.** :func:`reproducibility_table` prints the
build success rate in the same row as the equality verdicts, so a "True" bought
by eight failures is visible at the same glance as the "True".
"""

from __future__ import annotations

import collections
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

REPRODUCIBILITY_COLUMNS = (
    "Condition",
    "Builds",
    "Success rate",
    "Distinct digests",
    "SHA-256 equal",
    "Rows equal",
    "Schema equal",
)


class ReproducibilityError(RuntimeError):
    """Raised when determinism is asked of a set of builds that cannot answer."""


@dataclass(frozen=True)
class BuildOutcome:
    """One build of a repeated series.

    A failed build carries no output, so its digest, row count and schema are
    ``None`` rather than a placeholder that would compare equal to something.
    """

    status: str
    output_digest: str | None
    row_count: int | None
    schema: tuple[str, ...] | None

    @property
    def succeeded(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class ReproducibilityReport:
    repeats: int
    successes: int
    distinct_digests: int
    digest_equality: bool | None
    row_count_equality: bool | None
    schema_equality: bool | None

    @property
    def build_success_rate(self) -> float:
        return self.successes / self.repeats

    def to_dict(self) -> dict[str, Any]:
        return {
            "repeats": self.repeats,
            "successes": self.successes,
            "build_success_rate": self.build_success_rate,
            "distinct_digests": self.distinct_digests,
            "digest_equality": self.digest_equality,
            "row_count_equality": self.row_count_equality,
            "schema_equality": self.schema_equality,
        }


def _equality(values: Sequence[object]) -> bool | None:
    """Whether ``values`` agree, or ``None`` when there is nothing to compare.

    One value is not agreement. Returning ``True`` for a single build would let
    a series that failed nine times out of ten read as deterministic.
    """
    if len(values) < 2:
        return None
    return len(set(values)) == 1


def measure_reproducibility(outcomes: Sequence[BuildOutcome]) -> ReproducibilityReport:
    """Summarize repeated builds of the same frozen source."""
    if not outcomes:
        raise ReproducibilityError("no builds to measure")

    successful = [outcome for outcome in outcomes if outcome.succeeded]
    digests = [outcome.output_digest for outcome in successful]

    return ReproducibilityReport(
        repeats=len(outcomes),
        successes=len(successful),
        distinct_digests=len(set(digests)),
        digest_equality=_equality(digests),
        row_count_equality=_equality([outcome.row_count for outcome in successful]),
        schema_equality=_equality([outcome.schema for outcome in successful]),
    )


def digest_distribution(outcomes: Sequence[BuildOutcome]) -> dict[str, int]:
    """How many builds landed on each digest — what to inspect when the verdict fails.

    When determinism breaks, the split itself is the finding: two digests at 5/5
    points somewhere different from nine at 9/1.
    """
    counter = collections.Counter(
        outcome.output_digest for outcome in outcomes if outcome.succeeded
    )
    return {digest: count for digest, count in counter.most_common() if digest is not None}


def _verdict(value: bool | None) -> str:
    return "—" if value is None else str(value)


def reproducibility_table(reports: Mapping[str, ReproducibilityReport]) -> pd.DataFrame:
    """The determinism table: one row per condition.

    The success rate sits beside the equality verdicts on purpose — an equality
    bought by failures should not be readable without the failures.
    """
    rows = [
        {
            "Condition": condition,
            "Builds": report.repeats,
            "Success rate": f"{report.build_success_rate:.0%}",
            "Distinct digests": report.distinct_digests,
            "SHA-256 equal": _verdict(report.digest_equality),
            "Rows equal": _verdict(report.row_count_equality),
            "Schema equal": _verdict(report.schema_equality),
        }
        for condition, report in reports.items()
    ]
    return pd.DataFrame(rows, columns=list(REPRODUCIBILITY_COLUMNS))
