"""Task 1 — 네 조건이 같은 분석 입력에 도달하는지 검증한다 (#13).

조건 간 차이는 "어떤 계층에서 시작하는가"여야 하고, 도착지는 같아야 한다. 그래야
결과의 차이를 준비 과정에 귀속시킬 수 있다 (Internal Validity).
"""

from __future__ import annotations

import pandas as pd
import pytest

from kpx.contract import AnalysisInput, RunContext
from kpx.tasks.task01_price_analysis import analysis, bronze, gold, monolithic, silver
from kpx.tasks.task01_price_analysis import transforms as tf


class _Resolver:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def load(self, dataset: str, layer: str) -> pd.DataFrame:
        return self._frames[layer].copy()

    def path(self, dataset: str, layer: str) -> str:
        return f"memory://{dataset}/{layer}"


def _bronze_frame() -> pd.DataFrame:
    """Bronze의 표현 그대로 — 쉼표 금액, 문자열 면적, 연·월·일 분리."""
    return pd.DataFrame(
        {
            "sggCd": ["11110", "11110", "11110", "11140"],
            "dealAmount": ["31,000", "53,000", "40,000", "120,000"],
            "excluUseAr": ["54.7", "84.93", "54.7", "163.33"],
            "dealYear": [2020, 2020, 2020, 2020],
            "dealMonth": [1, 1, 2, 1],
            "dealDay": [3, 13, 5, 2],
        }
    )


def _silver_frame() -> pd.DataFrame:
    """BuildSpec이 만든 canonical 표현 — 타입이 이미 맞다."""
    return pd.DataFrame(
        {
            "district_code": ["11110", "11110", "11110", "11140"],
            "price_10k_krw": [31000, 53000, 40000, 120000],
            "area_m2": [54.7, 84.93, 54.7, 163.33],
            "deal_year": [2020, 2020, 2020, 2020],
            "deal_month": [1, 1, 2, 1],
        }
    )


def _gold_frame() -> pd.DataFrame:
    """과제용 재사용 데이터셋 — 자치구 × 월 집계까지만. 최종 답은 들어 있지 않다."""
    prepared = silver.Runner().prepare(_context("silver"))
    return prepared.frame.copy()


def _context(condition: str) -> RunContext:
    frames = {"bronze": _bronze_frame(), "silver": _silver_frame()}
    if condition == "gold":
        frames["gold"] = _gold_frame()
    return RunContext(
        task="task01",
        condition=condition,  # type: ignore[arg-type]
        run_id=f"task01/{condition}/seed0",
        snapshot_id="seoul-apartment-trades/test",
        pipeline_version="0.1.0",
        datasets=_Resolver(frames),
    )


class TestTransforms:
    def test_comma_separated_price_is_read(self) -> None:
        assert tf.parse_price_10k("31,000") == 31000.0

    def test_unreadable_price_is_missing_not_zero(self) -> None:
        # 0으로 읽으면 평균이 조용히 내려간다. 결측이어야 집계에서 빠진다.
        assert tf.parse_price_10k("해당없음") is None

    def test_district_code_keeps_its_leading_zero(self) -> None:
        assert tf.parse_district_code(1110) == "01110"

    def test_zero_area_does_not_produce_infinity(self) -> None:
        result = tf.price_per_m2(pd.Series([31000.0]), pd.Series([0.0]))
        assert pd.isna(result.iloc[0])


class TestConditionsAgree:
    """네 조건이 같은 분석 입력에 도달한다."""

    @pytest.mark.parametrize("module", [bronze, silver, monolithic])
    def test_reaches_the_same_shape_as_gold(self, module: object) -> None:
        expected = gold.Runner().prepare(_context("gold")).frame
        actual = module.Runner().prepare(_context(module.Runner.CONDITION)).frame  # type: ignore[attr-defined]

        pd.testing.assert_frame_equal(
            actual.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_like=True,
        )

    def test_aggregate_is_district_by_month(self) -> None:
        prepared = silver.Runner().prepare(_context("silver"))

        assert list(prepared.frame.columns) == [
            "district_code",
            "year_month",
            "n_deals",
            "mean_price_per_m2",
            "median_price_per_m2",
        ]
        assert len(prepared.frame) == 3  # 11110×2020-01, 11110×2020-02, 11140×2020-01


