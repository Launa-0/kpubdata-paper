"""Task 1 / Silver 조건 — canonical 데이터셋에서 시작한다.

타입은 이미 맞고 금액도 숫자다. 남은 준비는 과제가 필요로 하는 파생값(㎡당 가격)과
집계뿐이다.
"""

from __future__ import annotations

from kpx.contract import AnalysisInput, RunContext
from kpx.tasks.task01_price_analysis.transforms import (
    aggregate_by_district_month,
    price_per_m2,
    to_year_month,
)


class Runner:
    TASK = "task01"
    CONDITION = "silver"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        frame = ctx.load("seoul-apartment-trades")

        with ctx.step("compose_year_month"):
            frame["year_month"] = [
                to_year_month(year, month)
                for year, month in zip(frame["deal_year"], frame["deal_month"], strict=True)
            ]
        with ctx.step("compute_price_per_m2"):
            frame["price_per_m2"] = price_per_m2(frame["price_10k_krw"], frame["area_m2"])
        with ctx.step("aggregate_by_district_month"):
            aggregated = aggregate_by_district_month(frame)

        return AnalysisInput(frame=aggregated)
