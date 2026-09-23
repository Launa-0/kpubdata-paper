"""R2 — 상류 소스가 자랄 때 파이프라인이 계약을 유지하는가 (#18, H4 후반부).

수집 시점이 다른 스냅샷 3개는 만들 수 없다. 이 데이터는 과거 거래라 어제 받든 오늘
받든 같은 바이트가 온다. 대신 **기간 분할**로 상류가 자라는 상황을 만든다 — T1은
2020-2022, T2는 2020-2023, T3은 2020-2024다. T1을 받았던 시점에서 보면 T2는 "새
데이터가 추가된 같은 소스"다.

hash 일치를 기대하지 않는다. 소스가 달라졌으니 출력이 다른 것이 정상이고, 재는 것은
빌드 성공률·스키마 호환성·예상치 못한 행 손실이다.

**builder 가상환경에서 실행한다.** 판정은 r2_report.py가 한다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import add_common_arguments, snapshot_source  # noqa: E402
from trades_spec import build_spec  # noqa: E402

PERIODS = {"T1": 2022, "T2": 2023, "T3": 2024}


def split_by_period(source: Path, work_root: Path) -> dict[str, tuple[Path, int]]:
    """마지막 연도만 다른 누적 스냅샷 3개를 만든다."""
    work_root.mkdir(parents=True, exist_ok=True)
    counts = dict.fromkeys(PERIODS, 0)
    handles: dict[str, TextIO] = {}
    try:
        for name in PERIODS:
            handles[name] = (work_root / f"{name}.jsonl").open("w", encoding="utf-8")

        with source.open(encoding="utf-8") as lines:
            for line in lines:
                year = int(json.loads(line)["dealYear"])
                for name, last_year in PERIODS.items():
                    if year <= last_year:
                        handles[name].write(line)
                        counts[name] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return {name: (work_root / f"{name}.jsonl", counts[name]) for name in PERIODS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id")
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    import polars as pl
    from kpubdata_builder.pipeline import run_build
    from kpubdata_builder.uploads.store import SQLiteUploadRepository

    work_root: Path = args.work_root / "r2"
    if work_root.exists():
        shutil.rmtree(work_root)

    splits = split_by_period(snapshot_source(args.snapshots, args.snapshot_id), work_root)
    for name, (_, rows) in splits.items():
        print(f"{name}: {rows:,}행  (2020~{PERIODS[name]})", flush=True)

    largest = max(path.stat().st_size for path, _ in splits.values())
    repository = SQLiteUploadRepository(work_root / "uploads.sqlite3", max_bytes=largest + 1024)

    observations = []
    for name, (path, input_rows) in splits.items():
        upload = repository.put(
            "paper-experiment",
            content=path.read_bytes(),
            format="jsonl",
            encoding="utf-8",
            original_filename=f"{name}.jsonl",
        )
        result = run_build(
            build_spec(upload.upload_id, description="R2 소스 진화 안정성"),
            client=None,
            output_root=work_root / "runs",
            run_id=f"r2-{name}",
            owner_id="paper-experiment",
            upload_repository=repository,
        )

        output_rows, schema = 0, None
        table_path = work_root / "runs" / f"r2-{name}" / "silver" / "trades" / "table.parquet"
        if table_path.exists():
            table = pl.read_parquet(table_path)
            output_rows = table.height
            schema = [[column, str(dtype)] for column, dtype in table.schema.items()]

        observations.append(
            {
                "snapshot_id": name,
                "status": result.status,
                "input_rows": input_rows,
                "output_rows": output_rows,
                "schema": schema,
            }
        )
        print(f"  {name}: {result.status}  {input_rows:,} -> {output_rows:,}행", flush=True)

    target = args.work_root / "r2_observations.json"
    target.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"관측 {len(observations)}건 -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
