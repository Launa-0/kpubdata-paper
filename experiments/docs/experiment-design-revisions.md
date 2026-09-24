# 실험 설계 개정 기록

`statistics.md`, `monolithic-baseline.md`, `user-study-exclusion.md`가 각각 하나의
결정을 설명한다면, 이 문서는 **무엇이 바뀌었고 왜 바뀌었는지**를 한자리에 모은다.

이 문서가 필요한 이유는 하나다. 이슈와 PR 본문에는 원안이 그대로 남아 있고, 그것만
보고 작업하면 이미 폐기한 결과가 논문으로 되돌아온다 — `duplicate_rate`를 다시
Figure 3에 넣거나, 아파트 R2의 33%를 인용하는 식으로. **이슈를 고쳐 원안을 지우지
않는다.** 원안과 최종안의 차이가 보이는 편이 낫고, 그 차이를 읽는 자리가 여기다.

기록의 기준도 하나다. **"결과가 마음에 들지 않아서 바꿨다"는 개정 사유가 아니다.**
각 항목은 발견한 construct validity 결함을 먼저 적고, 그 결함이 수정을 강제했음을
보인다. RQ1은 git history에 중간 단계가 전부 남아 있으므로 더더욱 그렇게 적는다.

## 이 문서와 다른 문서의 역할

- **이 문서 = 변경 이력의 SSOT.** 원래 설계를 지우지 않는다. 바뀐 것은 아래에 누적한다.
- **README, 코드 docstring, `runner-contract.md`, `monolithic-baseline.md` 등 = 현재 상태.**
  현재 유효한 설계만 담는다. 옛 설계를 그 파일들에 남기면 서로 모순되므로, "왜 바뀌었는가"는
  이 문서에서만 보존한다.

개정 하나는 다음 형식으로 적는다.

```markdown
### <영역> — <원래> → <현재>

**원래 설계** / **문제 발견** / **확인 근거** / **수정한 설계** / **영향**
```

**원칙: 설계를 바꾸는 코드 변경은 이 문서 갱신과 같은 커밋에 넣는다.**

**잠금 (2026-09-24):** 이 개정 이후로는 **새 correctness 버그가 발견되지 않는 한 방법론
문구를 고치지 않는다.** 나머지 동기화는 아래 "동결 전 일괄 동기화"에서 한 번에 한다.

## 현재 작업 설계 — protocol freeze 전

**아직 동결하지 않았다.** 아래는 지금까지의 결정이고, 최종 timing 프로토콜과
`results/` 재생성은 동결 뒤에 한다.

| 축 | 실험 |
|---|---|
| Data standardization (RQ1) | 3개 데이터셋 Bronze -> Silver. **role × 전이 원인 셀 수가 primary** (`rq1_role_transition`, 원인은 결과 확인 전 사전 정의한 규칙 — `rq1-transition-classification.md`). 세대별 헤더 변화는 셀이 아니라 행 단위로 따로 (`rq1_coalesce_source`). aggregate change rate는 진단 |
| Analytical preparation (RQ2) | T1 단일 데이터셋 집계·추세 |
| Cross-dataset interoperability (RQ2) | T3 trades + rent join, 네 조건 |
| Equivalence gate | 네 조건이 같은 분석 결과(`output_hash`)에 도달해야 RQ2 비용을 비교한다. Bronze ↔ Silver는 독립 검증, Silver ↔ Gold와 Bronze ↔ Monolithic은 구성상 동등 |
| Recomputation / timing (RQ2) | T1·T3, 같은 엔진·포맷 통제, S1–S4 분리, raw 반복 저장, 조건 interleave — **재측정 예정** |
| Frozen-source determinism | R1 — 기존 구현. 이번 구현 감사에서 재검증하지 않았다 — protocol freeze 전 재검증 예정 |
| Source evolution | 따릉이 G1 / G2 / I1 / G3 / G4 |
| Contract boundary | 통제된 perturbation (선언 부족 / 표현력 한계 / 구현 결함으로 분류) |
| Storage trade-off | observed on-disk footprint + same-format controlled 비교 (반영 범위 검토 중) |
| External validation | T3 공개 통계 대조는 **미실행**. 모집단·정의가 달라 primary에서 제외, 보조 방향 비교로 쓸지 미정 |

따릉이는 RQ1(전이)과 원천 진화·계약 경계 실험의 핵심 데이터셋으로 남는다. 별도
downstream task인 T4는 두지 않는다.

