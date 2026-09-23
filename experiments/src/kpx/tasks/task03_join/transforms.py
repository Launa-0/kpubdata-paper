"""Task 3가 공유하는 변환 — 네 조건이 모두 여기에서 가져다 쓴다.

Task 1과 같은 이유로 한 곳에 둔다 (Baseline Bias). 조건이 달라지는 지점은 "이 중
몇 개를 호출해야 하는가"이지 "누가 파서를 더 잘 썼는가"가 아니다.

조인 키에 관한 결정
-------------------

매매와 전월세를 잇는 키는 ``(district_code, apt_name, year_month, area_bucket)``
이다. 같은 단지의 같은 크기 주택을 같은 달에 비교한다는 뜻이다.

면적을 값 그대로 쓰지 않고 구간으로 묶는다. 전용면적은 ``84.97``과 ``84.9`` 처럼
소수점 자리가 신고마다 흔들리고, 두 데이터셋이 같은 세대를 다른 값으로 적는 일이
잦다. 실수 동등비교로 조인하면 매칭이 사실상 무너진다.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

KRW_PER_10K = 10_000

#: 전용면적 구간 경계(㎡). 국민주택규모(85㎡)를 포함한, 시장에서 통용되는 구분이다.
AREA_EDGES: tuple[float, ...] = (40.0, 60.0, 85.0, 135.0)

_NON_NAME = re.compile(r"[^0-9A-Za-z가-힣]+")


def parse_amount_10k(value: object) -> float | None:
    """만원 단위 금액 문자열을 숫자로 읽는다 (``"31,000"`` -> ``31000.0``).

    거래금액과 보증금이 같은 표현을 쓴다. 쉼표를 지우지 않으면 전부 결측이 된다.
    """
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_area_m2(value: object) -> float | None:
    """전용면적을 실수로 읽는다."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_district_code(value: object) -> str | None:
    """시군구 코드를 5자리 문자열로 정규화한다.

    식별자이므로 정수로 읽지 않는다 — 앞자리 0이 사라지면 조인 키로 못 쓴다.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text.zfill(5) if text else None


def normalize_apt_name(value: object) -> str | None:
    """단지명을 조인 가능한 형태로 정규화한다.

    같은 단지가 두 데이터셋에서 ``"래미안 강남 힐즈(1단지)"`` 와
    ``"래미안강남힐즈 1단지"`` 처럼 다르게 적히는 일이 흔하다. 공백·괄호·구두점이
    다를 뿐인 이름을 서로 다른 키로 두면 조인이 무너진다.

    유니코드는 NFC로 맞춘다. 같은 한글이 자소 분리형(NFD)으로 들어오면 바이트가
    달라 문자열 동등비교가 실패한다 — 스냅샷 digest에서와 같은 결함이다.

    괄호는 **지우되 안의 내용은 남긴다.** 괄호 안에 동·단지 번호가 들어가는 일이
    흔해서(``"래미안 강남 힐즈(1단지)"``), 내용까지 지우면 1단지와 2단지가 같은 키가
    된다. 그건 조인이 실패하는 것보다 나쁘다 — 실패는 unmatched로 드러나지만,
    서로 다른 동을 합친 평균은 아무 표시 없이 전세가율에 섞인다.

    대가는 ``"(주상복합)"`` 같은 비식별 수식어가 남아 같은 단지가 갈릴 수 있다는
    것이다. 그쪽 오류는 unmatched 수로 관측되므로, 관측 가능한 실패를 택한다.
    """
    if value is None:
        return None
    text = unicodedata.normalize("NFC", str(value))
    text = _NON_NAME.sub("", text)
    return text or None


def to_year_month(year: object, month: object) -> str | None:
    """연/월 컬럼을 ``YYYY-MM`` 으로 합친다."""
    if year is None or month is None:
        return None
    try:
        return f"{int(str(year).strip()):04d}-{int(str(month).strip()):02d}"
    except ValueError:
        return None


def area_bucket(area_m2: object) -> str | None:
    """전용면적을 구간 라벨로 접는다 (``"60-85"``).

    실수 동등비교를 피하기 위한 조인 키다. 신고된 소수점 자리가 데이터셋마다
    흔들려도 같은 구간에 떨어진다.
    """
    value = parse_area_m2(area_m2)
    if value is None or value <= 0:
        return None
    lower = 0.0
    for edge in AREA_EDGES:
        if value < edge:
            return f"{lower:g}-{edge:g}"
        lower = edge
    return f"{lower:g}+"


def is_jeonse(monthly_rent_10k: pd.Series) -> pd.Series:
    """전세 계약만 남기는 마스크.

    월세가 0인 계약만 전세다. 월세가 붙은 계약의 보증금은 전세보증금과 다른 양이라,
    섞어서 평균 내면 전세가율이 아니라 아무 의미 없는 수가 나온다.

    결측은 전세가 아니라 **모름**이다. 0을 생략한 표기라는 계약 근거가 없으므로
    전세로 세지 않는다. 현재 두 원천 모두 결측이 0건이라 이 구분은 지금의 숫자를
    바꾸지 않지만, 결측이 하나라도 들어오는 순간 조용히 전세가율을 오염시킨다.
    """
    return monthly_rent_10k.eq(0)


def unit_price(amount_10k: pd.Series, area_m2: pd.Series) -> pd.Series:
    """㎡당 금액(원). 면적이 0 이하인 행은 결측으로 둔다."""
    safe_area = area_m2.where(area_m2 > 0)
    return amount_10k * KRW_PER_10K / safe_area


def fold_to_join_keys(frame: pd.DataFrame, value_column: str, out_column: str) -> pd.DataFrame:
    """단지·크기·월 단위로 접어 조인 키 하나당 한 행으로 만든다.

    같은 키에 여러 거래가 있을 수 있으므로 평균을 낸다. 접지 않고 조인하면
    매매 n건 × 전세 m건의 곱집합이 생겨 평균이 거래 빈도에 끌려간다.
    """
    usable = frame.dropna(subset=[*JOIN_KEYS, value_column])
    folded = usable.groupby(list(JOIN_KEYS), as_index=False).agg(
        **{out_column: (value_column, "mean")}
    )
    return folded


#: 매매와 전월세를 잇는 키.
JOIN_KEYS: tuple[str, ...] = ("district_code", "apt_name", "year_month", "area_bucket")


def join_sales_and_jeonse(sales: pd.DataFrame, jeonse: pd.DataFrame) -> pd.DataFrame:
    """접힌 매매·전세 표를 조인 키로 맞춘다.

    ``how="inner"`` 다. 한쪽에만 있는 키는 전세가율을 만들 수 없다.
    """
    return sales.merge(jeonse, on=list(JOIN_KEYS), how="inner")


def join_diagnostics(
    sales: pd.DataFrame, jeonse: pd.DataFrame, matched: pd.DataFrame
) -> dict[str, float]:
    """조인이 얼마나 맞았는지 — RQ3가 Task 3에서 재는 값.

    ``join_matching_rate`` 의 분모는 매매 쪽 키 수다. 전세가율은 매매 거래마다
    묻는 값이므로, "이 매매 거래에 짝지을 전세가 있었는가"가 답해야 할 질문이다.
    """
    sale_keys = len(sales)
    return {
        "join_matching_rate": len(matched) / sale_keys if sale_keys else 0.0,
        "unmatched_sale_keys": float(sale_keys - len(matched)),
        "unmatched_jeonse_keys": float(len(jeonse) - len(matched)),
    }


def invalid_key_rate(frame: pd.DataFrame) -> float:
    """조인 키를 만들지 못한 행의 비율.

    Bronze와 Monolithic은 이 행들을 스스로 찾아 버려야 한다 — 그 단계를 짜는 것이
    RQ2가 재는 비용의 일부다.
    """
    if frame.empty:
        return 0.0
    invalid = frame[list(JOIN_KEYS)].isna().any(axis=1)
    return float(invalid.mean())


def aggregate_by_district_month(matched: pd.DataFrame) -> pd.DataFrame:
    """조인된 표를 자치구 × 월로 접는다 — 네 조건이 도달해야 하는 공통 모양.

    전세가율 자체는 여기서 내지 않는다. 그것이 분석이고, Gold가 미리 담으면
    Gold 조건이 정답을 들고 시작하는 셈이 된다 (Internal Validity).
    """
    grouped = matched.groupby(["district_code", "year_month"], as_index=False).agg(
        n_matched=("sale_price_per_m2", "count"),
        mean_sale_price_per_m2=("sale_price_per_m2", "mean"),
        mean_jeonse_deposit_per_m2=("jeonse_deposit_per_m2", "mean"),
    )
    return grouped.sort_values(["district_code", "year_month"]).reset_index(drop=True)
