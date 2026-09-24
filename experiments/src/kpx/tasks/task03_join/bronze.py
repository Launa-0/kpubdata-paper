"""Task 3 / Bronze 조건 — 최소 파싱된 두 원천에서 시작한다.

금액은 쉼표 붙은 문자열, 면적은 문자열, 시점은 연·월·일 세 컬럼, 단지명은 신고된
그대로다. 조인 키를 만들려면 그 표현을 전부 준비 코드가 직접 풀어야 한다 — 그 코드
규모가 RQ2가 재는 값이다.

단지명 정규화는 여기서 **직접 호출한다**. Silver는 계층이 이미 해 둔 일이다.
raw 이름 그대로 조인하면 매칭률이 떨어지지만, 그렇게 두는 것은 baseline bias다 —
자세한 근거는 패키지 docstring에 적었다.
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
    normalize_apt_name,
    parse_amount_10k,
    parse_area_m2,
    parse_district_code,
    to_year_month,
    unit_price,
)


class Runner:
    TASK = "task03"
    CONDITION = "bronze"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        trades = ctx.load("seoul-apartment-trades")
        rents = ctx.load("seoul-apartment-rent")

        with ctx.step("parse_sale_columns"):
            trades["district_code"] = trades["sggCd"].map(parse_district_code)
            trades["apt_name"] = trades["aptNm"].map(normalize_apt_name)
            trades["area_m2"] = trades["excluUseAr"].map(parse_area_m2)
            trades["price_10k_krw"] = trades["dealAmount"].map(parse_amount_10k)

        with ctx.step("parse_rent_columns"):
            rents["district_code"] = rents["sggCd"].map(parse_district_code)
            rents["apt_name"] = rents["aptNm"].map(normalize_apt_name)
            rents["area_m2"] = rents["excluUseAr"].map(parse_area_m2)
            rents["deposit_10k_krw"] = rents["deposit"].map(parse_amount_10k)
            rents["monthly_rent_10k_krw"] = rents["monthlyRent"].map(parse_amount_10k)

        with ctx.step("select_jeonse"):
            rents = rents[is_jeonse(rents["monthly_rent_10k_krw"])].copy()

        with ctx.step("derive_sale_keys"):
            trades["year_month"] = [
                to_year_month(year, month)
                for year, month in zip(trades["dealYear"], trades["dealMonth"], strict=True)
            ]
            trades["area_bucket"] = trades["area_m2"].map(area_bucket)
            trades["sale_price_per_m2"] = unit_price(trades["price_10k_krw"], trades["area_m2"])

        with ctx.step("derive_jeonse_keys"):
            rents["year_month"] = [
                to_year_month(year, month)
                for year, month in zip(rents["dealYear"], rents["dealMonth"], strict=True)
            ]
            rents["area_bucket"] = rents["area_m2"].map(area_bucket)
            rents["jeonse_deposit_per_m2"] = unit_price(rents["deposit_10k_krw"], rents["area_m2"])

        with ctx.step("drop_rows_without_join_keys"):
            sale_invalid = invalid_key_rate(trades)
            jeonse_invalid = invalid_key_rate(rents)
            trades = trades.dropna(
                subset=["district_code", "apt_name", "year_month", "area_bucket"]
            )
            rents = rents.dropna(subset=["district_code", "apt_name", "year_month", "area_bucket"])

        with ctx.step("join_and_aggregate"):
            sales = fold_to_join_keys(trades, "sale_price_per_m2", "sale_price_per_m2")
            jeonse = fold_to_join_keys(rents, "jeonse_deposit_per_m2", "jeonse_deposit_per_m2")
            matched = join_sales_and_jeonse(sales, jeonse)
            aggregated = aggregate_by_district_month(matched)

        return AnalysisInput(
            frame=aggregated,
            notes={
                **join_diagnostics(sales, jeonse, matched),
                "invalid_sale_key_rate": sale_invalid,
                "invalid_jeonse_key_rate": jeonse_invalid,
            },
        )
