"""Task 1의 분석 — 네 조건이 동일하게 공유한다.

조건은 오직 ``AnalysisInput`` 에 어떻게 도달하느냐만 다르다. 분석이 조건마다 달라지면
결과 차이를 준비 과정에 귀속시킬 수 없다.
"""

from __future__ import annotations

import pandas as pd

from kpx.contract import AnalysisInput, AnalysisOutput

#: 전년 동월 대비 증감률을 볼 때 건너뛰는 개월 수.
MONTHS_IN_YEAR = 12


def previous_year_month(year_month: str) -> str:
    """``"2021-02"`` -> ``"2020-02"``."""
    year, month = year_month.split("-")
    return f"{int(year) - 1:04d}-{month}"


def analyze(prepared: AnalysisInput) -> AnalysisOutput:
    """자치구별 월평균 실거래가의 전년 동월 대비 변화와 순위를 낸다.

    Gold가 미리 담고 있지 않은 부분이 바로 여기다.

    ``mean_price_yoy_change``는 **거래된 아파트의 월평균 ㎡당 가격이 전년 동월
    대비 얼마나 달라졌는가**다. 시장 가격 상승률이 아니다 — 매달 거래되는 단지의
    구성이 바뀌므로 구성 효과가 섞인다. 시장 가격 추세와 비교하려면 공식
    매매가격지수를 External Reference Statistic으로 써야 한다 (#6).
    """
    prepared.require_columns("district_code", "year_month", "mean_price_per_m2", "n_deals")
    frame = prepared.frame.sort_values(["district_code", "year_month"]).copy()

    # 전년 동월을 위치가 아니라 키로 찾는다. 거래가 없는 달은 집계에 행이 생기지
    # 않으므로, 12행 전이 전년 동월이라는 보장이 없다.
    frame["_prev_year_month"] = frame["year_month"].map(previous_year_month)
    previous = frame[["district_code", "year_month", "mean_price_per_m2"]].rename(
        columns={"year_month": "_prev_year_month", "mean_price_per_m2": "_prev_mean"}
    )
    frame = frame.merge(previous, on=["district_code", "_prev_year_month"], how="left")
    frame["mean_price_yoy_change"] = frame["mean_price_per_m2"] / frame["_prev_mean"] - 1
    frame = frame.drop(columns=["_prev_year_month", "_prev_mean"])
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


def mean_transaction_price_yoy(result: pd.DataFrame) -> float:
    """자치구·월에 걸친 평균 실거래가 전년 대비 변화의 평균.

    공식 매매가격지수와 같은 양이 아니다. 지수는 구성 효과를 통제하지만 이 값은
    그렇지 않다. External Reference Statistic과 대조할 때는 수준이 아니라 방향과
    추세 상관으로 비교한다 (#6, metrics/reference.py).
    """
    return float(result["mean_price_yoy_change"].mean())
