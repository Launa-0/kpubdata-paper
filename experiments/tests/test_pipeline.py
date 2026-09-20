from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from kpx.pipeline import (
    ArtifactStore,
    DatasetArtifact,
    PipelineError,
    PipelineVersion,
    assert_same_pipeline,
    canonical_config,
    config_hash,
)

CONFIG = {"dedupe": True, "price_unit": "krw", "drop_cancelled": True}

# What kpubdata-builder writes; consumed as data, never imported.
BUILD_MANIFEST = {
    "build_id": "b-20260315-01",
    "schema_version": "1.0.0",
    "status": "ok",
    "build_environment": {
        "python_version": "3.12.3",
        "kpubdata_version": "0.9.2",
        "builder_version": "0.4.1",
    },
    "inputs_fingerprint": "sha256:abc123",
}


def version(**kwargs: object) -> PipelineVersion:
    defaults: dict[str, object] = {"builder_version": "0.4.1", "config_hash": config_hash(CONFIG)}
    defaults.update(kwargs)
    return PipelineVersion(**defaults)  # type: ignore[arg-type]


def build(root: Path, name: str = "trades", *, layer: str = "silver") -> Path:
    data = root / "built" / layer
    data.mkdir(parents=True, exist_ok=True)
    (data / f"{name}.json").write_text('[{"price_krw": 1200000000}]', encoding="utf-8")
    return data


# -- the config hash -------------------------------------------------------


def test_key_order_does_not_change_the_hash() -> None:
    """A config assembled in another order is the same config."""
    reordered = {"drop_cancelled": True, "price_unit": "krw", "dedupe": True}
    assert config_hash(CONFIG) == config_hash(reordered)


def test_a_changed_setting_changes_the_hash() -> None:
    assert config_hash(CONFIG) != config_hash({**CONFIG, "dedupe": False})


def test_paths_hash_the_same_on_every_platform() -> None:
    """The defect that made snapshot ids platform-dependent (#31), by another door."""
    posix = config_hash({"root": PurePosixPath("data/2020/01")})
    windows = config_hash({"root": PureWindowsPath(r"data\2020\01")})
    assert posix == windows


def test_nested_paths_are_normalized_too() -> None:
    posix = config_hash({"sources": [{"path": PurePosixPath("a/b")}]})
    windows = config_hash({"sources": [{"path": PureWindowsPath(r"a\b")}]})
    assert posix == windows


