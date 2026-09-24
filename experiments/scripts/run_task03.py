"""Task 3을 네 조건으로 실행한다 — 매매·전세 조인과 전세가율 (#15).

Gold는 run_task01.py처럼 여기서 만든다. builder의 Gold 단계는 packaging만 하고 두
데이터셋을 잇지 않는다. Gold는 자치구 × 월의 매칭 평균까지만 담고 전세가율은 담지
않는다 (``task03_join/gold.py``).

T3는 두 원천을 읽는다. provenance는 입력 하나를 전제하므로 Gold는
``record_joined_layer``로 합성 식별자를 적고, 네 조건의 run도 그 식별자를 물려받는다.

**harness 가상환경에서 실행한다.** 두 Silver가 빌드·기록돼 있어야 한다.
"""

from __future__ import annotations

import argparse
import inspect
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _builder_identity  # noqa: E402
import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS, snapshot_source  # noqa: E402
from rent_spec import SPEC as RENT_SPEC  # noqa: E402
from trades_spec import SPEC as TRADES_SPEC  # noqa: E402

from kpx.datasets import LayerStore  # noqa: E402
from kpx.metrics.runtime import MEASURED_RUNS, WARMUP_RUNS  # noqa: E402
from kpx.pipeline import bind_measured_artifact, record_joined_layer  # noqa: E402
from kpx.provenance import Provenance, ProvenanceError, ProvenanceStore  # noqa: E402
from kpx.results import default_store  # noqa: E402
from kpx.runner import run_condition  # noqa: E402
from kpx.tasks.task03_join import TASK  # noqa: E402
from kpx.tasks.task03_join import transforms as tf  # noqa: E402

TRADES = "seoul-apartment-trades"
RENTS = "seoul-apartment-rent"
GOLD = "seoul-apartment-trades-rent-monthly"
CONDITIONS = ("bronze", "silver", "gold", "monolithic")

#: 조건별 일치의 성격. 같은 해시라도 무게가 다르다 — 표에서 구분해 적는다.
KIND = {
    "silver": "reference",
    "bronze": "독립 (harness 파서 vs builder cast)",
    "monolithic": "구성상 bronze와 같은 helper·순서",
    "gold": "구성상 silver와 같은 함수 (materialization 일관성)",
}


def gold_recipe() -> str:
    """Gold를 만든 코드 — T1과 같은 이유로 모듈 전체를 넘긴다 (run_task01.gold_recipe)."""
    return f"{inspect.getsource(tf)}\n{inspect.getsource(build_gold)}"


def build_gold(trades_path: Path, rents_path: Path, gold_path: Path) -> float:
    """두 Silver에서 자치구 × 월 매칭 평균을 만든다. 전세가율은 담지 않는다."""
    started = time.perf_counter()
    trades = pd.read_parquet(trades_path)
    rents = pd.read_parquet(rents_path)
    rents = rents[tf.is_jeonse(rents["monthly_rent_10k_krw"])].copy()
    for frame, amount, target in (
        (trades, "price_10k_krw", "sale_price_per_m2"),
        (rents, "deposit_10k_krw", "jeonse_deposit_per_m2"),
    ):
        # Silver 계약은 단지명을 rename만 한다 — 조인 키 정규화는 여기서 한다.
        frame["apt_name"] = frame["apt_name"].map(tf.normalize_apt_name)
        frame["year_month"] = [
            tf.to_year_month(year, month)
            for year, month in zip(frame["deal_year"], frame["deal_month"], strict=True)
        ]
        frame["area_bucket"] = frame["area_m2"].map(tf.area_bucket)
        frame[target] = tf.unit_price(frame[amount], frame["area_m2"])
    sales = tf.fold_to_join_keys(trades, "sale_price_per_m2", "sale_price_per_m2")
    jeonse = tf.fold_to_join_keys(rents, "jeonse_deposit_per_m2", "jeonse_deposit_per_m2")
    gold = tf.aggregate_by_district_month(tf.join_sales_and_jeonse(sales, jeonse))

    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold.to_parquet(gold_path, index=False)
    elapsed = time.perf_counter() - started
    print(f"Gold: {len(gold):,}행 -> {gold_path.name}  ({elapsed:.2f}s)")
    return elapsed


