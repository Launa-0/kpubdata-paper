"""빌더 코드 신원이 clean/dirty를 구분하는지 (#51).

``pipeline_version``이 실험의 재현 단위라서, 여기서 같은 값이 나오면 안 되는 두
코드가 같은 값을 받는다. 특히 **추적되지 않은 파일**이 그렇다 — ``git diff HEAD``
만으로는 새로 만든 모듈 하나가 import되는데 해시에는 안 잡힌다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import _builder_identity as bi  # noqa: E402


def _repo(root: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    root.mkdir(parents=True, exist_ok=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (root / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    return root


def _status(repo: Path) -> str:
    return bi._git(repo, "status", "--porcelain")


def test_clean_worktree_has_no_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    assert _status(repo).strip() == ""


def test_tracked_edit_changes_digest(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    (repo / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    before = bi._worktree_digest(repo, _status(repo))
    (repo / "mod.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert bi._worktree_digest(repo, _status(repo)) != before


def test_a_non_ascii_edit_is_hashed_rather_than_crashing(tmp_path: Path) -> None:
    """빌더 소스는 한국어 주석투성이다. ``text=True``가 locale(cp949)로 diff를 읽으면
    reader 스레드가 죽고 stdout이 None이 된다 — dirty 빌더로 처음 빌드했을 때 났다."""
    repo = _repo(tmp_path / "r")
    (repo / "mod.py").write_text("# 날짜 조각 — 손실\nVALUE = 2\n", encoding="utf-8")
    before = bi._worktree_digest(repo, _status(repo))
    (repo / "mod.py").write_text("# 날짜 조각 — 손실 감사\nVALUE = 2\n", encoding="utf-8")
    assert bi._worktree_digest(repo, _status(repo)) != before


def test_untracked_file_content_changes_digest(tmp_path: Path) -> None:
    """``git diff HEAD``가 못 보는 구멍. 새 모듈은 import되지만 diff에 없다."""
    repo = _repo(tmp_path / "r")
    (repo / "extra.py").write_text("HELPER = 1\n", encoding="utf-8")
    before = bi._worktree_digest(repo, _status(repo))
    (repo / "extra.py").write_text("HELPER = 2\n", encoding="utf-8")
    assert bi._worktree_digest(repo, _status(repo)) != before


def test_ignored_file_leaves_identity_alone(tmp_path: Path) -> None:
    """빌드와 무관한 로컬 산출물이 신원을 흔들면 dirty가 무의미해진다."""
    repo = _repo(tmp_path / "r")
    (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text("dist/\n", encoding="utf-8")
    (repo / "dist").mkdir()
    (repo / "dist" / "out.bin").write_bytes(b"\x00\x01")
    assert _status(repo).strip() == ""


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (None, None),
        ({"package_version": "0.4.0.dev0", "git_commit": None}, "0.4.0.dev0"),
        (
            {"package_version": "0.4.0.dev0", "git_commit": "518fe2f0312f38e9", "git_dirty": False},
            "0.4.0.dev0+518fe2f0312f",
        ),
        (
            {
                "package_version": "0.4.0.dev0",
                "git_commit": "518fe2f0312f38e9",
                "git_dirty": True,
                "git_diff_sha256": "a1b2c3d4e5f6a7b8",
            },
            "0.4.0.dev0+518fe2f0312f.dirty.a1b2c3d4e5f6",
        ),
    ],
)
def test_as_version(identity: dict | None, expected: str | None) -> None:
    assert bi.as_version(identity) == expected


def test_write_read_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {
        "package_version": "9.9.9",
        "git_commit": "0" * 40,
        "git_dirty": False,
        "git_diff_sha256": None,
    }
    monkeypatch.setattr(bi, "capture", lambda: captured)
    run_dir = tmp_path / "runs" / "trades-silver-001"
    assert bi.write(run_dir) == captured
    assert bi.read(run_dir) == captured
    assert bi.read(tmp_path / "runs" / "absent") is None


def test_version_of_a_run_without_identity_stops(tmp_path: Path) -> None:
    """빌더를 모르는 산출물은 측정하지 않는다 — 체크섬으로는 빌더를 가를 수 없다."""
    with pytest.raises(SystemExit, match="builder_identity"):
        bi.version_of(tmp_path)


def test_version_of_matches_what_record_builds_writes(tmp_path: Path) -> None:
    identity = {
        "package_version": "0.4.0.dev0",
        "git_commit": "096d023f9546abc",
        "git_dirty": False,
    }
    (tmp_path / bi.FILENAME).write_text(json.dumps(identity), encoding="utf-8")
    assert bi.version_of(tmp_path) == bi.as_version(identity) == "0.4.0.dev0+096d023f9546"
