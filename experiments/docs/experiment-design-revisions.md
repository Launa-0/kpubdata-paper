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

**원칙: 설계를 바꾸는 코드 변경은 이 문서 갱신과 같은 커밋에 넣는다.**

## 현재 최종 설계

| 축 | 실험 |
|---|---|
| Data quality / standardization | 3개 데이터셋 Bronze -> Silver |
| Analytical preparation | T1 단일 데이터셋 집계·추세 |
| Cross-dataset interoperability | T3 trades + rent join |
| Temporal analysis | T4 따릉이 시계열 (deterministic, 모델 없음) |
| Frozen-source determinism | R1 |
| Source evolution | 따릉이 G1 / G2 / I1 / G3 / G4 |
| Storage trade-off | observed on-disk footprint |
| External validation | T1 / T3 공개 통계 대조 |

RQ2는 preparation code volume·complexity와 execution cost를 본다 (`analytical
effort`가 아니다 — #54). RQ3는 correctness 우열이 아니라 analytical consistency /
semantic preservation을 본다.

## 개정 목록

| 영역 | 기존 설계 | 확인된 문제 | 수정된 설계 | 결과 영향 |
|---|---|---|---|---|
| RQ1 quality | Bronze/Silver에 동일 metric 적용 | Bronze reader 비대칭 — 측정이 Bronze에만 계약 파서를 주지 않았다 | 양쪽에 같은 해석 능력 + Bronze를 semantic/naive 두 view로 | **기존 RQ1 결과 폐기·재측정** |
| RQ1 비교 단위 | `Bronze 컬럼 -> Silver 컬럼` 매핑 | `coalesce`/`derived`를 표현 못 해 role을 조용히 누락, 두 계층이 다른 분모 | semantic role + 계층별 projection | required 2->3 / 4->5 교정 |
| RQ1 duplicate | H1 primary | 저장 표현 위의 exact-row equality라 canonicalization이 값을 **올린다** | diagnostic으로 강등, 표시 분리 | 결과값은 스키마에 보존 |
| RQ2 runtime | 5회 -> median + paired inference | parquet에 median 1개만 저장되고 deterministic task는 seed 하나 — **n=1** | median/mean/std 기술통계, inferential test 제외 | 재실행 불필요 |
| RQ3 | 정제 계층이 correctness를 향상 | 네 조건이 같은 transform semantics를 공유하도록 **의도적으로** 통제됨 | analytical consistency / semantic preservation | 코드 유지, 질문만 수정 |
| Task3 jeonse | null monthly rent를 0으로 취급 | "생략된 0"이라는 계약 근거 없음 | `eq(0)`만 전세, 결측은 unknown | 현 데이터 null 0건이라 **결과 불변** |
| R2 | apartment 기간 분할 + `Null->String` | 전 기간 null이라 추론된 `Null`이 값이 생겨 `String`이 된 것은 semantic break가 아님 | 따릉이 G1/G2/I1/G3/G4 fixed-contract 실험 | **기존 33% 결과 폐기** |
| Storage | storage amplification | Bronze JSONL vs Silver/Gold Parquet — layering이 아니라 codec을 잰다 | observed on-disk footprint | 수치 유지, 해석 축소 |
| Task scope | T1–T4 모두 full task | T2/T4 prediction 미구현 + 방법론 면적이 큼 | T1 / T3 + 축소 T4, T2는 future work | scope 변경 |
| Provenance | 이름 규칙·glob으로 artifact 해결 | 폐기 artifact를 조용히 측정할 수 있었음 | snapshot / config_hash / checksum binding | RQ1 재측정 |

## RQ1 — 측정이 만든 효과였다

원래 표 2는 이렇게 읽혔다.

```
seoul-apartment-trades   parsing_failure  1.000 -> 0.000   schema_conformance  0.000 -> 1.000
  seoul-apartment-rent   parsing_failure  0.988 -> 0.000   schema_conformance  0.012 -> 1.000
```

두 개의 결함이 겹쳐 있었다.

**(1) Bronze reader 비대칭.** `quality.py`는 "Bronze도 파이프라인의 해석을 받는다"고
적어 두고, `quality_spectrum.py`는 정반대로 재고 있었다. `pd.to_numeric("120,000")`은
실패하지만 빌드는 그 값을 읽는다. 위 숫자는 데이터가 아니라 **reader에게 얼마나
적대적이라고 시켰는지**를 잰 값이다.

**(2) 비교 단위.** `rename`/`casts`만 보고 컬럼을 맞추면 `ym_raw`(`대여일자` **또는**
`대여년월`)와 `deal_date`(세 조각 조립)를 표현할 수 없다. 못 찾은 role은 Bronze
쪽에서만 빠지고 Silver 쪽에는 남아 **두 계층이 다른 분모 위에서 측정됐다.**

양쪽에 같은 해석 능력을 주고 같은 role 위에서 다시 재면 비교 지표가 전부 평평하다.

```
               Dataset  Roles  Required type_consistency   missing_rate schema_conformance parsing_failure_rate
seoul-apartment-trades     21         5   1.000 -> 1.000 0.000 -> 0.000     1.000 -> 1.000       0.000 -> 0.000
  seoul-apartment-rent     18         5   1.000 -> 1.000 0.000 -> 0.000     1.000 -> 1.000       0.000 -> 0.000
 seoul-bike-rent-month     11         3   1.000 -> 1.000 0.000 -> 0.000     1.000 -> 1.000       0.000 -> 0.000
```

**숫자를 되돌리지 않고 주장을 고쳤다.** Silver가 없애는 것은 원천의 오류가 아니라
반복되는 해석 비용이다 — 차이는 데이터가 아니라 해석 로직을 누가 갖느냐에 있다.
옛 숫자는 `Bronze (naive)` view에 그대로 남아 준비 비용을 보여준다 (RQ2와 함께 읽는다).

자세한 실측은 `bike-generation-runs.md`의 RQ1 절에 있다.

### 미해결

naive/semantic 격차는 현재 **화면에만 찍히고 결과 artifact에 저장되지 않는다.**
비교 지표가 평평해진 지금 RQ1이 실제로 보여주는 것이 그 격차이므로, 저장 대상이
아닌 것은 결함이다. `ResultRow`는 task-condition run 중심이라 RQ1 전용 측정 테이블을
따로 두는 쪽이 맞을 수 있다. **최종 metric 집합을 확정한 뒤 한 번에 저장한다** —
지금 필드만 더하면 곧 다시 뜯는다.

## RQ2 — runtime에 검정을 붙이지 않는다

프로토콜은 warm-up 1 + 측정 5회지만 `runner.py`는 median 하나만
`ResultRow.runtime_seconds`에 남긴다. `stats.py`는 `seed`로 pair하는데 T1/T3는
deterministic이라 seed가 하나다. 즉 runtime의 paired observation은 **n = 1**이다.
"5회 측정했으니 n=5"는 성립하지 않는다.

raw 5회를 보존해 repeat index끼리 pair하는 길도 있지만, 그러면 조건 실행 순서의
temporal bias를 없애기 위해 interleave/randomize까지 가야 한다. 프로토콜 변경 +
전면 재실행이다. 이 단계에서는 과하다.

그래서 RQ2는 preprocessing LOC / function count / transformation steps를 primary로
두고, runtime과 peak memory는 기술통계로만 보고한다. **runtime p-value는 내지
않는다.** 검정은 seed가 실제로 반복 단위를 이루는 실험에만 적용한다. T1에서 이미
조건 간 LOC·function·step 차이가 크게 나므로 기술적 결론에는 지장이 없다.

## RQ3 — 같게 나오도록 통제한 것을 우열로 읽지 않는다

T3(#56)는 Bronze/Silver/Gold/Monolithic이 `normalize_apt_name` 등 **같은 transform
semantics**를 쓰게 하고, `join_matching_rate`가 설계상 같아야 한다고 테스트한다.
이 통제 자체는 옳다 — Bronze에만 나쁜 정제를 주면 baseline bias다. T1도 같은 helper와
downstream analysis를 공유한다.

그러면 "정제 계층이 오류를 줄인다"는 이 설계로 검증할 수 없다. 네 조건이 같은 값을
내는 것은 상당 부분 **설계상 기대되는 결과**다. 따라서 질문을 바꾼다.

> 계층화된 materialization이 downstream analytical result를 바꾸지 않고 보존하는가?

External reference statistic도 "네 조건 중 누가 더 정확한가"가 아니라 **공통 결과가
외부 공개 통계와 얼마나 일관되는가**라는 별도 validation으로 둔다. ground truth라
부르지 않는다. 코드는 그대로 두고 질문과 문구만 고친다.

## Task3 — 결측 월세는 전세가 아니다

```python
return monthly_rent_10k.fillna(0) == 0   # 이전
return monthly_rent_10k.eq(0)            # 현재
```

이전 정의는 `월세 = 0`과 `월세 = 결측`을 같게 처리했다. 결측이 "0을 생략한 표기"라는
계약 근거는 어디에도 없다.

실데이터를 셌고 **결과는 바뀌지 않는다.**

```
Silver  1,221,491행   monthly_rent_10k_krw  null 0   == 0  729,205
Bronze  raw 1,221,491행   monthlyRent  결측 키 0   공백/None 0   parse -> None 0
```

`fillna(0)`은 한 번도 실행된 적이 없다. 그래도 고치는 이유는, 테스트가 `None -> True`를
기대하면서 없는 계약을 코드에 새기고 있었기 때문이다. 다음 세대 원천에 결측이 하나라도
들어오면 조용히 전세가율을 오염시킨다.

## R2 — 아파트 33%는 쓰지 않는다

`stability.py`는 참조 스키마와 dtype이 다르면 break로 센다. 아파트 스냅샷에서는 과거
기간에 값이 전부 없어 Polars가 `Null`로 추론한 컬럼이 나중에 값이 생겨 `String`이
됐다. 이것은 semantic break가 아니라 **"값이 없어 타입을 추론할 수 없었다 -> 값이 생겨
실제 타입이 드러났다"**에 가깝다. 이 위에서 계산한 schema compatibility 33%는 방어력이
약하다.

따릉이 세대 실험이 모든 면에서 낫다 — G1/G2/I1/G3는 실제 표현 진화이고, 같은 고정
계약과 같은 `config_hash`를 쓰며, G4는 실제 semantic incompatibility이고 fail-closed로
멈춘다. **최종 R2는 따릉이 세대 실험으로 교체한다.**

문구도 같이 줄인다. "Medallion이 monolithic보다 source evolution에 강하다"가 아니라,
**persisted layer + explicit contract가 표현 변화와 semantic incompatibility를 관찰
가능하게 만든다**가 맞다. Monolithic도 같은 계약을 적용하면 G1–G3는 통과하고 G4는
실패할 가능성이 높으므로 **build success 우위를 주장하지 않는다.**

## Storage — layering이 아니라 관측된 발자국

`storage.py`가 스스로 경고한다 — "Bronze가 JSON이고 Gold가 compressed Parquet이면
codec을 재는 것이다." 그런데 실제 산출물이 정확히 그 구성이다.

```
Bronze  raw_records.jsonl
Silver  table.parquet
Gold    table.parquet
```

`(Bronze + Silver + Gold) / Gold`를 **Medallion layering 자체의 증폭**으로 읽으면 안
된다. 버리지도 않는다 — 실제 시스템 비용으로는 유효하므로 **observed on-disk storage
footprint under the evaluated pipeline**으로 이름을 낮추고, Threats에 "계층별 저장
포맷이 달라 layering과 serialization/compression 효과를 분리하지 못한다"를 명시한다.
순수 amplification이 필요하면 세 계층을 공통 포맷으로 변환해 보조 분석하면 되지만,
이번 제출에서는 relabel + limitation으로 충분하다.

## Task scope — T2는 빼고 T4는 줄여서 유지

구현된 것은 `task01_price_analysis`와 `task03_join` 둘이다. `task02` / `task04`는
이름과 계획만 있다. Epic의 4x4 matrix는 실제와 맞지 않는다.

**T2(아파트 가격 예측)는 이번 제출 scope에서 제외한다.** 넣는 순간 temporal split,
feature leakage, 모델 선택, hyperparameter, seed, 모델 자체의 variance가 따라 들어온다.
그 전부가 Medallion 효과가 아니라 **ML 실험 설계 면적**을 늘린다. 게다가
`seoul-apartment-trades`는 T1에서 이미 쓰고 있어 데이터 breadth도 늘지 않는다.

**T4는 예측 모델 대신 deterministic 시계열 task로 축소해 유지한다.** Gold를
`station_code / year_month / use_count / lag_1 / lag_3 / rolling_mean_3`까지만 만들고,
downstream은 전월 대비 변화량·3개월 이동평균·station별 변화 ranking, 또는
`next_month_pred = lag_1`의 MAE/RMSE 정도로 둔다. **학습이 없으므로 seed가 필요 없다.**
목적은 예측력이 아니라 *같은 시계열 계산에 도달하는 데 Bronze/Silver/Gold가 각각 얼마나
다른 준비를 요구하는가*이다. 따릉이 데이터는 이와 별개로 R2 source-evolution에도 쓴다.

못 해서 자른 것이 아니다. 새 방법론 리스크 없이 task breadth를 유지하는 구성이다.

## 같이 맞춰야 하는 것

이 문서만으로는 부족하다.

- **Epic #1** — 과거 설계가 아니라 현재 SSOT만 유지한다. RQ/Task matrix를 위 표로 갱신.
- **관련 이슈·PR (#8 #16 #18 #19 #21 #22 #23 #25)** — 본문을 뜯어고쳐 원안을 지우지
  말고, 짧게 남긴다: *Final methodology superseded the original issue wording; see
  `experiment-design-revisions.md`*.
- **#22 Figure 3 / #23 Table 2** — 현재 정의가 개정 이전이다. `duplicate_rate`가 아직
  품질 개선 지표로 적혀 있어, 그대로 생성하면 폐기한 주장이 그림으로 되살아난다.
