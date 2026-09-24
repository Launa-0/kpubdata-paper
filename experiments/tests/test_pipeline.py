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
    transformation_recipe,
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


class TestTransformationRecipe:
    """pipeline_version이 해시하는 것 — 선언 한 벌에서 한 번만 만들어진다.

    이전에는 각 스크립트가 rename/casts/read_as 세 개만 골라 담았고, 그래서
    ``derived``를 고쳐도 식별자가 움직이지 않았다. 허용 목록은 새 규칙이 생길 때마다
    조용히 같은 결함을 다시 만든다.
    """

    SPEC = {
        "dataset_id": "seoul-apartment-trades",
        "title": "Seoul Apartment Trades",
        "source": {
            "kind": "file",
            "alias": "trades",
            "format": "jsonl",
            "upload_id": "upl_c82eb4f2",
        },
        "contract": {
            "read_as": {"sggCd": "str"},
            "required": ("district_code",),
            "rename": {"sggCd": "district_code"},
            "casts": {"price_10k_krw": "int_comma"},
            "null_tokens": (),
            "derived": ({"name": "deal_date", "kind": "date_parts"},),
        },
        "exports": ({"kind": "parquet", "output_path": "trades.parquet"},),
    }

    def _hash(self, **overrides: object) -> str:
        return config_hash(transformation_recipe({**self.SPEC, **overrides}))

    def test_a_changed_transformation_rule_moves_the_hash(self) -> None:
        for key, replacement in (
            ("read_as", {"sggCd": "int"}),
            ("required", ("district_code", "apt_name")),
            ("rename", {"sggCd": "gu"}),
            ("casts", {"price_10k_krw": "int"}),
            ("null_tokens", ("",)),
            ("derived", ({"name": "deal_date", "kind": "concat"},)),
        ):
            contract = {**self.SPEC["contract"], key: replacement}  # type: ignore[dict-item]

            assert self._hash(contract=contract) != self._hash(), key

    def test_the_export_format_counts_but_its_path_does_not(self) -> None:
        assert self._hash(exports=({"kind": "csv", "output_path": "trades.parquet"},)) != (
            self._hash()
        )
        assert self._hash(exports=({"kind": "parquet", "output_path": "elsewhere.parquet"},)) == (
            self._hash()
        )

    def test_values_that_change_every_run_are_left_out(self) -> None:
        """이것들이 들어가면 R1의 반복 빌드와 R2의 세대별 빌드가 서로 다른 파이프라인이
        되어 버린다 — 고치려던 것과 정반대의 고장이다."""
        other_run = {**self.SPEC["source"], "upload_id": "upl_ffffffff"}  # type: ignore[dict-item]

        assert self._hash(source=other_run) == self._hash()
        assert self._hash(title="Something Else") == self._hash()
        assert self._hash(description="R1 재빌드 결정성 측정") == self._hash()

    def test_a_new_rule_is_in_the_identity_without_anyone_adding_it(self) -> None:
        """거부 목록이라 기본값이 '포함'이다. 허용 목록이면 이 단언이 실패한다."""
        contract = {**self.SPEC["contract"], "filters": ("deal_year >= 2020",)}

        assert self._hash(contract=contract) != self._hash()


class TestBindMeasuredArtifact:
    """측정한 바이트가 어느 기록된 빌드인지 — builder까지 묶는다."""

    SPEC = {
        "dataset_id": "seoul-apartment-trades",
        "snapshot_id": "seoul-apartment-trades/20260922-6660c8e25162",
        "run_id": "trades-silver-001",
        "contract": {"rename": {"sggCd": "district_code"}},
    }

    def record(self, artifact: Path, store: object, builder: str) -> object:
        from kpx.pipeline import PipelineVersion, transformation_recipe
        from kpx.provenance import ProvenanceStore

        assert isinstance(store, ProvenanceStore)
        config = config_hash(transformation_recipe(self.SPEC))
        provenance = record_build(
            artifact,
            inputs=BuildInputs(
                dataset=str(self.SPEC["dataset_id"]),
                layer="silver",
                snapshot_id=str(self.SPEC["snapshot_id"]),
                pipeline_version=PipelineVersion(builder, config).identifier,
                config_hash=config,
                upstream_build_id="0" * 16,
            ),
            row_count=1,
            columns=["district_code"],
        )
        store.write(provenance)
        return provenance

    def test_the_build_of_the_named_builder_is_chosen_when_the_bytes_are_equal(
        self, tmp_path: Path
    ) -> None:
        """수정 전후 builder가 byte 단위로 같은 Silver를 냈다. 체크섬만으로는 어느
        builder의 빌드를 쟀는지 말할 수 없다 — 더 늦게 기록된 쪽을 집으면 틀린다."""
        from kpx.pipeline import bind_measured_artifact
        from kpx.provenance import ProvenanceStore

        artifact = tmp_path / "silver"
        artifact.mkdir()
        (artifact / "table.parquet").write_bytes(b"same bytes")
        store = ProvenanceStore(tmp_path / "datasets")
        old = self.record(artifact, store, "0.4.0.dev0+5d86eedf3a1a")
        self.record(artifact, store, "0.4.0.dev0+096d023f9546")

        bound = bind_measured_artifact(
            artifact, spec=self.SPEC, store=store, builder_version="0.4.0.dev0+5d86eedf3a1a"
        )

        assert bound == old

    def test_a_builder_with_no_recorded_build_is_refused(self, tmp_path: Path) -> None:
        from kpx.pipeline import bind_measured_artifact
        from kpx.provenance import ProvenanceError, ProvenanceStore

        artifact = tmp_path / "silver"
        artifact.mkdir()
        (artifact / "table.parquet").write_bytes(b"same bytes")
        store = ProvenanceStore(tmp_path / "datasets")
        self.record(artifact, store, "0.4.0.dev0+5d86eedf3a1a")

        with pytest.raises(ProvenanceError, match="builder"):
            bind_measured_artifact(
                artifact, spec=self.SPEC, store=store, builder_version="0.4.0.dev0+ffffffffffff"
            )

    def test_bytes_that_no_record_names_are_refused(self, tmp_path: Path) -> None:
        from kpx.pipeline import bind_measured_artifact
        from kpx.provenance import ProvenanceError, ProvenanceStore

        artifact = tmp_path / "silver"
        artifact.mkdir()
        (artifact / "table.parquet").write_bytes(b"recorded bytes")
        store = ProvenanceStore(tmp_path / "datasets")
        self.record(artifact, store, "0.4.0.dev0+5d86eedf3a1a")
        (artifact / "table.parquet").write_bytes(b"stale bytes")

        with pytest.raises(ProvenanceError, match="does not match"):
            bind_measured_artifact(
                artifact, spec=self.SPEC, store=store, builder_version="0.4.0.dev0+5d86eedf3a1a"
            )
