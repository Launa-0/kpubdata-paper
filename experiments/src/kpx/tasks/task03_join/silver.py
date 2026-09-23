"""Task 3 / Silver 조건 — 두 canonical 데이터셋에서 시작한다.

타입은 맞고 금액은 숫자이며 단지명도 이미 정규화돼 있다. 남은 준비는 과제가
필요로 하는 파생값(면적 구간, ㎡당 금액)과 조인·집계다.
"""

from __future__ import annotations

from kpx.contract import AnalysisInput, RunContext
from kpx.tasks.task03_join.transforms import (
    aggregate_by_district_month,
    area_bucket,
    fold_to_join_keys,
    invalid_key_rate,
    is_jeonse,
    join_diagnostics,
    join_sales_and_jeonse,
    to_year_month,
    unit_price,
)


class Runner:
    TASK = "task03"
    CONDITION = "silver"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        trades = ctx.load("seoul-apartment-trades")
        rents = ctx.load("seoul-apartment-rent")

        with ctx.step("derive_sale_keys"):
            trades["year_month"] = [
                to_year_month(year, month)
                for year, month in zip(trades["deal_year"], trades["deal_month"], strict=True)
            ]
            trades["area_bucket"] = trades["area_m2"].map(area_bucket)
            trades["sale_price_per_m2"] = unit_price(trades["price_10k_krw"], trades["area_m2"])

        with ctx.step("select_jeonse"):
            rents = rents[is_jeonse(rents["monthly_rent_10k_krw"])].copy()

        with ctx.step("derive_jeonse_keys"):
            rents["year_month"] = [
                to_year_month(year, month)
                for year, month in zip(rents["deal_year"], rents["deal_month"], strict=True)
            ]
            rents["area_bucket"] = rents["area_m2"].map(area_bucket)
            rents["jeonse_deposit_per_m2"] = unit_price(rents["deposit_10k_krw"], rents["area_m2"])

        with ctx.step("join_and_aggregate"):
            sales = fold_to_join_keys(trades, "sale_price_per_m2", "sale_price_per_m2")
            jeonse = fold_to_join_keys(rents, "jeonse_deposit_per_m2", "jeonse_deposit_per_m2")
            matched = join_sales_and_jeonse(sales, jeonse)
            aggregated = aggregate_by_district_month(matched)

        return AnalysisInput(
            frame=aggregated,
            notes={
                **join_diagnostics(sales, jeonse, matched),
                "invalid_sale_key_rate": invalid_key_rate(trades),
                "invalid_jeonse_key_rate": invalid_key_rate(rents),
            },
        )
