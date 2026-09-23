from __future__ import annotations

import pandas as pd
import pytest

from kpx.metrics.reference import (
    ReferenceError,
    ReferenceSpec,
    compare_to_reference,
)

MONTHS = [f"2024-{m:02d}" for m in range(1, 13)]


def frame(values: list[float], region: str = "강남구", periods: list[str] | None = None):
    periods = periods or MONTHS[: len(values)]
    return pd.DataFrame({"region": region, "period": periods, "value": values})


def rising(start: float, step: float, n: int = 12) -> list[float]:
    return [start + step * i for i in range(n)]


# -- APD --------------------------------------------------------------------


def test_apd_is_the_mean_absolute_percentage_gap() -> None:
    report = compare_to_reference(
        frame([110.0] * 12), frame([100.0] * 12), ReferenceSpec(), task="task01"
    )
    assert report.apd == pytest.approx(10.0)


def test_an_index_has_no_apd() -> None:
    """A base-100 index and a price in 만원/㎡ are not the same quantity.

    Returning a number here would look like a measurement of agreement while
    being arithmetic on unlike units.
    """
    report = compare_to_reference(
        frame([500, 505, 512, 516, 525, 531, 538, 540, 551, 559, 566, 570]),
        frame([100, 101, 103, 104, 106, 107, 109, 109.5, 111, 113, 114, 115]),
        ReferenceSpec(kind="index"),
        task="task01",
    )
    assert report.apd is None
    assert report.trend_correlation == pytest.approx(0.7165, abs=1e-3)


# -- trend correlation ------------------------------------------------------


def test_trend_correlation_is_computed_on_changes_not_levels() -> None:
    """Levels of two rising series correlate at ~1.0 whatever their trends do.

    Here the levels both rise, so a level correlation would read as near-perfect
    agreement, while the month-to-month changes are in opposition.
    """
    pipeline = frame([100, 110, 111, 121, 122, 132, 133, 143, 144, 154, 155, 165])
    reference = frame([100, 101, 111, 112, 122, 123, 133, 134, 144, 145, 155, 156])
    report = compare_to_reference(pipeline, reference, ReferenceSpec(), task="task01")

    assert report.trend_correlation is not None
    assert report.trend_correlation < 0
    assert report.trend_correlation == pytest.approx(-1.0)
    levels = pipeline["value"].corr(reference["value"])
    assert levels > 0.95


def test_a_flat_series_has_no_trend_correlation() -> None:
    """Zero variance gives nan, and nan must not reach a mean as a number."""
    report = compare_to_reference(
        frame(rising(100, 1)), frame([100.0] * 12), ReferenceSpec(), task="task01"
    )
    assert report.trend_correlation is None


# -- direction agreement ----------------------------------------------------


def test_direction_agreement_counts_changes_moving_the_same_way() -> None:
    pipeline = frame([10, 11, 12, 11, 12, 13, 12, 13, 14, 13, 14, 15])
    reference = frame([20, 21, 22, 21, 22, 23, 22, 23, 24, 23, 24, 25])
    report = compare_to_reference(pipeline, reference, ReferenceSpec(), task="task01")
    assert report.direction_agreement == pytest.approx(1.0)


def test_a_flat_reference_month_is_not_a_disagreement() -> None:
    """The reference is published to 0.1; our series moves by 0.02 a month.

    The reference is flat in ten of eleven months because it cannot print a move
    that small. Scoring those as disagreements would measure publication
    rounding, so a side that did not move contributes no direction at all.
    """
    pipeline = frame([50.0 + 0.02 * i for i in range(12)])
    reference = frame([50.0] * 6 + [50.1] * 6)

    report = compare_to_reference(pipeline, reference, ReferenceSpec(resolution=0.1), task="task03")
    assert report.changes_compared == 11
    assert report.direction_agreement == pytest.approx(1.0)


def test_resolution_reports_how_fine_our_movement_was_without_filtering() -> None:
    """``resolution`` is a diagnostic: agreement earned over movement the
    reference could not have printed is a weaker claim, and the count says so."""
    pipeline = frame([50.0 + 0.02 * i for i in range(12)])
    reference = frame([50.0] * 6 + [50.1] * 6)

    coarse = compare_to_reference(pipeline, reference, ReferenceSpec(resolution=0.1), task="task03")
    blind = compare_to_reference(pipeline, reference, ReferenceSpec(), task="task03")

    assert coarse.below_resolution == 11
    assert blind.below_resolution == 0
    assert coarse.direction_agreement == blind.direction_agreement


# -- excluded periods -------------------------------------------------------


