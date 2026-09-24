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


def test_silver_keeps_its_stored_date_rather_than_being_joined_again() -> None:
    """Silver의 deal_date는 한 컬럼이다. 조각 잇기를 Silver에도 걸면 date가 문자열이
    되어 Bronze의 이은 문자열과 같아 보이고, 모든 행에서 일어난 표현 변화가 0으로 잡힌다."""
    import datetime as dt

    role = next(role for role in _roles() if role.name == "deal_date")
    silver = pd.DataFrame({"deal_date": [dt.date(2023, 1, 5)]})
    assert project(silver, (role,), layer="silver")["deal_date"].iloc[0] == dt.date(2023, 1, 5)


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


def test_only_ascii_digits_read_as_numbers_like_the_builder() -> None:
    r"""``\d``는 전각 숫자도 받는다. polars의 캐스트는 받지 않는다 — 측정이 더 관대하면
    builder가 멈출 원천을 Bronze가 읽는 것처럼 센다."""
    from kpx.metrics.roles import INTERPRETERS

    for cast in ("int", "float", "int_comma", "float_comma"):
        assert INTERPRETERS[cast]("１２") is None
        assert INTERPRETERS[cast]("12") == 12


def test_coalesce_sources_count_which_column_supplied_each_row() -> None:
    """세대가 바뀌며 이름이 바뀐 컬럼은 셀 값 변화가 아니다 — 행 단위로 따로 센다."""
    from kpx.metrics.roles import Role, coalesce_sources

    role = Role(
        name="ym_raw",
        kind="text",
        required=True,
        cast="year_month",
        projection="coalesce",
        bronze=("대여일자", "대여년월"),
        silver=("ym_raw",),
    )
    frame = pd.DataFrame(
        {"대여일자": ["2020-01", "2020-02", None, None], "대여년월": [None, None, "202301", None]}
    )
    assert coalesce_sources(frame, (role,)) == [
        {"role": "ym_raw", "source": "대여일자", "rows": 2},
        {"role": "ym_raw", "source": "대여년월", "rows": 1},
        {"role": "ym_raw", "source": None, "rows": 1},
    ]


def test_a_null_token_does_not_win_the_coalesce() -> None:
    r"""builder는 null token을 null로 바꾼 **뒤** coalesce한다. 첫 후보의 ``\N``을 값으로
    보면 두 번째 후보의 실제 값을 버리고 builder와 다른 행을 잰다."""
    from kpx.metrics.roles import Role, coalesce_sources

    role = Role(
        name="distance_m",
        kind="numeric",
        required=False,
        cast="float",
        projection="coalesce",
        bronze=("이동거리", "이동거리(M)"),
        silver=("distance_m",),
        null_tokens=("\\N",),
    )
    frame = pd.DataFrame({"이동거리": ["\\N", "\\N"], "이동거리(M)": ["2230", None]})

    projected = project(frame, (role,), layer="bronze")["distance_m"]
    # 실제 값이 있으면 그것을, 없으면 원천이 적은 표기(\N)를 그대로 둔다.
    assert list(projected) == ["2230", "\\N"]
    assert coalesce_sources(frame, (role,)) == [
        {"role": "distance_m", "source": "이동거리(M)", "rows": 1},
        {"role": "distance_m", "source": None, "rows": 1},
    ]
