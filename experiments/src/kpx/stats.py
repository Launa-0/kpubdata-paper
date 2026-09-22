"""Statistical comparison of conditions.

Every hypothesis in the paper is a comparison between conditions of the *same*
task on the *same* snapshot, so the comparisons are paired. This module fixes
how they are tested, before any result exists, for the same reason the
preprocessing boundary was fixed before any condition was written: a test chosen
after seeing the numbers is a test chosen to produce them.

The decision rule
-----------------

Applied identically to every metric and every pair of conditions:

1. Pair the observations on ``seed`` — the same task, the same snapshot, the
   same seed, differing only in condition. Unpaired observations are dropped and
   counted, never matched up by position.
2. Fewer than two pairs: no test. Report the raw values and stop.
3. Two pairs, or differences that are all identical: no normality test is
   meaningful, so use the distribution-free **Wilcoxon signed-rank** test.
4. Otherwise run **Shapiro–Wilk** on the paired differences. ``p >= 0.05``
   routes to the **paired t-test**; below it, to Wilcoxon.

The rule is recorded on every :class:`Comparison` (``test`` and ``normality_p``)
so that a reader can see which branch each comparison took rather than take the
rule's existence on faith.

Why the effect size is not optional here
----------------------------------------

The design gives 4 conditions and 5 seeds, and at n = 5 a two-sided Wilcoxon
signed-rank test **cannot** return p < 0.05. Its smallest attainable p-value is
2 / 2ⁿ = 0.0625, because there are only 2⁵ sign assignments to be extreme
within. No effect, however large, is "significant" at that n by that test.

The paired t-test has no such floor — the same five pairs can reach p = 0.013
through it. Which means that at this sample size **whether a comparison can
attain significance at all is decided by the normality test**, not by the size
of the effect. A skewed set of differences routes to Wilcoxon and is capped at
0.0625; a well-behaved one routes to t and is not. That is a property of the
design rather than of the pipeline being measured.

So it is computed rather than discovered later:
:attr:`Comparison.significance_reachable` is False whenever the pairing cannot
reach ``alpha``, and :func:`summary_table` carries the column. A comparison
reporting ``p = 0.0625`` and nothing else reads as a null result when it is in
fact the strongest statement that test can make.

Every comparison therefore also carries Cohen's dₙ, the rank-biserial
correlation, a confidence interval on the mean difference, and the raw paired
values. The paper leads with effect sizes and raw measurements, and does not
conclude from a p-value alone. Six seeds instead of five would lift the floor
below 0.05; that is the cheapest available fix and belongs in the task design.

Multiple comparisons
--------------------

Four conditions give six pairs per metric. :func:`holm` applies the Holm–
Bonferroni step-down correction within a family, which is left to the caller to
define — the natural family is one metric within one task.

Requires the ``analysis`` extra (``scipy``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats

from kpx.contract import CONDITIONS, Condition

Test = Literal["paired_t", "wilcoxon", "none"]

#: Significance level, fixed here rather than per comparison.
ALPHA = 0.05

#: Shapiro–Wilk above this routes a comparison to the paired t-test.
NORMALITY_ALPHA = 0.05

#: Pairs needed before a two-sided Wilcoxon signed-rank test can reach ALPHA at
#: all: its minimum attainable p-value is 2 / 2ⁿ, which first drops below 0.05
#: at n = 6. The planned 5 seeds are one short of it.
MIN_PAIRS_FOR_SIGNIFICANCE = 6

#: Column the observations are paired on.
PAIR_ON = "seed"


class StatisticsError(ValueError):
    """Raised when a comparison cannot be made as specified."""


@dataclass(frozen=True)
class Summary:
    """Basic reporting for one condition's measurements of one metric."""

    n: int
    mean: float
    median: float
    sd: float | None
    ci_low: float | None
    ci_high: float | None

    @classmethod
    def of(cls, values: Sequence[float] | np.ndarray[Any, Any]) -> Summary:
        """Summarize ``values`` with a t-based 95% interval on the mean.

        ``sd`` and the interval are ``None`` for a single observation, where
        spread is undefined rather than zero.
        """
        array = np.asarray(values, dtype="float64")
        if array.size == 0:
            raise StatisticsError("cannot summarize an empty sample")
        if array.size == 1:
            value = float(array[0])
            return cls(n=1, mean=value, median=value, sd=None, ci_low=None, ci_high=None)

        sd = float(np.std(array, ddof=1))
        mean = float(np.mean(array))
        half_width = float(stats.t.ppf(1 - ALPHA / 2, array.size - 1)) * sd / math.sqrt(array.size)
        return cls(
            n=int(array.size),
            mean=mean,
            median=float(np.median(array)),
            sd=sd,
            ci_low=mean - half_width,
            ci_high=mean + half_width,
        )


