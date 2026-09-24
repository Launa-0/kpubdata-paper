"""표준화가 무엇을 바꿨고, 바꾸면서 뜻을 지켰는가."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from kpx.metrics.pairing import aggregate, assert_row_identity, pair_roles, token
from kpx.metrics.roles import Role

PRICE = Role(
    name="price_10k_krw",
    kind="numeric",
    required=True,
    cast="int_comma",
    projection="direct",
    bronze=("dealAmount",),
    silver=("price_10k_krw",),
)
STATION = Role(
    name="station_code",
    kind="text",
    required=True,
    cast="",
    projection="direct",
    bronze=("대여소번호",),
    silver=("station_code",),
    null_tokens=("\\N",),
    zfill=5,
)


def _pair(role, bronze_values, silver_values):
    bronze = pd.DataFrame({role.name: bronze_values})
    silver = pd.DataFrame({role.name: silver_values})
    return pair_roles(bronze, silver, (role,))[0]


def test_a_typed_token_separates_the_string_from_the_number() -> None:
    """str()로 비교하면 '1'과 1이 같아져 표준화가 한 일이 통째로 사라진다."""
    assert token("1") != token(1)
    assert token(None) != token("None")
    assert token(120000) != token(120000.0)


def test_a_cast_counts_as_a_representation_change() -> None:
    pair = _pair(PRICE, ["120,000"], [120000])
    assert pair.representation_changed_count == 1
    assert pair.semantic_preservation_rate == 1.0


def test_a_cast_that_preserves_meaning_is_not_a_semantic_change() -> None:
    """양쪽에 같은 canonicalizer를 주지 않으면 zfill이 의미 변화로 잘못 잡힌다."""
    pair = _pair(STATION, ["3"], ["00003"])
    assert pair.representation_changed_count == 1
    assert pair.semantic_preservation_rate == 1.0


def test_a_declared_null_token_means_absent_on_both_sides() -> None:
    pair = _pair(STATION, ["\\N"], [None])
    assert pair.semantic_comparable_count == 1
    assert pair.semantic_preservation_rate == 1.0


def test_an_unreadable_value_is_uncovered_not_preserved() -> None:
    """읽히지 않는 값을 '양쪽 다 None이니 보존'으로 세면 오염이 지표를 올린다."""
    pair = _pair(PRICE, ["열두개"], [None])
    assert pair.semantic_comparable_count == 0
    assert pair.semantic_coverage_rate == 0.0
    assert pair.semantic_preservation_rate is None


def test_a_real_meaning_change_is_caught() -> None:
    pair = _pair(PRICE, ["120,000"], [999])
    assert pair.semantic_comparable_count == 1
    assert pair.semantic_preserved_count == 0


def test_aggregation_weights_by_count_rather_than_by_role() -> None:
    """role별 rate의 단순 평균은 큰 role과 작은 role에 같은 표를 준다."""
    pairs = pair_roles(
        pd.DataFrame({"price_10k_krw": ["1", "2", "3", "4"], "station_code": ["3"] * 4}),
        pd.DataFrame({"price_10k_krw": [1, 2, 3, 4], "station_code": ["3"] * 4}),
        (PRICE, STATION),
    )
    total = aggregate(pairs)
    assert total["cells"] == 8
    assert total["representation_changed_count"] == 4
    assert total["representation_change_rate"] == 0.5
    assert total["semantic_preservation_rate"] == 1.0


def test_required_scope_is_a_filter_not_a_second_measurement() -> None:
    """all과 required를 따로 저장하지 않는다 — 같은 raw에서 걸러 낸다."""
    optional = replace(STATION, required=False)
    pairs = pair_roles(
        pd.DataFrame({"price_10k_krw": ["1"], "station_code": ["3"]}),
        pd.DataFrame({"price_10k_krw": [1], "station_code": ["3"]}),
        (PRICE, optional),
    )
    assert aggregate(pairs)["roles"] == 2
    assert aggregate(pairs, required_only=True)["roles"] == 1


def test_rows_in_the_same_order_pass_the_identity_check() -> None:
    bronze = pd.DataFrame({"price_10k_krw": ["1", "2"], "station_code": ["3", "4"]})
    silver = pd.DataFrame({"price_10k_krw": [1, 2], "station_code": ["00003", "00004"]})
    assert_row_identity(bronze, silver, (PRICE, STATION))


def test_equal_length_is_not_the_same_rows() -> None:
    """길이만 맞추면 뒤섞인 행끼리 짝지어도 통과한다 — 순서를 직접 확인한다."""
    bronze = pd.DataFrame({"price_10k_krw": ["1", "2"], "station_code": ["3", "4"]})
    silver = pd.DataFrame({"price_10k_krw": [2, 1], "station_code": ["00004", "00003"]})
    with pytest.raises(ValueError, match="2 of 2 rows"):
        assert_row_identity(bronze, silver, (PRICE, STATION))


def test_the_identity_check_needs_a_required_role() -> None:
    optional = replace(STATION, required=False)
    frame = pd.DataFrame({"station_code": ["3"]})
    with pytest.raises(ValueError, match="no required role"):
        assert_row_identity(frame, frame, (optional,))


def test_an_unreadable_key_does_not_count_as_the_same_row() -> None:
    bronze = pd.DataFrame({"price_10k_krw": ["열두개"]})
    silver = pd.DataFrame({"price_10k_krw": ["열두개"]})
    with pytest.raises(ValueError, match="1 of 1 rows"):
        assert_row_identity(bronze, silver, (PRICE,))


def test_a_mixed_column_keeps_each_value_s_own_type() -> None:
    """factorize는 1, 1.0, True를 한 값으로 묶는다(hash가 같다). 고유값 단위로
    파싱하다 보면 처음 본 표기가 나머지 행의 표기가 되어, 한 컬럼 안의 int/float
    혼재가 표현 변화에서 사라진다."""
    role = replace(PRICE, cast="int")
    pair = _pair(role, pd.Series([1, 1.0, True], dtype=object), [1, 1, 1])
    # 1 -> 1 은 그대로, 1.0 -> 1 과 True -> 1 은 표기가 바뀌었다.
    assert pair.representation_changed_count == 2
    # 1.0은 builder의 int 캐스트가 읽지 못한다 — 같은 1이라고 세면 안 된다.
    assert pair.semantic_comparable_count < 3


def test_a_null_token_is_matched_as_written_like_the_builder_does() -> None:
    r"""builder는 ``is_in``으로 정확히 맞춘다. 공백 붙은 ``\N``은 결측이 아니라 값이다."""
    assert _pair(STATION, [" \\N"], [" \\N"]).semantic_preserved_count == 1
    # builder라면 " \N"을 null로 만들지 않는다. Silver가 null이면 뜻이 바뀐 것이다.
    assert _pair(STATION, [" \\N"], [None]).semantic_preserved_count == 0


def test_zfill_pads_the_value_as_stored_like_the_builder_does() -> None:
    """builder는 zfill 전에 공백을 지우지 않는다 — ``" 3"``은 ``"000 3"``이 된다."""
    assert _pair(STATION, [" 3"], ["000 3"]).semantic_preserved_count == 1
    assert _pair(STATION, [" 3"], ["00003"]).semantic_preserved_count == 0


# -- 전이 원인 (overnight/rq1-transition/PRE_ANALYSIS.md 11절, 결과 보기 전 고정) --------


def _causes(role, bronze_values, silver_values):
    from kpx.metrics.pairing import pair_and_classify

    bronze = pd.DataFrame({role.name: pd.Series(bronze_values, dtype=object)})
    silver = pd.DataFrame({role.name: pd.Series(silver_values, dtype=object)})
    pairs, transitions = pair_and_classify(bronze, silver, (role,))
    return pairs[0], {row["category"]: row["cells"] for row in transitions}


GENDER = Role(
    name="gender",
    kind="text",
    required=False,
    cast="",
    projection="direct",
    bronze=("성별",),
    silver=("gender",),
    null_tokens=("\\N", ""),
)
YM = Role(
    name="ym_raw",
    kind="text",
    required=True,
    cast="year_month",
    projection="coalesce",
    bronze=("대여일자", "대여년월"),
    silver=("ym_raw",),
)
DISTRICT = Role(
    name="district_code",
    kind="text",
    required=True,
    cast="",
    projection="direct",
    bronze=("sggCd",),
    silver=("district_code",),
)
DEAL_DATE = Role(
    name="deal_date",
    kind="date",
    required=True,
    cast="",
    projection="parts",
    bronze=("dealYear", "dealMonth", "dealDay"),
    silver=("deal_date",),
)


def test_each_cause_is_named_by_the_pre_registered_rule() -> None:
    import datetime as dt

    assert _causes(PRICE, ["120,000"], [120000])[1] == {"numeric_formatting": 1}
    assert _causes(PRICE, ["120000"], [120000])[1] == {"primitive_type_normalization": 1}
    assert _causes(PRICE, [120000], [120000])[1] == {"unchanged": 1}
    assert _causes(STATION, ["3"], ["00003"])[1] == {"identifier_padding": 1}
    assert _causes(GENDER, ["\\N", "", "F"], [None, None, "F"])[1] == {
        "null_canonicalization": 2,
        "unchanged": 1,
    }
    assert _causes(YM, ["202207"], ["2022-07"])[1] == {"date_year_month_normalization": 1}
    assert _causes(DISTRICT, [11110], ["11110"])[1] == {"primitive_type_normalization": 1}
    assert _causes(DEAL_DATE, ["2023-01-05"], [dt.date(2023, 1, 5)])[1] == {"derived_field": 1}


def test_a_meaning_change_and_an_unreadable_value_are_not_hidden_as_causes() -> None:
    assert _causes(PRICE, ["120,000"], [12])[1] == {"other:semantic_difference": 1}
    assert _causes(PRICE, ["n/a"], [None])[1] == {"unreadable_lossy": 1}


def test_causes_partition_the_cells_and_agree_with_the_change_count() -> None:
    pair, causes = _causes(STATION, ["3", "00003", "\\N", "102"], ["00003", "00003", None, "00102"])
    assert sum(causes.values()) == pair.rows
    assert pair.rows - causes.get("unchanged", 0) == pair.representation_changed_count


def test_structure_is_a_role_attribute_not_a_cell_cause() -> None:
    """coalesce·rename은 셀 값을 바꾸지 않는다 — 셀 범주의 분모에 섞지 않는다."""
    from kpx.metrics.pairing import pair_and_classify

    bronze = pd.DataFrame({"ym_raw": ["2022-07"]})
    silver = pd.DataFrame({"ym_raw": ["2022-07"]})
    _, transitions = pair_and_classify(bronze, silver, (YM,))
    assert {row["structural"] for row in transitions} == {"coalesce"}
    assert {row["category"] for row in transitions} == {"unchanged"}
