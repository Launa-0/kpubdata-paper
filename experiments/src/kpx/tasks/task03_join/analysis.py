"""Task 3의 분석 — 네 조건이 동일하게 공유한다.

조건은 오직 ``AnalysisInput`` 에 어떻게 도달하느냐만 다르다.
"""

from __future__ import annotations

import pandas as pd

from kpx.contract import AnalysisInput, AnalysisOutput


def analyze(prepared: AnalysisInput) -> AnalysisOutput:
    """자치구 × 월 전세가율과 그 추세를 낸다.

    전세가율은 전세보증금을 매매가로 나눈 값이다. 여기서는 ㎡당 값끼리 나누므로
    같은 단지·같은 크기 구간에서 맞춰진 뒤의 비율이다 — 단지 구성이 다른 두
    모집단의 평균을 그냥 나눈 값이 아니다.

    Gold가 미리 담고 있지 않은 부분이 바로 이 비율과 추세다.
    """
    prepared.require_columns(
        "district_code",
        "year_month",
        "mean_sale_price_per_m2",
        "mean_jeonse_deposit_per_m2",
        "n_matched",
    )
    frame = prepared.frame.sort_values(["district_code", "year_month"]).copy()

    sale = frame["mean_sale_price_per_m2"].where(frame["mean_sale_price_per_m2"] > 0)
    frame["jeonse_ratio"] = frame["mean_jeonse_deposit_per_m2"] / sale

    # 전년 동월을 위치가 아니라 키로 찾는다. 조인이 비는 달은 행이 없으므로
    # 12행 전이 전년 동월이라는 보장이 없다.
    frame["_prev_year_month"] = frame["year_month"].map(previous_year_month)
    previous = frame[["district_code", "year_month", "jeonse_ratio"]].rename(
        columns={"year_month": "_prev_year_month", "jeonse_ratio": "_prev_ratio"}
    )
    frame = frame.merge(previous, on=["district_code", "_prev_year_month"], how="left")
    frame["jeonse_ratio_yoy_change"] = frame["jeonse_ratio"] - frame["_prev_ratio"]
    result = frame.drop(columns=["_prev_year_month", "_prev_ratio"])

    return AnalysisOutput(result=result.reset_index(drop=True), metrics={})


def previous_year_month(year_month: str) -> str:
    """``"2021-02"`` -> ``"2020-02"``."""
    year, month = year_month.split("-")
    return f"{int(year) - 1:04d}-{month}"


def mean_jeonse_ratio(result: pd.DataFrame) -> float:
    """자치구·월에 걸친 전세가율의 평균.

    한국부동산원의 "평균 매매가격 대비 전세가격"과 같은 양이 아니다 — 그쪽은 표본
    조사 기반이고 이쪽은 실거래 기반이며, 2021년 7월 표본 개편으로 생긴 단절도
    이쪽에는 없다. 대조할 때는 수준이 아니라 방향과 추세 상관으로 본다
    (#6, metrics/reference.py).
    """
    return float(result["jeonse_ratio"].mean())
