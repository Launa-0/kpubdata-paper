"""Task 3 — 매매·전월세 조인이 네 조건에서 같은 곳에 도착하는지 검증한다 (#15).

Task 1과 같은 불변식에 더해, 조인 과제에만 있는 것을 하나 더 고정한다: Bronze /
Silver / Monolithic의 ``join_matching_rate`` 는 **같아야 한다.** 다르게 나오면
세 조건이 서로 다른 정제를 한 것이고, 그건 계층의 효과가 아니라 baseline bias다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from kpx.contract import AnalysisInput, RunContext
from kpx.tasks.task03_join import analysis, bronze, gold, monolithic, silver
from kpx.tasks.task03_join import transforms as tf

TRADES = "seoul-apartment-trades"
RENTS = "seoul-apartment-rent"
GOLD_DATASET = "seoul-apartment-trades-rent-monthly"


class _Resolver:
    """``(dataset, layer)`` 로 프레임을 돌려준다 — Task 3는 두 데이터셋을 읽는다."""

    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        self._frames = frames

    def load(self, dataset: str, layer: str) -> pd.DataFrame:
        return self._frames[(dataset, layer)].copy()

    def path(self, dataset: str, layer: str) -> str:
        return f"memory://{dataset}/{layer}"


def _bronze_trades() -> pd.DataFrame:
    """Bronze 표현 그대로 — 쉼표 금액, 문자열 면적, 장식이 붙은 단지명."""
    return pd.DataFrame(
        {
            "sggCd": ["11110", "11110", "11110", "11140"],
            "aptNm": [
                "래미안 강남 힐즈(1단지)",
                "래미안 강남 힐즈(1단지)",
                "경희궁자이",
                "목동아파트",
            ],
            "excluUseAr": ["84.97", "59.8", "84.9", "114.7"],
            "dealAmount": ["120,000", "90,000", "150,000", "160,000"],
            "dealYear": [2021, 2021, 2021, 2021],
            "dealMonth": [3, 3, 3, 3],
        }
    )


def _bronze_rents() -> pd.DataFrame:
    """전세 세 건과 월세 한 건. 월세는 전세가율 계산에 들어가면 안 된다."""
    return pd.DataFrame(
        {
            "sggCd": ["11110", "11110", "11110", "11140"],
            "aptNm": ["래미안강남힐즈 1단지", "래미안강남힐즈 1단지", "경희궁자이", "목동아파트"],
            "excluUseAr": ["84.9", "59.84", "84.97", "114.7"],
            "deposit": ["72,000", "54,000", "90,000", "20,000"],
            "monthlyRent": ["0", "0", "0", "150"],
            "dealYear": [2021, 2021, 2021, 2021],
            "dealMonth": [3, 3, 3, 3],
        }
    )


def _silver_trades() -> pd.DataFrame:
    """canonical 표현 — 타입이 맞고 단지명도 이미 정규화돼 있다."""
    frame = _bronze_trades()
    return pd.DataFrame(
        {
            "district_code": frame["sggCd"],
            "apt_name": frame["aptNm"].map(tf.normalize_apt_name),
            "area_m2": frame["excluUseAr"].astype(float),
            "price_10k_krw": frame["dealAmount"].map(tf.parse_amount_10k),
            "deal_year": frame["dealYear"],
            "deal_month": frame["dealMonth"],
        }
    )


def _silver_rents() -> pd.DataFrame:
    frame = _bronze_rents()
    return pd.DataFrame(
        {
            "district_code": frame["sggCd"],
            "apt_name": frame["aptNm"].map(tf.normalize_apt_name),
            "area_m2": frame["excluUseAr"].astype(float),
            "deposit_10k_krw": frame["deposit"].map(tf.parse_amount_10k),
            "monthly_rent_10k_krw": frame["monthlyRent"].map(tf.parse_amount_10k),
            "deal_year": frame["dealYear"],
            "deal_month": frame["dealMonth"],
        }
    )


def _context(condition: str) -> RunContext:
    frames: dict[tuple[str, str], pd.DataFrame] = {
        (TRADES, "bronze"): _bronze_trades(),
        (RENTS, "bronze"): _bronze_rents(),
        (TRADES, "silver"): _silver_trades(),
        (RENTS, "silver"): _silver_rents(),
    }
    if condition == "gold":
        frames[(GOLD_DATASET, "gold")] = silver.Runner().prepare(_context("silver")).frame.copy()
    return RunContext(
        task="task03",
        condition=condition,  # type: ignore[arg-type]
        run_id=f"task03/{condition}/seed0",
        snapshot_id="seoul-apartment-trades/test",
        pipeline_version="0.1.0",
        datasets=_Resolver(frames),
    )


def _prepare(module: object) -> AnalysisInput:
    condition = module.Runner.CONDITION  # type: ignore[attr-defined]
    return module.Runner().prepare(_context(condition))  # type: ignore[attr-defined]


ALL_MODULES = [bronze, silver, gold, monolithic]
SELF_JOINING = [bronze, silver, monolithic]


class TestTransforms:
    def test_comma_separated_deposit_is_read(self) -> None:
        assert tf.parse_amount_10k("72,000") == 72000.0

    def test_unreadable_amount_is_missing_not_zero(self) -> None:
        assert tf.parse_amount_10k("해당없음") is None

    def test_district_code_keeps_its_leading_zero(self) -> None:
        assert tf.parse_district_code(1110) == "01110"

    def test_apt_name_drops_spacing_and_decoration(self) -> None:
        """같은 단지가 두 데이터셋에서 다르게 적히는 것이 조인의 주된 실패 원인이다."""
        assert tf.normalize_apt_name("래미안 강남 힐즈(1단지)") == tf.normalize_apt_name(
            "래미안강남힐즈 1단지"
        )

    def test_apt_name_normalizes_unicode_form(self) -> None:
        """자소 분리형(NFD)으로 들어온 한글은 바이트가 달라 동등비교가 실패한다."""
        import unicodedata

        composed = tf.normalize_apt_name(unicodedata.normalize("NFC", "경희궁자이"))
        decomposed = tf.normalize_apt_name(unicodedata.normalize("NFD", "경희궁자이"))
        assert composed == decomposed

    def test_apt_name_of_nothing_is_missing(self) -> None:
        assert tf.normalize_apt_name(" -- ") is None

    def test_apt_name_keeps_the_building_number_inside_parentheses(self) -> None:
        """괄호 안 내용까지 지우면 1단지와 2단지가 같은 키가 된다.

        조인 실패는 unmatched로 드러나지만, 서로 다른 동을 합친 평균은 아무 표시
        없이 전세가율에 섞인다.
        """
        assert tf.normalize_apt_name("래미안(1단지)") != tf.normalize_apt_name("래미안(2단지)")

    def test_area_bucket_absorbs_reporting_jitter(self) -> None:
        """84.97과 84.9는 같은 세대다. 실수 동등비교로 조인하면 매칭이 무너진다."""
        assert tf.area_bucket("84.97") == tf.area_bucket("84.9")

    def test_area_bucket_separates_sizes_that_differ(self) -> None:
        assert tf.area_bucket(59.8) != tf.area_bucket(84.9)

    def test_area_bucket_of_zero_is_missing(self) -> None:
        assert tf.area_bucket(0) is None

    def test_monthly_rent_contracts_are_not_jeonse(self) -> None:
        """월세 보증금은 전세보증금과 다른 양이다. 섞으면 전세가율이 아니다."""
        rents = pd.Series([0.0, 150.0, None])
        assert list(tf.is_jeonse(rents)) == [True, False, True]

    def test_unit_price_does_not_diverge_on_zero_area(self) -> None:
        prices = tf.unit_price(pd.Series([120000.0]), pd.Series([0.0]))
        assert prices.isna().all()

    def test_folding_collapses_repeated_keys(self) -> None:
        """접지 않고 조인하면 n×m 곱집합이 생겨 평균이 거래 빈도에 끌려간다."""
        frame = pd.DataFrame(
            {
                "district_code": ["11110", "11110"],
                "apt_name": ["a", "a"],
                "year_month": ["2021-03", "2021-03"],
                "area_bucket": ["60-85", "60-85"],
                "value": [100.0, 200.0],
            }
        )
        folded = tf.fold_to_join_keys(frame, "value", "value")
        assert len(folded) == 1
        assert folded["value"].iloc[0] == 150.0


class TestConditionsAgree:
    @pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.Runner.CONDITION)
    def test_reaches_the_same_analysis_input(self, module: object) -> None:
        expected = _prepare(silver).frame
        pd.testing.assert_frame_equal(_prepare(module).frame, expected)

    @pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.Runner.CONDITION)
    def test_reaches_the_same_jeonse_ratio(self, module: object) -> None:
        expected = analysis.analyze(_prepare(silver)).result
        pd.testing.assert_frame_equal(analysis.analyze(_prepare(module)).result, expected)

    @pytest.mark.parametrize("module", SELF_JOINING, ids=lambda m: m.Runner.CONDITION)
    def test_matching_rate_is_equal_across_conditions_that_join(self, module: object) -> None:
        """조건마다 다르면 정제 규칙이 갈린 것이다 — 계층의 효과가 아니라 버그다.

        Bronze가 raw 단지명으로 조인하게 두면 매칭률이 실제로 떨어지지만, 그것은
        baseline을 일부러 못 하게 만든 것이다 (#12).
        """
        assert _prepare(module).notes["join_matching_rate"] == pytest.approx(
            _prepare(silver).notes["join_matching_rate"]
        )


class TestJoin:
    def test_a_unit_matches_across_the_two_datasets(self) -> None:
        """조인이 실제로 맞는지 — 이름·면적이 흔들려도 같은 세대로 붙어야 한다."""
        assert _prepare(silver).notes["join_matching_rate"] > 0

    def test_a_sale_without_a_jeonse_counterpart_is_unmatched(self) -> None:
        """목동아파트는 월세뿐이라 전세 짝이 없다."""
        notes = _prepare(silver).notes
        assert notes["unmatched_sale_keys"] >= 1
        assert notes["join_matching_rate"] < 1

    def test_monthly_rent_never_enters_the_ratio(self) -> None:
        prepared = _prepare(silver)
        assert "11140" not in set(prepared.frame["district_code"])

    def test_rows_without_join_keys_are_reported(self) -> None:
        frame = pd.DataFrame(
            {
                "district_code": ["11110", None],
                "apt_name": ["a", "b"],
                "year_month": ["2021-03", "2021-03"],
                "area_bucket": ["60-85", "60-85"],
            }
        )
        assert tf.invalid_key_rate(frame) == pytest.approx(0.5)

    def test_matching_rate_of_an_empty_sale_side_is_zero_not_undefined(self) -> None:
        empty = pd.DataFrame(columns=[*tf.JOIN_KEYS, "sale_price_per_m2"])
        diagnostics = tf.join_diagnostics(empty, empty, empty)
        assert diagnostics["join_matching_rate"] == 0.0


class TestGoldHoldsNoAnswer:
    def test_gold_does_not_carry_the_ratio(self) -> None:
        """Gold가 전세가율을 담으면 정답을 미리 저장한 셈이 된다 (Internal Validity)."""
        assert "jeonse_ratio" not in _prepare(gold).frame.columns

    def test_the_analysis_produces_the_ratio(self) -> None:
        result = analysis.analyze(_prepare(gold)).result
        assert "jeonse_ratio" in result.columns
        assert "jeonse_ratio_yoy_change" in result.columns


class TestAnalysis:
    def test_ratio_is_jeonse_over_sale(self) -> None:
        prepared = AnalysisInput(
            frame=pd.DataFrame(
                {
                    "district_code": ["11110"],
                    "year_month": ["2021-03"],
                    "mean_sale_price_per_m2": [10_000_000.0],
                    "mean_jeonse_deposit_per_m2": [6_000_000.0],
                    "n_matched": [1],
                }
            )
        )
        assert analysis.analyze(prepared).result["jeonse_ratio"].iloc[0] == pytest.approx(0.6)

    def test_a_zero_sale_price_does_not_produce_infinity(self) -> None:
        prepared = AnalysisInput(
            frame=pd.DataFrame(
                {
                    "district_code": ["11110"],
                    "year_month": ["2021-03"],
                    "mean_sale_price_per_m2": [0.0],
                    "mean_jeonse_deposit_per_m2": [6_000_000.0],
                    "n_matched": [1],
                }
            )
        )
        assert analysis.analyze(prepared).result["jeonse_ratio"].isna().all()

    def test_year_over_year_is_found_by_key_not_by_position(self) -> None:
        """조인이 비는 달은 행이 없다 — 12행 전이 전년 동월이라는 보장이 없다."""
        prepared = AnalysisInput(
            frame=pd.DataFrame(
                {
                    "district_code": ["11110", "11110"],
                    "year_month": ["2020-03", "2021-03"],
                    "mean_sale_price_per_m2": [10_000_000.0, 10_000_000.0],
                    "mean_jeonse_deposit_per_m2": [5_000_000.0, 6_000_000.0],
                    "n_matched": [1, 1],
                }
            )
        )
        result = analysis.analyze(prepared).result
        change = result.loc[result["year_month"] == "2021-03", "jeonse_ratio_yoy_change"]
        assert change.iloc[0] == pytest.approx(0.1)

    def test_a_month_without_its_previous_year_has_no_change(self) -> None:
        result = analysis.analyze(_prepare(silver)).result
        assert result["jeonse_ratio_yoy_change"].isna().all()

    def test_a_wrongly_shaped_input_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="missing required column"):
            analysis.analyze(AnalysisInput(frame=pd.DataFrame({"district_code": []})))
