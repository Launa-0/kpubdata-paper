from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kpx.snapshot import (
    Snapshot,
    SnapshotError,
    SnapshotStore,
    dataset_table,
    scan_jsonl,
)

RETRIEVED = datetime(2026, 3, 15, 9, 30)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "pull"
    root.mkdir()
    (root / "2020.json").write_text('[{"거래금액": "120,000"}]', encoding="utf-8")
    (root / "2021.json").write_text('[{"거래금액": "135,500"}]', encoding="utf-8")
    return root


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snapshots")


def register(store: SnapshotStore, source: Path, **kwargs: object) -> Snapshot:
    defaults: dict[str, object] = {
        "dataset": "seoul-apartment-trades",
        "source_url": "https://api.odcloud.kr/api/RTMSDataSvcAptTrade",
        "row_count": 234_512,
        "columns": ("시군구", "거래금액", "계약년월", "계약일"),
        "data_schema_version": "rtms-apt-trade-v1",
        "retrieved_at": RETRIEVED,
        "period": ("2020-01", "2024-12"),
    }
    defaults.update(kwargs)
    return store.register(source, **defaults)  # type: ignore[arg-type]


def test_snapshot_id_is_content_addressed_and_date_prefixed(
    store: SnapshotStore, source: Path
) -> None:
    snapshot = register(store, source)
    assert snapshot.snapshot_id.startswith("seoul-apartment-trades/20260315-")
    assert snapshot.snapshot_id.endswith(snapshot.checksum[:12])


def test_same_bytes_produce_the_same_id(store: SnapshotStore, source: Path, tmp_path: Path) -> None:
    """R1's 'identical source' must be checkable, not assumed."""
    copy = tmp_path / "pull-copy"
    copy.mkdir()
    for child in source.iterdir():
        (copy / child.name).write_bytes(child.read_bytes())
    assert register(store, source).snapshot_id == register(store, copy).snapshot_id


def test_different_bytes_produce_a_different_id(store: SnapshotStore, source: Path) -> None:
    first = register(store, source)
    (source / "2022.json").write_text("[]", encoding="utf-8")
    assert register(store, source).snapshot_id != first.snapshot_id


def test_source_is_copied_not_referenced(store: SnapshotStore, source: Path) -> None:
    """A snapshot pointing at a working directory is not frozen."""
    snapshot = register(store, source)
    (source / "2020.json").write_text("mutated", encoding="utf-8")
    assert store.verify(snapshot.snapshot_id).ok


def test_verify_detects_drifted_bytes(store: SnapshotStore, source: Path) -> None:
    snapshot = register(store, source)
    (store.source_path(snapshot.snapshot_id) / "2020.json").write_text("drift", encoding="utf-8")
    result = store.verify(snapshot.snapshot_id)
    assert not result.ok
    assert "do not match" in result.reason
    with pytest.raises(SnapshotError, match="failed verification"):
        result.raise_for_status()


def test_verify_reports_missing_bytes(store: SnapshotStore, source: Path) -> None:
    """A reader who has metadata but not the data gets a clear answer."""
    import shutil

    snapshot = register(store, source)
    shutil.rmtree(store.source_path(snapshot.snapshot_id))
    result = store.verify(snapshot.snapshot_id)
    assert not result.ok
    assert result.actual is None
    assert "not present" in result.reason


def test_metadata_round_trips(store: SnapshotStore, source: Path) -> None:
    snapshot = register(store, source)
    assert store.load(snapshot.snapshot_id) == snapshot


def test_metadata_written_next_to_source_does_not_change_the_digest(
    store: SnapshotStore, source: Path
) -> None:
    snapshot = register(store, source)
    assert store.verify(snapshot.snapshot_id).ok


def test_list_is_ordered_oldest_first(store: SnapshotStore, source: Path) -> None:
    """R2 compares snapshots in time order."""
    t2 = register(store, source, retrieved_at=datetime(2026, 6, 1))
    (source / "2022.json").write_text("[]", encoding="utf-8")
    t3 = register(store, source, retrieved_at=datetime(2026, 9, 1))
    (source / "2023.json").write_text("[]", encoding="utf-8")
    t1 = register(store, source, retrieved_at=datetime(2026, 1, 1))
    assert [s.snapshot_id for s in store.list_snapshots()] == [
        t1.snapshot_id,
        t2.snapshot_id,
        t3.snapshot_id,
    ]


def test_list_can_filter_by_dataset(store: SnapshotStore, source: Path) -> None:
    register(store, source)
    register(store, source, dataset="seoul-bike-rent-month")
    bike = store.list_snapshots("seoul-bike-rent-month")
    assert [s.dataset for s in bike] == ["seoul-bike-rent-month"]


