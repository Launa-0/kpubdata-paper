from __future__ import annotations

import pandas as pd
import pytest

from kpx.stats import (
    ALPHA,
    MIN_PAIRS_FOR_SIGNIFICANCE,
    Comparison,
    StatisticsError,
    Summary,
    compare,
    compare_conditions,
    holm,
    summary_table,
)


def results_frame() -> pd.DataFrame:
    """Five seeds, three conditions, a metric where gold is cheapest."""
    rows = []
    for seed in range(5):
        rows.extend(
            [
                {
                    "task": "task02",
                    "condition": "bronze",
                    "seed": seed,
                    "runtime_seconds": 10 + seed * 0.1,
                },
                {
                    "task": "task02",
                    "condition": "silver",
                    "seed": seed,
                    "runtime_seconds": 6 + seed * 0.1,
                },
                {
                    "task": "task02",
                    "condition": "gold",
                    "seed": seed,
                    "runtime_seconds": 3 + seed * 0.1,
                },
            ]
        )
    return pd.DataFrame(rows)


# -- summaries -------------------------------------------------------------


def test_summary_reports_centre_and_spread() -> None:
    summary = Summary.of([1.0, 2.0, 3.0])
    assert summary.n == 3
    assert summary.mean == 2.0
    assert summary.median == 2.0
    assert summary.sd == 1.0


def test_summary_interval_brackets_the_mean() -> None:
    summary = Summary.of([1.0, 2.0, 3.0, 4.0])
    assert summary.ci_low is not None and summary.ci_high is not None
    assert summary.ci_low < summary.mean < summary.ci_high


def test_spread_of_a_single_observation_is_undefined_not_zero() -> None:
    summary = Summary.of([4.0])
    assert summary.sd is None
    assert summary.ci_low is None


def test_an_empty_sample_is_refused() -> None:
    with pytest.raises(StatisticsError, match="empty sample"):
        Summary.of([])


# -- the decision rule -----------------------------------------------------


def test_normal_differences_route_to_the_paired_t_test() -> None:
    baseline = [10.0, 10.2, 9.8, 10.1, 9.9, 10.05]
    condition = [8.0, 8.3, 7.7, 8.1, 7.95, 8.1]
    result = compare(baseline, condition, metric="runtime_seconds")
    assert result.test == "paired_t"
    assert result.normality_p is not None and result.normality_p >= 0.05


def test_non_normal_differences_route_to_wilcoxon() -> None:
    """One wild pair is enough for Shapiro–Wilk to reject."""
    baseline = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    condition = [1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 90.0]
    result = compare(baseline, condition, metric="runtime_seconds")
    assert result.test == "wilcoxon"
    assert result.normality_p is not None and result.normality_p < 0.05


def test_too_few_pairs_for_a_normality_test_use_wilcoxon() -> None:
    result = compare([1.0, 2.0], [3.0, 5.0], metric="rows")
    assert result.test == "wilcoxon"
    assert result.normality_p is None


def test_differences_that_are_constant_up_to_float_noise_skip_the_normality_test() -> None:
    """Otherwise Shapiro is asked to characterise rounding error.

    scipy warns that such a result is unreliable, and a statistics module
    should not route on a number its own library disowns.
    """
    baseline = [10.0 + seed * 0.1 for seed in range(5)]
    condition = [6.0 + seed * 0.1 for seed in range(5)]
    result = compare(baseline, condition, metric="runtime_seconds")
    assert result.test == "wilcoxon"
    assert result.normality_p is None


def test_identical_samples_are_p_one_rather_than_an_error() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    result = compare(values, values, metric="rows")
    assert result.p_value == 1.0
    assert result.rank_biserial == 0.0


def test_a_single_pair_gets_no_test() -> None:
    result = compare([1.0], [2.0], metric="rows")
    assert result.test == "none"
    assert result.p_value is None
    assert "at least 2" in result.note


