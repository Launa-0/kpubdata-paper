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
- [ ] 참고문헌 [4] 저장소 URL (공개 후)
- [ ] 참고문헌 [5] 국내 선행연구 1–2편 보강
- [ ] 학회 공식 양식(.hwp 또는 .docx)에 본문을 옮기고 **분량이 2–3쪽인지 확인**

## 분량 — 추정치이며 확인이 필요하다

이 초안은 **렌더링해서 눈으로 확인하지 않았다.** 작성 환경에 LibreOffice·pandoc
이 없고 설치도 Xcode 라이선스 동의(sudo) 때문에 막혔다.

대신 문서 자체의 기하로 계산했다: 본문 폭 16.5cm × 높이 25.7cm, 줄 간격 12pt,
한글 9pt를 정폭으로 두고 문단마다 줄 수를 세면 본문 5,813자가 117줄, 표 4개가
18행이다. 여기에 문단 간격을 더하면 **약 2.5쪽**이 된다.

오차가 ±20%여도 2.0–3.0쪽이라 규정(2–3쪽) 안이지만, 계산은 계산일 뿐이다.
제출 전에 반드시 열어서 실제 쪽수를 확인해야 한다.

재계산:

```bash
cd manuscript && npm install docx --no-save && node build_docx.js
```
