# `required` 선언 규칙 (H1 측정의 전제)

H1의 여섯 지표 중 **셋이 `required` 컬럼에 대해서만 정의된다.**

| 지표 | 정의 |
|---|---|
| `missing_rate` | 결측 셀 / 셀, **required 컬럼에 대해** |
| `parsing_failure_rate` | **required** 값 중 하나라도 present-but-unreadable인 레코드 / 레코드 |
| `schema_conformance` | **required** 컬럼이 전부 존재·해석 가능·범위 내인 레코드 / 레코드 |

그래서 `required`를 무엇으로 선언하느냐가 표 2의 절반을 결정한다. 이것이
`quality_spectrum.py`에서 측정 컬럼을 손으로 고르지 않게 만든 뒤에도 남아 있던
마지막 자유도였고, 그대로 두면 데이터셋마다 다른 기준이 적용된 표가 나온다.

실제로 그런 일이 있었다. 첫 측정에서 `seoul-apartment-trades`의 `required`에는
쉼표 낀 금액 컬럼이 들어 있어 Bronze `schema_conformance`가 0.000이었고,
`general-restaurant-permits`의 `required`는 깨끗한 텍스트 세 개뿐이라 1.000이었다.
두 숫자의 차이는 데이터가 아니라 계약을 쓴 사람이 만든 것이다.

## 규칙

> **`required`는 그 레코드가 무엇에 대한 것이고 무엇을 주장하는지 말하는 데 필요한
> 최소 컬럼이다.** 세 자리로 구성된다.

| 자리 | 무엇 | 없으면 |
|---|---|---|
| **식별자** | 레코드가 가리키는 대상 | 어떤 대상의 기록인지 알 수 없다 |
| **시점** | 레코드가 기술하는 때 | 언제의 사실인지 알 수 없다 |
| **주된 사실** | 레코드가 존재하는 이유인 값 | 기록할 내용이 없다 |

세 자리를 채우면 끝이다. 더 넣지 않는다.

## `required`가 아닌 것

- **부가 속성** — 전화번호, 등급, 주변환경 구분. 없어도 레코드는 온전하다.
- **조건부 필드** — 있을 수도 없을 수도 있는 것이 정상인 값. 영업 중인 업소의
  폐업일자가 그렇다. 이런 컬럼을 `required`로 두면 정상 레코드가 부적합으로
  집계된다.
- **중복 표현** — 같은 사실을 다른 형식으로 담은 컬럼(코드와 명칭이 쌍으로 올 때
  둘 중 하나).
- **파생 편의 필드** — 다른 required 컬럼에서 계산되는 값.

## 과제를 기준으로 삼지 않는 이유

"과제가 읽어야 하는 컬럼"이 더 직관적이지만 쓸 수 없다.
`general-restaurant-permits`에는 downstream 과제가 없다 — 품질 스펙트럼의 한쪽 끝을
고정하려고 넣은 데이터셋이라 T1~T4에 들어가지 않는다. 과제 기준 규칙은 이 데이터셋에
적용할 수 없고, 적용할 수 없는 규칙은 규칙이 아니다.

레코드 구조를 기준으로 삼으면 과제가 있든 없든 같은 방식으로 적용된다.

## 적용

| Dataset | 식별자 | 시점 | 주된 사실 |
|---|---|---|---|
| `seoul-apartment-trades` | `district_code`, `apt_name` | `deal_date` | `area_m2`, `price_10k_krw` |
| `seoul-apartment-rent` | `district_code`, `apt_name` | `contract_date` | `area_m2`, `deposit_10k_krw` |
| `seoul-bike-rent-month` | `station_code` | `year_month_raw` | `use_count` |
| `general-restaurant-permits` | `permit_no`, `business_name` | `permit_date` | `business_status` |

판단이 갈릴 만한 자리를 밝혀 둔다.

**면적을 주된 사실에 넣었다** (trades, rent). 거래 레코드가 보고하는 것은 "얼마에
팔렸다"가 아니라 "이 면적이 얼마에 팔렸다"다. 면적 없는 금액은 다른 거래와 비교할 수
없으므로 레코드의 주장을 이루는 값으로 본다.

**월세는 넣지 않았다** (rent). 전세 계약에서는 0이고, 보증금이 그 레코드의 주된
사실이다.

**폐업일자는 넣지 않았다** (restaurant). 영업 중인 업소에는 없는 것이 정상이다.
표본 10,000건 중 30.0%가 비어 있는데, 이것은 결함이 아니라 3,001건이 영업 중이라는
뜻이다. 실제로 `SALS_STTS_NM`과 대조하면 불일치가 2건(0.03%)뿐이다.

**업종 무관 컬럼은 넣지 않았다** (restaurant). `FCTRY_*`, `GRNAMT` 등은
localdata가 모든 인허가 업종에 같은 스키마를 쓰기 때문에 존재하며 일반음식점에는
해당하지 않는다.

## 이 규칙이 바꾸지 않는 것

`required`는 빌더에서 **컬럼 존재 여부만** 검사한다
(`stages/silver/validate.py`의 `validate_table`). 행 값을 보지 않으므로 이 선언을
바꿔도 Silver 산출물의 바이트는 달라지지 않는다.

다만 `required`는 `kpx.pipeline.transformation_recipe`가 해시하는 변환 규칙에
포함되므로 **`config_hash`와 `pipeline_version`, 그에 따라 `build_id`가 움직인다.**
계약을 바꾼 뒤에는 provenance를 다시 등록해야 한다.

## 동결

이 규칙은 표 2를 만들기 전에 정해 두는 것이다. 측정 결과를 보고 나서 `required`를
고치면 그때부터는 규칙이 아니라 결과에 맞춘 사후 조정이 된다. 바꿔야 할 이유가
생기면 이 문서를 먼저 고치고, 왜 바꾸는지와 어떤 숫자가 움직이는지를 같이 적는다.
