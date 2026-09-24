"""서울 아파트 실거래가의 Silver 계약 — 세 스크립트가 공유한다.

build_silver / r1_rebuild가 같은 BuildSpec을 써야 한다. 각자 복사해 두면
한 곳만 고쳤을 때 R1이 재는 "같은 recipe"가 더 이상 같지 않게 된다.

계약은 ``SPEC`` 한 벌로만 선언한다. ``build_spec()``이 그것으로 BuildSpec을 만들고
``kpx.pipeline.transformation_recipe``가 같은 것을 해시해 pipeline_version을 낸다.
둘이 각자 선언을 들고 있으면 한쪽만 고쳤을 때 규칙은 바뀌었는데 식별자는 그대로인
상태가 되고, 그게 ``derived``가 식별자에서 빠져 있던 이유다.
"""

from __future__ import annotations

from typing import Any

DATASET_ID = "seoul-apartment-trades"
ALIAS = "trades"

#: 이 데이터셋의 Silver 계약 전체. 여기 있는 모든 것이 pipeline_version에 들어간다.
SPEC: dict[str, Any] = {
    "dataset_id": DATASET_ID,
    "title": "Seoul Apartment Trades",
    "source": {"kind": "file", "alias": ALIAS, "format": "jsonl"},
    # 논문의 숫자를 만드는 빌드. 이름 규칙으로 추측하지 않는다 — 같은 dataset_id
    # 아래 폐기한 스냅샷이 남아 있을 수 있고, 어느 것을 쟀는지는 추측이 아니라
    # 선언이어야 한다. recipe에는 들어가지 않는다(RUN_SCOPED_KEYS).
    "snapshot_id": "seoul-apartment-trades/20260922-6660c8e25162",
    "run_id": "trades-silver-001",
    "contract": {
        # 행정구역·지번 코드는 식별자지 수량이 아니다. 원천 API가 JSON 정수로
        # 내보내기 때문에 선언하지 않으면 타입 추론에 맡겨지고, null이 섞인 코드는
        # 실수가 되어 roadNmSggCd가 11110.0으로 출력된다. 앞자리 0도 조용히 사라진다.
        "read_as": {
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
        },
        # docs/required-columns.md: 식별자 + 시점 + 주된 사실.
        "required": ("district_code", "apt_name", "deal_date", "area_m2", "price_10k_krw"),
        "rename": {
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
        },
        "casts": {
            "price_10k_krw": "int_comma",
            "area_m2": "float",
            "floor": "int",
            "build_year": "int",
            "deal_year": "int",
            "deal_month": "int",
            "deal_day": "int",
        },
        "derived": (
            {
                "name": "deal_date",
                "kind": "date_parts",
                "columns": ("deal_year", "deal_month", "deal_day"),
            },
        ),
    },
    "exports": ({"kind": "parquet", "output_path": "trades.parquet"},),
}


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

    contract = dict(SPEC["contract"])
    contract["derived"] = tuple(DerivedColumn(**column) for column in contract["derived"])

    return BuildSpec(
        dataset_id=SPEC["dataset_id"],
        title=SPEC["title"],
        description=description,
        sources=(
            SourceRef(
                upload_id=upload_id,
                schema=SchemaContract(**contract),
                **SPEC["source"],
            ),
        ),
        exports=tuple(ExportTarget(**export) for export in SPEC["exports"]),
    )
