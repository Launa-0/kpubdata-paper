"""서울 아파트 실거래가의 Silver 계약 — 세 스크립트가 공유한다.

build_silver / r1_rebuild / r2_build이 같은 BuildSpec을 써야 한다. 각자 복사해 두면
한 곳만 고쳤을 때 R1이 재는 "같은 recipe"가 더 이상 같지 않게 된다.
"""

from __future__ import annotations

from typing import Any

# 행정구역·지번 코드는 식별자지 수량이 아니다. 원천 API가 JSON 정수로 내보내기
# 때문에 선언하지 않으면 타입 추론에 맡겨지고, null이 섞인 코드는 실수가 되어
# roadNmSggCd가 11110.0으로 출력된다. 앞자리 0도 조용히 사라진다.
CODE_COLUMNS: dict[str, str] = {
    column: "str"
    for column in (
        "sggCd",
        "umdCd",
        "landCd",
        "roadNmCd",
        "roadNmSggCd",
        "roadNmSeq",
        "roadNmbCd",
        "roadNmBonbun",
        "roadNmBubun",
        "bonbun",
        "bubun",
        "aptDong",
        "jibun",
    )
}

RENAME: dict[str, str] = {
    "sggCd": "district_code",
    "umdNm": "neighborhood",
    "umdCd": "neighborhood_code",
    "aptNm": "apt_name",
    "aptSeq": "apt_seq",
    "excluUseAr": "area_m2",
    "dealAmount": "price_10k_krw",
    "dealYear": "deal_year",
    "dealMonth": "deal_month",
    "dealDay": "deal_day",
    "buildYear": "build_year",
    "jibun": "lot_number",
    "rgstDate": "registration_date",
    "cdealType": "cancel_type",
    "cdealDay": "cancel_day",
    "dealingGbn": "dealing_type",
    "estateAgentSggNm": "agent_district",
    "buyerGbn": "buyer_type",
    "slerGbn": "seller_type",
}

CASTS: dict[str, str] = {
    "price_10k_krw": "int_comma",
    "area_m2": "float",
    "floor": "int",
    "build_year": "int",
    "deal_year": "int",
    "deal_month": "int",
    "deal_day": "int",
}

DATASET_ID = "seoul-apartment-trades"


def build_spec(upload_id: str, *, description: str) -> Any:
    """얼린 스냅샷 하나를 Silver까지 끌고 가는 BuildSpec.

    ``kind="file"`` 소스라 빌드가 API를 호출하지 않는다 — R1이 같은 Bronze를 몇 번이고
    다시 빌드할 수 있는 것이 이 때문이다.
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
        title="Seoul Apartment Trades",
        description=description,
        sources=(
            SourceRef(
                kind="file",
                upload_id=upload_id,
                format="jsonl",
                alias="trades",
                schema=SchemaContract(
                    read_as=CODE_COLUMNS,
                    required=("district_code", "apt_name", "price_10k_krw", "deal_date"),
                    rename=RENAME,
                    casts=CASTS,
                    derived=(
                        DerivedColumn(
                            name="deal_date",
                            kind="date_parts",
                            columns=("deal_year", "deal_month", "deal_day"),
                        ),
                    ),
                ),
            ),
        ),
        exports=(ExportTarget(kind="parquet", output_path="trades.parquet"),),
    )
