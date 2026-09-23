"""Task 1을 네 조건으로 실행하고 표 1·3의 숫자를 만든다 (#13, #23).

Gold 계층은 여기서 만든다 — builder의 Gold 단계는 split/join/packaging을 하고 집계는
하지 않으므로, 과제별 집계는 실험이 정의한 단계다. 이 차이는 Threats에 기록한다.

**harness 가상환경에서 실행한다.** 먼저 build_silver.py로 Silver를 만들어 두어야 한다.
"""

from __future__ import annotations

import argparse
import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS, snapshot_source  # noqa: E402

from kpx.datasets import LayerStore  # noqa: E402
from kpx.metrics.breakeven import break_even  # noqa: E402
from kpx.metrics.runtime import MEASURED_RUNS, WARMUP_RUNS  # noqa: E402
from kpx.pipeline import assert_same_inputs, record_derived_layer  # noqa: E402
from kpx.provenance import ProvenanceError, ProvenanceStore  # noqa: E402
from kpx.results import default_store  # noqa: E402
from kpx.runner import run_condition  # noqa: E402
from kpx.tasks.task01_price_analysis import TASK  # noqa: E402
from kpx.tasks.task01_price_analysis import transforms as tf  # noqa: E402

DATASET = "seoul-apartment-trades"
CONDITIONS = ("bronze", "silver", "gold", "monolithic")


def gold_recipe() -> str:
    """Gold를 만든 변환 — provenance가 identity에 섞어 넣는 것.

    builder가 만드는 계층은 BuildSpec이 규칙을 선언하지만 이 Gold는 코드가 곧
    규칙이다. 그래서 요약이 아니라 소스를 넘긴다 — 요약은 코드와 갈라지는 사본이고,
    갈라지는 사본이 Gold build_id를 제자리에 묶어 두던 원인이다.

    ``build_gold``만으로는 모자란다. 그것은 ``transforms``의 함수들을 호출할 뿐이라,
    ``price_per_m2``의 본문이 바뀌면 Gold의 내용은 달라지는데 wrapper의 소스는
    그대로다. 그래서 호출하는 함수를 골라 적지 않고 **모듈 전체**를 넘긴다 — 골라
    적으면 새 호출이 생겼을 때 목록에 넣는 것을 잊어버릴 수 있고, 그것이 방금
    ``derived``를 식별자에서 빠뜨렸던 실수와 같은 종류다.

    Gold가 호출하지 않는 함수까지 들어가므로 build_id가 필요 이상으로 움직인다.
    쓸데없이 움직이는 식별자는 번거로움이고, 움직여야 할 때 가만히 있는 식별자는
    틀린 기록이다.
    """
    return f"{inspect.getsource(tf)}\n{inspect.getsource(build_gold)}"


