"""Task 1 — 네 조건이 같은 분석 입력에 도달하는지 검증한다 (#13).

조건 간 차이는 "어떤 계층에서 시작하는가"여야 하고, 도착지는 같아야 한다. 그래야
결과의 차이를 준비 과정에 귀속시킬 수 있다 (Internal Validity).
"""

from __future__ import annotations

import pandas as pd
import pytest

from kpx.contract import RunContext
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

        assert "yoy_growth" not in prepared.frame.columns

        output = analysis.analyze(prepared)

        assert "yoy_growth" in output.result.columns
