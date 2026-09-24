from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from kpx.datasets import DatasetNotBuilt, LayerStore, schema_report


@pytest.fixture
def silver(tmp_path: Path) -> Path:
    path = tmp_path / "trades.parquet"
    pd.DataFrame(
        {
            "district_code": ["11110", "11140", "11170"],
            "price_10k_krw": [120_000, 135_500, None],
            "area_m2": [84.97, 59.82, 101.3],
        }
    ).to_parquet(path)
    return path


@pytest.fixture
def bronze(tmp_path: Path) -> Path:
    path = tmp_path / "raw.jsonl"
    path.write_text('{"sggCd": "11110", "dealAmount": "120,000"}\n', encoding="utf-8")
    return path


class TestLayerStore:
    def test_bronze_is_read_as_jsonl_with_values_left_as_strings(
        self, tmp_path: Path, bronze: Path
    ) -> None:
        store = LayerStore({("trades", "bronze"): bronze})

        frame = store.load("trades", "bronze")

        assert frame.loc[0, "dealAmount"] == "120,000"

    def test_silver_is_read_as_parquet(self, silver: Path) -> None:
        store = LayerStore({("trades", "silver"): silver})

        assert list(store.load("trades", "silver").columns) == [
            "district_code",
            "price_10k_krw",
            "area_m2",
        ]

    def test_an_unregistered_layer_names_the_dataset_it_could_not_find(self) -> None:
        store = LayerStore({})

        with pytest.raises(DatasetNotBuilt, match="trades"):
            store.path_for("trades", "gold")

    def test_a_registered_but_unbuilt_layer_is_not_reported_as_missing_registration(
        self, tmp_path: Path
    ) -> None:
        store = LayerStore({("trades", "gold"): tmp_path / "absent.parquet"})

        with pytest.raises(DatasetNotBuilt, match="not built"):
            store.path_for("trades", "gold")


class TestSchemaReport:
    """Silver의 스키마는 문서로 남아야 한다 (#7).

    "정규화했다"만 적힌 논문은 무엇이 무엇으로 바뀌었는지 독자가 확인할 방법이 없다.
    """

    def test_one_row_per_column_in_the_frame_order(self, silver: Path) -> None:
        frame = LayerStore({("t", "silver"): silver}).load("t", "silver")

        report = schema_report(frame)

        assert list(report["Column"]) == ["district_code", "price_10k_krw", "area_m2"]

    def test_dtype_is_reported_so_the_reader_sees_the_cast_landed(self, silver: Path) -> None:
        frame = LayerStore({("t", "silver"): silver}).load("t", "silver")

        report = schema_report(frame).set_index("Column")

        assert report.loc["area_m2", "Type"] == "float64"

    def test_non_null_rate_counts_the_nulls(self, silver: Path) -> None:
        frame = LayerStore({("t", "silver"): silver}).load("t", "silver")

        report = schema_report(frame).set_index("Column")

        assert report.loc["price_10k_krw", "Non-null"] == pytest.approx(2 / 3)
        assert report.loc["district_code", "Non-null"] == 1.0

    def test_example_skips_nulls(self) -> None:
        frame = pd.DataFrame({"cdealDay": [None, None, "12"]})

        assert schema_report(frame).loc[0, "Example"] == "12"

    def test_an_all_null_column_has_no_example_rather_than_the_string_none(self) -> None:
        frame = pd.DataFrame({"cdealType": [None, None]})

        assert schema_report(frame).loc[0, "Example"] == ""
