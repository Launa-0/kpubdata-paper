"""R1 — 같은 Bronze 스냅샷을 N회 재빌드해 결정성을 측정한다 (#17, RQ3).

API를 다시 호출하지 않는다. 얼린 스냅샷을 로컬 upload store에서 읽어 같은 BuildSpec
으로 반복 빌드하고, 매번 산출물의 content digest와 행 수·스키마를 기록한다.

같은 소스 + 같은 코드 + 같은 설정 -> 같은 출력이어야 한다. 아니라면 그 원인 자체가
논문의 findings다.

**builder 가상환경에서 실행한다.** 관측은 JSON으로 남기고, 판정은 r1_report.py가
harness 가상환경에서 한다 — 두 패키지가 서로 다른 환경에 설치돼 있어 한 프로세스에서
같이 import할 수 없다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import add_common_arguments, snapshot_source  # noqa: E402
from trades_spec import build_spec  # noqa: E402


def digest_tree(directory: Path) -> str:
    """디렉터리 안 파일들의 내용을 경로 순서로 이어 붙여 해시한다.

    kpx.digest.digest_tree와 같은 기준(경로를 POSIX로 정규화해 정렬, 내용만 해시)을
    쓰되 harness를 import하지 않는다.
    """
    hasher = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        hasher.update(path.relative_to(directory).as_posix().encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id")
    parser.add_argument("--repeats", type=int, default=10)
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    import polars as pl
    from kpubdata_builder.pipeline import run_build
    from kpubdata_builder.uploads.store import SQLiteUploadRepository

    work_root: Path = args.work_root / "r1"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)

    content = snapshot_source(args.snapshots, args.snapshot_id).read_bytes()
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
    spec = build_spec(upload.upload_id, description="R1 재빌드 결정성 측정")

    observations = []
    for index in range(1, args.repeats + 1):
        run_id = f"r1-{index:02d}"
        started = time.time()
        result = run_build(
            spec,
            client=None,
            output_root=work_root / "runs",
            run_id=run_id,
            owner_id="paper-experiment",
            upload_repository=repository,
        )
        elapsed = time.time() - started

        silver = work_root / "runs" / run_id / "silver" / "trades"
        digest, rows, schema = None, 0, None
        if (silver / "table.parquet").exists():
            digest = digest_tree(silver)
            table = pl.read_parquet(silver / "table.parquet")
            rows = table.height
            schema = [[name, str(dtype)] for name, dtype in table.schema.items()]

        observations.append(
            {
                "run_id": run_id,
                "status": result.status,
                "output_digest": digest,
                "row_count": rows,
                "schema": schema,
                "seconds": round(elapsed, 1),
            }
        )
        head = digest[:16] if digest else "—"
        print(f"  {run_id}: {result.status}  {elapsed:5.1f}s  rows={rows:,}  {head}…", flush=True)

    target = args.work_root / "r1_observations.json"
    target.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"관측 {len(observations)}건 -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