RQ2는 preparation code volume·complexity와 execution cost를 본다 (`analytical
effort`가 아니다 — #54). RQ3는 correctness 우열이 아니라 analytical consistency를
보는 equivalence gate다.

## 개정 목록 (색인)

| 영역 | 기존 설계 | 확인된 문제 | 수정된 설계 | 결과 영향 | 상세 |
|---|---|---|---|---|---|
| RQ1 quality | Bronze/Silver에 동일 metric 적용 | Bronze reader 비대칭 — 측정이 Bronze에만 계약 파서를 주지 않았다 | 양쪽에 같은 해석 능력 + Bronze를 semantic/naive 두 view로 | **기존 RQ1 결과 폐기·재측정** | R-1 |
| RQ1 비교 단위 | `Bronze 컬럼 -> Silver 컬럼` 매핑 | `coalesce`/`derived`를 표현 못 해 role을 조용히 누락, 두 계층이 다른 분모 | semantic role + 계층별 projection | required 2->3 / 4->5 교정 | R-1 |
| RQ1 duplicate | H1 primary | 저장 표현 위의 exact-row equality라 canonicalization이 값을 **올린다** | diagnostic으로 강등, 표시 분리 | 결과값은 스키마에 보존 | R-1 |
| RQ1 headline | aggregate `representation_change_rate` | 계약의 `read_as` 컬럼을 role에 넣느냐에 따라 trades 0.238 ↔ 0.450, rent 0.225 ↔ 0.413 — 원천의 성질이 아니라 role 정의의 함수 | role × 전이 원인 표를 primary로, aggregate는 진단. coverage/preservation은 integrity check | 수치 불변, 표시 변경 | R-1 |
| RQ1 측정 파서 | builder와 같다고 가정 | builder 실제 함수와 대조하니 null token·zfill 앞 공백 제거, 전각 숫자, `factorize`의 `1`/`1.0`/`True` 병합, coalesce의 null token 처리가 달랐다 | builder 동작에 맞춤 | 서울 3종 해당 값 0 — **결과 불변** | R-1 |
| RQ2 runtime | 5회 -> median + paired inference | parquet에 median 1개만 저장되고 deterministic task는 seed 하나 — **n=1** | 1차: 기술통계만. 2차(번복): 같은 엔진·포맷 통제 재측정 | 기존 timing 수치 폐기 예정 | R-2 |
| RQ3 | 정제 계층이 correctness를 향상 | 네 조건이 같은 transform semantics를 공유하도록 **의도적으로** 통제됨 | equivalence gate (독립 / 구성상 동등 구분) | 코드 유지, 질문만 수정 | R-3 |
| R2 | apartment 기간 분할 + `Null->String` | 전 기간 null이라 추론된 `Null`이 값이 생겨 `String`이 된 것은 semantic break가 아님 | 따릉이 G1/G2/I1/G3/G4 fixed-contract 실험 | **기존 33% 결과 폐기** | R-4 |
| Task3 jeonse | null monthly rent를 0으로 취급 | "생략된 0"이라는 계약 근거 없음 | `eq(0)`만 전세, 결측은 unknown | 현 데이터 null 0건이라 **결과 불변** | R-5 |
| Storage | storage amplification | Bronze JSONL vs Silver/Gold Parquet — layering이 아니라 codec을 잰다 | observed on-disk footprint (+ 통제 비교 검토) | 수치 유지, 해석 축소 | R-6 |
| Task scope | T1–T4 모두 full task | T2/T4 prediction 미구현 + 방법론 면적이 큼 | 1차: T1 / T3 + 축소 T4. 2차(번복): T4도 제외 | scope 변경 | R-7 |
| Provenance | 이름 규칙·glob으로 artifact 해결 | 폐기 artifact를 조용히 측정할 수 있었음. 체크섬만으로 builder를 구분 못 함. Gold를 mtime으로 재사용 | snapshot / config / checksum / builder identity binding, Gold 매번 재빌드, 두 원천 합성 식별자 | 결과 불변 | R-8 |

---

## 개정 상세

### R-1. RQ1 — 품질 개선 가설 → 표현 전이 측정

**원래 설계**

- Bronze → Silver에서 type consistency, parsing failure, schema conformance, missing,
  duplicate, code validity의 **개선**을 측정한다 (표 2).
- H1: Silver가 Bronze보다 데이터 품질이 높다. 원래 표 2는 이렇게 읽혔다.

```
seoul-apartment-trades   parsing_failure  1.000 -> 0.000   schema_conformance  0.000 -> 1.000
  seoul-apartment-rent   parsing_failure  0.988 -> 0.000   schema_conformance  0.012 -> 1.000
```

- 비교 단위는 `rename`/`casts`로 맞춘 `Bronze 컬럼 -> Silver 컬럼`. `duplicate_rate`도
  primary.

**문제 발견**

1. **Bronze reader 비대칭.** `quality.py`는 "Bronze도 파이프라인의 해석을 받는다"고
   적어 두고, `quality_spectrum.py`는 정반대로 재고 있었다. `pd.to_numeric("120,000")`은
   실패하지만 빌드는 그 값을 읽는다. 위 숫자는 데이터가 아니라 **reader에게 얼마나
   적대적이라고 시켰는지**를 잰 값이다.
2. **비교 단위.** `rename`/`casts`만 보고 컬럼을 맞추면 `ym_raw`(`대여일자` **또는**
   `대여년월`)와 `deal_date`(세 조각 조립)를 표현할 수 없다. 못 찾은 role은 Bronze
   쪽에서만 빠지고 Silver 쪽에는 남아 **두 계층이 다른 분모 위에서 측정됐다.**
3. **비교 지표는 구조적으로 평평하다.** 빌더는 선언된 cast가 값을 null로 떨어뜨리면
   빌드를 세운다(#188). 빌드가 성공했다는 것은 Bronze를 계약 파서로 읽어도 실패가 없다는
   뜻이므로, 성공한 빌드에서 Bronze(semantic)과 Silver는 이 지표로 달라질 수 없다.
4. **`duplicate_rate`는 저장 표현 위의 exact-row equality**라 canonicalization이 값을
   올린다 (결측 성별 `\N`과 `""`가 Silver에서 같아진다).
5. **aggregate change rate는 role 정의의 함수다.** `read_as`만 받는 컬럼을 role에 넣으면
   trades 0.238 → 0.450, rent 0.225 → 0.413. 원천의 고유 성질이 아니다. 또 `projection`
   (direct/coalesce/parts)은 값이 **왜** 바뀌었는지를 말하지 않는다.
6. **측정 파서가 빌더와 달랐던 곳들.** Silver 날짜를 문자열로 다시 조립해 변화를 0으로
   셌다. builder 실제 함수에 edge case를 넣어 대조하니 null token·zfill 앞 공백 제거, 전각
   숫자 허용, `factorize`의 `1`/`1.0`/`True` 병합이 달랐고, coalesce가 null token을 값으로
   보고 있었다.

**확인 근거**

- 양쪽에 같은 해석 능력을 주고 같은 role 위에서 다시 재면 비교 지표가 전부 평평하다.

```
               Dataset  Roles  Required type_consistency   missing_rate schema_conformance parsing_failure_rate
seoul-apartment-trades     21         5   1.000 -> 1.000 0.000 -> 0.000     1.000 -> 1.000       0.000 -> 0.000
  seoul-apartment-rent     18         5   1.000 -> 1.000 0.000 -> 0.000     1.000 -> 1.000       0.000 -> 0.000
 seoul-bike-rent-month     11         3   1.000 -> 1.000 0.000 -> 0.000     1.000 -> 1.000       0.000 -> 0.000
```

- null token·role projection·날짜 투영을 고친 뒤에도 같다. 파서 불일치들이 걸리는 값은
  서울 3종에 0이고, 고친 코드로 재측정한 role 표는 이전과 한 행도 다르지 않다.
- T1·T3의 분석 결과도 독립 구현(harness 파서 vs builder cast) 사이에서 일치한다.
- role별 변경 수는 raw JSON 타입 수와 정확히 맞는다 (예: rent `monthly_rent` 52,294 =
  JSON 문자열 52,294; bike `gender` 1,981,081 = `""` 1,040,784 + `\N` 940,297).
- 결과 확인 전 사전 정의한 규칙으로 분류한 전이 원인은 독립된 두 구현(사전 정의 문서를 따른 스크립트, 하네스)이 role ×
  원인 60칸 전부 같았다.

**수정한 설계**

- 품질 improvement를 primary에서 제외한다. 비교 지표는 integrity check.
- **role × 전이 원인 셀 수를 RQ1 primary로** (`rq1_role_transition`). 원인은 결과 보기 전에
  고정한 규칙(`rq1-transition-classification.md`)으로 붙인다.
- 세대별 헤더 수렴(coalesce)은 셀 분모에 넣지 않고 행 단위로 따로 센다
  (`rq1_coalesce_source`).
- aggregate change rate는 진단, coverage/preservation은 integrity check. required role의
  preservation은 row identity guard 때문에 1.0이 전제된다.
- Bronze naive는 계약이 설정하지 않은 reader의 **sensitivity view**로만 쓴다. 데이터 품질
  baseline도, 분석자 노력의 측정도 아니다.
- 비교 단위는 semantic role + 계층별 projection (`direct` / `coalesce` / `parts`).
  `duplicate_rate`는 diagnostic으로 강등하고 표시를 분리한다 (스키마에는 보존).

**당시 미해결로 남긴 것과 그 처리**

- (당시 기록) naive/semantic 격차가 화면에만 찍히고 결과 artifact에 저장되지 않았다.
  `ResultRow`는 task-condition run 중심이라 RQ1 전용 측정 테이블을 따로 두는 쪽이 맞을 수
  있으니, 최종 metric 집합을 확정한 뒤 한 번에 저장한다고 적었다.
- (처리) RQ1 전용 테이블로 해결했다 — `rq1_layer_quality`가 naive / semantic / Silver 세
  view를, `rq1_role_pair`·`rq1_role_transition`·`rq1_coalesce_source`가 role 단위 측정을
  저장한다.

**영향**

- 기존 H1의 방향성 주장("Silver가 품질을 높인다")은 폐기한다.
- 데이터셋과 Builder 산출물은 바뀌지 않는다. RQ1 결과표와 해석만 바뀐다.
- required role 수가 2→3 (따릉이), 4→5 (실거래가·전월세)로 교정됐다.

### R-2. RQ2 runtime — 검정 → 기술통계 → 통제 재측정

**원래 설계**

- warm-up 1 + 측정 5회, median + seed로 짝지은 paired inference.

**문제 발견**

1. `runner.py`는 median 하나만 `ResultRow.runtime_seconds`에 남긴다. `stats.py`는 `seed`로
   pair하는데 T1/T3는 deterministic이라 seed가 하나다. 즉 runtime의 paired observation은
   **n = 1**이다. "5회 측정했으니 n=5"는 성립하지 않는다.
2. (2차) 통제 pilot에서 기존 timing이 JSONL vs Parquet, pandas vs polars, builder 부기 비용과
   섞여 있었다. S1 이득과 S3/S4 손해가 **양방향으로 과장**됐다.

**확인 근거**

- (1차) raw 5회를 보존해 repeat index끼리 pair하는 길도 있었지만, 그러면 조건 실행 순서의
  temporal bias를 없애기 위해 interleave/randomize까지 가야 해서 당시에는 과하다고 봤다.
- (2차) monolithic 시간의 약 89%가 pandas JSONL 파싱이었다. 같은 엔진·포맷으로 재면 S1 약
  420배 → 약 3–40배, S3/S4 "medallion 7–8배 느림" → 1.0–1.4배, break-even 5–9 → 1–3.

**수정한 설계**

- 1차: preprocessing LOC / function count를 primary로 두고 runtime과 peak memory는
  기술통계로만. **runtime p-value는 내지 않는다** (이 결정은 유지).
- 2차 (1차의 "재실행 불필요"를 **번복**): 최종 timing은 T1·T3, 같은 엔진·포맷 통제, S1–S4
  분리, raw 반복 저장, 조건 interleave로 다시 잰다.

**영향**

- 기존 timing 수치(0.024s vs 10.1s, 56–69s vs 8s, N* 5–9)는 폐기 예정. 방향만 참고한다.

### R-3. RQ3 — correctness 향상 → equivalence gate

**원래 설계**

- 정제 계층이 분석 correctness를 향상시킨다. Bronze/Silver/Gold는 서로 다른 품질의 계층을
  읽으므로 **서로 달라도 되고, 그 차이가 RQ3의 signal**이다. monolithic만 동등성 검사를
  받는다. 외부 공개 통계는 validation으로 대조한다.

**문제 발견**

- T3(#56)는 Bronze/Silver/Gold/Monolithic이 `normalize_apt_name` 등 **같은 transform
  semantics**를 쓰게 하고, `join_matching_rate`가 설계상 같아야 한다고 테스트한다. 이 통제
  자체는 옳다 — Bronze에만 나쁜 정제를 주면 baseline bias다. T1도 같은 helper와 downstream
  analysis를 공유한다. 그러면 "정제 계층이 오류를 줄인다"는 이 설계로 검증할 수 없고, 네
  조건이 같은 값을 내는 것은 상당 부분 **설계상 기대되는 결과**다.
- 외부 참조 통계는 표본 조사 가격이고 T3는 매칭된 실거래 key의 ㎡당 평균이라 모집단·가중·
  정의가 다르다. 대조는 한 번도 실행되지 않았다.

**확인 근거**

- T1: 네 조건 `output_hash` 동일. T3: Silver 러너의 단지명 정규화 누락을 고친 뒤 네 조건
  `output_hash` 동일(`607132358d10…`), 매칭률 동일.
- 전세가율 정의(key/거래 가중, ratio of means/mean of ratios)만 바꿔도 headline이 3.6%p
  움직인다 — 외부 통계와의 수준 비교는 정의 선택을 재게 된다.

**수정한 설계**

- 질문을 바꾼다: *계층화된 materialization이 downstream 분석 결과를 바꾸지 않고
  보존하는가?* 이것은 RQ2 비용을 비교하기 위한 **equivalence gate**다.
- 일치의 무게를 나눠 적는다. Bronze ↔ Silver는 서로 다른 구현이 같은 값에 도달한 **독립
  검증**이다. Silver ↔ Gold(같은 집계 함수)와 Bronze ↔ Monolithic(같은 helper·순서)은
  **구성상 기대되는 동등**이다.
- 외부 참조는 primary validation에서 뺀다. 추세 방향의 보조 비교로 쓸지는 참조 정의를
  확인한 뒤 정한다. ground truth라 부르지 않는다.

**영향**

- 코드는 유지하고 질문과 문구를 고쳤다. "계층마다 결과가 달라도 된다"는 옛 설명은 README,
  `baseline.py`, `monolithic-baseline.md`, `runner-contract.md`에서 현재 설계로 바꿨다.

### R-4. R2 — 아파트 기간 분할 → 따릉이 세대 실험

**원래 설계**

- 아파트 스냅샷을 기간으로 잘라 스키마 호환성을 재고, `Null -> String` 변화를 break로 센다
  (schema compatibility 33%).

**문제 발견**

- `stability.py`는 참조 스키마와 dtype이 다르면 break로 센다. 아파트 스냅샷에서는 과거
  기간에 값이 전부 없어 Polars가 `Null`로 추론한 컬럼이 나중에 값이 생겨 `String`이
  됐다. 이것은 semantic break가 아니라 **"값이 없어 타입을 추론할 수 없었다 -> 값이 생겨
  실제 타입이 드러났다"**에 가깝다.

**확인 근거**

- 따릉이 G1/G2/I1/G3는 실제 표현 진화이고, 같은 고정 계약과 같은 `config_hash`를 쓰며, G4는
  실제 semantic incompatibility(관측 단위 변경, 측정값 삭제)이고 fail-closed로 멈춘다.

**수정한 설계**

- **최종 R2는 따릉이 세대 실험으로 교체한다.**
- 문구: "Medallion이 monolithic보다 source evolution에 강하다"가 아니라, **persisted layer
  + explicit contract가 표현 변화와 semantic incompatibility를 관찰 가능하게 만든다.**
  Monolithic도 같은 계약을 적용하면 G1–G3는 통과하고 G4는 실패할 가능성이 높으므로 **build
  success 우위를 주장하지 않는다.**
- 통제된 perturbation의 조용한 통과는 "실패 수"가 아니라 구현 결함 / 선언 부족 / 표현력
  한계로 분류한다.

**영향**

- 기존 33% 결과는 폐기한다.

### R-5. Task3 — 결측 월세는 전세가 아니다

**원래 설계**

```python
return monthly_rent_10k.fillna(0) == 0   # 이전
```

**문제 발견**

- 이전 정의는 `월세 = 0`과 `월세 = 결측`을 같게 처리했다. 결측이 "0을 생략한 표기"라는
  계약 근거는 어디에도 없다. 테스트가 `None -> True`를 기대하면서 없는 계약을 코드에 새기고
  있었다.

**확인 근거**

```
Silver  1,221,491행   monthly_rent_10k_krw  null 0   == 0  729,205
Bronze  raw 1,221,491행   monthlyRent  결측 키 0   공백/None 0   parse -> None 0
```

`fillna(0)`은 한 번도 실행된 적이 없다.

**수정한 설계**

```python
return monthly_rent_10k.eq(0)            # 현재
```

**영향**

- 현재 데이터에서는 **결과 불변**. 다음 세대 원천에 결측이 들어와도 전세가율을 조용히
  오염시키지 않는다.

### R-6. Storage — amplification → 관측된 발자국

**원래 설계**

- `(Bronze + Silver + Gold) / Gold`를 Medallion layering의 storage amplification으로 보고한다.

**문제 발견**

- `storage.py`가 스스로 경고한다 — "Bronze가 JSON이고 Gold가 compressed Parquet이면 codec을
  재는 것이다." 실제 산출물이 정확히 그 구성이다 (Bronze `raw_records.jsonl`, Silver·Gold
  `table.parquet`).

**확인 근거**

- 같은 포맷(ZSTD Parquet, 같은 row group·dictionary 설정)으로 통제한 pilot에서 Bronze/Silver
  비는 0.92–0.99였고, 1 미만의 격차는 Silver의 파생 날짜 컬럼으로 전부 설명된다 (공유 필드만
  비교하면 약 1.00). 관측 비율 22–30배는 거의 전부 codec이다.

**수정한 설계**

- **observed on-disk storage footprint under the evaluated pipeline**으로 이름을 낮추고,
  Threats에 "계층별 저장 포맷이 달라 layering과 serialization/compression 효과를 분리하지
  못한다"를 명시한다. 버리지 않는다 — 실제 시스템 비용으로는 유효하다.
- 통제 결과를 본문에 넣을지는 검토 중이다.

**영향**

- 수치는 유지, 해석은 축소.

### R-7. Task scope — T2 제외, T4 축소 유지 → T4도 제외

**원래 설계**

- T1–T4 모두 full task (Epic의 4x4 matrix). 구현된 것은 `task01_price_analysis`와
  `task03_join` 둘이고, `task02` / `task04`는 이름과 계획만 있었다.

**문제 발견**

- T2(아파트 가격 예측)는 temporal split, feature leakage, 모델 선택, hyperparameter, seed,
  모델 자체의 variance를 끌고 들어온다. 그 전부가 Medallion 효과가 아니라 ML 실험 설계
  면적을 늘리고, `seoul-apartment-trades`는 T1에서 이미 쓰고 있어 데이터 breadth도 늘지
  않는다.
- (2차) 축소 T4를 dry-run으로 검토하니, 시간 변환(lag·순위)은 T1의 공유 분석이 이미 키 기반으로
  하고 Bronze 쪽 준비(헤더 coalesce·연월 정규화·식별자 패딩)는 R2·RQ1·perturbation이 이미 잰
  단계라 새 construct가 없다.

**확인 근거**

- T4 dry-run: 올바른 준비를 한 Bronze와 Silver의 lag/rolling/MoM이 0셀 차이. 준비를 빼면
  차이가 나지만 그것은 RQ1이 이미 잰 전이다.

**수정한 설계**

- 1차: T2는 이번 제출 scope에서 제외, T4는 예측 모델 대신 deterministic 시계열 task로 축소해
  유지 (`station_code / year_month / use_count / lag_1 / lag_3 / rolling_mean_3`).
- 2차 (**번복**): T4도 두지 않는다. 따릉이 데이터는 빠지지 않는다 — RQ1 전이 원인, 원천 세대
  진화, 계약 경계 실험의 핵심 데이터셋으로 남는다.

**영향**

- scope 변경. 못 해서 자른 것이 아니라 새 construct가 없어서 뺐다.

### R-8. Provenance — 이름 추측 → 바이트·빌더에 묶기

**원래 설계**

- 측정 대상을 이름 규칙·glob으로 해결한다. 러너는 "마지막으로 기록된 Silver"를 읽는다.
  harness가 만든 Gold는 파일이 Silver보다 새로우면 재사용한다.

**문제 발견**

1. 이름 규칙은 폐기한 artifact를 조용히 측정할 수 있었다.
2. 수정 전후 builder(`5d86eed`, `096d023`)의 Silver가 byte 단위로 같아 **체크섬만으로는
   어느 builder의 빌드인지 구분할 수 없다.** "마지막 기록"은 다른 스냅샷·빌더의 빌드가
   나중에 기록되면 틀린 빌드를 집는다.
3. Gold를 mtime으로 재사용하면, Gold를 만드는 코드가 바뀌었는데 Silver가 그대로일 때 옛
   바이트가 새 recipe로 기록된다.
4. T3는 두 원천을 읽는데 provenance 스키마는 snapshot·pipeline_version·upstream을 하나씩만
   갖는다.

**확인 근거**

- 새 binding이 기존 세 빌드(`cdee737a…`, `50c1bf15…`, `7184f2cc…`)를 그대로 다시 찾고, 같은
  바이트의 다른 builder 기록만 있는 저장소에서는 거부한다.
- Gold를 매번 재빌드해도 T1·T3 결과와 T3 Gold `build_id`가 같다.

**수정한 설계**

- snapshot / config_hash / checksum에 더해 실행 디렉터리의 `builder_identity.json`까지 기록과
  맞춘다 (`bind_measured_artifact(builder_version=…)`). T1·T3 러너가 같은 binding을 쓴다.
- Gold는 매번 다시 만든다.
- 두 원천을 읽는 층은 입력을 dataset 이름순으로 `|`로 이은 합성 식별자로 기록하고
  (`record_joined_layer`), `lineage()`는 DAG를 걷는다.

**영향**

- 결과 불변. 측정이 어느 빌드를 읽었는지 말할 수 있게 됐다.

---

## Canonical 실행 매핑

timing을 뺀 최종 결과는 논문 커밋 `4fcca24`, 빌더 `096d023`(`paper-eval-builder-096d023`)에서
`scripts/canonical.sh`로 한 번 만들었다. clean tree에서 14단계가 모두 성공했고, timing 결과
파일은 실행 전후 sha256이 같다.

- 행 단위 결과 스키마에는 builder / config / build provenance가 들어 있다. 논문 커밋과 결과
  파일 hash는 `results/canonical_manifest.json`에 적었다 (`scripts/canonical_manifest.py`가
  실행 identity와 결과 파일에서 만든다).
- 실행에 쓴 driver와 레포의 `scripts/canonical.sh`는 첫 `cd` 줄만 다르다. 실행본은 절대경로로,
  레포본은 스크립트 위치 기준으로 이동한다.
- 이전 파일 대비 달라진 값은 하나다. RQ1 `rq1_role_pair`의 `deal_date`·`contract_date`
  `representation_change_rate`가 0에서 1.0이 됐다. **측정 로직 수정에 따른 변화**다. Silver
  바이트와 config는 같고, 이전 파일은 날짜 투영 수정 전 harness에서 나왔다
  (`rq1-transition-classification.md`). 현재 분류기의 `rq1_role_transition`과는 불일치가 0이다.
- Perturbation은 의미가 깨지는 변형 20개 중 12 reject / 8 silent pass다. `5d86eed` 기준 11 / 9에서
  T-B09가 reject로 바뀐 것은 이번 실행에서 생긴 변화가 아니다. 빌더 correctness 수정이 들어간
  `096d023`에서 이미 그랬고, 이번 실행은 그것을 재현했다.

## 동결 전 일괄 동기화 (TODO)

아래는 **timing 전에 하나씩 고치지 않는다.** timing 결과가 나온 뒤 protocol freeze 때 한
번에 현재 설계로 맞춘다.

- `statistics.md` 전체 (runtime 부분, "four tasks / three datasets" 등 옛 범위 서술)
- `required-columns.md` 등 legacy scope 문서의 restaurant / T1–T4 흔적
- `Analytical Effort` 명칭, task02용 schema field, 옛 Table/Figure 번호, T4라는 과거
  snapshot 명칭
- 최종 RQ 문구, Table/Figure, Threats, 최종 `results/`
- R1 재검증

## 같이 맞춰야 하는 것

이 문서만으로는 부족하다.

- **Epic #1** — 과거 설계가 아니라 현재 SSOT만 유지한다. RQ/Task matrix를 위 표로 갱신.
- **관련 이슈·PR (#8 #16 #18 #19 #21 #22 #23 #25)** — 본문을 뜯어고쳐 원안을 지우지
  말고, 짧게 남긴다: *Final methodology superseded the original issue wording; see
  `experiment-design-revisions.md`*.
- **#22 Figure 3 / #23 Table 2** — 현재 정의가 개정 이전이다. `duplicate_rate`가 아직
  품질 개선 지표로 적혀 있어, 그대로 생성하면 폐기한 주장이 그림으로 되살아난다.