def test_an_excluded_period_drops_the_change_but_keeps_the_levels() -> None:
    """The 2021-07 sample redesign is the case this exists for.

    A break in the reference is not a disagreement, but the level on either side
    of it is still a statement about one month and stays in the comparison.
    """
    periods = ["2021-05", "2021-06", "2021-07", "2021-08"]
    pipeline = frame([50.0, 50.1, 50.2, 50.3], periods=periods)
    reference = frame([50.0, 50.1, 45.0, 45.1], periods=periods)
    spec = ReferenceSpec(excluded_periods=frozenset({"2021-07"}), min_overlap=4)

    report = compare_to_reference(pipeline, reference, spec, task="task03")
    assert report.aligned == 4
    assert report.changes_compared == 2
    assert report.excluded_changes == 1
    assert report.direction_agreement == pytest.approx(1.0)

    kept = compare_to_reference(pipeline, reference, ReferenceSpec(min_overlap=4), task="task03")
    assert kept.direction_agreement == pytest.approx(2.0 / 3)


def test_excluding_a_period_does_not_change_the_level_comparison() -> None:
    periods = ["2021-05", "2021-06", "2021-07", "2021-08"]
    pipeline = frame([50.0, 50.0, 50.0, 50.0], periods=periods)
    reference = frame([50.0, 50.0, 45.0, 45.0], periods=periods)

    with_exclusion = compare_to_reference(
        pipeline,
        reference,
        ReferenceSpec(excluded_periods=frozenset({"2021-07"}), min_overlap=4),
        task="task03",
    )
    without = compare_to_reference(pipeline, reference, ReferenceSpec(min_overlap=4), task="task03")
    assert with_exclusion.apd == without.apd


# -- alignment --------------------------------------------------------------


def test_regions_missing_from_one_side_are_reported_not_dropped() -> None:
    pipeline = pd.concat([frame(rising(50, 1), "강남구"), frame(rising(40, 1), "종로구")])
    reference = pd.concat([frame(rising(50, 1), "강남구"), frame(rising(30, 1), "중구")])
    report = compare_to_reference(pipeline, reference, ReferenceSpec(), task="task01")

    assert report.unmatched_pipeline == ("종로구",)
    assert report.unmatched_reference == ("중구",)
    assert report.aligned == 12


def test_too_little_overlap_is_refused() -> None:
    """A metric over four months would describe the overlap, not the agreement."""
    with pytest.raises(ReferenceError, match="aligned"):
        compare_to_reference(
            frame(rising(50, 1, 4)), frame(rising(50, 1, 4)), ReferenceSpec(), task="task01"
        )


def test_changes_do_not_run_from_one_region_into_the_next() -> None:
    """A region's first period contributes no change."""
    pipeline = pd.concat([frame(rising(50, 1, 6), "강남구"), frame(rising(90, 1, 6), "종로구")])
    reference = pd.concat([frame(rising(50, 1, 6), "강남구"), frame(rising(90, 1, 6), "종로구")])
    report = compare_to_reference(pipeline, reference, ReferenceSpec(min_overlap=12), task="task01")
    assert report.aligned == 12
    assert report.changes_compared == 10


# -- refusals ---------------------------------------------------------------


def test_two_values_for_one_region_and_period_are_refused() -> None:
    doubled = pd.DataFrame(
        {"region": "강남구", "period": ["2024-01", "2024-01"], "value": [50.0, 60.0]}
    )
    with pytest.raises(ReferenceError, match="more than one value"):
        compare_to_reference(doubled, frame(rising(50, 1)), ReferenceSpec(), task="task01")


def test_a_missing_column_is_refused() -> None:
    with pytest.raises(ReferenceError, match="value"):
        compare_to_reference(
            pd.DataFrame({"region": ["강남구"], "period": ["2024-01"]}),
            frame(rising(50, 1)),
            ReferenceSpec(),
            task="task01",
        )


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ReferenceError, match="unknown reference kind"):
        ReferenceSpec(kind="ratio")  # type: ignore[arg-type]


def test_min_overlap_below_two_is_refused() -> None:
    with pytest.raises(ReferenceError, match="not a trend"):
        ReferenceSpec(min_overlap=1)


# -- the result row ---------------------------------------------------------


def test_to_dict_leaves_an_undefined_metric_absent() -> None:
    """0.0 would enter a mean as perfect agreement; missing does not."""
    from kpx.results import FIELDS

    report = compare_to_reference(
        frame(rising(500, 5)),
        frame(rising(100, 1)),
        ReferenceSpec(kind="index"),
        task="task01",
    )
    fields = report.to_dict()
    assert fields["reference_apd"] is None
    assert set(fields) <= set(FIELDS)
    assert all(FIELDS[name].requirement == "optional" for name in fields)