@dataclass(frozen=True)
class Comparison:
    """One paired comparison of two conditions on one metric.

    Carries the test *and* the effect size *and* the raw differences, because a
    p-value at this sample size does not support a conclusion on its own.
    """

    metric: str
    baseline: Condition
    condition: Condition
    task: str | None
    n: int
    baseline_summary: Summary | None
    condition_summary: Summary | None
    difference: Summary | None
    differences: tuple[float, ...]
    test: Test
    statistic: float | None = None
    p_value: float | None = None
    p_adjusted: float | None = None
    normality_p: float | None = None
    cohens_dz: float | None = None
    rank_biserial: float | None = None
    unpaired: int = 0
    note: str = ""

    @property
    def significance_reachable(self) -> bool:
        """Whether this pairing could reach :data:`ALPHA` at all.

        False for a Wilcoxon test below :data:`MIN_PAIRS_FOR_SIGNIFICANCE`,
        where no effect size can produce a significant p-value. Reported so that
        such a comparison is not read as a null result.
        """
        if self.test == "none":
            return False
        if self.test == "wilcoxon":
            return self.n >= MIN_PAIRS_FOR_SIGNIFICANCE
        return self.n >= 2

    @property
    def significant(self) -> bool:
        """Whether the adjusted p-value clears :data:`ALPHA`."""
        p = self.p_adjusted if self.p_adjusted is not None else self.p_value
        return p is not None and p < ALPHA

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "metric": self.metric,
            "baseline": self.baseline,
            "condition": self.condition,
            "n": self.n,
            "baseline_mean": None if self.baseline_summary is None else self.baseline_summary.mean,
            "condition_mean": (
                None if self.condition_summary is None else self.condition_summary.mean
            ),
            "mean_difference": None if self.difference is None else self.difference.mean,
            "ci_low": None if self.difference is None else self.difference.ci_low,
            "ci_high": None if self.difference is None else self.difference.ci_high,
            "test": self.test,
            "p_value": self.p_value,
            "p_adjusted": self.p_adjusted,
            "cohens_dz": self.cohens_dz,
            "rank_biserial": self.rank_biserial,
            "significance_reachable": self.significance_reachable,
            "note": self.note,
        }


def compare(
    baseline: Sequence[float],
    condition: Sequence[float],
    *,
    metric: str,
    baseline_name: Condition = "bronze",
    condition_name: Condition = "silver",
    task: str | None = None,
    unpaired: int = 0,
) -> Comparison:
    """Compare two paired samples under the module's decision rule.

    ``baseline[i]`` and ``condition[i]`` must be the same pair — same task, same
    snapshot, same seed. :func:`compare_conditions` builds them from a results
    frame rather than leaving the alignment to the caller.
    """
    if len(baseline) != len(condition):
        raise StatisticsError(
            f"paired samples must be the same length, got {len(baseline)} and {len(condition)}"
        )

    left = np.asarray(baseline, dtype="float64")
    right = np.asarray(condition, dtype="float64")
    differences = right - left
    shared = dict(
        metric=metric,
        baseline=baseline_name,
        condition=condition_name,
        task=task,
        differences=tuple(float(d) for d in differences),
        unpaired=unpaired,
    )

    if differences.size < 2:
        return Comparison(
            n=int(differences.size),
            baseline_summary=Summary.of(left) if left.size else None,
            condition_summary=Summary.of(right) if right.size else None,
            difference=Summary.of(differences) if differences.size else None,
            test="none",
            note=f"{differences.size} pair(s); a paired test needs at least 2",
            **shared,  # type: ignore[arg-type]
        )

    test, normality_p = _choose_test(differences)
    statistic, p_value = _run_test(test, left, right, differences)

    return Comparison(
        n=int(differences.size),
        baseline_summary=Summary.of(left),
        condition_summary=Summary.of(right),
        difference=Summary.of(differences),
        test=test,
        statistic=statistic,
        p_value=p_value,
        normality_p=normality_p,
        cohens_dz=_cohens_dz(differences),
        rank_biserial=_rank_biserial(differences),
        note=_reachability_note(test, int(differences.size)),
        **shared,  # type: ignore[arg-type]
    )


def compare_conditions(
    frame: pd.DataFrame,
    metric: str,
    *,
    task: str | None = None,
    baseline: Condition = "bronze",
    pair_on: str = PAIR_ON,
) -> list[Comparison]:
    """Compare every other condition against ``baseline`` on one metric.

    Rows are paired on ``pair_on``; a seed present for one condition and not the
    other is dropped and counted in ``unpaired`` rather than matched by
    position, which would silently compare different runs.
    """
    for column in ("condition", metric, pair_on):
        if column not in frame.columns:
            raise StatisticsError(f"results frame has no {column!r} column")
    if task is not None:
        frame = frame[frame["task"] == task]
    if frame.empty:
        raise StatisticsError("no rows to compare")

    by_condition = {
        str(name): group.set_index(pair_on)[metric].astype("float64")
        for name, group in frame.groupby("condition")
    }
    if baseline not in by_condition:
        raise StatisticsError(f"no rows for the baseline condition {baseline!r}")

    reference = by_condition[baseline]
    comparisons: list[Comparison] = []
    for name in CONDITIONS:
        if name == baseline or name not in by_condition:
            continue
        other = by_condition[name]
        shared_keys = reference.index.intersection(other.index)
        dropped = len(reference.index.union(other.index)) - len(shared_keys)
        comparisons.append(
            compare(
                reference.loc[shared_keys].tolist(),
                other.loc[shared_keys].tolist(),
                metric=metric,
                baseline_name=baseline,
                condition_name=name,
                task=task,
                unpaired=dropped,
            )
        )
    return comparisons


