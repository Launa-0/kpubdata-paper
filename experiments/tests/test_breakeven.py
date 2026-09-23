"""Gold를 몇 번 재사용해야 미리 만든 비용이 회수되는가 (#19 Discussion)."""

from __future__ import annotations

import pytest

from kpx.metrics.breakeven import BreakEvenError, break_even


class TestBreakEven:
    def test_the_build_cost_divided_by_what_each_analysis_saves(self) -> None:
        report = break_even(build_cost=50.0, baseline_per_analysis=5.0, derived_per_analysis=1.0)

        assert report.saving_per_analysis == pytest.approx(4.0)
        assert report.analyses_to_break_even == 13  # 50/4 = 12.5 -> 13번째에 회수

    def test_an_exact_division_does_not_round_up_a_whole_analysis(self) -> None:
        report = break_even(build_cost=40.0, baseline_per_analysis=5.0, derived_per_analysis=1.0)

        assert report.analyses_to_break_even == 10

    def test_a_derived_layer_that_saves_nothing_never_pays_for_itself(self) -> None:
        report = break_even(build_cost=50.0, baseline_per_analysis=1.0, derived_per_analysis=1.0)

        assert report.analyses_to_break_even is None

    def test_a_derived_layer_that_costs_more_never_pays_for_itself(self) -> None:
        report = break_even(build_cost=50.0, baseline_per_analysis=1.0, derived_per_analysis=2.0)

        assert report.analyses_to_break_even is None

    def test_a_free_build_pays_for_itself_immediately(self) -> None:
        report = break_even(build_cost=0.0, baseline_per_analysis=5.0, derived_per_analysis=1.0)

        assert report.analyses_to_break_even == 0

    def test_negative_costs_are_refused(self) -> None:
        with pytest.raises(BreakEvenError, match="negative"):
            break_even(build_cost=-1.0, baseline_per_analysis=5.0, derived_per_analysis=1.0)

    def test_the_total_cost_of_n_analyses_is_reported_both_ways(self) -> None:
        report = break_even(build_cost=50.0, baseline_per_analysis=5.0, derived_per_analysis=1.0)

        assert report.baseline_total(10) == pytest.approx(50.0)
        assert report.derived_total(10) == pytest.approx(60.0)
        assert report.derived_total(20) < report.baseline_total(20)
