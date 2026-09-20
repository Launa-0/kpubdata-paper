from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kpx.digest import digest_tree, file_sha256


def write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_file_sha256_matches_hashlib(tmp_path: Path) -> None:
    path = write(tmp_path, "a.csv", "거래금액\n120,000\n")
    assert file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_digest_of_a_single_file(tmp_path: Path) -> None:
    write(tmp_path, "a.csv", "x")
    digest = digest_tree(tmp_path / "a.csv")
    assert digest.file_count == 1
    assert digest.size_bytes == 1


def test_digest_is_stable_across_directory_ordering(tmp_path: Path) -> None:
    """Filesystem iteration order must not change the digest."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for name in ("b.json", "a.json", "c.json"):
        write(first, name, name)
    for name in ("c.json", "a.json", "b.json"):
        write(second, name, name)
    assert digest_tree(first).sha256 == digest_tree(second).sha256


def test_digest_changes_when_content_changes(tmp_path: Path) -> None:
    write(tmp_path, "a.json", "one")
    before = digest_tree(tmp_path).sha256
    write(tmp_path, "a.json", "two")
    assert digest_tree(tmp_path).sha256 != before


def test_digest_changes_when_a_file_is_renamed(tmp_path: Path) -> None:
    """The manifest covers paths, not just bytes."""
    write(tmp_path, "a.json", "same")
    before = digest_tree(tmp_path).sha256
    (tmp_path / "a.json").rename(tmp_path / "b.json")
    assert digest_tree(tmp_path).sha256 != before


def test_metadata_and_hidden_files_are_excluded(tmp_path: Path) -> None:
    """Writing a snapshot's own metadata must not change the data's digest."""
    write(tmp_path, "a.json", "payload")
    before = digest_tree(tmp_path).sha256
    write(tmp_path, "metadata.json", '{"snapshot_id": "x"}')
    write(tmp_path, ".DS_Store", "junk")
    write(tmp_path, ".hidden/secret", "junk")
    assert digest_tree(tmp_path).sha256 == before


def test_nested_files_are_included(tmp_path: Path) -> None:
    write(tmp_path, "2020/01.json", "a")
    write(tmp_path, "2021/01.json", "b")
    digest = digest_tree(tmp_path)
    assert digest.file_count == 2
    assert [entry.path for entry in digest.files] == ["2020/01.json", "2021/01.json"]


def test_missing_path_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        digest_tree(tmp_path / "nope")


def test_empty_tree_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="no files to digest"):
        digest_tree(tmp_path / "empty")
