from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from kpx.provenance import (
    BuildInputs,
    Environment,
    Provenance,
    ProvenanceError,
    ProvenanceStore,
    config_hash,
    record_build,
)

BUILT_AT = datetime(2026, 3, 16, 10, 0)


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    (root / "data.parquet").write_bytes(b"canonical rows")
    return root


def bronze_inputs(**kwargs: object) -> BuildInputs:
    defaults: dict[str, object] = {
        "dataset": "seoul-apartment-trades",
        "layer": "bronze",
        "snapshot_id": "seoul-apartment-trades/20260315-4f2a91c0d3b7",
        "pipeline_version": "0.1.0a0",
        "config_hash": config_hash({"preserve_source_columns": True}),
    }
    defaults.update(kwargs)
    return BuildInputs(**defaults)  # type: ignore[arg-type]


# -- config hashing ---------------------------------------------------------


def test_config_hash_ignores_key_order_and_whitespace() -> None:
    assert config_hash({"a": 1, "b": [2, 3]}) == config_hash({"b": [2, 3], "a": 1})


def test_config_hash_changes_with_the_config() -> None:
    assert config_hash({"drop_duplicates": True}) != config_hash({"drop_duplicates": False})


# -- the recipe -------------------------------------------------------------


def test_build_id_is_deterministic() -> None:
    assert bronze_inputs().build_id == bronze_inputs().build_id


def test_build_id_changes_with_the_snapshot() -> None:
    """R2 varies the snapshot; the recipe must say so."""
    other = bronze_inputs(snapshot_id="seoul-apartment-trades/20260601-aaaaaaaaaaaa")
    assert other.build_id != bronze_inputs().build_id


def test_build_id_changes_with_the_pipeline_version() -> None:
    assert bronze_inputs(pipeline_version="0.2.0").build_id != bronze_inputs().build_id


def test_build_id_changes_with_the_config() -> None:
    other = bronze_inputs(config_hash=config_hash({"preserve_source_columns": False}))
    assert other.build_id != bronze_inputs().build_id


def test_build_id_changes_with_the_upstream_build() -> None:
    bronze = bronze_inputs()
    silver = BuildInputs(
        dataset=bronze.dataset,
        layer="silver",
        snapshot_id=bronze.snapshot_id,
        pipeline_version=bronze.pipeline_version,
        config_hash=bronze.config_hash,
        upstream_build_id=bronze.build_id,
    )
    assert silver.build_id != bronze.build_id


def test_bronze_may_not_claim_an_upstream_build() -> None:
    with pytest.raises(ProvenanceError, match="built from a snapshot"):
        bronze_inputs(upstream_build_id="deadbeef")


def test_derived_layers_must_name_their_upstream() -> None:
    with pytest.raises(ProvenanceError, match="must name the build"):
        bronze_inputs(layer="silver")


def test_unknown_layer_is_rejected() -> None:
    with pytest.raises(ProvenanceError, match="unknown layer"):
        bronze_inputs(layer="platinum")


# -- environment ------------------------------------------------------------


def test_environment_is_not_part_of_the_recipe() -> None:
    """Otherwise a rebuild on another machine could never be compared."""
    assert "environment" not in BuildInputs.__dataclass_fields__


def test_capture_records_the_running_interpreter() -> None:
    captured = Environment.capture()
    assert captured.python_version.count(".") == 2
    assert "pandas" in captured.packages


def test_environment_differences_name_what_moved() -> None:
    mine = Environment("3.12.4", "macOS", {"pandas": "3.0.3"})
    theirs = Environment("3.12.4", "Linux", {"pandas": "2.2.2", "scipy": "1.14"})
    assert mine.differences(theirs) == {
        "platform": ("macOS", "Linux"),
        "packages.pandas": ("3.0.3", "2.2.2"),
        "packages.scipy": ("—", "1.14"),
    }


def test_identical_environments_differ_in_nothing() -> None:
    env = Environment("3.12.4", "macOS", {"pandas": "3.0.3"})
    assert env.differences(env) == {}


# -- recording a build ------------------------------------------------------


def test_record_build_digests_the_artifact(artifact: Path) -> None:
    provenance = record_build(
        artifact, inputs=bronze_inputs(), row_count=234_512, columns=["시군구", "거래금액"]
    )
    assert provenance.output_size_bytes == len(b"canonical rows")
    assert provenance.output_file_count == 1
    assert provenance.build_id == bronze_inputs().build_id


def test_same_recipe_and_same_bytes_give_the_same_checksum(artifact: Path) -> None:
    """This is exactly what R1 asserts."""
    first = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    second = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    assert first.build_id == second.build_id
    assert first.output_checksum == second.output_checksum


def test_different_output_bytes_are_visible_under_the_same_recipe(artifact: Path) -> None:
    """A non-deterministic build must be detectable, not averaged away."""
    first = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    (artifact / "data.parquet").write_bytes(b"different rows")
    second = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    assert first.build_id == second.build_id
    assert first.output_checksum != second.output_checksum


def test_provenance_file_does_not_change_the_output_checksum(artifact: Path) -> None:
    before = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    (artifact / "provenance.json").write_text("{}", encoding="utf-8")
    after = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    assert before.output_checksum == after.output_checksum


def test_tampered_build_id_is_refused(artifact: Path) -> None:
    provenance = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    payload = provenance.to_json()
    payload["build_id"] = "0000000000000000"
    with pytest.raises(ProvenanceError, match="has been edited"):
        Provenance.from_json(payload)


