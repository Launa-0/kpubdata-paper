"""timing 프로토콜 — 순서, 전략이 하는 일, pandas 엔진의 계약·Gold, 요약."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import _timing  # noqa: E402
import run_task01  # noqa: E402
import run_task03  # noqa: E402
import time_pandas  # noqa: E402
import timing_report  # noqa: E402


class TestSchedule:
    def test_every_cell_gets_one_warmup_and_five_measured_runs_per_strategy(self) -> None:
        slots = list(_timing.schedule())
        measured = Counter((s.task, s.scenario, s.strategy) for s in slots if not s.warmup)
        warmups = Counter((s.task, s.scenario, s.strategy) for s in slots if s.warmup)
        cells = len(_timing.TASKS) * len(_timing.SCENARIOS) * len(_timing.STRATEGIES)
        assert len(measured) == len(warmups) == cells
        assert set(measured.values()) == {_timing.MEASURED_RUNS}
        assert set(warmups.values()) == {_timing.WARMUP_RUNS}

    def test_strategies_alternate_which_goes_first(self) -> None:
        """한 전략이 늘 먼저 돌면 기계 상태의 흐름이 그 전략에만 쌓인다."""
        slots = [s for s in _timing.schedule(("task01",), ("S1",)) if not s.warmup]
        first = [s.strategy for s in slots if s.order_position == 0]
        assert first == ["materialized", "monolithic", "materialized", "monolithic", "materialized"]

    def test_the_order_is_the_same_every_time(self) -> None:
        assert list(_timing.schedule()) == list(_timing.schedule())

    def test_warmup_runs_before_the_measured_rounds_of_its_cell(self) -> None:
        slots = list(_timing.schedule(("task01",), ("S1", "S2")))
        assert [s.warmup for s in slots[:2]] == [True, True]
        assert [s.warmup for s in slots[12:14]] == [True, True]


class Recorder:
    """호출만 기록하는 엔진. 전략이 어느 계층을 읽고 쓰는지 본다."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def read(self, path: Path) -> Any:
        self.calls.append(("read", path.parent.name))
        return path.stem

    def write(self, frame: Any, path: Path) -> None:
        self.calls.append(("write", path.parent.name))

    def contract(self, bronze: Any, dataset: str) -> Any:
        self.calls.append(("contract", dataset))
        return dataset

    def gold(self, task: str, silvers: dict[str, Any]) -> Any:
        self.calls.append(("gold", task))
        return task

    def analyze(self, task: str, gold: Any) -> Any:
        self.calls.append(("analyze", task))
        return gold

    def digest(self, result: Any) -> str:
        return str(result)


def _calls(strategy: str, task: str, scenario: str) -> list[tuple[str, str]]:
    engine = Recorder()
    _timing.STRATEGY[strategy](engine, _timing.Layout(Path("root")), task, scenario)
    return engine.calls


class TestStrategies:
    def test_s1_reads_the_stored_gold_and_only_analyzes(self) -> None:
        assert _calls("materialized", "task01", "S1") == [("read", "gold"), ("analyze", "task01")]

    def test_s2_rebuilds_gold_from_stored_silver(self) -> None:
        assert _calls("materialized", "task01", "S2") == [
            ("read", "silver"),
            ("gold", "task01"),
            ("write", "gold"),
            ("read", "gold"),
            ("analyze", "task01"),
        ]

    @pytest.mark.parametrize("scenario", ["S3", "S4"])
    def test_s3_and_s4_rebuild_every_silver_the_task_reads(self, scenario: str) -> None:
        calls = _calls("materialized", "task03", scenario)
        assert calls.count(("read", "bronze")) == 2
        assert calls.count(("write", "silver")) == 2
        assert ("write", "gold") in calls

    @pytest.mark.parametrize("scenario", _timing.SCENARIOS)
    def test_monolithic_starts_from_bronze_and_writes_nothing(self, scenario: str) -> None:
        calls = _calls("monolithic", "task03", scenario)
        assert [c for c in calls if c[0] == "write"] == []
        assert calls.count(("read", "bronze")) == 2
        assert calls[-1] == ("analyze", "task03")


CONTRACT = {
    "read_as": {"sggCd": "str"},
    "required": ("district_code", "deal_date", "price_10k_krw"),
    "rename": {"sggCd": "district_code", "dealAmount": "price_10k_krw", "dealYear": "deal_year"},
    "casts": {"price_10k_krw": "int_comma", "deal_year": "int", "area": "float"},
    "derived": ({"name": "deal_date", "kind": "date_parts", "columns": ("deal_year", "m", "d")},),
}


def _bronze(**overrides: list[Any]) -> pd.DataFrame:
    columns: dict[str, list[Any]] = {
        "sggCd": ["11110", "11140"],
        "dealAmount": [" 120,000", "9,500"],
        "dealYear": [2023, 2023],
        "m": [1, 12],
        "d": [5, 31],
        "area": ["84.97", None],
    }
    return pd.DataFrame({**columns, **overrides})


