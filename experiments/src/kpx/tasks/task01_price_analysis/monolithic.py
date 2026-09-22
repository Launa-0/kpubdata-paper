"""Task 1 / Monolithic baseline — Bronze에서 분석 입력까지 한 번에 간다.

중간 canonical 산출물을 저장하지 않는다. 변환 의미는 Medallion 경로와 동일해야
하므로 같은 ``transforms`` 를 import 한다 — 정제 알고리즘을 다르게 만들어 성능
차이를 유도하지 않는다는 baseline 규약이다.
"""

from __future__ import annotations

from kpx.contract import AnalysisInput, RunContext
from kpx.tasks.task01_price_analysis.transforms import (
    aggregate_by_district_month,
    parse_area_m2,
    parse_district_code,
    parse_price_10k,
    price_per_m2,
    to_year_month,
)


class Runner:
    TASK = "task01"
    CONDITION = "monolithic"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        frame = ctx.load("seoul-apartment-trades")

        with ctx.step("normalize_and_aggregate"):
            frame = frame.assign(
                district_code=frame["sggCd"].map(parse_district_code),
                price_10k_krw=frame["dealAmount"].map(parse_price_10k),
                area_m2=frame["excluUseAr"].map(parse_area_m2),
                # pandas-stubs의 assign은 값에 None이 섞인 리스트를 받지 않는다고
                # 보지만, 결측을 None으로 두는 것이 여기서 맞다 — 아래 dropna가
                # 그 행을 걸러낸다.
                year_month=[
                    to_year_month(year, month)  # type: ignore[misc]
                    for year, month in zip(frame["dealYear"], frame["dealMonth"], strict=True)
                ],
            )
            frame["price_per_m2"] = price_per_m2(frame["price_10k_krw"], frame["area_m2"])
            frame = frame.dropna(subset=["district_code", "year_month", "price_per_m2"])
            aggregated = aggregate_by_district_month(frame)

        return AnalysisInput(frame=aggregated)
