from __future__ import annotations

import pandas as pd
import pytest

from kpx.metrics.quality import (
    DIAGNOSTIC_METRICS,
    INTEGRITY_METRICS,
    LAYER_QUALITY_METRICS,
    ColumnSpec,
    QualityError,
    QualityReport,
    QualitySpec,
    duplicate_rate,
    measure_quality,
)

SEOUL_CODES = frozenset({"11110", "11140", "11170"})


def parse_price(value: str) -> int:
    """The task's own parser: '120,000' is ten-thousands of won."""
    return int(value.replace(",", "")) * 10_000


# -- fixtures --------------------------------------------------------------


def bronze_frame() -> pd.DataFrame:
    """Minimally parsed source: Korean columns, strings, commas in amounts."""
    return pd.DataFrame(
        {
            "거래금액": ["120,000", "95,500", "not a price", None],
            "전용면적": ["84.97", "59.5", "-3", "72.0"],
            "법정동시군구코드": ["11110", "11140", "99999", "11170"],
        }
    )


def bronze_spec(*, interpret: bool = True) -> QualitySpec:
    return QualitySpec(
        columns=(
            ColumnSpec(
                column="거래금액",
                role="price",
                kind="numeric",
                interpret=parse_price if interpret else None,
                minimum=0,
            ),
            ColumnSpec(column="전용면적", role="area", kind="numeric", minimum=0),
            ColumnSpec(column="법정동시군구코드", role="district_code", kind="code"),
        ),
        valid_codes=SEOUL_CODES,
    )


def silver_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "price_krw": [1_200_000_000, 955_000_000, 880_000_000, 1_010_000_000],
            "area_m2": [84.97, 59.5, 45.0, 72.0],
            "district_code": ["11110", "11140", "11170", "11110"],
        }
    )


def silver_spec() -> QualitySpec:
    return QualitySpec(
        columns=(
            ColumnSpec(column="price_krw", role="price", kind="numeric", minimum=0),
            ColumnSpec(column="area_m2", role="area", kind="numeric", minimum=0),
            ColumnSpec(column="district_code", role="district_code", kind="code"),
        ),
        valid_codes=SEOUL_CODES,
    )


# -- the bias control that matters most ------------------------------------


def test_bronze_is_credited_with_what_the_pipeline_can_read() -> None:
    """Reading Bronze naively would measure our hostility, not the data.

    'not a price' is a genuine defect; '120,000' is not.
    """
    frame = bronze_frame()
    with_parser = measure_quality(frame, bronze_spec(), layer="bronze")
    naively = measure_quality(frame, bronze_spec(interpret=False), layer="bronze")

    assert with_parser.parsing_failure_rate == 0.25  # only 'not a price'
    assert naively.parsing_failure_rate == 0.75  # every comma-formatted amount too
    assert with_parser.type_consistency is not None
    assert naively.type_consistency is not None
    assert with_parser.type_consistency > naively.type_consistency


def test_missing_and_unreadable_are_counted_separately() -> None:
    """An absent value and a corrupt one are different defects."""
    report = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    assert report.missing_by_column["거래금액"] == 0.25  # the None
    assert report.parsing_failure_rate == 0.25  # the 'not a price'


# -- missing ---------------------------------------------------------------


def test_missing_rate_is_reported_per_column() -> None:
    """A column that improved by disappearing must not hide inside an average."""
    report = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    assert report.missing_by_column == {"거래금액": 0.25, "전용면적": 0.0, "법정동시군구코드": 0.0}


def test_missing_rate_is_cells_over_cells() -> None:
    report = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    assert report.missing_rate == pytest.approx(1 / 12)


def test_optional_columns_are_not_counted_as_missing() -> None:
    frame = pd.DataFrame({"price_krw": [1.0, 2.0], "note": [None, None]})
    spec = QualitySpec(
        columns=(
            ColumnSpec(column="price_krw", role="price"),
            ColumnSpec(column="note", role="note", kind="text", required=False),
        )
    )
    assert measure_quality(frame, spec, layer="silver").missing_rate == 0.0


def test_rows_are_part_of_the_report() -> None:
    """A missing rate is only comparable alongside the rows it was computed over."""
    assert measure_quality(silver_frame(), silver_spec(), layer="silver").rows == 4


# -- duplicates ------------------------------------------------------------


def test_duplicate_rate_over_whole_rows() -> None:
    frame = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    assert duplicate_rate(frame) == pytest.approx(1 / 3)


def test_duplicate_rate_over_a_key() -> None:
    frame = pd.DataFrame({"id": ["a", "a", "b"], "value": [1, 2, 3]})
    assert duplicate_rate(frame, ("id",)) == pytest.approx(1 / 3)
    assert duplicate_rate(frame) == 0.0


def test_duplicates_in_an_empty_frame_are_refused() -> None:
    with pytest.raises(QualityError, match="empty frame"):
        duplicate_rate(pd.DataFrame({"a": []}))


# -- type consistency ------------------------------------------------------