def bound_silver(
    builds: ProvenanceStore, spec: dict[str, Any], snapshot_id: str, run_dir: Path
) -> Provenance:
    """이 run 디렉터리의 Silver 바이트가 어느 기록된 빌드인지 확정한다.

    "가장 최근에 기록된 빌드"를 집지 않는다. 다른 스냅샷이나 다른 빌더의 빌드가
    나중에 기록되면 틀린 기록을 집고, 수정 전후 빌더처럼 같은 바이트를 낸 빌드는
    체크섬으로 구분되지 않는다 — 스냅샷·계약·체크섬·빌더 신원을 모두 맞춘다.
    """
    if snapshot_id != spec["snapshot_id"]:
        raise SystemExit(
            f"{spec['dataset_id']} spec은 {spec['snapshot_id']}를 선언하는데 "
            f"{snapshot_id}로 측정하려 한다."
        )
    try:
        return bind_measured_artifact(
            run_dir / "silver" / spec["source"]["alias"],
            spec={**spec, "run_id": run_dir.name},
            store=builds,
            builder_version=_builder_identity.version_of(run_dir),
        )
    except ProvenanceError as error:
        raise SystemExit(f"{error}\n먼저 scripts/record_builds.py를 실행하라.") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trades_snapshot_id")
    parser.add_argument("rent_snapshot_id")
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--trades-run-id", default="trades-silver-001")
    parser.add_argument("--rent-run-id", default="rent-silver-001")
    parser.add_argument("--datasets", type=Path, default=None, help="provenance 저장소")
    parser.add_argument("--warmup", type=int, default=WARMUP_RUNS)
    parser.add_argument("--repeat", type=int, default=MEASURED_RUNS)
    parser.add_argument("--results", type=Path, default=None, metavar="FILE")
    parser.add_argument(
        "--fresh", action="store_true", help="이 과제의 이전 결과 행을 지우고 새로 기록한다"
    )
    args = parser.parse_args(argv)

    runs = args.work_root / "runs"
    trades_silver = runs / args.trades_run_id / "silver" / "trades" / "table.parquet"
    rents_silver = runs / args.rent_run_id / "silver" / "rent" / "table.parquet"
    # 과제별 디렉터리 — provenance가 디렉터리를 통째로 digest한다 (run_task01 참조).
    gold_dir = args.work_root / "gold" / "task03"
    gold = gold_dir / "trades_rent_district_month.parquet"

    store_root = args.datasets or Path(__file__).resolve().parents[1] / "datasets"
    builds = ProvenanceStore(store_root)
    upstreams = [
        bound_silver(builds, TRADES_SPEC, args.trades_snapshot_id, runs / args.trades_run_id),
        bound_silver(builds, RENT_SPEC, args.rent_snapshot_id, runs / args.rent_run_id),
    ]

    # Gold는 매번 다시 만든다. mtime으로 재사용하면 ``gold_recipe``가 바뀌었는데
    # Silver가 그대로일 때 옛 바이트가 새 recipe로 기록된다 (run_task01 참조).
    gold_build_seconds = build_gold(trades_silver, rents_silver, gold)

    materialized = pd.read_parquet(gold)
    gold_build = record_joined_layer(
        gold_dir,
        dataset=GOLD,
        layer="gold",
        upstreams=upstreams,
        recipe=gold_recipe(),
        row_count=len(materialized),
        columns=tuple(materialized.columns),
        store=builds,
    )
    print(f"gold build {gold_build.build_id} <- {gold_build.inputs.upstream_build_id}")
    print(f"snapshot_id      = {gold_build.inputs.snapshot_id}")
    print(f"pipeline_version = {gold_build.inputs.pipeline_version}")

    store = LayerStore(
        paths={
            (TRADES, "bronze"): snapshot_source(args.snapshots, args.trades_snapshot_id),
            (RENTS, "bronze"): snapshot_source(args.snapshots, args.rent_snapshot_id),
            (TRADES, "silver"): trades_silver,
            (RENTS, "silver"): rents_silver,
            (GOLD, "gold"): gold,
        }
    )

    results = default_store(args.results)
    if args.fresh:
        # 이 과제의 행만 지운다 — 파일째 지우면 T1 결과가 함께 사라진다.
        results.drop_task(TASK.name)

    inherited = gold_build.run_fields
    rows = []
    for condition in CONDITIONS:
        print(f"\n--- {condition} ---", flush=True)
        row = run_condition(
            TASK,
            condition,  # type: ignore[arg-type]
            datasets=store,
            snapshot_id=inherited["source_snapshot"],
            pipeline_version=inherited["pipeline_version"],
            warmup=args.warmup,
            repeat=args.repeat,
        )
        rows.append(row)
        results.append(row)
        if row.status != "ok":
            print(f"  status={row.status}  (측정값 없음)")
            continue
        matching = row.join_matching_rate
        print(
            f"  rows={row.rows} runtime={row.runtime_seconds:.2f}s loc={row.preprocessing_loc} "
            f"matching={'—' if matching is None else f'{matching:.10f}'}"
        )

    measured = [row for row in rows if row.status == "ok"]
    failed = [row.condition for row in rows if row.status != "ok"]
    if failed:
        print(f"\n[!] 실패한 조건: {failed}")

    reference = next((row.output_hash for row in measured if row.condition == "silver"), None)
    print("\n=== Silver 대비 결과 일치 ===")
    print(
        pd.DataFrame(
            [
                {
                    "Condition": row.condition,
                    "output_hash": row.output_hash[:16] + "…",
                    "Matches silver": row.output_hash == reference,
                    "Kind": KIND[row.condition],
                    "LOC": row.preprocessing_loc,
                    "fn": row.function_count,
                    "matching": row.join_matching_rate,
                }
                for row in measured
            ]
        ).to_string(index=False)
    )
    print(f"\nGold 빌드 비용: {gold_build_seconds:.2f}s (1회)")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
