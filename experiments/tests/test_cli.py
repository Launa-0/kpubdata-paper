from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kpx.cli import main
from kpx.pipeline import ArtifactStore, PipelineVersion
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


@pytest.fixture
def datasets(tmp_path: Path) -> Path:
    root = tmp_path / "datasets"
    store = ArtifactStore(root)
    data = store.data_path("seoul-apartment-trades", "silver")
    data.mkdir(parents=True)
    (data / "trades.json").write_text('[{"price_krw": 1200000000}]', encoding="utf-8")
    store.register(
        data,
        dataset="seoul-apartment-trades",
        layer="silver",
        snapshot_id="seoul-apartment-trades/20260315-4f2a91c0d3b7",
        pipeline=PipelineVersion(builder_version="0.4.1", config_hash="a" * 64),
        row_count=234_512,
        columns=("district_code", "price_krw"),
    )
    return root


def test_artifact_list(datasets: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--datasets", str(datasets), "artifact", "list"]) == 0
    out = capsys.readouterr().out
    assert "seoul-apartment-trades" in out
    assert "pipeline=0.4.1+aaaaaaaaaaaa" in out


def test_artifact_list_when_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--datasets", str(tmp_path), "artifact", "list"]) == 0
    assert "no artifacts registered" in capsys.readouterr().out


def test_artifact_show_prints_the_provenance_block(
    datasets: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--datasets", str(datasets), "artifact", "show", "seoul-apartment-trades", "silver"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Pipeline version: 0.4.1+" in out
    assert "Source snapshot: seoul-apartment-trades/" in out


def test_artifact_verify_passes(datasets: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--datasets", str(datasets), "artifact", "verify"]) == 0
    assert capsys.readouterr().out.startswith("ok ")


def test_artifact_verify_fails_loudly_on_drift(
    datasets: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rebuilt artifact that no longer matches its record invalidates R1."""
    data = ArtifactStore(datasets).data_path("seoul-apartment-trades", "silver")
    (data / "trades.json").write_text("drift", encoding="utf-8")
    assert main(["--datasets", str(datasets), "artifact", "verify"]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_unknown_artifact_exits_with_an_error(
    datasets: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--datasets", str(datasets), "artifact", "show", "nope", "gold"])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_unknown_snapshot_exits_with_an_error(
    snapshots: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--snapshots", str(snapshots), "snapshot", "show", "d/20260101-abc"])
    assert code == 2
    assert "error:" in capsys.readouterr().err
