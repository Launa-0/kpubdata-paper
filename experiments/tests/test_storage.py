from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kpx.metrics.storage import (
    StorageError,
    measure_storage,
    storage_table,
)
from kpx.provenance import (
    BuildInputs,
    Environment,
    Provenance,
    ProvenanceStore,
    config_hash,
)

DATASET = "seoul-apartment-trades"
SNAPSHOT = "seoul-apartment-trades/20260315-4f2a91c0d3b7"
PIPELINE = "0.1.0a0+aaaaaaaaaaaa"

ENVIRONMENT = Environment("3.12.9", "Windows-11", {"pandas": "3.0.6"})


def inputs(
    layer: str,
    *,
    snapshot_id: str = SNAPSHOT,
    pipeline_version: str = PIPELINE,
    config: str = "base",
) -> BuildInputs:
    return BuildInputs(
        dataset=DATASET,
        layer=layer,  # type: ignore[arg-type]
        snapshot_id=snapshot_id,
        pipeline_version=pipeline_version,
        config_hash=config_hash({"layer": layer, "variant": config}),
        upstream_build_id=None if layer == "bronze" else "0" * 16,
    )


def build(
    layer: str,
    *,
    size: int,
    rows: int = 100,
    files: int = 1,
    status: str = "ok",
    snapshot_id: str = SNAPSHOT,
    pipeline_version: str = PIPELINE,
    config: str = "base",
) -> Provenance:
    recipe = inputs(
        layer, snapshot_id=snapshot_id, pipeline_version=pipeline_version, config=config
    )
    return Provenance(
        build_id=recipe.build_id,
        inputs=recipe,
        environment=ENVIRONMENT,
        built_at=datetime(2026, 3, 16, 10, 0),
        row_count=rows,
        columns=("district_code", "price_krw"),
        output_checksum="c" * 64,
        output_size_bytes=size,
        output_file_count=files,
        kpx_version="0.1.0",
        status=status,
    )


def store_with(tmp_path: Path, *builds: Provenance) -> ProvenanceStore:
    store = ProvenanceStore(tmp_path / "datasets")
    for provenance in builds:
        store.write(provenance)
    return store


def medallion(tmp_path: Path, **sizes: int) -> ProvenanceStore:
    """A complete Bronze/Silver/Gold set, sized as asked."""
    defaults = {"bronze": 1000, "silver": 600, "gold": 400}
    defaults.update(sizes)
    return store_with(tmp_path, *(build(layer, size=n) for layer, n in defaults.items()))


# -- the trade-off the issue asks for --------------------------------------


def test_amplification_is_medallion_storage_over_final_only(tmp_path: Path) -> None:
    profile = measure_storage(medallion(tmp_path), DATASET)
    assert profile.total_bytes == 2000
    assert profile.baseline_bytes == 400
    assert profile.amplification_factor == 5.0


def test_overhead_is_what_layering_costs_over_storing_the_final_dataset(tmp_path: Path) -> None:
    profile = measure_storage(medallion(tmp_path), DATASET)
    assert profile.overhead_bytes == 1600


def test_each_layer_is_reported_separately(tmp_path: Path) -> None:
    profile = measure_storage(medallion(tmp_path), DATASET)
    assert [layer.layer for layer in profile.layers] == ["bronze", "silver", "gold"]
    bronze = profile.layer("bronze")
    assert bronze is not None and bronze.bytes == 1000


def test_bytes_per_row_makes_a_format_difference_visible(tmp_path: Path) -> None:
    """An amplification factor across formats would be measuring the codec."""
    store = store_with(
        tmp_path,
        build("bronze", size=10_000, rows=100),
        build("silver", size=600, rows=100),
        build("gold", size=400, rows=100),
    )
    profile = measure_storage(store, DATASET)
    bronze = profile.layer("bronze")
    gold = profile.layer("gold")
    assert bronze is not None and gold is not None
    assert bronze.bytes_per_row == 100.0
    assert gold.bytes_per_row == 4.0


def test_bytes_per_row_of_an_empty_layer_is_undefined(tmp_path: Path) -> None:
    store = store_with(
        tmp_path,
        build("bronze", size=1000, rows=0),
        build("silver", size=600),
        build("gold", size=400),
    )
    bronze = measure_storage(store, DATASET).layer("bronze")
    assert bronze is not None and bronze.bytes_per_row is None


# -- what must not be compared ---------------------------------------------