class TestPandasContract:
    def test_applies_rename_casts_and_derived(self) -> None:
        silver = time_pandas.apply_contract(_bronze(), CONTRACT)
        assert list(silver["price_10k_krw"]) == [120000, 9500]
        assert list(silver["deal_date"].dt.strftime("%Y-%m-%d")) == ["2023-01-05", "2023-12-31"]
        assert silver["area"].iloc[0] == 84.97
        # 원래 없던 값은 손실이 아니다.
        assert pd.isna(silver["area"].iloc[1])

    def test_a_value_the_cast_cannot_read_stops_like_the_builder(self) -> None:
        with pytest.raises(time_pandas.ContractError, match="price_10k_krw"):
            time_pandas.apply_contract(_bronze(dealAmount=["120,000", "12만"]), CONTRACT)

    def test_a_fraction_is_not_an_integer(self) -> None:
        """polars의 ``cast(Int64, strict=False)``도 ``"12.5"``를 null로 만든다."""
        with pytest.raises(time_pandas.ContractError, match="price_10k_krw"):
            time_pandas.apply_contract(_bronze(dealAmount=["120,000", "12.5"]), CONTRACT)

    def test_parts_that_form_no_date_stop_like_the_builder(self) -> None:
        with pytest.raises(time_pandas.ContractError, match="deal_date"):
            time_pandas.apply_contract(_bronze(d=[5, 32]), CONTRACT)

    def test_a_renamed_column_missing_from_the_source_stops(self) -> None:
        with pytest.raises(time_pandas.ContractError, match="dealAmount"):
            time_pandas.apply_contract(_bronze().drop(columns="dealAmount"), CONTRACT)

    def test_an_undeclared_contract_key_is_refused_rather_than_skipped(self) -> None:
        with pytest.raises(time_pandas.ContractError, match="zfill"):
            time_pandas.apply_contract(_bronze(), {**CONTRACT, "zfill": {"district_code": 5}})

    def test_the_real_contracts_use_only_what_the_engine_implements(self) -> None:
        for contract in time_pandas.CONTRACTS.values():
            assert set(contract) <= time_pandas.SUPPORTED


def _silver_trades() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "district_code": ["11110", "11110", "11110", "11140", " 1111"],
            "apt_name": [
                "래미안 강남 힐즈(1단지)",
                "래미안 강남 힐즈(1단지)",
                "경희궁자이",
                "목동",
                "목동",
            ],
            "area_m2": [84.97, 59.8, 84.9, 114.7, 0.0],
            "price_10k_krw": [120000, 90000, 150000, 160000, 1],
            "deal_year": [2021, 2022, 2022, 2022, 2022],
            "deal_month": [3, 3, 3, 3, 3],
        }
    )


def _silver_rents() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "district_code": ["11110", "11110", "11110", "11140"],
            "apt_name": ["래미안강남힐즈 1단지", "래미안강남힐즈 1단지", "경희궁자이", "목동"],
            "area_m2": [84.9, 59.84, 84.97, 114.7],
            "deposit_10k_krw": [72000, 54000, 90000, 20000],
            "monthly_rent_10k_krw": [0, 0, 0, 150],
            "deal_year": [2021, 2022, 2022, 2022],
            "deal_month": [3, 3, 3, 3],
        }
    )


class TestPandasGoldMatchesTheRealBuild:
    """timing의 Gold는 run_task0x.build_gold의 본문을 옮긴 것이다 — 갈라지면 잰 것이 다르다."""

    def test_task01(self, tmp_path: Path) -> None:
        silver, gold = tmp_path / "silver.parquet", tmp_path / "gold.parquet"
        _silver_trades().to_parquet(silver, index=False)
        run_task01.build_gold(silver, gold)
        expected = pd.read_parquet(gold)
        pd.testing.assert_frame_equal(time_pandas.gold_task01(_silver_trades()), expected)

    def test_task03(self, tmp_path: Path) -> None:
        trades, rents = tmp_path / "trades.parquet", tmp_path / "rents.parquet"
        _silver_trades().to_parquet(trades, index=False)
        _silver_rents().to_parquet(rents, index=False)
        run_task03.build_gold(trades, rents, tmp_path / "gold.parquet")
        expected = pd.read_parquet(tmp_path / "gold.parquet")
        actual = time_pandas.gold_task03(_silver_trades(), _silver_rents())
        assert len(actual) > 0
        pd.testing.assert_frame_equal(actual, expected)


class TestReport:
    def _raw(self) -> pd.DataFrame:
        rows = []
        for strategy, seconds in (
            ("materialized", [9.0, 1, 2, 3, 4, 5]),
            ("monolithic", [9.0, 2, 4, 6, 8, 10]),
        ):
            for round_, value in enumerate(seconds):
                rows.append(
                    {
                        "task": "task01",
                        "engine": "pandas",
                        "scenario": "S1",
                        "strategy": strategy,
                        "round": round_,
                        "warmup": round_ == 0,
                        "seconds": value,
                    }
                )
        return pd.DataFrame(rows)

    def test_summary_leaves_out_the_warmup(self) -> None:
        summary = timing_report.summarize(self._raw()).set_index("strategy")
        assert summary.loc["materialized", "n"] == 5
        assert summary.loc["materialized", "median"] == 3
        assert summary.loc["materialized", "max"] == 5
        assert summary.loc["materialized", "iqr"] == 2

    def test_ratio_above_one_means_materialized_is_faster(self) -> None:
        ratio = timing_report.ratios(timing_report.summarize(self._raw()))
        assert ratio["monolithic_over_materialized"].iloc[0] == 2

    def test_same_result_tolerates_only_the_last_digits(self) -> None:
        left = pd.DataFrame({"k": ["a"], "v": [1.0]})
        assert (
            timing_report.same_result(left, pd.DataFrame({"k": ["a"], "v": [1.0 + 1e-12]})) is None
        )
        assert timing_report.same_result(left, pd.DataFrame({"k": ["a"], "v": [1.001]})) is not None
        assert timing_report.same_result(left, pd.DataFrame({"k": ["b"], "v": [1.0]})) is not None