def holm(comparisons: Iterable[Comparison]) -> list[Comparison]:
    """Holm–Bonferroni correction within one family of comparisons.

    The family is the caller's to define; the natural one here is a single
    metric within a single task, where four conditions give three comparisons
    against the baseline. Comparisons without a p-value take no part in the
    correction and keep ``p_adjusted`` at ``None``.
    """
    items = list(comparisons)
    testable = [item for item in items if item.p_value is not None]
    if not testable:
        return items

    order = sorted(range(len(testable)), key=lambda i: testable[i].p_value or 0.0)
    total = len(testable)
    running = 0.0
    adjusted: dict[int, float] = {}
    for rank, index in enumerate(order):
        p = testable[index].p_value or 0.0
        running = max(running, min(1.0, p * (total - rank)))
        adjusted[index] = running

    corrected = {id(item): replace(item, p_adjusted=adjusted[i]) for i, item in enumerate(testable)}
    return [corrected.get(id(item), item) for item in items]


def summary_table(comparisons: Iterable[Comparison]) -> pd.DataFrame:
    """The comparison table the paper prints, one row per comparison."""
    rows = [comparison.to_dict() for comparison in comparisons]
    if not rows:
        return pd.DataFrame(
            columns=["task", "metric", "baseline", "condition", "n", "p_value", "cohens_dz"]
        )
    return pd.DataFrame(rows)


# -- internals -------------------------------------------------------------


def _choose_test(differences: np.ndarray[Any, Any]) -> tuple[Test, float | None]:
    """Apply the pre-registered rule and report which branch it took."""
    if differences.size < 3 or _effectively_constant(differences):
        # Shapiro–Wilk needs three points, and on a sample that barely varies it
        # reports a number scipy itself warns is unreliable. The distribution-
        # free test is the conservative default in both cases.
        return "wilcoxon", None
    normality_p = float(stats.shapiro(differences).pvalue)
    return ("paired_t" if normality_p >= NORMALITY_ALPHA else "wilcoxon"), normality_p


def _effectively_constant(differences: np.ndarray[Any, Any]) -> bool:
    """Whether the spread is float noise rather than variation.

    A condition that costs the same on every seed produces differences that are
    equal up to the last bits. Feeding those to a normality test asks it to
    characterise rounding error.
    """
    return bool(np.allclose(differences, differences[0]))


def _run_test(
    test: Test,
    left: np.ndarray[Any, Any],
    right: np.ndarray[Any, Any],
    differences: np.ndarray[Any, Any],
) -> tuple[float | None, float | None]:
    if test == "paired_t":
        result = stats.ttest_rel(right, left)
        return float(result.statistic), float(result.pvalue)
    if not np.any(differences != 0):
        # Wilcoxon has nothing to rank; identical samples are p = 1 by
        # definition rather than an error to propagate.
        return 0.0, 1.0
    result = stats.wilcoxon(differences, alternative="two-sided")
    return float(result.statistic), float(result.pvalue)


def _cohens_dz(differences: np.ndarray[Any, Any]) -> float | None:
    """Paired Cohen's dₙ: the mean difference in units of its own spread."""
    sd = float(np.std(differences, ddof=1))
    if sd == 0:
        return None
    return float(np.mean(differences)) / sd


def _rank_biserial(differences: np.ndarray[Any, Any]) -> float | None:
    """Matched-pairs rank-biserial correlation, the Wilcoxon effect size.

    Runs from -1 to 1: the share of signed rank mass pointing one way.
    """
    nonzero = differences[differences != 0]
    if nonzero.size == 0:
        return 0.0
    ranks = stats.rankdata(np.abs(nonzero))
    positive = float(ranks[nonzero > 0].sum())
    negative = float(ranks[nonzero < 0].sum())
    total = positive + negative
    return (positive - negative) / total if total else None


def _reachability_note(test: Test, n: int) -> str:
    if test == "wilcoxon" and n < MIN_PAIRS_FOR_SIGNIFICANCE:
        minimum = 2 / (2**n)
        return (
            f"n={n}: a two-sided Wilcoxon test cannot reach p<{ALPHA} here "
            f"(smallest attainable p is {minimum:.4f}); read the effect size"
        )
    return ""