def test_mismatched_sample_lengths_are_refused() -> None:
    with pytest.raises(StatisticsError, match="same length"):
        compare([1.0, 2.0], [1.0], metric="rows")


# -- the small-n limit the design runs into --------------------------------


def test_five_seeds_cannot_reach_significance_under_wilcoxon() -> None:
    """A property of the design, not of the data.

    Two-sided Wilcoxon at n=5 has a smallest attainable p of 0.0625, so no
    effect however large can clear 0.05. Reporting p alone would read as a null
    result when it is the strongest the test can express.
    """
    # Skewed differences, so the rule routes this to Wilcoxon.
    baseline = [2.0, 2.0, 2.0, 2.0, 2.0]
    condition = [1.0, 1.0, 1.0, 1.0, -48.0]
    result = compare(baseline, condition, metric="runtime_seconds")
    assert result.test == "wilcoxon"
    assert result.n == 5
    assert result.p_value == pytest.approx(0.0625)
    assert result.p_value > ALPHA
    assert not result.significance_reachable
    assert "cannot reach" in result.note


def test_one_more_seed_makes_significance_reachable() -> None:
    baseline = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    condition = [1.0, 1.0, 1.0, 1.0, 1.0, -48.0]
    result = compare(baseline, condition, metric="runtime_seconds")
    assert result.test == "wilcoxon"
    assert result.n == MIN_PAIRS_FOR_SIGNIFICANCE
    assert result.significance_reachable


def test_the_same_five_pairs_are_reachable_through_the_t_test() -> None:
    """At this n the *route* decides whether significance is attainable at all.

    Well-behaved differences reach p≈0.013 through the t-test; skewed ones are
    capped at 0.0625 by Wilcoxon. That is a property of the design, and the
    reason the paper leads with effect sizes rather than p-values.
    """
    result = compare([10.0, 20.0, 30.0, 40.0, 50.0], [1.0, 2.0, 3.0, 4.0, 5.0], metric="x")
    assert result.test == "paired_t"
    assert result.significance_reachable
    assert result.p_value is not None and result.p_value < ALPHA


def test_a_huge_effect_is_still_reported_when_p_cannot_clear_alpha() -> None:
    """This is why the effect size is not optional."""
    result = compare([2.0, 2.0, 2.0, 2.0, 2.0], [1.0, 1.0, 1.0, 1.0, -48.0], metric="x")
    assert result.test == "wilcoxon"
    assert result.rank_biserial == -1.0
    assert result.cohens_dz is not None
    assert not result.significant
    assert not result.significance_reachable


# -- effect sizes ----------------------------------------------------------


def test_cohens_dz_is_the_mean_difference_over_its_spread() -> None:
    """Differences are 1,2,3,4: mean 2.5 over sd 1.290994."""
    result = compare([0.0, 0.0, 0.0, 0.0], [1.0, 2.0, 3.0, 4.0], metric="x")
    assert result.cohens_dz == pytest.approx(1.936492, rel=1e-6)


def test_cohens_dz_is_undefined_for_a_constant_difference() -> None:
    result = compare([1.0, 2.0, 3.0], [2.0, 3.0, 4.0], metric="x")
    assert result.cohens_dz is None


def test_rank_biserial_runs_from_minus_one_to_one() -> None:
    all_up = compare([1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0], metric="x")
    all_down = compare([5.0, 6.0, 7.0, 8.0], [1.0, 2.0, 3.0, 4.0], metric="x")
    assert all_up.rank_biserial == 1.0
    assert all_down.rank_biserial == -1.0


# -- pairing from a results frame ------------------------------------------


def test_conditions_are_compared_against_the_baseline() -> None:
    comparisons = compare_conditions(results_frame(), "runtime_seconds", task="task02")
    assert [c.condition for c in comparisons] == ["silver", "gold"]
    assert all(c.baseline == "bronze" for c in comparisons)
    assert all(c.n == 5 for c in comparisons)


