# RQ1 전이 원인 분류 규칙

RQ1의 primary 표(`rq1_role_transition`)는 role마다 셀이 **왜** 바뀌었는지를 센다. 원인은
아래 규칙으로 기계적으로 붙이고, 사람이 셀이나 role을 골라 분류하지 않는다. 구현은
`kpx.metrics.pairing.pair_and_classify`다.

## 언제, 어떻게 정했는가

- 이 규칙은 **분류를 실행하기 전에** 사전 등록 문서(`overnight/rq1-transition/PRE_ANALYSIS.md`
  11절, 2026-09-24 02:24)에 고정했다. 그 문서를 따르는 분류 스크립트는 03:03에, 첫 결과는
  03:05에 만들어졌다. 사전 등록 문서 자체는 작업용 기록이라 저장소에 올리지 않고, 규칙만 이
  문서로 옮겼다.
- 결과를 본 뒤 **범주 정의를 바꾸지 않았다.** 이후 측정 코드의 날짜 투영 버그를 고쳐 다시
  돌렸을 때도 규칙은 그대로였고, 규칙 4(`derived_field`)가 실제로 적용되기 시작했을 뿐이다.
- 하네스 구현(`pair_and_classify`)은 사전 등록 스크립트와 별개로 다시 작성했다. 서울 3종 전수에서
  role × 원인 60칸이 사전 등록 스크립트의 결과와 **모두 같았다** (불일치 0).

## 입력

셀 하나마다:

- Bronze token `bt = (btype, bval)`, Silver token `st = (stype, sval)` — 타입을 보존한 저장
  표현 (`kpx.metrics.pairing.token`)
- role 선언 — `cast`, `zfill`, `projection`, `null_tokens`
- 두 값의 canonical 해석 `cb`, `cs` — 계약이 선언한 해석으로 읽은 값
  (`kpx.metrics.pairing._canonicaliser`)

## 규칙 (위에서부터, 처음 맞는 것 하나)

| # | 조건 | 원인 |
|---|---|---|
| 1 | `bt == st` | `unchanged` |
| 2 | `cb` 또는 `cs`를 읽을 수 없다 | `unreadable_lossy` |
| 3 | `cb != cs` (뜻이 다르다) | `other:semantic_difference` |
| 4 | `projection == "parts"` (조각에서 조립) | `derived_field` |
| 5 | `stype`이 null이고 Bronze가 문자열이며 `bval.strip()`이 선언된 null token | `null_canonicalization` |
| 6 | `cast == "year_month"`, 또는 cast 없는 date role | `date_year_month_normalization` |
| 7 | `zfill` 선언, 양쪽 문자열, `sval == bval.strip().zfill(n)` | `identifier_padding` |
| 8 | cast가 숫자 계열(`int`/`int64`/`float`/`float64`/`int_comma`/`float_comma`): Bronze가 `","`를 포함한 문자열이면 | `numeric_formatting` |
|   | 그 밖의 숫자 cast | `primitive_type_normalization` |
| 9 | cast 없음, Bronze가 int/float이고 Silver가 문자열 (`read_as`) | `primitive_type_normalization` |
| 10 | 그 외 | `other` |

규칙 5와 7의 `strip()`은 사전 등록된 그대로다. 측정한 스냅샷에서 이 `strip()`에 걸리는 값은
없다.

## 셀 원인이 아닌 것: 구조적 전이

컬럼 이름 변경(`rename`)과 세대별 헤더 수렴(`coalesce`)은 값을 바꾸지 않으므로 **셀 원인이
될 수 없다.** 그래서 셀 분모에 넣지 않고 따로 적는다.

- `rq1_role_transition`의 `structural` 열 — role마다 `same_name` / `rename` / `coalesce` /
  `derived`
- `rq1_coalesce_source` — coalesce role마다 **어느 원천 컬럼이 값을 댔는가를 행 단위로**.
  빌더처럼 null token은 값으로 치지 않는다.

## 불변식

- role마다 원인별 셀 수의 합 = 그 role의 행 수
- `unchanged`를 뺀 합 = `rq1_role_pair.representation_changed_count`

둘 다 `tests/test_pairing.py`가 고정한다.
