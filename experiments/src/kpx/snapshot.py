"""Frozen source snapshots.

A snapshot is a public-data pull, frozen and content-addressed, so that every
number in the paper can name the exact input it came from.

The snapshot id embeds the digest::

    seoul-apartment-trades/20260315-4f2a91c0d3b7
                           ^date    ^digest prefix

so two snapshots with the same id necessarily hold the same bytes. That is what
lets R1 assert "identical source" instead of assuming it, and what lets R2 say
which of T1/T2/T3 a build consumed. The date prefix keeps ids readable and
sortable, which matters because R2 compares snapshots over time.

Layout::

    snapshots/<dataset>/<date>-<digest>/
    ├── metadata.json     # the Snapshot record; committed
    └── source/           # the frozen bytes; git-ignored, republished elsewhere

Only ``metadata.json`` is committed. The data itself is large and is published
on Hugging Face; a reader who wants to rerun the pipeline restores ``source/``
and :meth:`SnapshotStore.verify` confirms they restored the right thing.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import pandas as pd

from kpx.digest import TreeDigest, digest_tree

METADATA_FILENAME = "metadata.json"
SOURCE_DIRNAME = "source"
SCHEMA_VERSION = 1


class SnapshotError(RuntimeError):
    """Raised when a snapshot is missing, malformed, or fails verification."""


@dataclass(frozen=True)
class Snapshot:
    """Metadata describing one frozen source pull.

    ``period`` is the ``(start, end)`` of the data's own time coverage, which is
    not the same as ``retrieved_at``: a pull made in March 2026 may cover
    2020–2024. Table 1 needs both.
    """

    snapshot_id: str
    dataset: str
    retrieved_at: datetime
    source_url: str
    row_count: int
    columns: tuple[str, ...]
    checksum: str
    size_bytes: int
    file_count: int
    data_schema_version: str
    period: tuple[str, str] | None = None
    builder_version: str | None = None
    notes: str = ""
    metadata_schema_version: int = SCHEMA_VERSION

    @property
    def retrieved_on(self) -> date:
        return self.retrieved_at.date()

    @property
    def column_count(self) -> int:
        return len(self.columns)

    def table1_row(self) -> dict[str, Any]:
        """The Table 1 (Dataset) row for this snapshot."""
        period = f"{self.period[0]}–{self.period[1]}" if self.period else "—"
        return {
            "Dataset": self.dataset,
            "Rows": self.row_count,
            "Columns": self.column_count,
            "Period": period,
            "Size": self.size_bytes,
            "Snapshot": self.snapshot_id,
        }

    def citation(self) -> str:
        """The snapshot block quoted in the paper."""
        return (
            f"Snapshot date: {self.retrieved_on.isoformat()}\n"
            f"Rows: {self.row_count:,}\n"
            f"SHA-256: {self.checksum}"
        )

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["retrieved_at"] = self.retrieved_at.isoformat()
        payload["columns"] = list(self.columns)
        payload["period"] = list(self.period) if self.period else None
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Snapshot:
        version = payload.get("metadata_schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise SnapshotError(
                f"snapshot metadata is version {version}, this harness understands "
                f"{SCHEMA_VERSION}; upgrade kpx rather than reading it partially"
            )
        data = dict(payload)
        data["retrieved_at"] = datetime.fromisoformat(data["retrieved_at"])
        data["columns"] = tuple(data["columns"])
        period = data.get("period")
        data["period"] = tuple(period) if period else None
        return cls(**data)


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of re-digesting a snapshot's stored bytes."""

    snapshot_id: str
    ok: bool
    expected: str
    actual: str | None
    reason: str = ""

    def raise_for_status(self) -> None:
        if not self.ok:
            raise SnapshotError(f"snapshot {self.snapshot_id} failed verification: {self.reason}")


@dataclass(frozen=True)
class SourceScan:
    """What the frozen bytes themselves say about their shape."""

    row_count: int
    columns: tuple[str, ...]


def scan_jsonl(source: Path | str) -> SourceScan:
    """Count rows and collect the column union across the JSONL under ``source``.

    Columns are the union over records, not the first record's keys: these APIs
    omit a field entirely when it has no value, so the first record understates
    the schema and Table 1 would report a column count that is simply wrong.
    """
    source = Path(source)
    files = sorted(source.rglob("*.jsonl"))
    if not files:
        raise SnapshotError(f"no .jsonl files under {source}")

    rows = 0
    columns: dict[str, None] = {}
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rows += 1
                columns.update(dict.fromkeys(json.loads(line)))
    return SourceScan(row_count=rows, columns=tuple(sorted(columns)))


def table1(snapshots: Sequence[Snapshot]) -> pd.DataFrame:
    """Table 1 (Dataset): one row per snapshot, sizes in MiB.

    Raw byte counts in a paper table are unreadable; the snapshot id keeps the
    exact bytes identifiable, so the size only has to give the order of
    magnitude.
    """
    rows = []
    for snapshot in snapshots:
        row = snapshot.table1_row()
        row["Size"] = f"{row['Size'] / 1024 / 1024:.1f} MiB"
        rows.append(row)
    return pd.DataFrame(rows)


