"""빌더가 남긴 산출물을 provenance 사슬로 잇는다 (#40, #51).

Bronze -> Silver -> Gold가 upstream_build_id로 이어져야 R1이 "같은 recipe"를,
R2가 "같은 파이프라인"을 증명할 수 있다. 사슬이 없으면 두 실험 모두 가정에
기댄다.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path

import pytest

from kpx.pipeline import (
    UNKNOWN,
    PipelineVersion,
    assert_same_inputs,
    record_derived_layer,
    record_layer_chain,
)
from kpx.provenance import Provenance, ProvenanceError, ProvenanceStore
from kpx.snapshot import Snapshot

#: Silver가 내놓는 컬럼 — rename/cast/derived를 거친 뒤의 이름들.
SILVER_COLUMNS = ("district_code", "apt_name", "price_10k_krw", "deal_date")

#: 얼린 원천이 갖고 있는 컬럼 — API가 준 그대로의 이름들. Silver와 개수도 이름도
#: 다르다. 같은 값이면 Bronze가 Silver 것을 베껴도 테스트가 눈치채지 못한다.
BRONZE_COLUMNS = ("aptNm", "dealAmount", "dealDay", "dealMonth", "dealYear", "sggCd")

#: 원천에 있던 행 수. 계약이 required를 강제하며 일부를 떨어뜨리므로 Silver보다 많다.
BRONZE_ROWS = 233_600
SILVER_ROWS = 233_596

MANIFEST = {
    "build_id": "trades-silver-001",
    "status": "ok",
    "build_environment": {
        "builder_version": "0.1.0",
        "kpubdata_version": "0.5.0",
        "python_version": "3.13.2",
    },
    "row_counts": {"trades": SILVER_ROWS},
    "schema_summaries": {
        "trades": {"fields": [{"name": name} for name in SILVER_COLUMNS]},
    },
}
CONFIG = {"rename": {"sggCd": "district_code"}, "casts": {"price": "int_comma"}}

SNAPSHOT = Snapshot(
    snapshot_id="seoul-apartment-trades/20260922-6660c8e25162",
    dataset="seoul-apartment-trades",
    retrieved_at=datetime.fromisoformat("2026-09-22T14:47:57+00:00"),
    source_url="https://example.invalid/apt-trade",
    row_count=BRONZE_ROWS,
    columns=BRONZE_COLUMNS,
    checksum="0" * 64,
    size_bytes=1024,
    file_count=1,
    data_schema_version="datago.apt_trade",
)

GOLD_RECIPE = "def aggregate(frame):\n    return frame.groupby('district_code').mean()\n"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "trades-silver-001"
    for layer in ("bronze", "silver"):
        directory = root / layer / "trades"
        directory.mkdir(parents=True)
        (directory / "table.parquet").write_text(f"{layer} bytes", encoding="utf-8")
    # 빌더는 Bronze를 내용 주소 디렉터리 안에 쓰고 그 옆에 자기 metadata를 남긴다.
    bronze = root / "bronze" / "trades" / "b9e9559d76d1"
    bronze.mkdir(parents=True)
    (bronze / "metadata.json").write_text(
        json.dumps({"record_count": BRONZE_ROWS}), encoding="utf-8"
    )
    (root / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    return root


@pytest.fixture
def store(tmp_path: Path) -> ProvenanceStore:
    return ProvenanceStore(tmp_path / "datasets")


def chain(run_dir: Path, store: ProvenanceStore, **kwargs: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "snapshot": SNAPSHOT,
        "config": CONFIG,
        "alias": "trades",
        "store": store,
    }
    defaults.update(kwargs)
    return record_layer_chain(run_dir, **defaults)  # type: ignore[arg-type]


def derive(
    artifact: Path, upstream: Provenance, store: ProvenanceStore, **kwargs: object
) -> Provenance:
    artifact.mkdir(exist_ok=True)
    (artifact / "aggregate.parquet").write_text("gold bytes", encoding="utf-8")
    defaults: dict[str, object] = {
        "layer": "gold",
        "upstream": upstream,
        "recipe": GOLD_RECIPE,
        "row_count": 1500,
        "columns": ("district_code", "year_month"),
        "store": store,
    }
    defaults.update(kwargs)
    return record_derived_layer(artifact, **defaults)  # type: ignore[arg-type]


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
        assert recorded["silver"].row_count == SILVER_ROWS

    def test_the_pipeline_version_comes_from_the_manifest_not_a_literal(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        expected = PipelineVersion.from_build_manifest(MANIFEST, CONFIG).identifier

        assert chain(run_dir, store)["silver"].inputs.pipeline_version == expected
        assert "0.1.0" in expected


class TestBronzeDescribesItself:
    """Bronze는 Silver의 모양을 물려받지 않는다.

    manifest의 row_counts/schema_summaries는 canonical 출력을 말한다. 그것을 Bronze
    기록에 그대로 쓰면 Bronze가 원천에 없는 컬럼을 자기 것이라 주장하고, 계층 간
    행 손실이 정의상 0이 되어 R2가 재려는 것이 사라진다.
    """

    def test_bronze_counts_the_rows_the_builder_fetched(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)

        assert recorded["bronze"].row_count == BRONZE_ROWS
        assert recorded["silver"].row_count == SILVER_ROWS

    def test_bronze_columns_come_from_the_frozen_snapshot(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)

        assert recorded["bronze"].columns == BRONZE_COLUMNS
        assert recorded["silver"].columns == SILVER_COLUMNS

    def test_a_bronze_artifact_without_metadata_is_refused(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        (run_dir / "bronze" / "trades" / "b9e9559d76d1" / "metadata.json").unlink()

        with pytest.raises(Exception, match="metadata"):
            chain(run_dir, store)


class TestBuildEnvironment:
    """빌드가 돈 곳은 manifest가 말하는 곳이지, 이 기록을 읽는 곳이 아니다."""

    def test_the_builder_versions_are_taken_from_the_manifest(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        environment = chain(run_dir, store)["silver"].environment

        assert environment.python_version == "3.13.2"
        assert environment.packages["kpubdata-builder"] == "0.1.0"
        assert environment.packages["kpubdata"] == "0.5.0"

    def test_the_harness_platform_is_not_written_onto_a_builder_run(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        # manifest는 어느 기계에서 빌드했는지 말하지 않는다. 읽는 쪽 기계를 적으면
        # Environment.differences가 "환경이 움직였나"에 거짓으로 답하게 된다.
        environment = chain(run_dir, store)["bronze"].environment

        assert environment.platform == UNKNOWN
        assert "pandas" not in environment.packages


class TestGold:
    """과제용 Gold는 harness가 Silver에서 만든다. 사슬은 거기서 이어져야 한다."""

    def test_gold_names_silver_as_its_upstream(
        self, tmp_path: Path, run_dir: Path, store: ProvenanceStore
    ) -> None:
        recorded = chain(run_dir, store)

        gold = derive(tmp_path / "gold", recorded["silver"], store)

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

        gold = derive(tmp_path / "gold", recorded["silver"], store)

        assert gold.inputs.snapshot_id == recorded["silver"].inputs.snapshot_id
        assert gold.inputs.pipeline_version == recorded["silver"].inputs.pipeline_version

    def test_changing_the_aggregation_moves_the_gold_build_id(
        self, tmp_path: Path, run_dir: Path, store: ProvenanceStore
    ) -> None:
        # Gold 레시피가 identity에 없으면, 집계를 고쳐도 같은 build_id가 나와서
        # 기록이 자기가 본 적 없는 바이트를 서술하게 된다.
        recorded = chain(run_dir, store)

        first = derive(tmp_path / "gold", recorded["silver"], store)
        second = derive(
            tmp_path / "gold", recorded["silver"], store, recipe=GOLD_RECIPE + "# 중앙값도 낸다\n"
        )

        assert first.build_id != second.build_id
        assert first.inputs.config_hash != second.inputs.config_hash

    def test_gold_records_the_harness_that_actually_built_it(
        self, tmp_path: Path, run_dir: Path, store: ProvenanceStore
    ) -> None:
        # Gold는 builder가 아니라 이 harness가 만든다. upstream의 builder 환경을
        # 물려받으면 이번에는 반대 방향으로 거짓말을 하게 된다.
        recorded = chain(run_dir, store)

        gold = derive(tmp_path / "gold", recorded["silver"], store)

        assert gold.environment != recorded["silver"].environment
        assert gold.environment.platform != UNKNOWN


class TestMixingArtifacts:
    """서로 다른 스냅샷이나 파이프라인의 산출물을 섞으면 즉시 실패해야 한다.

    섞인 채로 측정이 끝나면 그 숫자는 어떤 입력에서 나온 것인지 말할 수 없다.
    """

    def test_a_different_snapshot_is_refused(self, run_dir: Path, store: ProvenanceStore) -> None:
        first = chain(run_dir, store)["silver"]
        other = dataclasses.replace(SNAPSHOT, snapshot_id="seoul-apartment-trades/other-1234")
        second = chain(run_dir, store, snapshot=other)["silver"]

        with pytest.raises(ProvenanceError, match="snapshot"):
            assert_same_inputs([first, second])

    def test_a_different_pipeline_version_is_refused(
        self, run_dir: Path, store: ProvenanceStore
    ) -> None:
        first = chain(run_dir, store)["silver"]
        second = chain(run_dir, store, config={"rename": {}, "casts": {}})["silver"]

        with pytest.raises(ProvenanceError, match="pipeline"):
            assert_same_inputs([first, second])

    def test_matching_builds_pass(self, run_dir: Path, store: ProvenanceStore) -> None:
        recorded = chain(run_dir, store)

        assert_same_inputs([recorded["bronze"], recorded["silver"]])
