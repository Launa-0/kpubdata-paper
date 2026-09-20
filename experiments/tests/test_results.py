from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from kpx.results import (
    COLUMNS,
    IDENTITY_FIELDS,
    MEASURED_FIELDS,
    RESULT_SCHEMA,
    ResultRow,
    ResultSchemaError,
    ResultStore,
    empty_frame,
    output_digest,
    validate,
)


def make_row(**kwargs: Any) -> ResultRow:
    defaults: dict[str, Any] = {
        "run_id": "task01/silver/seed0/r0",
        "task": "task01",
        "dataset": "seoul-apartment-trades",
        "condition": "silver",
        "source_snapshot": "seoul-apartment-trades/20260315-4f2a91c0d3b7",
        "pipeline_version": "0.1.0",
        "rows": 234_000,
        "runtime_seconds": 1.25,
        "preprocessing_loc": 18,
        "function_count": 3,
        "transformation_steps": 4,
        "output_hash": "a" * 64,
    }
    defaults.update(kwargs)
    return ResultRow(**defaults)


def store(tmp_path: Path) -> ResultStore:
    return ResultStore(tmp_path / "results" / "experiment_results.parquet")


# -- the schema itself -----------------------------------------------------


def test_every_field_is_reachable_from_the_row() -> None:
    """The dataclass and the schema must not drift apart."""
    assert set(COLUMNS) == set(make_row().to_dict())


def test_identity_and_measured_fields_are_disjoint() -> None:
    assert not set(IDENTITY_FIELDS) & set(MEASURED_FIELDS)


def test_empty_frame_carries_the_schema() -> None:
    frame = empty_frame()
    assert list(frame.columns) == list(COLUMNS)
    assert frame.empty


def test_task_specific_metrics_are_optional() -> None:
    """mae belongs to task02, join_matching_rate to task03."""
    optional = {f.name for f in RESULT_SCHEMA if f.requirement == "optional"}
    assert {"mae", "rmse", "join_matching_rate", "peak_memory_mb"} <= optional


# -- validation ------------------------------------------------------------


def test_a_complete_row_validates() -> None:
    frame = validate(pd.DataFrame([make_row().to_dict()]))
    assert list(frame.columns) == list(COLUMNS)
    assert frame.loc[0, "rows"] == 234_000


def test_absent_optional_columns_are_added_as_missing() -> None:
    payload = make_row().to_dict()
    del payload["mae"]
    frame = validate(pd.DataFrame([payload]))
    assert frame["mae"].isna().all()


def test_a_missing_identity_column_is_refused() -> None:
    payload = make_row().to_dict()
    del payload["source_snapshot"]
    with pytest.raises(ResultSchemaError, match="missing identity column"):
        validate(pd.DataFrame([payload]))


def test_a_null_identity_value_is_refused() -> None:
    """An unattributable result cannot be published."""
    frame = pd.DataFrame([make_row(source_snapshot=None).to_dict()])
    with pytest.raises(ResultSchemaError, match="source_snapshot is null"):
        validate(frame)


def test_an_unknown_column_is_refused() -> None:
    payload = make_row().to_dict() | {"f1_score": 0.9}
    with pytest.raises(ResultSchemaError, match="unknown result column"):
        validate(pd.DataFrame([payload]))


def test_an_unknown_condition_is_refused() -> None:
    frame = pd.DataFrame([make_row(condition="platinum").to_dict()])
    with pytest.raises(ResultSchemaError, match="unknown condition: platinum"):
        validate(frame)


def test_an_unknown_status_is_refused() -> None:
    frame = pd.DataFrame([make_row(status="maybe").to_dict()])
    with pytest.raises(ResultSchemaError, match="unknown status"):
        validate(frame)


def test_a_rate_outside_the_unit_interval_is_refused() -> None:
    frame = pd.DataFrame([make_row(missing_rate=1.4).to_dict()])
    with pytest.raises(ResultSchemaError, match="missing_rate above"):
        validate(frame)


def test_a_negative_runtime_is_refused() -> None:
    frame = pd.DataFrame([make_row(runtime_seconds=-0.1).to_dict()])
    with pytest.raises(ResultSchemaError, match="runtime_seconds below"):
        validate(frame)


@pytest.mark.parametrize("field", MEASURED_FIELDS)
def test_a_successful_run_must_report_what_it_cost(field: str) -> None:
    frame = pd.DataFrame([make_row(**{field: None}).to_dict()])
    with pytest.raises(ResultSchemaError, match=f"{field} is missing"):
        validate(frame)


def test_a_failed_run_may_report_nothing() -> None:
    """Dropping failures would describe a more successful experiment."""
    payload = make_row(status="failed").to_dict()
    for field in MEASURED_FIELDS:
        payload[field] = None
    frame = validate(pd.DataFrame([payload]))
    assert frame.loc[0, "status"] == "failed"


def test_duplicate_run_ids_are_refused() -> None:
    rows = [make_row().to_dict(), make_row().to_dict()]
    with pytest.raises(ResultSchemaError, match="duplicate run_id"):
        validate(pd.DataFrame(rows))


def test_values_that_do_not_fit_the_schema_types_are_refused() -> None:
    frame = pd.DataFrame([make_row(rows="lots").to_dict()])
    with pytest.raises(ResultSchemaError, match="do not fit the schema's types"):
        validate(frame)


# -- the store -------------------------------------------------------------


