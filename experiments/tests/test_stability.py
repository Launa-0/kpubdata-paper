from __future__ import annotations

import pytest

from kpx.metrics.stability import (
    BuildObservation,
    StabilityError,
    measure_stability,
    table_stability,
)

SCHEMA = (("district_code", "str"), ("price_10k_krw", "int64"))


def seen(
    snapshot: str = "t1",
    *,
    status: str = "ok",
    input_rows: int = 100,
    output_rows: int = 100,
    schema: tuple[tuple[str, str], ...] | None = SCHEMA,
) -> BuildObservation:
    return BuildObservation(
        snapshot_id=snapshot,
        status=status,
        input_rows=input_rows,
        output_rows=output_rows,
        schema=schema,
    )


class TestBuildSuccess:
    def test_all_snapshots_build(self) -> None:
        report = measure_stability([seen("t1"), seen("t2"), seen("t3")])

        assert report.build_success_rate == 1.0
        assert report.pipeline_breakages == ()

    def test_a_failed_build_is_a_pipeline_breakage(self) -> None:
        report = measure_stability([seen("t1"), seen("t2", status="failed")])

        assert report.build_success_rate == 0.5
        assert [b.snapshot_id for b in report.pipeline_breakages] == ["t2"]

    def test_no_observations_is_an_error(self) -> None:
        with pytest.raises(StabilityError, match="no builds"):
            measure_stability([])


class TestSchemaCompatibility:
    """상류 스키마는 시간이 지나면 변한다. 변화의 방향이 중요하다."""

    def test_an_added_column_is_not_a_breakage(self) -> None:
        later = (*SCHEMA, ("new_field", "str"))

        report = measure_stability([seen("t1"), seen("t2", schema=later)])

        assert report.schema_breakages == ()
        assert report.schema_compatibility == 1.0

    def test_a_removed_column_is_a_breakage(self) -> None:
        later = (SCHEMA[0],)

        report = measure_stability([seen("t1"), seen("t2", schema=later)])

        assert [b.snapshot_id for b in report.schema_breakages] == ["t2"]
        assert report.schema_breakages[0].missing == ("price_10k_krw",)

    def test_a_changed_dtype_is_a_breakage(self) -> None:
        later = (("district_code", "int64"), SCHEMA[1])

        report = measure_stability([seen("t1"), seen("t2", schema=later)])

        assert report.schema_breakages[0].changed == (("district_code", "str", "int64"),)

    def test_the_first_successful_build_is_the_reference(self) -> None:
        report = measure_stability([seen("t1", status="failed"), seen("t2"), seen("t3")])

        assert report.schema_breakages == ()


class TestRowLoss:
    """행이 줄어드는 것은 조용한 실패다 — 빌드는 성공으로 끝난다."""

    def test_every_input_row_reaching_the_output_is_no_loss(self) -> None:
        assert measure_stability([seen(input_rows=100, output_rows=100)]).row_losses == ()

    def test_fewer_output_rows_than_input_is_recorded_with_the_count(self) -> None:
        report = measure_stability([seen("t2", input_rows=100, output_rows=93)])

        assert report.row_losses[0].snapshot_id == "t2"
        assert report.row_losses[0].lost == 7
        assert report.row_losses[0].rate == pytest.approx(0.07)

    def test_a_build_that_output_nothing_is_a_breakage_not_merely_a_loss(self) -> None:
        report = measure_stability([seen("t2", input_rows=100, output_rows=0)])

        assert [b.snapshot_id for b in report.pipeline_breakages] == ["t2"]


class TestTable:
    def test_one_row_per_snapshot_in_the_order_given(self) -> None:
        frame = table_stability([seen("t1"), seen("t2", input_rows=200, output_rows=200)])

        assert list(frame["Snapshot"]) == ["t1", "t2"]
        assert list(frame.columns) == [
            "Snapshot",
            "Status",
            "Input rows",
            "Output rows",
            "Row loss",
            "Schema",
        ]

    def test_a_breaking_schema_is_named_not_merely_flagged(self) -> None:
        frame = table_stability([seen("t1"), seen("t2", schema=(SCHEMA[0],))])

        assert "price_10k_krw" in frame.loc[1, "Schema"]
