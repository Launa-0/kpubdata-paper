"""Task 1을 네 조건으로 실행하고 표 1·3의 숫자를 만든다 (#13, #23).

Gold 계층은 여기서 만든다 — builder의 Gold 단계는 split/join/packaging을 하고 집계는
하지 않으므로, 과제별 집계는 실험이 정의한 단계다. 이 차이는 Threats에 기록한다.

**harness 가상환경에서 실행한다.** 먼저 build_silver.py로 Silver를 만들어 두어야 한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS, snapshot_source  # noqa: E402
from kpx.datasets import LayerStore  # noqa: E402
from kpx.runner import run_condition  # noqa: E402

from kpx.tasks.task01_price_analysis import TASK  # noqa: E402
from kpx.tasks.task01_price_analysis import transforms as tf  # noqa: E402

DATASET = "seoul-apartment-trades"
CONDITIONS = ("bronze", "silver", "gold", "monolithic")


def build_gold(silver_path: Path, gold_path: Path) -> None:
    """Silver에서 과제용 Gold(자치구 x 월 집계)를 만든다.

    최종 답(YoY·순위)은 담지 않는다 — Gold 조건이 부당하게 유리해지지 않도록 집계까지만
    저장한다.
    """
    silver = pd.read_parquet(silver_path)
    silver["district_code"] = silver["district_code"].map(tf.parse_district_code)
    silver["year_month"] = [
        tf.to_year_month(year, month)
        for year, month in zip(silver["deal_year"], silver["deal_month"], strict=True)
    ]
    silver["price_per_m2"] = tf.price_per_m2(silver["price_10k_krw"], silver["area_m2"])
    gold = tf.aggregate_by_district_month(silver)

    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold.to_parquet(gold_path, index=False)
    print(f"Gold: {len(gold):,}행 -> {gold_path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id")
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--run-id", default="trades-silver-001")
    parser.add_argument("--pipeline-version", default="0.1.0")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeat", type=int, default=6)
    args = parser.parse_args(argv)

    silver = args.work_root / "runs" / args.run_id / "silver" / "trades" / "table.parquet"
    gold = args.work_root / "gold" / "trades_district_month.parquet"
    if not gold.exists():
        build_gold(silver, gold)

    store = LayerStore(
        paths={
            (DATASET, "bronze"): snapshot_source(args.snapshots, args.snapshot_id),
            (DATASET, "silver"): silver,
            (DATASET, "gold"): gold,
        }
    )

    rows = []
    for condition in CONDITIONS:
        print(f"\n--- {condition} ---", flush=True)
        row = run_condition(
            TASK,
            condition,  # type: ignore[arg-type]
            datasets=store,
            snapshot_id=args.snapshot_id,
            pipeline_version=args.pipeline_version,
            warmup=args.warmup,
            repeat=args.repeat,
        )
        rows.append(row)
        print(
            f"  status={row.status} rows={row.rows} runtime={row.runtime_seconds:.2f}s "
            f"peak={row.peak_memory_mb:.0f}MB loc={row.preprocessing_loc} "
            f"steps={row.transformation_steps}"
        )
        print(f"  output_hash={row.output_hash[:16]}…")

    print("\n=== 표 3: Analytical Effort (RQ2) ===")
    print(
        pd.DataFrame(
            [
                {
                    "Condition": row.condition,
                    "LOC": row.preprocessing_loc,
                    "Functions": row.function_count,
                    "Steps": row.transformation_steps,
                    "Runtime (s)": round(row.runtime_seconds, 2),
                    "Peak memory (MB)": round(row.peak_memory_mb, 0),
                }
                for row in rows
            ]
        ).to_string(index=False)
    )

    print("\n=== 조건 간 결과 일치 (RQ3의 내부 일관성) ===")
    reference = {row.condition: row.output_hash for row in rows}["silver"]
    print(
        pd.DataFrame(
            [
                {
                    "Condition": row.condition,
                    "output_hash": row.output_hash[:16] + "…",
                    "Same as silver": row.output_hash == reference,
                }
                for row in rows
            ]
        ).to_string(index=False)
    )

    print("\n=== 계층별 저장 크기 (#19) ===")
    for layer in ("bronze", "silver", "gold"):
        print(f"  {layer:<7}{store.size_bytes(DATASET, layer) / 1024 / 1024:8.1f} MiB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
