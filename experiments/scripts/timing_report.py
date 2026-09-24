"""timing 원자료에서 요약을 만든다 (harness 가상환경).

    python scripts/timing_report.py            # results/timing_raw_*.parquet
    python scripts/timing_report.py --pilot    # .build/timing/pilot_timing_raw_*.parquet

요약은 원자료에서만 만든다. 기술통계뿐이다 — median, 사분위(선형 보간), min–max.
검정과 신뢰구간은 내지 않는다.

요약 전에 확인한다. 하나라도 어긋나면 요약을 쓰지 않는다.

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


def ratios(summary: pd.DataFrame) -> pd.DataFrame:
    """monolithic median ÷ materialized median. 1보다 크면 materialized가 빠르다."""
    wide = summary.pivot_table(
        index=["task", "engine", "scenario"], columns="strategy", values="median"
    ).reset_index()
    wide["monolithic_over_materialized"] = wide["monolithic"] / wide["materialized"]
    return wide


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
    problems = check(raw, _timing.WORK)
    if problems:
        raise SystemExit("요약하지 않는다:\n  " + "\n  ".join(problems))

    summary = summarize(raw)
    summary.to_csv(source / f"{prefix}timing_summary.csv", index=False)
    with pd.option_context("display.width", 200, "display.float_format", "{:.4f}".format):
        print(summary.to_string(index=False))
        print()
        print(ratios(summary).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
