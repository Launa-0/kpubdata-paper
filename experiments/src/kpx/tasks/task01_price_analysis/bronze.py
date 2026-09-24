"""Task 1 / Bronze 조건 — 최소 파싱된 원천에서 시작한다.

금액은 쉼표 붙은 문자열, 면적은 문자열, 거래 시점은 연·월·일 세 컬럼이다. 분석에
쓰려면 그 표현을 전부 준비 코드가 직접 풀어야 한다 — 그 코드 규모가 RQ2가 재는 값이다.
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
    CONDITION = "bronze"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        frame = ctx.load("seoul-apartment-trades")

        with ctx.step("parse_district_code"):
            frame["district_code"] = frame["sggCd"].map(parse_district_code)
        with ctx.step("parse_price"):
            frame["price_10k_krw"] = frame["dealAmount"].map(parse_price_10k)
        with ctx.step("parse_area"):
            frame["area_m2"] = frame["excluUseAr"].map(parse_area_m2)
        with ctx.step("compose_year_month"):
            frame["year_month"] = [
                to_year_month(year, month)
                for year, month in zip(frame["dealYear"], frame["dealMonth"], strict=True)
            ]
        with ctx.step("compute_price_per_m2"):
            frame["price_per_m2"] = price_per_m2(frame["price_10k_krw"], frame["area_m2"])
        with ctx.step("drop_unusable_rows"):
            frame = frame.dropna(subset=["district_code", "year_month", "price_per_m2"])
        with ctx.step("aggregate_by_district_month"):
            aggregated = aggregate_by_district_month(frame)

        return AnalysisInput(frame=aggregated)