def make_snapshot_id(dataset: str, retrieved_at: datetime, digest: TreeDigest) -> str:
    """Build the content-addressed, date-prefixed snapshot id."""
    return f"{dataset}/{retrieved_at:%Y%m%d}-{digest.short}"


class SnapshotStore:
    """Registers, reads and verifies snapshots under a root directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- locations ---------------------------------------------------------

    def directory(self, snapshot_id: str) -> Path:
        dataset, _, leaf = snapshot_id.partition("/")
        if not dataset or not leaf:
            raise SnapshotError(f"malformed snapshot id: {snapshot_id!r}")
        return self.root / dataset / leaf

    def source_path(self, snapshot_id: str) -> Path:
        """Where the frozen bytes for ``snapshot_id`` live."""
        return self.directory(snapshot_id) / SOURCE_DIRNAME

    # -- writing -----------------------------------------------------------

    def register(
        self,
        source: Path | str,
        *,
        dataset: str,
        source_url: str,
        row_count: int,
        columns: tuple[str, ...] | list[str],
        data_schema_version: str,
        retrieved_at: datetime | None = None,
        period: tuple[str, str] | None = None,
        builder_version: str | None = None,
        notes: str = "",
    ) -> Snapshot:
        """Digest ``source``, copy it into the store, and write its metadata.

        The source is copied rather than referenced: a snapshot that points at a
        working directory is not frozen, and R1 would be measuring whatever
        happened to be on disk at build time.
        """
        source = Path(source)
        digest = digest_tree(source)
        retrieved_at = retrieved_at or datetime.now().astimezone()
        snapshot_id = make_snapshot_id(dataset, retrieved_at, digest)

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            dataset=dataset,
            retrieved_at=retrieved_at,
            source_url=source_url,
            row_count=row_count,
            columns=tuple(columns),
            checksum=digest.sha256,
            size_bytes=digest.size_bytes,
            file_count=digest.file_count,
            data_schema_version=data_schema_version,
            period=period,
            builder_version=builder_version,
            notes=notes,
        )

        target = self.source_path(snapshot_id)
        if target.exists():
            existing = self.verify(snapshot_id)
            if not existing.ok:
                raise SnapshotError(
                    f"{snapshot_id} already exists but its bytes do not match its id"
                )
        else:
            self._copy_source(source, target)

        self._write_metadata(snapshot)
        return snapshot

    def _copy_source(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / source.name)
        else:
            shutil.copytree(source, target)

    def _write_metadata(self, snapshot: Snapshot) -> None:
        path = self.directory(snapshot.snapshot_id) / METADATA_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(snapshot.to_json(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # -- reading -----------------------------------------------------------

    def load(self, snapshot_id: str) -> Snapshot:
        path = self.directory(snapshot_id) / METADATA_FILENAME
        if not path.exists():
            raise SnapshotError(f"no snapshot registered as {snapshot_id}")
        return Snapshot.from_json(json.loads(path.read_text(encoding="utf-8")))

    def list_snapshots(self, dataset: str | None = None) -> list[Snapshot]:
        """Every registered snapshot, oldest first.

        R2 compares snapshots in time order, so the ordering is part of the API
        rather than left to each caller.
        """
        pattern = f"{dataset}/*/{METADATA_FILENAME}" if dataset else f"*/*/{METADATA_FILENAME}"
        snapshots = [
            Snapshot.from_json(json.loads(path.read_text(encoding="utf-8")))
            for path in self.root.glob(pattern)
        ]
        return sorted(snapshots, key=lambda s: (s.dataset, s.retrieved_at))

    # -- verification ------------------------------------------------------

    def verify(self, snapshot_id: str) -> VerifyResult:
        """Re-digest the stored bytes and compare against the recorded checksum.

        Called before every reproducibility build. A snapshot that has drifted
        invalidates the premise of R1, so it must be detected rather than
        silently measured.
        """
        snapshot = self.load(snapshot_id)
        source = self.source_path(snapshot_id)
        if not source.exists():
            return VerifyResult(
                snapshot_id=snapshot_id,
                ok=False,
                expected=snapshot.checksum,
                actual=None,
                reason=f"source bytes are not present at {source}",
            )
        actual = digest_tree(source)
        if actual.sha256 != snapshot.checksum:
            return VerifyResult(
                snapshot_id=snapshot_id,
                ok=False,
                expected=snapshot.checksum,
                actual=actual.sha256,
                reason="stored bytes do not match the recorded checksum",
            )
        return VerifyResult(
            snapshot_id=snapshot_id, ok=True, expected=snapshot.checksum, actual=actual.sha256
        )

    def verify_all(self, dataset: str | None = None) -> list[VerifyResult]:
        return [self.verify(s.snapshot_id) for s in self.list_snapshots(dataset)]


def default_store(root: Path | str | None = None) -> SnapshotStore:
    """The store at ``experiments/snapshots`` unless told otherwise."""
    if root is not None:
        return SnapshotStore(root)
    return SnapshotStore(Path(__file__).resolve().parents[2] / "snapshots")
