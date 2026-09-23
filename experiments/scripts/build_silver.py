"""얼린 스냅샷에서 Bronze/Silver/Gold를 빌드한다 — API를 다시 호출하지 않는다.

스냅샷의 raw_records.jsonl을 로컬 upload store에 넣고 ``kind="file"`` source로
선언한다. 이후의 모든 실험이 이 산출물 위에서 돈다.

**builder 가상환경에서 실행한다** (polars 필요). harness 가상환경에는 builder가
설치돼 있지 않다.
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _builder_identity  # noqa: E402
from _paths import add_common_arguments, snapshot_source  # noqa: E402

# 데이터셋마다 Silver 계약이 다르다. 같은 기관의 같은 계열 API인데도 컬럼명 규칙과
# 금액 표현이 다르다 — 그 차이가 T3(통합)에서 Bronze 조건이 치르는 비용이다.
SPECS = {"trades": "trades_spec", "rent": "rent_spec"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id", help="예: seoul-apartment-trades/20260922-6660c8e25162")
    parser.add_argument("--spec", choices=sorted(SPECS), default="trades")
    parser.add_argument("--run-id", default=None, help="기본값: <spec>-silver-001")
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    build_spec = importlib.import_module(SPECS[args.spec]).build_spec
    args.run_id = args.run_id or f"{args.spec}-silver-001"

    from kpubdata_builder.pipeline import run_build
    from kpubdata_builder.uploads.store import SQLiteUploadRepository

    source = snapshot_source(args.snapshots, args.snapshot_id)
    content = source.read_bytes()
    print(f"스냅샷 바이트: {len(content) / 1024 / 1024:.1f} MiB", flush=True)

    work_root: Path = args.work_root
    if (work_root / "runs" / args.run_id).exists():
        shutil.rmtree(work_root / "runs" / args.run_id)
    work_root.mkdir(parents=True, exist_ok=True)

    repository = SQLiteUploadRepository(
        work_root / "uploads.sqlite3", max_bytes=len(content) + 1024
    )
    upload = repository.put(
        "paper-experiment",
        content=content,
        format="jsonl",
        encoding="utf-8",
        original_filename="raw_records.jsonl",
    )

    started = time.time()
    result = run_build(
        build_spec(upload.upload_id, description="논문 실험용 Silver"),
        client=None,
        output_root=work_root / "runs",
        run_id=args.run_id,
        owner_id="paper-experiment",
        upload_repository=repository,
    )
    # 어느 빌더 코드가 이 산출물을 만들었는지 옆에 남긴다. 패키지 버전만으로는
    # 식별되지 않는다 — _builder_identity 참조.
    identity = _builder_identity.write(work_root / "runs" / args.run_id)
    print(f"builder: {_builder_identity.as_version(identity)}")
    if identity["git_dirty"]:
        print("  [!] 작업 트리가 커밋과 다르다 — 최종 실험에는 쓰지 마라")
    print(f"status: {result.status}  ({time.time() - started:.1f}s)")
    for outcome in result.outcomes:
        print(f"  {outcome.source_key}: {outcome.status} stages={outcome.stages_completed}")
        if outcome.error:
            print(f"    error: {outcome.error}")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