def test_comparisons_come_back_in_medallion_order() -> None:
    frame = results_frame()
    frame = frame[frame["condition"].isin(["bronze", "gold", "silver"])]
    comparisons = compare_conditions(frame, "runtime_seconds", task="task02")
    assert [c.condition for c in comparisons] == ["silver", "gold"]


def test_an_unpaired_seed_is_dropped_and_counted() -> None:
    """Matching by position would silently compare different runs."""
    frame = results_frame()
    frame = frame[~((frame["condition"] == "silver") & (frame["seed"] == 4))]
    (silver, _gold) = compare_conditions(frame, "runtime_seconds", task="task02")
    assert silver.n == 4
    assert silver.unpaired == 1


def test_a_missing_baseline_is_refused() -> None:
    frame = results_frame()
    frame = frame[frame["condition"] != "bronze"]
    with pytest.raises(StatisticsError, match="baseline condition"):
        compare_conditions(frame, "runtime_seconds", task="task02")


def test_a_missing_column_is_refused() -> None:
    with pytest.raises(StatisticsError, match="no 'mae' column"):
        compare_conditions(results_frame(), "mae", task="task02")


def test_no_matching_rows_is_refused() -> None:
    with pytest.raises(StatisticsError, match="no rows"):
        compare_conditions(results_frame(), "runtime_seconds", task="task99")


# -- multiple comparisons --------------------------------------------------


def test_holm_adjusts_upward_and_preserves_order() -> None:
    raw = [0.01, 0.02, 0.04]
    comparisons = [
        Comparison(
            metric="x",
            baseline="bronze",
            condition="silver",
            task=None,
            n=6,
            baseline_summary=None,
            condition_summary=None,
            difference=None,
            differences=(),
            test="paired_t",
            p_value=p,
        )
        for p in raw
    ]
    adjusted = [c.p_adjusted for c in holm(comparisons)]
    assert adjusted == [pytest.approx(0.03), pytest.approx(0.04), pytest.approx(0.04)]


def test_holm_is_monotone() -> None:
    """A step-down correction must never decrease as raw p increases."""
    comparisons = [
        Comparison(
            metric="x",
            baseline="bronze",
            condition="silver",
            task=None,
            n=6,
            baseline_summary=None,
            condition_summary=None,
            difference=None,
            differences=(),
            test="paired_t",
            p_value=p,
        )
        for p in (0.001, 0.5, 0.02)
    ]
    adjusted = [c.p_adjusted for c in holm(comparisons)]
    assert adjusted[0] is not None and adjusted[2] is not None and adjusted[1] is not None
    assert adjusted[0] <= adjusted[2] <= adjusted[1]


def test_holm_leaves_untested_comparisons_alone() -> None:
    untested = compare([1.0], [2.0], metric="x")
    assert holm([untested])[0].p_adjusted is None


def test_holm_of_nothing_is_nothing() -> None:
    assert holm([]) == []


def test_significance_uses_the_adjusted_p_value() -> None:
    comparison = Comparison(
        metric="x",
        baseline="bronze",
        condition="silver",
        task=None,
        n=6,
        baseline_summary=None,
        condition_summary=None,
        difference=None,
        differences=(),
        test="paired_t",
        p_value=0.01,
        p_adjusted=0.30,
    )
    assert not comparison.significant


# -- the table -------------------------------------------------------------


def test_summary_table_carries_effect_size_beside_the_p_value() -> None:
    table = summary_table(
        holm(compare_conditions(results_frame(), "runtime_seconds", task="task02"))
    )
    assert {"p_value", "p_adjusted", "cohens_dz", "significance_reachable"} <= set(table.columns)
    assert len(table) == 2


def test_summary_table_of_nothing_is_empty_but_shaped() -> None:
    table = summary_table([])
    assert table.empty
    assert "cohens_dz" in table.columns
