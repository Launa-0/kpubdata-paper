r"""서울 공공자전거 월별 이용정보의 Silver 계약 (T4 #16, R2 #18).

**하나의 계약으로 다섯 세대를 마주한다.** 이 데이터셋은 2020-01~2024-12 사이에 헤더와
값 표현이 다섯 번 바뀌는데, 세대마다 계약을 갈아 끼우면 R2가 재려는 것 — 고정된 선언이
원천의 진화를 얼마나 견디는가 — 이 사라진다. 세대 구분과 근거는
docs/bike-source-generations.md에 고정돼 있다.

계약이 흡수하는 것과 남기는 것:

===========================  ==================================================
`이동거리`/`이동거리(M)`/     coalesce. 세대마다 같은 양에 다른 이름이 붙었다.
`이용거리(M)`                 ``이용거리(M)``는 I1의 오타지만 배포된 원천이 그렇다.
`대여일자`/`대여년월`          coalesce.
`2020-01` / `202207`          year_month. G2 **내부에서** 표기가 바뀐다.
`3` / `00003` / `102`         zfill. 대여소번호는 T4의 식별자라 폭이 맞아야 한다.
`\N`                          null_tokens. 성별만이 아니라 운동량·탄소량에도 있다.
                              성별은 결측 표기가 둘이라(빈 문자열 병행)
                              column_null_tokens로 그 컬럼에만 더한다.
`AGE_003` / `~10대`           **남긴다.** 두 체계의 대응을 말해 주는 근거가 배포
                              파일에 없다. 근거 없는 값 매핑은 정규화가 아니라 조작이고,
                              T4는 이 컬럼을 쓰지 않는다.
`F`/`f`/`M`/`m`               **남긴다.** 같은 이유다.
===========================  ==================================================

G4(2024)는 이 계약으로 빌드되지 않는다. 인구통계 차원이 사라지고 `이용건수`가
`대여건수`/`반납건수`로 갈렸다. 표현이 아니라 **의미**가 바뀐 소스는 고정 계약이
fail-closed 하는 것이 옳은 결과이고, 그것이 R2가 재려는 경계다.

## read_as를 선언하지 않는 이유

원천이 CSV라 ingest_bike.py가 모든 값을 문자열로 내보낸다. 선언해도 하는 일이 없고,
아무 일도 하지 않는 선언이 config_hash에 들어가면 pipeline_version이 실제 규칙보다
많은 것을 말하게 된다. 그 대신 zfill이 대상 컬럼이 Utf8인지 직접 확인한다.

계약은 ``SPEC`` 한 벌로만 선언한다 (trades_spec 참조).
"""

from __future__ import annotations

from typing import Any

DATASET_ID = "seoul-bike-rent-month"
ALIAS = "bike"

SPEC: dict[str, Any] = {
    "dataset_id": DATASET_ID,
    "title": "Seoul Public Bicycle Monthly Usage",
    "source": {"kind": "file", "alias": ALIAS, "format": "jsonl"},
    # 논문의 숫자를 만드는 빌드. 이름 규칙으로 추측하지 않는다 — 같은 dataset_id
    # 아래 폐기한 스냅샷이 남아 있을 수 있고, 어느 것을 쟀는지는 추측이 아니라
    # 선언이어야 한다. recipe에는 들어가지 않는다(RUN_SCOPED_KEYS).
    "snapshot_id": "seoul-bike-rent-month/20260923-637ec21bb5b1",
    "run_id": "bike-t4-silver",
    "contract": {
        # 결측을 빈 값이 아니라 문자열 \N으로 적는다. 캐스팅 전에 null로 모으지
        # 않으면 수치 컬럼에서 #188의 data-loss 가드가 빌드를 세운다.
        "null_tokens": ("\\N",),
        # 성별의 결측은 표기가 둘이다 — 같은 파일 같은 달에 `\N`과 빈 문자열이
        # 동시에 나오고, T4 기준으로 빈 문자열 쪽이 더 많다(1,040,784 vs 940,297).
        # 전역 null_tokens에 ""를 넣으면 **모든 문자열 컬럼**의 빈 문자열을 결측으로
        # 해석하게 된다. T4 범위에서는 빈 문자열이 성별에서만 관측되어 결과가 같지만,
        # 원천의 의미를 컬럼 단위로 말하기 위해 column_null_tokens를 쓴다 — 성별 하나
        # 때문에 계약 전체의 결측 정의를 바꾸지 않는다.
        # on_absent는 **이 규칙**의 presence policy다. 성별이 없는 세대에서 결측
        # 정규화를 건너뛸 뿐, 성별 컬럼을 optional로 만들지는 않는다 — rename이
        # 여전히 성별을 요구하므로 ym_raw가 있고 성별만 없는 세대는 rename에서
        # 멈춘다. 끊은 것은 "null 표기를 선언했다 = 그 컬럼이 반드시 있다"는
        # 불필요한 결합 하나다.
        "column_null_tokens": {"성별": {"tokens": ("",), "on_absent": "ignore"}},
        # 세대마다 다른 이름이 붙은 같은 양. 후보 순서가 우선순위이므로 recipe의
        # 일부다 — 세대가 섞인 스냅샷에서 값이 어긋나면 fail-closed 한다.
        "coalesce": {
            "ym_raw": ("대여일자", "대여년월"),
            "distance_m": ("이동거리", "이동거리(M)", "이용거리(M)"),
            "duration_min": ("이용시간", "이용시간(분)", "이용시간(본)"),
        },
        "rename": {
            "대여소번호": "station_code",
            "대여소명": "station_name",
            "대여구분코드": "pass_type",
            "성별": "gender",
            "연령대코드": "age_band",
            "이용건수": "use_count",
            "운동량": "exercise_kcal",
            "탄소량": "carbon_kg",
        },
        # 같은 대여소가 3과 00003으로 오면 집계에서 둘로 갈린다.
        "zfill": {"station_code": 5},
        "casts": {
            "ym_raw": "year_month",
            "use_count": "int",
            "distance_m": "float",
            "duration_min": "float",
            "exercise_kcal": "float",
            "carbon_kg": "float",
        },
        # docs/required-columns.md: 식별자 + 시점 + 주된 사실.
        # 성별·연령대는 넣지 않는다 — 그 표현 변화를 일부러 계약 밖에 남겼으므로,
        # required에 넣으면 품질 지표가 계약이 보장하지 않는 것을 세게 된다.
        "required": ("station_code", "ym_raw", "use_count"),
    },
    "exports": ({"kind": "parquet", "output_path": "bike.parquet"},),
}


def build_spec(upload_id: str, *, description: str) -> Any:
    """얼린 스냅샷 하나를 Silver까지 끌고 가는 BuildSpec (trades_spec 참조)."""
    from kpubdata_builder.spec.models import (
        BuildSpec,
        ColumnNullTokens,
        ExportTarget,
        SchemaContract,
        SourceRef,
    )

    contract = dict(SPEC["contract"])
    contract["column_null_tokens"] = {
        column: ColumnNullTokens(**rule) for column, rule in contract["column_null_tokens"].items()
    }

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
