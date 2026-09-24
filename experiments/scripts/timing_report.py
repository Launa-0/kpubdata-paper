"""timing 원자료에서 요약을 만든다 (harness 가상환경).

    python scripts/timing_report.py            # results/timing_raw_*.parquet
    python scripts/timing_report.py --pilot    # .build/timing/pilot_timing_raw_*.parquet

요약은 원자료에서만 만든다. 기술통계뿐이다 — median, 사분위(선형 보간), min–max.
검정과 신뢰구간은 내지 않는다.

- ``timing_summary.csv``: 전략별 32행 기술통계
- ``timing_comparison.csv``: task × engine × scenario 16행, 같은 round 쌍의 비교
  (``compare`` 참조)

요약 전에 확인한다. 하나라도 어긋나면 요약을 쓰지 않는다.

- 원자료의 모양이 프로토콜 그대로다 — 32셀, 셀마다 warm-up 1 + 측정 5, round 중복·누락
  없음, round마다 두 전략, 정해진 실행 순서, 입력은 Parquet.

- 모든 실행의 결과가 기준과 같다 (``equivalent``). pandas는 해시까지 Gold 조건의 기준과
  같아야 한다. polars는 병렬 합산 순서 때문에 마지막 자리가 흔들리므로 준비 실행과
  ``_timing.RTOL`` 안에서 같은지를 본다.
- polars 결과가 pandas 기준과 같다. 행 수·키·문자열·정수·결측 위치는 정확히, 부동소수
  분석값만 ``_timing.RTOL`` 안에서 (절대오차 허용 없음).
- 두 엔진이 같은 기계(``environment_id``)와 같은 코드(``paper_sha``, ``builder_sha``)에서 돌았다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _timing  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kpx.contract import AnalysisInput  # noqa: E402
from kpx.tasks.task01_price_analysis import TASK as TASK01  # noqa: E402
from kpx.tasks.task03_join import TASK as TASK03  # noqa: E402

GOLD = {
    "task01": _timing.EXPERIMENTS / ".build" / "gold" / "task01" / "trades_district_month.parquet",
    "task03": _timing.EXPERIMENTS
    / ".build"
    / "gold"
    / "task03"
    / "trades_rent_district_month.parquet",
}
ANALYZE = {"task01": TASK01.analyze, "task03": TASK03.analyze}
CELL = ["task", "engine", "scenario", "strategy"]


def summarize(raw: pd.DataFrame) -> pd.DataFrame:
    """셀마다 측정 실행(warm-up 제외)의 기술통계."""
    measured = raw[~raw["warmup"]]
    grouped = measured.groupby(CELL, sort=False)["seconds"]
    summary = grouped.agg(
        n="count",
        median="median",
        q1=lambda s: s.quantile(0.25),
        q3=lambda s: s.quantile(0.75),
        min="min",
        max="max",
    ).reset_index()
    summary["iqr"] = summary["q3"] - summary["q1"]
    return summary


def compare(raw: pd.DataFrame) -> pd.DataFrame:
    """task × engine × scenario마다 두 전략의 비교.

    같은 round 안에서 번갈아 돈 두 실행을 한 쌍으로 본다. 본문 비교값은 쌍의 값 —
    ``median_paired_ratio``(monolithic ÷ materialized)와 ``median_paired_delta_seconds``
    (monolithic − materialized)다. 둘 다 1·0보다 크면 materialized가 빠르다. 비율만
    쓰면 수 ms 대 수 s의 차이가 과장돼 보이므로 절대 차이를 함께 둔다. 전략별
    median의 비율(``ratio_of_medians``)도 같이 남긴다.
    """
    measured = raw[~raw["warmup"]]
    pairs = measured.pivot_table(
        index=["task", "engine", "scenario", "round"], columns="strategy", values="seconds"
    ).reset_index()
    pairs["ratio"] = pairs["monolithic"] / pairs["materialized"]
    pairs["delta"] = pairs["monolithic"] - pairs["materialized"]
    table = (
        pairs.groupby(["task", "engine", "scenario"], sort=False)
        .agg(
            n_pairs=("round", "count"),
            materialized_median=("materialized", "median"),
            monolithic_median=("monolithic", "median"),
            median_paired_ratio=("ratio", "median"),
            median_paired_delta_seconds=("delta", "median"),
        )
        .reset_index()
    )
    table.insert(6, "ratio_of_medians", table["monolithic_median"] / table["materialized_median"])
    return table


def check_structure(raw: pd.DataFrame, tasks: tuple[str, ...], repeats: int) -> list[str]:
    """원자료가 프로토콜이 정한 모양 그대로인지 — 아니면 요약하지 않는다.

    셀 구성, round 0(warm-up)부터 ``repeats``까지의 중복·누락, round마다 두 전략, 실행
    순서를 ``_timing.schedule``이 만드는 것과 행 단위로 맞춘다.
    """
    key = ["task", "engine", "scenario", "strategy", "round", "order_position", "warmup"]
    expected = pd.DataFrame(
        [
            (s.task, engine, s.scenario, s.strategy, s.round, s.order_position, s.warmup)
            for engine in ("pandas", "polars")
            for s in _timing.schedule(tasks, repeats=repeats)
        ],
        columns=key,
    )
    problems = []
    duplicated = raw.duplicated(key[:5]).sum()
    if duplicated:
        problems.append(f"같은 셀·round의 실행이 {duplicated}개 중복됐다")
    actual = raw[key].astype({"round": "int64", "order_position": "int64", "warmup": "bool"})
    merged = expected.merge(actual.drop_duplicates(), how="outer", indicator=True)
    missing, extra = (
        (merged["_merge"] == "left_only").sum(),
        (merged["_merge"] == "right_only").sum(),
    )
    if missing or extra:
        problems.append(f"프로토콜과 다른 실행: 빠짐 {missing}개, 예정에 없음 {extra}개")
    if not (raw["input_format"] == _timing.INPUT_FORMAT).all():
        problems.append(f"입력 형식이 {_timing.INPUT_FORMAT}가 아닌 실행이 있다")
    return problems


def same_result(left: pd.DataFrame, right: pd.DataFrame) -> str | None:
    """두 엔진의 분석 결과가 같은지. 다르면 이유를, 같으면 ``None``."""
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return f"모양이 다르다: {left.shape} {list(left.columns)} vs {right.shape}"
    for column in left.columns:
        a, b = left[column], right[column]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            x, y = a.to_numpy("float64", na_value=np.nan), b.to_numpy("float64", na_value=np.nan)
            if not np.array_equal(np.isnan(x), np.isnan(y)):
                return f"{column}: 결측 위치가 다르다"
            # 정수(건수·순위)는 정확히, 부동소수 분석값만 상대오차로 본다.
            exact = pd.api.types.is_integer_dtype(a) or pd.api.types.is_integer_dtype(b)
            rtol = 0.0 if exact else _timing.RTOL
            if not np.allclose(x, y, rtol=rtol, atol=0.0, equal_nan=True):
                return f"{column}: 최대 차이 {np.nanmax(np.abs(x - y))}"
        elif not a.astype("string").equals(b.astype("string")):
            return f"{column}: 값이 다르다"
    return None


def check(raw: pd.DataFrame, root: Path) -> list[str]:
    problems = []
    for key in ("environment_id", "paper_sha", "builder_sha"):
        if raw[key].nunique() != 1:
            problems.append(f"{key}가 여럿이다: {sorted(raw[key].unique())}")
    pandas_rows = raw[raw["engine"] == "pandas"]
    wrong = pandas_rows[
        pandas_rows["output_hash"] != pandas_rows["task"].map(_timing.REFERENCE_HASH)
    ]
    if len(wrong):
        problems.append(f"pandas 실행 {len(wrong)}개가 기준 해시와 다르다")
    if not raw["equivalent"].all():
        problems.append(f"실행 {int((~raw['equivalent']).sum())}개가 기준 결과와 다르다")
    for task in raw["task"].unique():
        reference = ANALYZE[task](AnalysisInput(frame=pd.read_parquet(GOLD[task]))).result
        polars = pd.read_parquet(root / "polars" / f"{task}_result.parquet")
        reason = same_result(reference, polars)
        if reason:
            problems.append(f"{task}: polars 결과가 pandas 기준과 다르다 — {reason}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args(argv)
    source = _timing.WORK if args.pilot else _timing.RESULTS
    prefix = "pilot_" if args.pilot else ""

    raw = pd.concat(
        [pd.read_parquet(source / f"{prefix}timing_raw_{e}.parquet") for e in ("pandas", "polars")],
        ignore_index=True,
    )
    # 파일럿은 줄여 돌리므로 그 모양에 맞춰 본다. 최종은 프로토콜 그대로여야 한다.
    tasks = tuple(raw["task"].unique()) if args.pilot else tuple(_timing.TASKS)
    repeats = int(raw["round"].max()) if args.pilot else _timing.MEASURED_RUNS
    problems = check_structure(raw, tasks, repeats) + check(raw, _timing.WORK)
    if problems:
        raise SystemExit("요약하지 않는다:\n  " + "\n  ".join(problems))

    summary, comparison = summarize(raw), compare(raw)
    summary.to_csv(source / f"{prefix}timing_summary.csv", index=False)
    comparison.to_csv(source / f"{prefix}timing_comparison.csv", index=False)
    with pd.option_context("display.width", 200, "display.float_format", "{:.4f}".format):
        print(summary.to_string(index=False))
        print()
        print(comparison.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
