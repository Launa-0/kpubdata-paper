"""Task 1의 분석 — 네 조건이 동일하게 공유한다.

조건은 오직 ``AnalysisInput`` 에 어떻게 도달하느냐만 다르다. 분석이 조건마다 달라지면
결과 차이를 준비 과정에 귀속시킬 수 없다.
"""

from __future__ import annotations

import pandas as pd

from kpx.contract import AnalysisInput, AnalysisOutput

#: 전년 동월 대비 증감률을 볼 때 건너뛰는 개월 수.
MONTHS_IN_YEAR = 12


def analyze(prepared: AnalysisInput) -> AnalysisOutput:
    """자치구별 가격 추세를 산출한다 — 전년 동월 대비 증감률과 순위.

    Gold가 미리 담고 있지 않은 부분이 바로 여기다.
    """
    prepared.require_columns("district_code", "year_month", "mean_price_per_m2", "n_deals")
    frame = prepared.frame.sort_values(["district_code", "year_month"]).copy()

    frame["yoy_growth"] = frame.groupby("district_code")["mean_price_per_m2"].pct_change(
        periods=MONTHS_IN_YEAR
    )
    latest = frame["year_month"].max()
    ranking = (
        frame[frame["year_month"] == latest]
        .sort_values("mean_price_per_m2", ascending=False)
        .assign(price_rank=lambda f: range(1, len(f) + 1))[["district_code", "price_rank"]]
    )
    result = frame.merge(ranking, on="district_code", how="left")

    return AnalysisOutput(
        result=result.reset_index(drop=True),
        metrics={},
    )


def national_mean_yoy(result: pd.DataFrame) -> float:
    """External Reference Statistic과 비교할 하나의 요약값."""
    return float(result["yoy_growth"].mean())