class TestAnalysis:
    def test_yoy_and_ranking_are_computed_by_the_analysis_not_the_layer(self) -> None:
        # Gold가 최종 답(YoY, 순위)을 이미 갖고 있으면 Gold 조건이 부당하게
        # 유리해진다. Gold는 집계까지만, 그 위는 분석의 몫이다 (Internal Validity).
        prepared = gold.Runner().prepare(_context("gold"))

        assert "mean_price_yoy_change" not in prepared.frame.columns

        output = analysis.analyze(prepared)

        assert "mean_price_yoy_change" in output.result.columns


class TestAggregationIsIndependentOfPreCleaning:
    """집계가 쓸 수 없는 행을 스스로 걸러야 네 조건이 같은 곳에 도착한다.

    Bronze와 Monolithic은 집계 전에 dropna를 한다 — 분석자가 그 단계를 직접 짜야
    하는 것이 RQ2가 재는 비용이다. Silver와 Gold는 하지 않는다. 그런데 집계가
    쓸 수 없는 행을 그대로 세면 같은 데이터에서 조건마다 다른 결과가 나온다.

    이번 스냅샷에서 해시가 일치한 것은 결측이 하나도 없었기 때문이지 설계가
    보장해서가 아니었다.
    """

    @staticmethod
    def _frame() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "district_code": ["11110", "11110", "11140", "11140"],
                "year_month": ["2020-01", "2020-01", "2020-02", "2020-02"],
                "price_per_m2": [100.0, None, None, None],
            }
        )

    def test_n_deals_counts_usable_rows_not_every_row(self) -> None:
        aggregated = tf.aggregate_by_district_month(self._frame())

        assert aggregated.loc[0, "n_deals"] == 1

    def test_a_district_month_with_nothing_usable_does_not_appear(self) -> None:
        aggregated = tf.aggregate_by_district_month(self._frame())

        assert list(aggregated["district_code"]) == ["11110"]

    def test_pre_dropping_changes_nothing(self) -> None:
        frame = self._frame()
        pre_dropped = frame.dropna(subset=["district_code", "year_month", "price_per_m2"])

        pd.testing.assert_frame_equal(
            tf.aggregate_by_district_month(frame),
            tf.aggregate_by_district_month(pre_dropped),
        )


class TestYearOnYearNeedsTheActualPreviousYear:
    """12행 전이 전년 동월이라는 보장은 없다.

    거래가 없는 달은 집계에 행이 생기지 않는다. 위치로 12를 세면 그 구멍만큼
    어긋난 달과 비교하게 되고, 결과는 조용히 틀린다.
    """

    @staticmethod
    def _prepared(months: list[str], values: list[float]) -> AnalysisInput:
        return AnalysisInput(
            frame=pd.DataFrame(
                {
                    "district_code": ["11110"] * len(months),
                    "year_month": months,
                    "mean_price_per_m2": values,
                    "n_deals": [1] * len(months),
                }
            )
        )

    def test_a_missing_month_does_not_shift_the_comparison(self) -> None:
        months = [f"2020-{m:02d}" for m in range(1, 13)]
        # 2021-01은 빠지고 2021-02만 있다. 위치로 12를 세면 2020-12와 비교한다.
        months += ["2021-02"]
        values = [100.0] * 12 + [110.0]

        result = analysis.analyze(self._prepared(months, values)).result
        row = result[result["year_month"] == "2021-02"].iloc[0]

        # 2020-02가 기준이어야 한다. 그 값도 100.0이므로 0.10이 맞다.
        assert row["mean_price_yoy_change"] == pytest.approx(0.10)

    def test_a_month_without_its_previous_year_has_no_value(self) -> None:
        result = analysis.analyze(self._prepared(["2020-01", "2020-02"], [100.0, 110.0])).result

        assert result["mean_price_yoy_change"].isna().all()
