from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path, PureWindowsPath

import pytest

from kpx.pipeline import (
    UNKNOWN,
    PipelineError,
    PipelineVersion,
    assert_same_pipeline,
    canonical_config,
    config_hash,
)
from kpx.provenance import BuildInputs, record_build

# -- canonical config -------------------------------------------------------


def test_key_order_does_not_change_the_hash() -> None:
    assert config_hash({"a": 1, "b": [2, 3]}) == config_hash({"b": [2, 3], "a": 1})


def test_a_different_config_hashes_differently() -> None:
    assert config_hash({"drop_duplicates": True}) != config_hash({"drop_duplicates": False})


def test_nested_key_order_does_not_change_the_hash() -> None:
    first = {"silver": {"rename": True, "retype": False}}
    second = {"silver": {"retype": False, "rename": True}}
    assert config_hash(first) == config_hash(second)


def test_paths_are_hashed_posix_style(tmp_path: Path) -> None:
    """A config naming a directory must not hash differently on Windows.

    The same defect that made snapshot ids platform-dependent, reached through
    another door.
    """
    windows = canonical_config({"out": PureWindowsPath("datasets") / "trades" / "silver"})
    posix = canonical_config({"out": "datasets/trades/silver"})
    assert windows == posix


def test_a_tuple_and_a_list_hash_alike() -> None:
    assert config_hash({"columns": ("a", "b")}) == config_hash({"columns": ["a", "b"]})


def test_nan_is_refused_rather_than_hashed() -> None:
    with pytest.raises(ValueError):
        config_hash({"threshold": math.nan})


def test_an_unserializable_value_is_stringified_not_dropped() -> None:
    class Opaque:
        def __repr__(self) -> str:
            return "Opaque(v=1)"

    assert "Opaque(v=1)" in canonical_config({"strategy": Opaque()})


# -- the identifier ---------------------------------------------------------


def test_identifier_joins_the_code_and_the_configuration() -> None:
    version = PipelineVersion(builder_version="0.1.0a0", config_hash="a" * 64)
    assert version.identifier == "0.1.0a0+aaaaaaaaaaaa"


def test_identifier_moves_when_the_code_moves() -> None:
    config = config_hash({"normalize": "canonical"})
    first = PipelineVersion(builder_version="0.1.0a0", config_hash=config)
    second = PipelineVersion(builder_version="0.2.0", config_hash=config)
    assert first.identifier != second.identifier


def test_identifier_moves_when_the_configuration_moves() -> None:
    first = PipelineVersion(builder_version="0.1.0a0", config_hash=config_hash({"a": 1}))
    second = PipelineVersion(builder_version="0.1.0a0", config_hash=config_hash({"a": 2}))
    assert first.identifier != second.identifier


def test_a_version_missing_a_component_is_not_complete() -> None:
    """The gap belongs in the methodology section, not in an unwritten footnote."""
    version = PipelineVersion(builder_version=UNKNOWN, config_hash="a" * 64)
    assert not version.is_complete


def test_a_fully_established_version_is_complete() -> None:
    version = PipelineVersion(
        builder_version="0.1.0a0",
        config_hash="a" * 64,
        kpubdata_version="0.1.0a0",
        python_version="3.12.4",
    )
    assert version.is_complete


def test_round_trips_through_json() -> None:
    version = PipelineVersion.capture({"normalize": "canonical"}, builder_version="0.1.0a0")
    assert PipelineVersion.from_json(version.to_json()) == version


# -- reading a builder manifest ---------------------------------------------
#
# kpubdata-builder's BuildManifest today carries build_id, timings, inputs,
# outputs, warnings, errors and row_counts — and no version fields at all.


def today_manifest() -> dict[str, object]:
    return {
        "build_id": "b-2026-03-16-01",
        "started_at": "2026-03-16T10:00:00+00:00",
        "finished_at": "2026-03-16T10:04:00+00:00",
        "inputs": ["rtms-apt-trade"],
        "outputs": ["trades.parquet"],
        "warnings": [],
        "errors": [],
        "row_counts": {"trades": 234512},
    }