def build_gold(silver_path: Path, gold_path: Path) -> float:
    """Silver에서 과제용 Gold(자치구 x 월 집계)를 만든다.

    최종 답(YoY·순위)은 담지 않는다 — Gold 조건이 부당하게 유리해지지 않도록 집계까지만
    저장한다.
    """
    started = time.perf_counter()
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
    elapsed = time.perf_counter() - started
    print(f"Gold: {len(gold):,}행 -> {gold_path.name}  ({elapsed:.2f}s)")
    return elapsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id")
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--run-id", default="trades-silver-001")
    parser.add_argument(
        "--datasets",
        type=Path,
        default=None,
        help="provenance 저장소 (기본: experiments/datasets)",
    )
    # 반복 횟수는 harness가 정한 측정 규약을 따른다 (warm-up 1 + 측정 5).
    # 스크립트가 제 값을 갖고 있으면 규약이 두 곳에 생기고, 둘이 갈린다.
    parser.add_argument("--warmup", type=int, default=WARMUP_RUNS)
    parser.add_argument("--repeat", type=int, default=MEASURED_RUNS)
    parser.add_argument(
        "--results",
        type=Path,
        default=None,
        metavar="FILE",
        help="결과 parquet (기본: experiments/results/experiment_results.parquet)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="이전 결과를 지우고 새로 기록한다 (측정 방법이 바뀐 뒤의 재실행)",
    )
    args = parser.parse_args(argv)

    silver = args.work_root / "runs" / args.run_id / "silver" / "trades" / "table.parquet"
    # Gold는 과제별 디렉터리에 둔다. provenance가 디렉터리를 통째로 digest하므로,
    # 공용 폴더에 두면 T2~T4의 Gold가 생길 때 Task 1의 checksum이 남의 파일 때문에
    # 움직인다 — 행 수와 컬럼은 그대로인 채로.
    gold_dir = args.work_root / "gold" / "task01"
    gold = gold_dir / "trades_district_month.parquet"

    # 어떤 빌드를 읽는지 기록에서 확인한다. 기록이 없으면 이 측정이 어떤 입력에서
    # 나왔는지 말할 수 없으므로, 추측하지 않고 멈춘다.
    store_root = args.datasets or Path(__file__).resolve().parents[1] / "datasets"
    builds = ProvenanceStore(store_root)
    silver_builds = builds.list_builds(DATASET, "silver")
    if not silver_builds:
        raise SystemExit(
            f"{DATASET}의 silver 빌드 기록이 없다. "
            f"먼저 scripts/record_builds.py {args.snapshot_id} 를 실행하라."
        )
    silver_build = silver_builds[-1]
    if silver_build.inputs.snapshot_id != args.snapshot_id:
        raise SystemExit(
            f"기록된 silver 빌드는 {silver_build.inputs.snapshot_id} 에서 나왔는데 "
            f"{args.snapshot_id} 로 측정하려 한다."
        )

    # Gold는 Silver에서 파생된다. Silver를 다시 빌드했는데 Gold가 그대로면 옛
    # 스키마로 만든 집계 위에서 측정이 돌고, 그 숫자는 틀린 채로 맞아 보인다.
    # --fresh는 Gold도 다시 만든다. 결과 행만 지우면 빌드 비용을 재지 않게 되어
    # 손익분기가 빠지는데, 그것도 --fresh가 다시 내야 할 숫자다.
    gold_build_seconds: float | None = None
    if args.fresh or not gold.exists() or gold.stat().st_mtime < silver.stat().st_mtime:
        gold_build_seconds = build_gold(silver, gold)

    materialized = pd.read_parquet(gold)
    gold_build = record_derived_layer(
        gold_dir,
        layer="gold",
        upstream=silver_build,
        recipe=gold_recipe(),
        row_count=len(materialized),
        columns=tuple(materialized.columns),
        store=builds,
    )
    try:
        assert_same_inputs([silver_build, gold_build])
    except ProvenanceError as error:
        raise SystemExit(str(error)) from error

    print(f"silver build {silver_build.build_id} -> gold build {gold_build.build_id}")
    print(f"pipeline_version = {gold_build.inputs.pipeline_version}")

    store = LayerStore(
        paths={
            (DATASET, "bronze"): snapshot_source(args.snapshots, args.snapshot_id),
            (DATASET, "silver"): silver,
            (DATASET, "gold"): gold,
        }
    )

    # 결과는 화면이 아니라 파일에 남는다. 콘솔 스크롤백은 논문의 근거가 될 수 없다.
    results = default_store(args.results)
    if args.fresh:
        # 측정 방법이 바뀐 뒤의 재실행이다. 이전 행과 섞이면 한 표 안에 서로 다른
        # 방법으로 잰 숫자가 공존하게 된다. 저장소는 같은 run_id의 재기록을
        # 거부하므로, 지우는 것은 의도를 밝힌 경우에만 한다.
        for path in (results.path, results.csv_path):
            path.unlink(missing_ok=True)
        print(f"이전 결과를 지우고 새로 기록한다: {results.path.name}")

    # 스냅샷과 파이프라인 식별자는 손으로 넣지 않고 방금 읽은 빌드 기록에서 가져온다.
    # run_fields의 키는 결과 스키마의 이름이고, 러너 인자명은 다르다.
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
            # 실패한 실행은 측정값이 없다. 그것을 포맷하려다 여기서 죽으면
            # run_condition이 예외를 삼켜 행을 돌려준 이유가 사라진다.
            print(f"  status={row.status}  (측정값 없음)")
            continue
        print(
            f"  status={row.status} rows={row.rows} runtime={row.runtime_seconds:.2f}s "
            f"peak={row.peak_memory_mb:.0f}MB loc={row.preprocessing_loc} "
            f"steps={row.transformation_steps}"
        )
        print(f"  output_hash={row.output_hash[:16]}…")

    # 표에는 측정된 실행만 담는다. 실패한 조건은 표에서 빠지되 그 사실은 적는다 —
    # 조용히 사라지면 표가 실제보다 성공적인 실험을 서술하게 된다.
    measured = [row for row in rows if row.status == "ok"]
    failed = [row.condition for row in rows if row.status != "ok"]
    if failed:
        print(f"\n[!] 실패한 조건: {failed}")

    # primary와 diagnostic을 한 표에 섞어 찍으면 읽는 사람이 무엇으로 논증하는지
    # 알 수 없다. 조건 간 비교의 근거는 왼쪽 넷이고, Instrumented stages는
    # 선언된 값이라 비교에 쓰지 않는다 (docs/code-metrics.md).
    print("\n=== 표 3: Analytical Effort (RQ2) — primary ===")
    print(
        pd.DataFrame(
            [
                {
                    "Condition": row.condition,
                    "Preprocessing LOC": row.preprocessing_loc,
                    "Transformation functions": row.function_count,
                    "Runtime (s)": round(row.runtime_seconds, 2),
                    "Peak memory (MB)": round(row.peak_memory_mb, 0),
                }
                for row in measured
            ]
        ).to_string(index=False)
    )

    print("\n--- diagnostic (논증에 쓰지 않음) ---")
    print(
        pd.DataFrame(
            [
                {
                    "Condition": row.condition,
                    "Instrumented preparation stages": row.transformation_steps,
                }
                for row in measured
            ]
        ).to_string(index=False)
    )

    # 네 조건이 같은 해시에 도달하지만, 그 일치가 모두 같은 무게를 갖지는 않는다.
    # Gold 파일은 silver 조건이 계산하는 것과 같은 집계 함수로 만들어지므로
    # gold ≡ silver는 구조상 참이다 — 검증이 아니라 materialization 일관성 확인이다.
    # 독립적으로 도달한 것은 bronze와 monolithic 둘뿐이다.
    KIND = {
        "bronze": "semantic equivalence (독립)",
        "monolithic": "baseline equivalence (독립)",
        "gold": "materialization consistency (항등)",
        "silver": "reference",
    }
    print("\n=== Silver 대비 결과 일치 (RQ3) ===")
    digests = {row.condition: row.output_hash for row in measured}
    reference = digests.get("silver")
    print(
        pd.DataFrame(
            [
                {
                    "Condition": row.condition,
                    "output_hash": row.output_hash[:16] + "…",
                    "Matches silver": row.output_hash == reference,
                    "Kind": KIND.get(row.condition, "—"),
                }
                for row in measured
            ]
        ).to_string(index=False)
    )

    # 저장 trade-off는 kpx.metrics.storage가 빌드 기록에서 계산한다 (#19, PR #53).
    # 여기서 파일 크기를 따로 재면 같은 값을 두 곳에서 구하게 되고, 둘이 갈린다.

    # Gold의 준비 비용이 낮은 것은 그 비용이 사라져서가 아니라 상류 빌드로 옮겨갔기
    # 때문이다. 낮은 숫자만 보고하면 trade-off의 절반만 적는 셈이다.
    per_analysis = {row.condition: row.runtime_seconds for row in measured}
    if gold_build_seconds is not None and {"silver", "gold"} <= per_analysis.keys():
        report = break_even(
            build_cost=gold_build_seconds,
            baseline_per_analysis=per_analysis["silver"],
            derived_per_analysis=per_analysis["gold"],
        )
        print("\n=== Gold materialization의 손익분기 (#19 Discussion) ===")
        print(f"  Gold 빌드 비용        : {report.build_cost:.2f}s (1회)")
        print(f"  분석 1회당 Silver     : {report.baseline_per_analysis:.2f}s")
        print(f"  분석 1회당 Gold       : {report.derived_per_analysis:.2f}s")
        print(f"  분석 1회당 절감       : {report.saving_per_analysis:.2f}s")
        print(f"  손익분기              : {report.analyses_to_break_even}회째 분석")
        print("\n  Silver 빌드 비용은 두 조건에 공통이라 상쇄된다. 여기서 분할상환되는")
        print("  것은 Gold 빌드뿐이다.")
    else:
        print("\n  (Gold가 이미 있어 빌드 비용을 재지 않았다. --fresh 로 다시 돌리면 나온다.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
