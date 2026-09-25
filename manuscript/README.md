# manuscript — ACK 2026 원고

한국정보처리학회 추계학술발표대회(ACK 2026, 11/5–7, 세종대) 학부생 논문경진대회
제출 원고. 분량 2–3쪽, 제출 포맷 `.hwp`/`.docx`.

## 파일

| 파일 | 설명 |
|---|---|
| `ACK2026_medallion_draft.docx` | 원고 초안 |
| `build_docx.js` | 초안을 생성하는 스크립트 (`node build_docx.js`) |

`build_docx.js`는 `docx` npm 패키지만 쓴다. 초안을 손으로 고치기 시작하면 이
스크립트는 더 이상 정본이 아니다 — 그 시점에 스크립트를 지우거나, 반대로 본문을
스크립트로 되돌려 한쪽만 남긴다.

## 본문의 모든 숫자는 동결된 결과에서 왔다

원고에 등장하는 수치는 전부 `experiments/tables/` 의 표에서 인용했고, 그 표는
`experiments/results/` 의 canonical 측정값에서 생성된다. 동결 지점은 결과
`4fcca24`, builder `096d023`.

| 원고 위치 | 출처 |
|---|---|
| 표 1 데이터셋 범위 | `tables/dataset_scope.md` |
| 표 2 변경률·원인 | `tables/rq1_transition_by_dataset.md` |
| 준비 코드 LOC | `tables/rq2_preparation.md` |
| 표 3 재계산 비율 | `tables/rq2_timing.md` |
| 표 4 변형 분류 | `tables/rq3_perturbation.md` |
| R1 / R2 | `tables/rq3_determinism.md`, `rq3_source_evolution.md` |
| 저장 발자국 | `tables/appendix_storage.md` |
| T3 매칭률 0.634 | `tables/rq2_preparation.md` (`join_matching_rate`) |

## 제출 전에 반드시 채워야 하는 것

- [ ] **제출 마감일 확인** — 학회 공지와 대회 페이지 어디에도 없다.
      manuscriptlink 로그인 후 확인이 필요하다.
- [ ] 저자·소속·이메일 (현재 `[저자명]` 등 자리표시자)
- [ ] **발표자 확정** — ACK 는 발표자 기준으로 등록한다
- [ ] 참고문헌 [7] 저장소 URL (공개 후) — 유일하게 남은 인용 자리표시자
- [ ] 학회 공식 양식(.hwp 또는 .docx)에 본문을 옮기고 **분량 재확인** (현재 3쪽, 상한)

참고문헌 [1]~[6]은 모두 실제 문헌을 확인하고 넣었다 — Lakehouse(CIDR 2021),
Delta Lake(PVLDB 13(12):3411–3424), 박고은·김창재(디지털융복합연구
13(10):135–146, 2015), 김학래(한국콘텐츠학회논문지 20(9):439–447, 2020).

## 분량 — Microsoft Word로 실측: **3쪽**

```
pages=3  words=1577
```

규정(2–3쪽) 안이지만 **상한에 정확히 걸린다.** 학회 공식 양식은 여백·글꼴·단
구성이 다를 수 있으므로, 양식에 옮긴 뒤 반드시 다시 확인해야 한다.

넘칠 경우 의미 손실이 가장 적은 순서로 줄인다.

| 순서 | 대상 | 절감 |
|---|---|---|
| 1 | 3.1절 마지막 문장의 셀 수 3개 → 1개 | 약 1줄 |
| 2 | 4절 "외적 타당도와 표본" 단락의 S3·S4 방향성 설명 | 약 2줄 |
| 3 | 2절 "준비 코드의 경계" 단락을 각주로 | 약 3줄 |
| 4 | 표 1에서 '용도' 열 삭제 | 약 4줄 |

3.2절의 계측 행 논의와 3.3절의 P class 단락은 줄이지 않는다 — 그 둘이 이
원고에서 가장 방어하기 어려운 주장을 방어하는 부분이다.

측정 방법(참고): `osascript`로 Word에 `compute statistics ... statistic pages`를
물었다. Word는 같은 경로의 문서를 캐시하므로, 다시 잴 때는 Word를 종료하거나
다른 파일명으로 복사해서 열어야 한다 — 그러지 않아 처음엔 옛 수치를 읽었다.

재계산:

```bash
cd manuscript && npm install docx --no-save && node build_docx.js
```