def test_loading_an_absent_store_gives_an_empty_frame(tmp_path: Path) -> None:
    assert store(tmp_path).load().empty


def test_append_round_trips_through_parquet(tmp_path: Path) -> None:
    results = store(tmp_path)
    results.append(make_row())
    loaded = results.load()
    assert len(loaded) == 1
    assert loaded.loc[0, "run_id"] == "task01/silver/seed0/r0"
    assert loaded.loc[0, "runtime_seconds"] == 1.25
    assert list(loaded.columns) == list(COLUMNS)


def test_append_accumulates(tmp_path: Path) -> None:
    results = store(tmp_path)
    results.append(make_row(run_id="r1", condition="bronze"))
    results.append(make_row(run_id="r2", condition="gold"))
    assert sorted(results.load()["condition"]) == ["bronze", "gold"]


def test_a_csv_mirror_is_written_beside_the_parquet(tmp_path: Path) -> None:
    """The committed results need a readable diff."""
    results = store(tmp_path)
    results.append(make_row())
    assert results.csv_path.exists()
    assert list(pd.read_csv(results.csv_path).columns) == list(COLUMNS)


def test_a_mapping_may_be_appended_instead_of_a_row(tmp_path: Path) -> None:
    results = store(tmp_path)
    results.append(make_row().to_dict())
    assert len(results.load()) == 1


def test_a_rejected_row_leaves_the_file_untouched(tmp_path: Path) -> None:
    results = store(tmp_path)
    results.append(make_row(run_id="r1"))
    with pytest.raises(ResultSchemaError):
        results.append(make_row(run_id="r2", missing_rate=9.0))
    assert list(results.load()["run_id"]) == ["r1"]


def test_a_run_id_repeated_across_appends_is_refused(tmp_path: Path) -> None:
    """R1 rebuilds the same run ten times; the ids have to distinguish them."""
    results = store(tmp_path)
    results.append(make_row(run_id="r1"))
    with pytest.raises(ResultSchemaError, match="duplicate run_id"):
        results.append(make_row(run_id="r1"))


def test_extend_writes_nothing_when_given_nothing(tmp_path: Path) -> None:
    assert store(tmp_path).extend([]).empty


# -- querying --------------------------------------------------------------


def populated(tmp_path: Path) -> ResultStore:
    results = store(tmp_path)
    results.extend(
        [
            make_row(run_id="t1-bronze", task="task01", condition="bronze", runtime_seconds=4.0),
            make_row(run_id="t1-silver", task="task01", condition="silver", runtime_seconds=2.0),
            make_row(run_id="t1-gold", task="task01", condition="gold", runtime_seconds=1.0),
            make_row(run_id="t1-mono", task="task01", condition="monolithic", runtime_seconds=5.0),
            make_row(run_id="t2-silver", task="task02", condition="silver", runtime_seconds=3.0),
            make_row(run_id="t2-failed", task="task02", condition="gold", status="failed"),
        ]
    )
    return results


def test_query_filters_by_task_and_condition(tmp_path: Path) -> None:
    results = populated(tmp_path)
    assert list(results.query(task="task01")["condition"]) == [
        "bronze",
        "silver",
        "gold",
        "monolithic",
    ]
    assert len(results.query(condition="silver")) == 2


def test_query_hides_failed_runs_by_default(tmp_path: Path) -> None:
    """A failed run must not reach a table by accident."""
    results = populated(tmp_path)
    assert "t2-failed" not in set(results.query(task="task02")["run_id"])
    assert "t2-failed" in set(results.query(task="task02", status=None)["run_id"])


def test_by_condition_lays_out_the_table_the_paper_prints(tmp_path: Path) -> None:
    table = populated(tmp_path).by_condition("runtime_seconds")
    assert list(table.columns) == ["bronze", "silver", "gold", "monolithic"]
    assert table.loc["task01", "gold"] == 1.0
    assert table.loc["task02", "silver"] == 3.0


def test_by_condition_averages_repeated_runs(tmp_path: Path) -> None:
    """Seeds and R1 rebuilds are repetitions of one cell, not separate cells."""
    results = store(tmp_path)
    results.extend(
        [
            make_row(run_id="s0", seed=0, runtime_seconds=1.0),
            make_row(run_id="s1", seed=1, runtime_seconds=3.0),
        ]
    )
    assert results.by_condition("runtime_seconds").loc["task01", "silver"] == 2.0


def test_by_condition_on_an_empty_store_is_empty(tmp_path: Path) -> None:
    assert store(tmp_path).by_condition("runtime_seconds").empty


def test_by_condition_refuses_a_metric_the_schema_does_not_have(tmp_path: Path) -> None:
    with pytest.raises(ResultSchemaError, match="no such metric"):
        store(tmp_path).by_condition("f1_score")


# -- output hashing --------------------------------------------------------


def test_the_same_result_hashes_the_same() -> None:
    frame = pd.DataFrame({"district": ["종로구"], "mean_price": [1.5]})
    assert output_digest(frame) == output_digest(frame.copy())


def test_a_changed_value_changes_the_hash() -> None:
    before = output_digest(pd.DataFrame({"v": [1.0]}))
    assert output_digest(pd.DataFrame({"v": [1.0000001]})) != before


def test_the_index_is_not_part_of_the_result() -> None:
    """A positional index is an artifact of how the frame was built."""
    frame = pd.DataFrame({"v": [1.0, 2.0]})
    assert output_digest(frame) == output_digest(frame.iloc[::-1].iloc[::-1])
