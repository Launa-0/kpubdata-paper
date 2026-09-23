"""r2_build.py가 남긴 관측을 읽어 R2 판정을 내고, Monolithic과 대조한다 (#18).

Medallion 쪽에서는 Silver 산출물의 스키마를 이전 빌드와 비교할 수 있다. 그게 계층이
남기는 것이다. Monolithic에는 비교할 중간 산출물이 없고, 관측할 수 있는 것은 최종
분석 결과뿐이다. 그래서 이 스크립트가 재는 것은 "Monolithic이 더 자주 깨지는가"가
아니라 **같은 드리프트가 Monolithic 경로에서 관측되는가**다.

Monolithic의 행 수가 원천보다 적은 것은 손실이 아니라 집계다. 두 경로를 비교할 수
있는 지점은 분석 결과이고, 대조표는 그 지점에서 잰다.

**harness 가상환경에서 실행한다.**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT  # noqa: E402

from kpx.datasets import LayerStore  # noqa: E402
from kpx.metrics.stability import (  # noqa: E402
    BuildObservation,
    measure_stability,
    table_stability,
)
from kpx.runner import run_condition  # noqa: E402
from kpx.tasks.task01_price_analysis import TASK  # noqa: E402

DATASET = "seoul-apartment-trades"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument(
        "--skip-monolithic",
        action="store_true",
        help="Medallion 판정만 낸다 (대조군 실행에 몇 분 걸린다)",
    )
    args = parser.parse_args(argv)

    raw = json.loads((args.work_root / "r2_observations.json").read_text(encoding="utf-8"))
    observations = [
        BuildObservation(
            snapshot_id=item["snapshot_id"],
            status=item["status"],
            input_rows=item["input_rows"],
            output_rows=item["output_rows"],
            schema=tuple(tuple(pair) for pair in item["schema"]) if item["schema"] else None,
        )
        for item in raw
    ]

    report = measure_stability(observations)
    print("=== R2 — 소스 진화 안정성 (Medallion) ===")
    print(f"  build success rate   : {report.successes}/{report.builds}")
    print(f"  schema compatibility : {report.schema_compatibility:.0%}")
    print(f"  schema breakages     : {len(report.schema_breakages)}")
    print(f"  row losses           : {len(report.row_losses)}")
    print(f"  pipeline breakages   : {len(report.pipeline_breakages)}")
    print()
    print(table_stability(observations).to_string(index=False))
    for breakage in report.schema_breakages:
        print()
        print(f"  [스키마] {breakage.snapshot_id}")
        print(f"    사라짐: {breakage.missing}")
        print(f"    변경  : {breakage.changed}")

    if args.skip_monolithic:
        return 0

    print("\n=== R2 — Medallion vs Monolithic (같은 단위) ===", flush=True)
    rows = []
    for item in raw:
        name = item["snapshot_id"]
        store = LayerStore(
            paths={
                (DATASET, "bronze"): args.work_root / "r2" / f"{name}.jsonl",
                (DATASET, "silver"): args.work_root
                / "r2"
                / "runs"
                / f"r2-{name}"
                / "silver"
                / "trades"
                / "table.parquet",
            }
        )
        results = {
            condition: run_condition(
                TASK,
                condition,  # type: ignore[arg-type]
                datasets=store,
                snapshot_id=f"r2-{name}",
                pipeline_version="0.1.0",
                warmup=0,
                repeat=1,
            )
            for condition in ("silver", "monolithic")
        }
        rows.append(
            {
                "Snapshot": name,
                "Source rows": f"{item['input_rows']:,}",
                "Silver rows": f"{results['silver'].rows:,}",
                "Monolithic rows": f"{results['monolithic'].rows:,}",
                "Same result": results["silver"].output_hash == results["monolithic"].output_hash,
            }
        )
        print(f"  {name} 완료", flush=True)

    print()
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
