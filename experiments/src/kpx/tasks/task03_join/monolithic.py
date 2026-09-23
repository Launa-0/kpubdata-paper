"""Task 3 / Monolithic baseline — 두 원천에서 분석 입력까지 한 번에 간다.

중간 canonical 산출물을 저장하지 않는다. 변환 의미는 Medallion 경로와 동일해야
하므로 같은 ``transforms`` 를 import 한다.

Task 3에서 이 baseline이 특히 불리해지는 지점은 조인이다. 두 데이터셋의 키를
동시에 들고 있어야 하므로 한 패스 안에 양쪽 정제가 모두 들어간다 — 중간 산출물을
재사용할 수 없다는 것이 무슨 뜻인지가 여기서 드러난다.
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

JOIN_KEYS = ["district_code", "apt_name", "year_month", "area_bucket"]


class Runner:
    TASK = "task03"
    CONDITION = "monolithic"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        with ctx.step("normalize_join_and_aggregate"):
            trades = ctx.load("seoul-apartment-trades")
            rents = ctx.load("seoul-apartment-rent")

            trades = trades.assign(
                district_code=trades["sggCd"].map(parse_district_code),
                apt_name=trades["aptNm"].map(normalize_apt_name),
                area_m2=trades["excluUseAr"].map(parse_area_m2),
                price_10k_krw=trades["dealAmount"].map(parse_amount_10k),
                # pandas-stubs의 assign은 None이 섞인 리스트를 받지 않는다고 보지만,
                # 결측을 None으로 두는 것이 여기서 맞다 — 아래 dropna가 걸러낸다.
                year_month=[
                    to_year_month(year, month)  # type: ignore[misc]
                    for year, month in zip(trades["dealYear"], trades["dealMonth"], strict=True)
                ],
            )
            trades["area_bucket"] = trades["area_m2"].map(area_bucket)
            trades["sale_price_per_m2"] = unit_price(trades["price_10k_krw"], trades["area_m2"])

            rents = rents.assign(
                district_code=rents["sggCd"].map(parse_district_code),
                apt_name=rents["aptNm"].map(normalize_apt_name),
                area_m2=rents["excluUseAr"].map(parse_area_m2),
                deposit_10k_krw=rents["deposit"].map(parse_amount_10k),
                monthly_rent_10k_krw=rents["monthlyRent"].map(parse_amount_10k),
                year_month=[
                    to_year_month(year, month)  # type: ignore[misc]
                    for year, month in zip(rents["dealYear"], rents["dealMonth"], strict=True)
                ],
            )
            rents = rents[is_jeonse(rents["monthly_rent_10k_krw"])].copy()
            rents["area_bucket"] = rents["area_m2"].map(area_bucket)
            rents["jeonse_deposit_per_m2"] = unit_price(rents["deposit_10k_krw"], rents["area_m2"])

            sale_invalid = invalid_key_rate(trades)
            jeonse_invalid = invalid_key_rate(rents)
            trades = trades.dropna(subset=JOIN_KEYS)
            rents = rents.dropna(subset=JOIN_KEYS)

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