def test_an_incomplete_medallion_set_is_refused(tmp_path: Path) -> None:
    """Summing two layers would understate what keeping three costs."""
    store = store_with(tmp_path, build("bronze", size=1000), build("silver", size=600))
    with pytest.raises(StorageError, match="no successful build for gold"):
        measure_storage(store, DATASET)


def test_layers_from_different_pipeline_versions_are_refused(tmp_path: Path) -> None:
    store = store_with(
        tmp_path,
        build("bronze", size=1000),
        build("silver", size=600, pipeline_version="0.2.0+bbbbbbbbbbbb"),
        build("gold", size=400),
    )
    with pytest.raises(StorageError, match="different pipeline_versions"):
        measure_storage(store, DATASET)


def test_layers_from_different_snapshots_are_refused(tmp_path: Path) -> None:
    store = store_with(
        tmp_path,
        build("bronze", size=1000),
        build("silver", size=600, snapshot_id=f"{DATASET}/20260601-bbbbbbbbbbbb"),
        build("gold", size=400),
    )
    with pytest.raises(StorageError, match="different snapshot_ids"):
        measure_storage(store, DATASET)


def test_one_run_can_be_picked_out_of_several(tmp_path: Path) -> None:
    later = f"{DATASET}/20260601-bbbbbbbbbbbb"
    store = store_with(
        tmp_path,
        build("bronze", size=1000),
        build("silver", size=600),
        build("gold", size=400),
        build("bronze", size=1100, snapshot_id=later),
        build("silver", size=660, snapshot_id=later),
        build("gold", size=440, snapshot_id=later),
    )
    profile = measure_storage(store, DATASET, snapshot_id=later)
    assert profile.snapshot_id == later
    assert profile.total_bytes == 2200


def test_a_failed_build_contributes_no_bytes_but_is_counted(tmp_path: Path) -> None:
    """A build that broke did not produce a stored dataset."""
    store = store_with(
        tmp_path,
        build("bronze", size=1000),
        build("silver", size=600),
        build("gold", size=400),
        build("silver", size=9_999_999, status="schema_breakage", config="broken"),
    )
    profile = measure_storage(store, DATASET)
    assert profile.total_bytes == 2000
    assert profile.skipped == 1


def test_a_dataset_whose_every_build_failed_is_refused(tmp_path: Path) -> None:
    store = store_with(tmp_path, build("bronze", size=1000, status="failed"))
    with pytest.raises(StorageError, match="nothing is stored"):
        measure_storage(store, DATASET)


def test_a_dataset_with_no_builds_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="no builds recorded"):
        measure_storage(ProvenanceStore(tmp_path), DATASET)


def test_a_baseline_that_stores_nothing_is_refused(tmp_path: Path) -> None:
    profile = measure_storage(medallion(tmp_path, gold=0), DATASET)
    with pytest.raises(StorageError, match="divide by zero"):
        _ = profile.amplification_factor


# -- Gold proliferation, which is one of the costs -------------------------


def test_several_golds_make_the_baseline_ambiguous(tmp_path: Path) -> None:
    """Picking one quietly would halve the amplification factor."""
    store = store_with(
        tmp_path,
        build("bronze", size=1000),
        build("silver", size=600),
        build("gold", size=400, config="t1"),
        build("gold", size=300, config="t3"),
    )
    with pytest.raises(StorageError, match="2 gold artifacts exist"):
        measure_storage(store, DATASET)


def test_every_gold_counts_toward_storage_but_only_one_is_the_baseline(tmp_path: Path) -> None:
    first = build("gold", size=400, config="t1")
    second = build("gold", size=300, config="t3")
    store = store_with(
        tmp_path, build("bronze", size=1000), build("silver", size=600), first, second
    )
    profile = measure_storage(store, DATASET, baseline_build_id=first.build_id)
    assert profile.total_bytes == 2300
    assert profile.baseline_bytes == 400
    gold = profile.layer("gold")
    assert gold is not None and gold.builds == 2


def test_an_unknown_baseline_build_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="no gold build"):
        measure_storage(medallion(tmp_path), DATASET, baseline_build_id="f" * 16)


# -- the table -------------------------------------------------------------


def test_the_table_carries_per_layer_sizes_beside_the_factor(tmp_path: Path) -> None:
    table = storage_table([measure_storage(medallion(tmp_path), DATASET)])
    assert table.loc[0, "amplification_factor"] == 5.0
    assert table.loc[0, "bronze_bytes"] == 1000
    assert "gold_bytes_per_row" in table.columns


def test_the_table_of_nothing_is_empty_but_shaped() -> None:
    table = storage_table([])
    assert table.empty
    assert "amplification_factor" in table.columns
