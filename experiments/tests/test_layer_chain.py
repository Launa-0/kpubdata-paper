"""빌더가 남긴 산출물을 provenance 사슬로 잇는다 (#40, #51).

Bronze -> Silver -> Gold가 upstream_build_id로 이어져야 R1이 "같은 recipe"를,
R2가 "같은 파이프라인"을 증명할 수 있다. 사슬이 없으면 두 실험 모두 가정에
기댄다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kpx.pipeline import (
    PipelineVersion,
    assert_same_inputs,
    record_derived_layer,
    record_layer_chain,
)
from kpx.provenance import Provenance, ProvenanceError, ProvenanceStore

MANIFEST = {
    "build_id": "trades-silver-001",
    "status": "ok",
    "build_environment": {
        "builder_version": "0.1.0",
        "kpubdata_version": "0.5.0",
        "python_version": "3.13.2",
    },
    "row_counts": {"trades": 233_596},
}
CONFIG = {"rename": {"sggCd": "district_code"}, "casts": {"price": "int_comma"}}
SNAPSHOT = "seoul-apartment-trades/20260922-6660c8e25162"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "trades-silver-001"
    for layer in ("bronze", "silver"):
        directory = root / layer / "trades"
        directory.mkdir(parents=True)
        (directory / "table.parquet").write_text(f"{layer} bytes", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    return root


@pytest.fixture
def store(tmp_path: Path) -> ProvenanceStore:
    return ProvenanceStore(tmp_path / "datasets")


def chain(run_dir: Path, store: ProvenanceStore, **kwargs: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "dataset": "seoul-apartment-trades",
        "snapshot_id": SNAPSHOT,
        "config": CONFIG,
        "alias": "trades",
        "store": store,
    }
    defaults.update(kwargs)
    return record_layer_chain(run_dir, **defaults)  # type: ignore[arg-type]


class TestChain:
    def test_bronze_and_silver_are_both_recorded(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)

        assert sorted(recorded) == ["bronze", "silver"]
        assert [build.inputs.layer for build in store.list_builds()] == ["bronze", "silver"]

    def test_silver_names_bronze_as_its_upstream(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)

        assert recorded["silver"].inputs.upstream_build_id == recorded["bronze"].build_id

    def test_bronze_has_no_upstream_because_it_comes_from_a_snapshot(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        assert chain(run_dir, store)["bronze"].inputs.upstream_build_id is None

    def test_lineage_of_silver_starts_at_bronze(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)

        lineage = store.lineage(recorded["silver"].build_id)

        assert [build.inputs.layer for build in lineage] == ["bronze", "silver"]

    def test_every_layer_records_its_own_bytes(self, run_dir: Path, store: ProvenanceStore) -> None:
        recorded = chain(run_dir, store)

        assert recorded["bronze"].output_checksum != recorded["silver"].output_checksum
        assert recorded["silver"].output_size_bytes > 0
        assert recorded["silver"].row_count == 233_596

    def test_the_pipeline_version_comes_from_the_manifest_not_a_literal(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        expected = PipelineVersion.from_build_manifest(MANIFEST, CONFIG).identifier

        assert chain(run_dir, store)["silver"].inputs.pipeline_version == expected
        assert "0.1.0" in expected


class TestRefusals:
    def test_a_failed_build_is_not_recorded_as_a_clean_one(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        manifest = {**MANIFEST, "status": "failed"}
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        recorded = chain(run_dir, store)

        assert all(build.status == "failed" for build in recorded.values())

    def test_a_missing_layer_directory_is_named(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        import shutil

        shutil.rmtree(run_dir / "silver")

        with pytest.raises(ProvenanceError, match="silver"):
            chain(run_dir, store)

    def test_a_run_without_a_manifest_is_refused(
        self, tmp_path: Path, store: ProvenanceStore
    ) -> None:
        with pytest.raises(ProvenanceError, match="manifest"):
            chain(tmp_path / "absent", store)


class TestGold:
    """과제용 Gold는 harness가 Silver에서 만든다. 사슬은 거기서 이어져야 한다."""

    def test_gold_names_silver_as_its_upstream(
        self, tmp_path: Path, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)
        artifact = tmp_path / "gold"
        artifact.mkdir()
        (artifact / "aggregate.parquet").write_text("gold bytes", encoding="utf-8")

        gold = record_derived_layer(
            artifact,
            layer="gold",
            upstream=recorded["silver"],
            row_count=1500,
            columns=("district_code", "year_month"),
            store=store,
        )

        assert gold.inputs.upstream_build_id == recorded["silver"].build_id
        assert [b.inputs.layer for b in store.lineage(gold.build_id)] == [
            "bronze",
            "silver",
            "gold",
        ]

    def test_gold_inherits_the_snapshot_and_pipeline_of_its_upstream(
        self, tmp_path: Path, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)
        artifact = tmp_path / "gold"
        artifact.mkdir()
        (artifact / "aggregate.parquet").write_text("gold bytes", encoding="utf-8")

        gold = record_derived_layer(
            artifact,
            layer="gold",
            upstream=recorded["silver"],
            row_count=1500,
            columns=(),
            store=store,
        )

        assert gold.inputs.snapshot_id == recorded["silver"].inputs.snapshot_id
        assert gold.inputs.pipeline_version == recorded["silver"].inputs.pipeline_version


class TestMixingArtifacts:
    """서로 다른 스냅샷이나 파이프라인의 산출물을 섞으면 즉시 실패해야 한다.

    섞인 채로 측정이 끝나면 그 숫자는 어떤 입력에서 나온 것인지 말할 수 없다.
    """

    def _other(self, run_dir: Path, store: ProvenanceStore, **kwargs: object) -> Provenance:
        return chain(run_dir, store, **kwargs)["silver"]

    def test_a_different_snapshot_is_refused(self, run_dir: Path, store: ProvenanceStore) -> None:
        first = chain(run_dir, store)["silver"]
        second = self._other(run_dir, store, snapshot_id="seoul-apartment-trades/other-1234")

        with pytest.raises(ProvenanceError, match="snapshot"):
            assert_same_inputs([first, second])

    def test_a_different_pipeline_version_is_refused(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        first = chain(run_dir, store)["silver"]
        second = self._other(run_dir, store, config={"rename": {}, "casts": {}})

        with pytest.raises(ProvenanceError, match="pipeline"):
            assert_same_inputs([first, second])

    def test_matching_builds_pass(self, run_dir: Path, store: ProvenanceStore) -> None:
        recorded = chain(run_dir, store)

        assert_same_inputs([recorded["bronze"], recorded["silver"]])
