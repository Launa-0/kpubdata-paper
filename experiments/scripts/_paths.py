"""스크립트들이 공유하는 경로 해석.

절대경로를 스크립트마다 박아 두면 그 스크립트는 그것을 쓴 사람의 기계에서만 돈다.
모든 경로는 레포 위치에서 유도하고, 기계마다 다를 수밖에 없는 것만 인자로 받는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parents[1]
SNAPSHOTS = EXPERIMENTS / "snapshots"
DEFAULT_WORK_ROOT = EXPERIMENTS / ".build"


def add_common_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--snapshots",
        type=Path,
        default=SNAPSHOTS,
        metavar="DIR",
        help="snapshot store root (default: experiments/snapshots)",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=DEFAULT_WORK_ROOT,
        metavar="DIR",
        help="where builds are written (default: experiments/.build, git-ignored)",
    )
    return parser


def snapshot_source(snapshots: Path, snapshot_id: str) -> Path:
    """얼린 바이트의 위치.

    원천은 커밋되지 않으므로, 재현하려는 사람은 metadata.json의 checksum으로 자기
    수집본을 대조한 뒤 이 자리에 놓는다.
    """
    dataset, _, leaf = snapshot_id.partition("/")
    path = snapshots / dataset / leaf / "source" / "raw_records.jsonl"
    if not path.exists():
        raise SystemExit(
            f"원천 바이트가 없다: {path}\n"
            f"  스냅샷 metadata는 커밋되지만 바이트는 커밋되지 않는다.\n"
            f"  수집본을 이 자리에 놓고 `kpx snapshot verify {snapshot_id}` 로 대조하라."
        )
    return path