def test_re_registering_identical_bytes_is_idempotent(store: SnapshotStore, source: Path) -> None:
    first = register(store, source)
    assert register(store, source) == first


def test_dataset_row_carries_every_column_the_table_needs(
    store: SnapshotStore, source: Path
) -> None:
    row = register(store, source).dataset_row()
    assert set(row) == {"Dataset", "Rows", "Columns", "Period", "Size", "Snapshot"}
    assert row["Period"] == "2020-01–2024-12"
    assert row["Columns"] == 4


def test_period_is_optional(store: SnapshotStore, source: Path) -> None:
    assert register(store, source, period=None).dataset_row()["Period"] == "—"


def test_citation_matches_the_block_quoted_in_the_paper(store: SnapshotStore, source: Path) -> None:
    lines = register(store, source).citation().splitlines()
    assert lines[0] == "Snapshot date: 2026-03-15"
    assert lines[1] == "Rows: 234,512"
    assert lines[2].startswith("SHA-256: ")


def test_retrieved_at_is_distinct_from_the_data_period(store: SnapshotStore, source: Path) -> None:
    snapshot = register(store, source)
    assert snapshot.retrieved_on.year == 2026
    assert snapshot.period == ("2020-01", "2024-12")


def test_unknown_snapshot_is_reported(store: SnapshotStore) -> None:
    with pytest.raises(SnapshotError, match="no snapshot registered"):
        store.load("seoul-apartment-trades/20260315-deadbeefcafe")


def test_malformed_snapshot_id_is_rejected(store: SnapshotStore) -> None:
    with pytest.raises(SnapshotError, match="malformed snapshot id"):
        store.directory("not-a-snapshot-id")


def test_newer_metadata_version_is_refused_rather_than_partially_read() -> None:
    with pytest.raises(SnapshotError, match="upgrade kpx"):
        Snapshot.from_json(
            {
                "snapshot_id": "d/20260101-abc",
                "dataset": "d",
                "retrieved_at": "2026-01-01T00:00:00",
                "source_url": "",
                "row_count": 1,
                "columns": [],
                "checksum": "x",
                "size_bytes": 1,
                "file_count": 1,
                "data_schema_version": "v1",
                "metadata_schema_version": 99,
            }
        )


class TestScanJsonl:
    """A snapshot's row count and schema are read from the bytes, not typed in.

    Registering by hand means row_count and columns are whatever the person
    typed, and a typo there is invisible — it lands in Table 1 as fact.
    """

    def test_counts_rows_across_every_jsonl_file(self, tmp_path: Path) -> None:
        source = tmp_path / "pull"
        source.mkdir()
        (source / "a.jsonl").write_text('{"x": 1}\n{"x": 2}\n', encoding="utf-8")
        (source / "b.jsonl").write_text('{"x": 3}\n', encoding="utf-8")

        assert scan_jsonl(source).row_count == 3

    def test_columns_are_the_union_over_records_not_the_first_record(self, tmp_path: Path) -> None:
        source = tmp_path / "pull"
        source.mkdir()
        (source / "a.jsonl").write_text(
            '{"aptNm": "x"}\n{"aptNm": "y", "cdealDay": "12"}\n', encoding="utf-8"
        )

        assert scan_jsonl(source).columns == ("aptNm", "cdealDay")

    def test_blank_lines_are_not_rows(self, tmp_path: Path) -> None:
        source = tmp_path / "pull"
        source.mkdir()
        (source / "a.jsonl").write_text('{"x": 1}\n\n{"x": 2}\n', encoding="utf-8")

        assert scan_jsonl(source).row_count == 2

    def test_a_source_with_no_jsonl_is_an_error(self, tmp_path: Path) -> None:
        source = tmp_path / "pull"
        source.mkdir()
        (source / "a.csv").write_text("x\n1\n", encoding="utf-8")

        with pytest.raises(SnapshotError, match="no .jsonl"):
            scan_jsonl(source)


class TestTable1:
    def test_one_row_per_snapshot_with_the_columns_the_paper_prints(
        self, store: SnapshotStore, source: Path
    ) -> None:
        register(store, source)

        frame = dataset_table(store.list_snapshots())

        assert list(frame.columns) == ["Dataset", "Rows", "Columns", "Period", "Size", "Snapshot"]
        assert frame.loc[0, "Rows"] == 234_512

    def test_sizes_are_human_readable_not_raw_bytes(
        self, store: SnapshotStore, source: Path
    ) -> None:
        register(store, source)

        assert dataset_table(store.list_snapshots()).loc[0, "Size"].endswith("MiB")