def test_canonical_form_is_compact_sorted_json() -> None:
    assert canonical_config({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_korean_values_are_not_escaped() -> None:
    assert "종로구" in canonical_config({"district": "종로구"})


def test_a_config_holding_nan_is_refused() -> None:
    """Not valid JSON, and a mistake worth surfacing at build time."""
    with pytest.raises(ValueError):
        config_hash({"threshold": float("nan")})


# -- the pipeline version --------------------------------------------------


def test_the_identifier_names_code_and_configuration() -> None:
    assert version().identifier == f"0.4.1+{config_hash(CONFIG)[:12]}"


def test_the_identifier_moves_when_the_config_moves() -> None:
    """R1 holds code and config fixed; one string has to cover both."""
    other = version(config_hash=config_hash({**CONFIG, "dedupe": False}))
    assert version().identifier != other.identifier


def test_the_identifier_moves_when_the_builder_moves() -> None:
    assert version().identifier != version(builder_version="0.4.2").identifier


def test_the_builders_manifest_is_read_rather_than_reimplemented() -> None:
    pipeline = PipelineVersion.from_build_manifest(BUILD_MANIFEST, CONFIG)
    assert pipeline.builder_version == "0.4.1"
    assert pipeline.kpubdata_version == "0.9.2"
    assert pipeline.python_version == "3.12.3"
    assert pipeline.build_id == "b-20260315-01"
    assert pipeline.config_hash == config_hash(CONFIG)


def test_a_legacy_manifest_without_an_environment_still_reads() -> None:
    """ "unknown" in a version column is honest where a guess would not be."""
    pipeline = PipelineVersion.from_build_manifest({"build_id": "b-1"}, CONFIG)
    assert pipeline.builder_version == "unknown"
    assert pipeline.identifier.startswith("unknown+")


def test_a_malformed_environment_is_refused() -> None:
    with pytest.raises(PipelineError, match="not an object"):
        PipelineVersion.from_build_manifest({"build_environment": "0.4.1"}, CONFIG)


def test_capture_records_what_is_installed_here() -> None:
    pipeline = PipelineVersion.capture(CONFIG, builder_version="0.4.1")
    assert pipeline.python_version.startswith("3.")
    assert pipeline.config_hash == config_hash(CONFIG)


def test_a_pipeline_version_round_trips() -> None:
    pipeline = version(build_id="b-1")
    assert PipelineVersion.from_json(pipeline.to_json()) == pipeline


# -- the artifact record ---------------------------------------------------


def registered(tmp_path: Path, **kwargs: object) -> DatasetArtifact:
    store = ArtifactStore(tmp_path / "datasets")
    defaults: dict[str, object] = {
        "dataset": "seoul-apartment-trades",
        "layer": "silver",
        "snapshot_id": "seoul-apartment-trades/20260315-4f2a91c0d3b7",
        "pipeline": version(),
        "row_count": 234_512,
        "columns": ("district_code", "price_krw"),
        "built_at": datetime(2026, 3, 15, 12, 0),
    }
    defaults.update(kwargs)
    return store.register(build(tmp_path), **defaults)  # type: ignore[arg-type]


def test_an_artifact_names_its_source_and_its_pipeline(tmp_path: Path) -> None:
    artifact = registered(tmp_path)
    assert artifact.run_fields() == {
        "source_snapshot": "seoul-apartment-trades/20260315-4f2a91c0d3b7",
        "pipeline_version": f"0.4.1+{config_hash(CONFIG)[:12]}",
    }


def test_run_fields_are_exactly_the_result_schema_columns(tmp_path: Path) -> None:
    """The link #4 exists to make: artifact provenance into a result row."""
    assert set(registered(tmp_path).run_fields()) == {"source_snapshot", "pipeline_version"}


def test_the_citation_block_carries_both_halves_of_the_version(tmp_path: Path) -> None:
    citation = registered(tmp_path).citation()
    assert "Pipeline version: 0.4.1+" in citation
    assert f"Config SHA-256: {config_hash(CONFIG)}" in citation
    assert "Builder: 0.4.1" in citation


def test_the_record_is_written_beside_the_data(tmp_path: Path) -> None:
    registered(tmp_path)
    path = tmp_path / "datasets" / "seoul-apartment-trades" / "silver" / "artifact.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["pipeline"]["builder_version"] == "0.4.1"


def test_an_artifact_round_trips(tmp_path: Path) -> None:
    artifact = registered(tmp_path)
    store = ArtifactStore(tmp_path / "datasets")
    assert store.load("seoul-apartment-trades", "silver") == artifact


def test_reading_an_unregistered_artifact_is_refused(tmp_path: Path) -> None:
    """A run cannot record the pipeline version of data it cannot identify."""
    with pytest.raises(PipelineError, match="no artifact registered"):
        ArtifactStore(tmp_path).load("seoul-apartment-trades", "silver")


def test_an_unknown_layer_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="unknown layer"):
        ArtifactStore(tmp_path).directory("trades", "platinum")  # type: ignore[arg-type]


def test_metadata_from_a_newer_harness_is_refused(tmp_path: Path) -> None:
    artifact = registered(tmp_path)
    payload = artifact.to_json() | {"metadata_schema_version": 99}
    with pytest.raises(PipelineError, match="upgrade kpx"):
        DatasetArtifact.from_json(payload)


def test_artifacts_list_in_medallion_order(tmp_path: Path) -> None:
    """monolithic reads bronze, and a reader expects the layers in build order."""
    for layer in ("gold", "bronze", "silver"):
        registered(tmp_path, layer=layer)
    store = ArtifactStore(tmp_path / "datasets")
    assert [a.layer for a in store.list_artifacts()] == ["bronze", "silver", "gold"]


# -- verification ----------------------------------------------------------


def test_verification_passes_for_untouched_data(tmp_path: Path) -> None:
    registered(tmp_path)
    store = ArtifactStore(tmp_path / "datasets")
    data = store.data_path("seoul-apartment-trades", "silver")
    data.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "built" / "silver").rename(data)
    assert store.verify("seoul-apartment-trades", "silver").ok


def test_verification_fails_when_the_data_is_absent(tmp_path: Path) -> None:
    registered(tmp_path)
    result = ArtifactStore(tmp_path / "datasets").verify("seoul-apartment-trades", "silver")
    assert not result.ok
    assert "not present" in result.reason
    with pytest.raises(PipelineError, match="failed verification"):
        result.raise_for_status()


def test_verification_fails_on_drift(tmp_path: Path) -> None:
    registered(tmp_path)
    store = ArtifactStore(tmp_path / "datasets")
    data = store.data_path("seoul-apartment-trades", "silver")
    data.mkdir(parents=True, exist_ok=True)
    (data / "trades.json").write_text("drifted", encoding="utf-8")
    result = store.verify("seoul-apartment-trades", "silver")
    assert not result.ok
    assert result.actual != result.expected


# -- R2's precondition -----------------------------------------------------


def test_artifacts_built_by_one_pipeline_agree(tmp_path: Path) -> None:
    artifacts = [registered(tmp_path, layer=layer) for layer in ("bronze", "silver")]
    assert assert_same_pipeline(artifacts) == f"0.4.1+{config_hash(CONFIG)[:12]}"


def test_artifacts_built_by_different_pipelines_are_refused(tmp_path: Path) -> None:
    """R2 varies the source; if the pipeline moved too, nothing follows."""
    artifacts = [
        registered(tmp_path, layer="bronze"),
        registered(tmp_path, layer="silver", pipeline=version(builder_version="0.5.0")),
    ]
    with pytest.raises(PipelineError, match="different pipeline versions"):
        assert_same_pipeline(artifacts)


def test_comparing_no_artifacts_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="no artifacts"):
        assert_same_pipeline([])
