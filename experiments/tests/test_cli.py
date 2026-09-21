from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kpx.cli import main
from kpx.snapshot import SnapshotStore


@pytest.fixture
def snapshots(tmp_path: Path) -> Path:
    root = tmp_path / "snapshots"
    source = tmp_path / "pull"
    source.mkdir()
    (source / "2020.json").write_text('[{"거래금액": "120,000"}]', encoding="utf-8")
    SnapshotStore(root).register(
        source,
        dataset="seoul-apartment-trades",
        source_url="https://example.invalid/api",
        row_count=234_512,
        columns=("시군구", "거래금액"),
        data_schema_version="rtms-apt-trade-v1",
        retrieved_at=datetime(2026, 3, 15),
    )
    return root


def test_info_lists_conditions_and_layers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "monolithic" in out
    assert "gold" in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "kpx" in capsys.readouterr().out


def test_snapshot_list(snapshots: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--snapshots", str(snapshots), "snapshot", "list"]) == 0
    out = capsys.readouterr().out
    assert "seoul-apartment-trades/20260315-" in out
    assert "rows=234,512" in out


def test_snapshot_list_when_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--snapshots", str(tmp_path), "snapshot", "list"]) == 0
    assert "no snapshots registered" in capsys.readouterr().out


def test_snapshot_verify_passes(snapshots: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--snapshots", str(snapshots), "snapshot", "verify"]) == 0
    assert capsys.readouterr().out.startswith("ok ")


def test_snapshot_verify_fails_loudly_on_drift(
    snapshots: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A drifted snapshot must break the build, not be silently measured."""
    store = SnapshotStore(snapshots)
    snapshot_id = store.list_snapshots()[0].snapshot_id
    (store.source_path(snapshot_id) / "2020.json").write_text("drift", encoding="utf-8")
    assert main(["--snapshots", str(snapshots), "snapshot", "verify"]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_snapshot_show_prints_the_citation_block(
    snapshots: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot_id = SnapshotStore(snapshots).list_snapshots()[0].snapshot_id
    assert main(["--snapshots", str(snapshots), "snapshot", "show", snapshot_id]) == 0
    assert "SHA-256: " in capsys.readouterr().out


def test_unknown_snapshot_exits_with_an_error(
    snapshots: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--snapshots", str(snapshots), "snapshot", "show", "d/20260101-abc"])
    assert code == 2
    assert "error:" in capsys.readouterr().err


@pytest.fixture
def datasets(tmp_path: Path) -> Path:
    from kpx.provenance import BuildInputs, ProvenanceStore, config_hash, record_build

    artifact = tmp_path / "out"
    artifact.mkdir()
    (artifact / "data.parquet").write_bytes(b"rows")

    root = tmp_path / "datasets"
    store = ProvenanceStore(root)
    bronze = BuildInputs(
        dataset="seoul-apartment-trades",
        layer="bronze",
        snapshot_id="seoul-apartment-trades/20260315-4f2a91c0d3b7",
        pipeline_version="0.1.0a0",
        config_hash=config_hash({"preserve": True}),
    )
    silver = BuildInputs(
        dataset=bronze.dataset,
        layer="silver",
        snapshot_id=bronze.snapshot_id,
        pipeline_version=bronze.pipeline_version,
        config_hash=config_hash({"normalize": "canonical"}),
        upstream_build_id=bronze.build_id,
    )
    for index, inputs in enumerate((bronze, silver)):
        store.write(
            record_build(
                artifact,
                inputs=inputs,
                row_count=234_512,
                columns=["a"],
                built_at=datetime(2026, 3, 16, 10, index),
            )
        )
    return root


def test_build_list(datasets: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--datasets", str(datasets), "build", "list"]) == 0
    out = capsys.readouterr().out
    assert "bronze" in out
    assert "silver" in out
    assert "rows=234,512" in out


def test_build_list_filters_by_layer(datasets: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--datasets", str(datasets), "build", "list", "--layer", "silver"]) == 0
    out = capsys.readouterr().out
    assert "silver" in out
    assert "bronze" not in out


def test_build_list_when_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--datasets", str(tmp_path), "build", "list"]) == 0
    assert "no builds recorded" in capsys.readouterr().out


def test_build_lineage_runs_bronze_first(
    datasets: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from kpx.provenance import ProvenanceStore

    silver = ProvenanceStore(datasets).list_builds(layer="silver")[0]
    assert main(["--datasets", str(datasets), "build", "lineage", silver.build_id]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("bronze")
    assert lines[1].startswith("  silver")


def test_unknown_build_exits_with_an_error(
    datasets: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--datasets", str(datasets), "build", "lineage", "0000000000000000"])
    assert code == 2
    assert "error:" in capsys.readouterr().err