def test_todays_manifest_yields_unknown_versions_rather_than_a_guess() -> None:
    version = PipelineVersion.from_build_manifest(today_manifest(), {"normalize": "canonical"})
    assert version.builder_version == UNKNOWN
    assert not version.is_complete


def test_the_builders_build_id_is_carried_through() -> None:
    version = PipelineVersion.from_build_manifest(today_manifest(), {})
    assert version.builder_build_id == "b-2026-03-16-01"


def test_versions_may_be_supplied_by_the_caller() -> None:
    version = PipelineVersion.from_build_manifest(
        today_manifest(),
        {"normalize": "canonical"},
        builder_version="0.1.0a0",
        kpubdata_version="0.1.0a0",
        python_version="3.12.4",
    )
    assert version.is_complete
    assert version.identifier.startswith("0.1.0a0+")


def test_a_future_manifest_carrying_an_environment_is_read() -> None:
    manifest = today_manifest() | {
        "build_environment": {
            "builder_version": "0.3.0",
            "kpubdata_version": "0.3.1",
            "python_version": "3.13.1",
        }
    }
    version = PipelineVersion.from_build_manifest(manifest, {})
    assert version.builder_version == "0.3.0"
    assert version.is_complete


def test_an_explicit_version_wins_over_the_manifest() -> None:
    manifest = today_manifest() | {"build_environment": {"builder_version": "0.3.0"}}
    version = PipelineVersion.from_build_manifest(manifest, {}, builder_version="0.4.0")
    assert version.builder_version == "0.4.0"


def test_a_malformed_environment_is_refused() -> None:
    with pytest.raises(PipelineError, match="not an object"):
        PipelineVersion.from_build_manifest(today_manifest() | {"build_environment": "0.3.0"}, {})


def test_capture_reads_the_running_interpreter() -> None:
    version = PipelineVersion.capture({}, builder_version="0.1.0a0")
    assert version.python_version.count(".") == 2


# -- R2's precondition ------------------------------------------------------


def build(tmp_path: Path, snapshot: str, pipeline_version: str) -> object:
    artifact = tmp_path / snapshot.replace("/", "_")
    artifact.mkdir()
    (artifact / "data.parquet").write_bytes(b"rows")
    return record_build(
        artifact,
        inputs=BuildInputs(
            dataset="seoul-bike-rent-month",
            layer="bronze",
            snapshot_id=snapshot,
            pipeline_version=pipeline_version,
            config_hash=config_hash({"preserve": True}),
        ),
        row_count=119_000,
        columns=["station_id"],
        built_at=datetime(2026, 3, 16, 10, 0),
    )


def test_snapshots_built_by_one_pipeline_compare(tmp_path: Path) -> None:
    builds = [
        build(tmp_path, f"seoul-bike-rent-month/2026030{n}-aaaaaaaaaaaa", "0.1.0a0+abc123def456")
        for n in (1, 2, 3)
    ]
    assert assert_same_pipeline(builds) == "0.1.0a0+abc123def456"


def test_a_pipeline_change_across_snapshots_is_refused(tmp_path: Path) -> None:
    """Otherwise R2 would attribute a pipeline change to the source."""
    builds = [
        build(tmp_path, "seoul-bike-rent-month/20260301-aaaaaaaaaaaa", "0.1.0a0+abc123def456"),
        build(tmp_path, "seoul-bike-rent-month/20260601-bbbbbbbbbbbb", "0.2.0+abc123def456"),
    ]
    with pytest.raises(PipelineError, match="different pipeline versions"):
        assert_same_pipeline(builds)


def test_comparing_nothing_is_refused() -> None:
    with pytest.raises(PipelineError, match="no builds to compare"):
        assert_same_pipeline([])
