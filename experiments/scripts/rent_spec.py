"""서울 아파트 전월세의 Silver 계약 (T3 조인의 한쪽).

매매와 같은 기관·같은 계열의 API지만 스키마가 다르다. 컬럼명 대소문자 규칙부터
다르고(`roadNm` 대 `roadnm`), 금액이 보증금과 월세 둘로 나뉘며, 월세는 레코드에 따라
정수로도 문자열로도 온다.

**같은 기관의 같은 주제 API 둘이 서로 다른 표현을 쓴다** — T3가 통합 과제인 이유이고,
Bronze 조건이 치러야 할 비용이 어디서 오는지이기도 하다.
"""

from __future__ import annotations

from typing import Any

# 코드·지번은 식별자지 수량이 아니다. 원천이 JSON 정수로 내보내므로 선언하지 않으면
# 타입 추론에 맡겨진다. jibun과 monthlyRent는 레코드마다 타입이 갈려서(#187) 선언이
# 없으면 빌드가 실패한다.
CODE_COLUMNS: dict[str, str] = {
    column: "str"
    for column in (
        "sggCd",
        "roadnmcd",
        "roadnmsggcd",
        "roadnmseq",
        "roadnmbcd",
        "roadnmbonbun",
        "roadnmbubun",
        "jibun",
        "monthlyRent",
    )
}

RENAME: dict[str, str] = {
    "sggCd": "district_code",
    "umdNm": "neighborhood",
    "aptNm": "apt_name",
    "aptSeq": "apt_seq",
    "excluUseAr": "area_m2",
    "deposit": "deposit_10k_krw",
    "monthlyRent": "monthly_rent_10k_krw",
    "dealYear": "deal_year",
    "dealMonth": "deal_month",
    "dealDay": "deal_day",
    "buildYear": "build_year",
    "jibun": "lot_number",
    "contractType": "contract_type",
    "contractTerm": "contract_term",
    "preDeposit": "prior_deposit",
    "preMonthlyRent": "prior_monthly_rent",
}

CASTS: dict[str, str] = {
    "deposit_10k_krw": "int_comma",
    "monthly_rent_10k_krw": "int_comma",
    "area_m2": "float",
    "floor": "int",
    "build_year": "int",
    "deal_year": "int",
    "deal_month": "int",
    "deal_day": "int",
}

DATASET_ID = "seoul-apartment-rent"


def build_spec(upload_id: str, *, description: str) -> Any:
    """얼린 전월세 스냅샷을 Silver까지 끌고 가는 BuildSpec.

    `join_key`는 매매 쪽과 같은 규칙으로 만든다 — 자치구 코드, 단지명, 계약 연월.
    두 데이터셋이 같은 키를 갖는 것이 T3에서 Silver/Gold 조건이 제공하는 것이다.
    """
    from kpubdata_builder.spec.models import (
        BuildSpec,
        DerivedColumn,
        ExportTarget,
        SchemaContract,
        SourceRef,
    )

    return BuildSpec(
        dataset_id=DATASET_ID,
        title="Seoul Apartment Rent",
        description=description,
        sources=(
            SourceRef(
                kind="file",
                upload_id=upload_id,
                format="jsonl",
                alias="rent",
                schema=SchemaContract(
                    read_as=CODE_COLUMNS,
                    required=("district_code", "apt_name", "deposit_10k_krw", "contract_date"),
                    rename=RENAME,
                    casts=CASTS,
                    derived=(
                        DerivedColumn(
                            name="contract_date",
                            kind="date_parts",
                            columns=("deal_year", "deal_month", "deal_day"),
                        ),
                    ),
                ),
            ),
        ),
        exports=(ExportTarget(kind="parquet", output_path="rent.parquet"),),
    )
