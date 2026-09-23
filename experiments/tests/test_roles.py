"""role 투영이 두 계층을 같은 것 위에 세우는가."""

from __future__ import annotations

import pandas as pd
import pytest

from kpx.metrics.roles import RoleError, assert_symmetric, interpreter_for, plan_roles, project

CONTRACT = {
    "rename": {"dealAmount": "price_10k_krw", "sggCd": "district_code"},
    "coalesce": {"ym_raw": ("대여일자", "대여년월")},
    "casts": {
        "price_10k_krw": "int_comma",
        "ym_raw": "year_month",
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
    "required": ("price_10k_krw", "ym_raw", "deal_date"),
}


def _roles():
    return plan_roles(CONTRACT)


def test_every_required_column_becomes_a_role() -> None:
    """예전 계획은 coalesce와 derived를 몰라 required를 조용히 잃었다."""
    required = {role.name for role in _roles() if role.required}
    assert required == {"price_10k_krw", "ym_raw", "deal_date"}


def test_a_required_column_with_no_source_is_an_error() -> None:
    contract = dict(CONTRACT, required=("price_10k_krw", "nowhere"))
    with pytest.raises(RoleError, match="nowhere"):
        plan_roles(contract)


def test_projection_gives_both_layers_the_same_columns() -> None:
    roles = _roles()
    bronze = pd.DataFrame(
        {
            "dealAmount": ["120,000"],
            "sggCd": ["11110"],
            "대여일자": [None],
            "대여년월": ["202207"],
            "deal_year": ["2023"],
            "deal_month": ["1"],
            "deal_day": ["5"],
        }
    )
    silver = pd.DataFrame(
        {
            "price_10k_krw": [120000],
            "district_code": ["11110"],
            "ym_raw": ["2022-07"],
            "deal_date": ["2023-01-05"],
            "deal_year": [2023],
            "deal_month": [1],
            "deal_day": [5],
        }
    )
    b, s = project(bronze, roles, layer="bronze"), project(silver, roles, layer="silver")
    assert_symmetric(b, s, roles)
    # coalesce는 값이 있는 후보를 고른다.
    assert b["ym_raw"].iloc[0] == "202207"
    # parts는 저장된 조각을 그대로 잇는다 — 폭만 맞추고 검증하지 않는다.
    assert b["deal_date"].iloc[0] == "2023-01-05"


def test_a_role_no_column_can_produce_stops_the_measurement() -> None:
    """빠뜨리면 두 계층의 분모가 달라지고 표는 그대로 찍힌다."""
    roles = _roles()
    bronze = pd.DataFrame(
        {
            "dealAmount": ["1"],
            "sggCd": ["11110"],
            "deal_year": ["2023"],
            "deal_month": ["1"],
            "deal_day": ["5"],
        }
    )
    with pytest.raises(RoleError, match="ym_raw"):
        project(bronze, roles, layer="bronze")


def test_the_declared_cast_reads_what_the_pipeline_reads() -> None:
    """``pd.to_numeric('120,000')``이 실패하는 것은 데이터가 아니라 읽는 쪽 문제다."""
    price = next(role for role in _roles() if role.name == "price_10k_krw")
    assert interpreter_for(price)("120,000") == 120000.0
    month = next(role for role in _roles() if role.name == "ym_raw")
    assert interpreter_for(month)("202207") == "2022-07"
    assert interpreter_for(month)("2022-07") == "2022-07"
    assert interpreter_for(month)("2022-13") is None
