from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from kpx.cli import main
from kpx.snapshot import SnapshotStore


@pytest.fixture
def gold_layer(tmp_path: Path) -> Path:
    """Task 1의 Gold가 담는 모양 — 자치구 x 월 집계까지, 최종 답은 없이."""
    path = tmp_path / "gold" / "trades_district_month.parquet"
    path.parent.mkdir(parents=True)
    months = [f"{year}-{month:02d}" for year in (2023, 2024) for month in range(1, 13)]
    pd.DataFrame(
        {
            "district_code": ["11110"] * len(months) + ["11140"] * len(months),
            "year_month": months * 2,
            "n_deals": list(range(1, len(months) * 2 + 1)),
            "mean_price_per_m2": [1.0e7 + n for n in range(len(months) * 2)],
            "median_price_per_m2": [1.0e7 + n for n in range(len(months) * 2)],
        }
    ).to_parquet(path, index=False)
    return path


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


def test_env_prints_the_methodology_block(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["env"]) == 0
    out = capsys.readouterr().out
    assert "- Python:" in out
    assert "pandas" in out


def test_env_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["env", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packages"]["pandas"]


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


class TestSnapshotRegister:
    """Registering is a command, not a throwaway script.

    A snapshot registered by an ad-hoc script is a snapshot whose row count and
    collector version are whatever that copy of the script happened to say.
    """

    @pytest.fixture
    def pull(self, tmp_path: Path) -> Path:
        source = tmp_path / "pull"
        source.mkdir()
        (source / "raw_records.jsonl").write_text(
            '{"aptNm": "x", "dealAmount": "120,000"}\n{"aptNm": "y"}\n', encoding="utf-8"
        )
        return source

    def _register(self, pull: Path, root: Path, *extra: str) -> int:
        return main(
            [
                "--snapshots",
                str(root),
                "snapshot",
                "register",
                str(pull),
                "--dataset",
                "seoul-apartment-trades",
                "--source-url",
                "https://example.invalid/api",
                "--schema-version",
                "rtms-apt-trade-v1",
                *extra,
            ]
        )

    def test_row_count_and_columns_come_from_the_bytes(
        self, tmp_path: Path, pull: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "snapshots"

        assert self._register(pull, root) == 0

        registered = SnapshotStore(root).list_snapshots()[0]
        assert registered.row_count == 2
        assert registered.columns == ("aptNm", "dealAmount")
        assert registered.snapshot_id in capsys.readouterr().out

    def test_collector_version_is_recorded(self, tmp_path: Path, pull: Path) -> None:
        root = tmp_path / "snapshots"

        self._register(pull, root, "--collector", "kpubdata 0.5.0")

        assert SnapshotStore(root).list_snapshots()[0].builder_version == "kpubdata 0.5.0"

    def test_period_is_recorded_when_given(self, tmp_path: Path, pull: Path) -> None:
        root = tmp_path / "snapshots"

        self._register(pull, root, "--period", "2020-01", "2024-12")

        assert SnapshotStore(root).list_snapshots()[0].period == ("2020-01", "2024-12")

    def test_registering_bytes_without_jsonl_fails_instead_of_writing_metadata(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "snapshots"
        source = tmp_path / "pull"
        source.mkdir()
        (source / "records.csv").write_text("aptNm\nx\n", encoding="utf-8")

        assert self._register(source, root) == 2
        assert SnapshotStore(root).list_snapshots() == []


class TestSchemaCommand:
    def test_prints_one_line_per_column_of_a_built_artifact(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trades.parquet"
        pd.DataFrame({"district_code": ["11110"], "price_10k_krw": [120_000]}).to_parquet(path)

        assert main(["schema", str(path)]) == 0

        out = capsys.readouterr().out
        assert "district_code" in out
        assert "price_10k_krw" in out

    def test_a_missing_artifact_is_an_error_not_a_traceback(self, tmp_path: Path) -> None:
        assert main(["schema", str(tmp_path / "absent.parquet")]) == 2


class TestRunCommand:
    """`kpx run` — #13이 정한 실행 경로.

    스크립트가 아니라 설치된 명령이 실험을 돌려야, 재현하려는 사람이 레포 구조를
    몰라도 결과를 다시 만들 수 있다.
    """

    def test_lists_the_tasks_it_knows(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["run", "--list"]) == 0

        assert "task01" in capsys.readouterr().out

    def test_an_unknown_task_is_an_error_not_a_traceback(self) -> None:
        assert main(["run", "--task", "task99", "--condition", "silver"]) == 2

    def test_an_unknown_condition_is_an_error(self) -> None:
        assert main(["run", "--task", "task01", "--condition", "platinum"]) == 2

    def test_a_run_without_layers_says_so_instead_of_crashing(self) -> None:
        assert main(["run", "--task", "task01", "--condition", "gold"]) == 2

    def test_a_malformed_layer_is_an_error(self, tmp_path: Path) -> None:
        assert (
            main(
                [
                    "run",
                    "--task",
                    "task01",
                    "--condition",
                    "gold",
                    "--layer",
                    "seoul-apartment-trades=gold",
                    "--snapshot",
                    "seoul-apartment-trades/20260922-6660c8e25162",
                    "--pipeline-version",
                    "0.1.0+b545c2bd9a32",
                ]
            )
            == 2
        )

    def test_a_run_that_does_not_say_where_its_input_came_from_is_refused(
        self, gold_layer: Path
    ) -> None:
        # 출처 없는 행은 표에 실을 수 없다. 기본값을 넣어 주면 그 자리에 추측이 남는다.
        assert (
            main(
                [
                    "run",
                    "--task",
                    "task01",
                    "--condition",
                    "gold",
                    "--layer",
                    f"seoul-apartment-trades=gold={gold_layer}",
                ]
            )
            == 2
        )

    def test_a_successful_run_is_appended_to_the_result_store(
        self, gold_layer: Path, tmp_path: Path
    ) -> None:
        """#13이 요구한 경로의 끝은 화면이 아니라 experiment_results.parquet이다."""
        results = tmp_path / "results" / "experiment_results.parquet"

        assert (
            main(
                [
                    "run",
                    "--task",
                    "task01",
                    "--condition",
                    "gold",
                    "--layer",
                    f"seoul-apartment-trades=gold={gold_layer}",
                    "--snapshot",
                    "seoul-apartment-trades/20260922-6660c8e25162",
                    "--pipeline-version",
                    "0.1.0+b545c2bd9a32",
                    "--results",
                    str(results),
                ]
            )
            == 0
        )

        stored = pd.read_parquet(results)
        assert list(stored["run_id"]) == ["task01/gold/seed0"]
        assert list(stored["status"]) == ["ok"]
        assert stored["source_snapshot"].iloc[0] == "seoul-apartment-trades/20260922-6660c8e25162"
        assert stored["output_hash"].iloc[0]