def test_type_consistency_excludes_missing_from_the_denominator() -> None:
    """Absence is counted by missing_rate; counting it twice couples the two."""
    report = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    # 11 present values across three columns, one of which does not read
    assert report.type_consistency == pytest.approx(10 / 11)


def test_type_consistency_is_undefined_without_typed_columns() -> None:
    frame = pd.DataFrame({"note": ["a", "b"]})
    spec = QualitySpec(columns=(ColumnSpec(column="note", role="note", kind="text"),))
    assert measure_quality(frame, spec, layer="bronze").type_consistency is None


# -- schema conformance ----------------------------------------------------


def test_schema_conformance_applies_an_exclusive_lower_bound() -> None:
    """The bounds H1 cares about are price > 0 and area > 0."""
    frame = pd.DataFrame({"price_krw": [1.0, 0.0, -2.0]})
    spec = QualitySpec(columns=(ColumnSpec(column="price_krw", role="price", minimum=0),))
    assert measure_quality(frame, spec, layer="silver").schema_conformance == pytest.approx(1 / 3)


def test_schema_conformance_rejects_unreadable_and_missing_records() -> None:
    report = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    # row 0 conforms; row 1 conforms; row 2 fails price and area and code; row 3 is missing a price
    assert report.schema_conformance == 0.5


def test_a_custom_predicate_is_applied() -> None:
    frame = pd.DataFrame({"year_month": ["202401", "20240", "202413"]})
    spec = QualitySpec(
        columns=(
            ColumnSpec(
                column="year_month",
                role="year_month",
                kind="text",
                predicate=lambda v: len(v) == 6 and v[4:] in {f"{m:02d}" for m in range(1, 13)},
            ),
        )
    )
    assert measure_quality(frame, spec, layer="bronze").schema_conformance == pytest.approx(1 / 3)


def test_a_silver_frame_conforms_completely() -> None:
    assert measure_quality(silver_frame(), silver_spec(), layer="silver").schema_conformance == 1.0


# -- code validity ---------------------------------------------------------


def test_code_validity_against_the_reference_list() -> None:
    report = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    assert report.code_validity == pytest.approx(3 / 4)  # 99999 is not a district


def test_code_validity_is_not_claimed_without_a_reference_list() -> None:
    """A five-digit regex would accept 99999 — that is format, not validity."""
    spec = QualitySpec(
        columns=(ColumnSpec(column="법정동시군구코드", role="district_code", kind="code"),)
    )
    assert measure_quality(bronze_frame(), spec, layer="bronze").code_validity is None


# -- the interface itself --------------------------------------------------


def test_the_same_spec_shape_serves_both_layers() -> None:
    """Bronze and Silver differ in vocabulary, not in what is measured."""
    bronze = measure_quality(bronze_frame(), bronze_spec(), layer="bronze")
    silver = measure_quality(silver_frame(), silver_spec(), layer="silver")
    for name in LAYER_QUALITY_METRICS:
        assert (bronze.metric(name) is None) == (silver.metric(name) is None)


def test_an_empty_frame_is_refused() -> None:
    """Reporting 0.0 over no rows would claim perfection."""
    with pytest.raises(QualityError, match="empty frame"):
        measure_quality(pd.DataFrame({"price_krw": []}), silver_spec(), layer="silver")


def test_a_frame_missing_a_specified_column_is_refused() -> None:
    with pytest.raises(QualityError, match="missing specified column"):
        measure_quality(pd.DataFrame({"price_krw": [1.0]}), silver_spec(), layer="silver")


def test_a_spec_without_columns_is_refused() -> None:
    with pytest.raises(QualityError, match="at least one column"):
        QualitySpec(columns=())


def test_a_role_declared_twice_is_refused() -> None:
    with pytest.raises(QualityError, match="declared more than once"):
        QualitySpec(
            columns=(
                ColumnSpec(column="price_krw", role="price"),
                ColumnSpec(column="거래금액", role="price"),
            )
        )


def test_an_unknown_metric_name_is_refused() -> None:
    report = measure_quality(silver_frame(), silver_spec(), layer="silver")
    with pytest.raises(QualityError, match="no such quality metric"):
        report.metric("f1_score")


# -- integrity vs diagnostic ----------------------------------------------


def reports() -> dict[str, QualityReport]:
    return {
        "bronze": measure_quality(bronze_frame(), bronze_spec(), layer="bronze"),
        "silver": measure_quality(silver_frame(), silver_spec(), layer="silver"),
    }


def test_every_report_carries_its_row_count() -> None:
    """행을 버려 바뀐 비율이 그 변화 옆에 보여야 한다."""
    assert {layer: report.rows for layer, report in reports().items()} == {
        "bronze": 4,
        "silver": len(silver_frame()),
    }


def test_the_layer_table_still_carries_every_metric() -> None:
    """진단으로 내린 것이지 버린 것이 아니다."""
    assert set(LAYER_QUALITY_METRICS) == set(INTEGRITY_METRICS) | set(DIAGNOSTIC_METRICS)
    report = measure_quality(silver_frame(), silver_spec(), layer="silver")
    assert report.metric("duplicate_rate") is not None
