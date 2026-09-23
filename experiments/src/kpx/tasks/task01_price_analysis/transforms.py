"""Task 1이 공유하는 변환 — 네 조건이 모두 여기에서 가져다 쓴다.

Baseline Bias 통제 때문에 한 곳에 둔다. monolithic baseline이 자기 나름의 정제
알고리즘을 다시 구현하면, 조건 간 차이가 "중간 산출물을 저장하는가"가 아니라
"누가 파서를 더 잘 썼는가"가 되어 버린다. 그래서 monolithic도 이 모듈을 import
한다 — 실제 일회성 스크립트보다 약간 유리해지지만, 그 편향은 우리 가설에
불리한 쪽이라 안전한 오류다.

여기 있는 함수의 본문은 어느 조건에도 LOC로 청구되지 않는다 (code_metrics의
공유 헬퍼 규칙). 조건이 달라지는 지점은 "이 중 몇 개를 호출해야 하는가"다.
"""

from __future__ import annotations

import pandas as pd

#: 만원 단위로 저장된 금액을 원으로 바꾸는 배수.
KRW_PER_10K = 10_000


def parse_price_10k(value: object) -> float | None:
    """Bronze의 금액 표현을 숫자로 읽는다.

    국토부는 거래금액을 만원 단위 문자열로 주고, 천 단위마다 쉼표를 넣는다
    (``"31,000"``). 쉼표를 지우지 않고 숫자로 바꾸면 전부 결측이 된다.
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
    """전용면적을 실수로 읽는다. Bronze에서는 문자열로 저장돼 있다."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_district_code(value: object) -> str | None:
    """시군구 코드를 5자리 문자열로 정규화한다.

    코드는 계산 대상이 아니라 식별자다. 정수로 읽으면 앞자리 0이 사라지고,
    데이터셋마다 자리수가 달라져 조인 키로 쓸 수 없게 된다.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text.zfill(5) if text else None


def to_year_month(year: object, month: object) -> str | None:
    """연/월 컬럼을 ``YYYY-MM`` 으로 합친다.

    Bronze는 거래 시점을 연·월·일 세 컬럼으로 나눠 준다. 월별 집계는 그 셋을
    합쳐야 시작할 수 있다.
    """
    if year is None or month is None:
        return None
    try:
        return f"{int(str(year).strip()):04d}-{int(str(month).strip()):02d}"
    except ValueError:
        return None


def price_per_m2(price_10k: pd.Series, area_m2: pd.Series) -> pd.Series:
    """㎡당 가격(원). 면적이 0 이하인 행은 결측으로 둔다 — 나누면 발산한다."""
    safe_area = area_m2.where(area_m2 > 0)
    return price_10k * KRW_PER_10K / safe_area


def aggregate_by_district_month(frame: pd.DataFrame) -> pd.DataFrame:
    """거래 단위 표를 자치구 × 월 집계로 접는다.

    네 조건이 도달해야 하는 공통 모양이다. Gold 조건은 이 집계를 이미 갖고
    시작하고, 나머지 셋은 여기까지 스스로 와야 한다.

    쓸 수 없는 행은 여기서 버린다. Bronze와 Monolithic은 집계 전에 직접 버리고
    — 그 단계를 짜는 것이 RQ2가 재는 비용이다 — Silver와 Gold는 그러지 않는다.
    그 차이가 결과에 남으면 조건 간 비교가 준비 과정이 아니라 정제 규칙의 차이를
    재게 된다. 그래서 버리는 일을 네 조건이 모두 통과하는 이 한 곳에 둔다.

    ``n_deals``는 ``size``가 아니라 ``count``다. 크기를 세면 값이 없는 행까지
    거래로 집계된다.
    """
    usable = frame.dropna(subset=["price_per_m2"])
    grouped = usable.groupby(["district_code", "year_month"], as_index=False).agg(
        n_deals=("price_per_m2", "count"),
        mean_price_per_m2=("price_per_m2", "mean"),
        median_price_per_m2=("price_per_m2", "median"),
    )
    return grouped.sort_values(["district_code", "year_month"]).reset_index(drop=True)