def test_result_row_carries_the_result_schema_fields(artifact: Path) -> None:
    row = record_build(
        artifact, inputs=bronze_inputs(), row_count=234_512, columns=["a"]
    ).result_row
    assert set(row) == {"source_snapshot", "pipeline_version", "rows", "output_hash", "status"}
    assert row["source_snapshot"] == bronze_inputs().snapshot_id


def test_failed_build_is_recordable(artifact: Path) -> None:
    """R2 counts build success rate, so a failure needs a row too."""
    provenance = record_build(
        artifact, inputs=bronze_inputs(), row_count=0, columns=[], status="schema_breakage"
    )
    assert provenance.result_row["status"] == "schema_breakage"


# -- the store --------------------------------------------------------------


def medallion_chain(artifact: Path, store: ProvenanceStore) -> tuple[str, str, str]:
    bronze = bronze_inputs()
    silver = BuildInputs(
        dataset=bronze.dataset,
        layer="silver",
        snapshot_id=bronze.snapshot_id,
        pipeline_version=bronze.pipeline_version,
        config_hash=config_hash({"normalize": "canonical"}),
        upstream_build_id=bronze.build_id,
    )
    gold = BuildInputs(
        dataset=bronze.dataset,
        layer="gold",
        snapshot_id=bronze.snapshot_id,
        pipeline_version=bronze.pipeline_version,
        config_hash=config_hash({"aggregate": "district_month"}),
        upstream_build_id=silver.build_id,
    )
    for index, inputs in enumerate((bronze, silver, gold)):
        store.write(
            record_build(
                artifact,
                inputs=inputs,
                row_count=100,
                columns=["a"],
                built_at=datetime(2026, 3, 16, 10, index),
            )
        )
    return bronze.build_id, silver.build_id, gold.build_id


def test_round_trips_through_the_store(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    provenance = record_build(
        artifact, inputs=bronze_inputs(), row_count=1, columns=["a"], built_at=BUILT_AT
    )
    store.write(provenance)
    assert store.load("seoul-apartment-trades", "bronze", provenance.build_id) == provenance


def test_artifact_bytes_live_under_the_record_not_beside_it(tmp_path: Path) -> None:
    """The bytes go in ``data/`` so git can exclude them and keep the record.

    A directory git ignores cannot have individual files rescued back out of it,
    so ``provenance.json`` has to sit outside whatever gets ignored.
    """
    store = ProvenanceStore(tmp_path / "datasets")
    build = store.directory("seoul-apartment-trades", "bronze", "a1b2c3d4e5f60718")
    data = store.data_directory("seoul-apartment-trades", "bronze", "a1b2c3d4e5f60718")
    assert data.parent == build
    assert data.name == "data"


def test_the_record_is_written_outside_the_data_directory(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    provenance = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    path = store.write(provenance)
    assert path.parent == store.directory_for(provenance)
    assert store.DATA_DIRNAME not in path.parts


def test_finding_a_build_is_unaffected_by_the_data_directory(
    artifact: Path, tmp_path: Path
) -> None:
    """``find``/``list_builds`` glob for the record, which did not move."""
    store = ProvenanceStore(tmp_path / "datasets")
    provenance = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    store.write(provenance)
    store.data_directory_for(provenance).mkdir(parents=True)
    (store.data_directory_for(provenance) / "data.parquet").write_bytes(b"canonical rows")
    assert store.find(provenance.build_id) == provenance
    assert store.list_builds() == [provenance]


def test_rebuilding_the_same_recipe_lands_in_the_same_place(artifact: Path, tmp_path: Path) -> None:
    """An R1 repeat compares against the previous result, not a new directory."""
    store = ProvenanceStore(tmp_path / "datasets")
    first = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"])
    store.write(first)
    store.write(record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"]))
    assert len(store.list_builds()) == 1


def test_lineage_runs_bronze_first(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    _, _, gold_id = medallion_chain(artifact, store)
    assert [p.inputs.layer for p in store.lineage(gold_id)] == ["bronze", "silver", "gold"]


def test_lineage_of_bronze_is_just_bronze(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    bronze_id, _, _ = medallion_chain(artifact, store)
    assert [p.build_id for p in store.lineage(bronze_id)] == [bronze_id]


def test_lineage_reports_a_broken_chain(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    _, silver_id, gold_id = medallion_chain(artifact, store)
    (store.root / "seoul-apartment-trades" / "silver" / silver_id / "provenance.json").unlink()
    with pytest.raises(ProvenanceError, match="no build recorded with id"):
        store.lineage(gold_id)


def test_lineage_detects_a_cycle(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    _, silver_id, _ = medallion_chain(artifact, store)
    path = store.root / "seoul-apartment-trades" / "silver" / silver_id / "provenance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["inputs"]["upstream_build_id"] = silver_id
    payload["build_id"] = BuildInputs(**payload["inputs"]).build_id
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProvenanceError, match="cycle"):
        store.lineage(silver_id)


def test_list_builds_can_filter_by_layer(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    medallion_chain(artifact, store)
    assert [p.inputs.layer for p in store.list_builds(layer="silver")] == ["silver"]


def test_list_builds_is_ordered_oldest_first(artifact: Path, tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    medallion_chain(artifact, store)
    assert [p.inputs.layer for p in store.list_builds()] == ["bronze", "silver", "gold"]


def test_unknown_build_is_reported(tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path / "datasets")
    with pytest.raises(ProvenanceError, match="no build recorded"):
        store.find("0000000000000000")


def test_newer_schema_version_is_refused(artifact: Path) -> None:
    payload = record_build(artifact, inputs=bronze_inputs(), row_count=1, columns=["a"]).to_json()
    payload["schema_version"] = 99
    with pytest.raises(ProvenanceError, match="upgrade kpx"):
        Provenance.from_json(payload)
