# 재현성 안내 (Artifact)

논문 「계약 기반 Medallion 파이프라인의 한국 공공데이터 적용에 대한 실증 평가」의
artifact 색인이다. 논문에 나오는 모든 수치가 어디서 왔고, 무엇을 어디까지 다시
만들 수 있는지를 한 곳에 적는다.

세부 절차는 [`experiments/README.md`](experiments/README.md)에 있다. 이 문서는
**무엇이 공개되어 있고 무엇이 아직 아닌지**를 밝히는 것이 목적이다.

## 동결 지점

| 항목 | 값 |
|---|---|
| 논문·실험 저장소 | `4fcca24` |
| 빌더 (kpubdata-builder) | `096d023`, 태그 `paper-eval-builder-096d023`, 버전 `0.4.0.dev0+096d023f9546` |
| 시간 측정 | `920e019`, 태그 `timing-measured-920e019` |
| 결과 최초 커밋 | `99ab145` |

`experiments/results/canonical_manifest.json`이 위 두 커밋과 결과 파일 11개의
sha256을 묶는다. `experiments/tests/test_canonical_manifest.py`가 이 대응을
검사하므로, 결과 파일이 바뀌면 CI가 실패한다.

## 재현 수준

같은 명령이 같은 결과를 내는 범위는 층마다 다르다. 섞어 읽지 않도록 나눈다.

| 수준 | 다시 만들 수 있는 것 | 필요한 것 | 상태 |
|---|---|---|---|
| **L1 표·그림** | `tables/`, `figures/` 전부 | 이 저장소만 | ✅ 공개됨 |
| **L2 측정값** | `results/` 전부 (약 1시간) | 스냅샷 바이트 + 빌더 `096d023` | ⚠️ 스냅샷 바이트 미공개 |
| **L3 원천 수집** | 스냅샷 자체 | 공공데이터포털·서울 열린데이터광장 API 키 | ⚠️ 원천이 갱신되면 동일 바이트가 나오지 않음 |

L1은 지금 이 저장소를 clone하면 바로 된다:

```bash
cd experiments
make install
uv run python scripts/paper_tables.py    # tables/
uv run python scripts/paper_figures.py   # figures/
```

두 스크립트는 `canonical_manifest.json`의 해시와 맞지 않는 결과 파일을 보면
생성을 거부한다. 따라서 L1 재현은 "논문의 표가 동결된 측정값에서 나왔다"는 것을
확인하는 절차이기도 하다.

L2는 스냅샷 바이트를 복원한 뒤:

```bash
uv run python -m kpx.cli snapshot verify <snapshot_id>   # 바이트 무결성
bash scripts/canonical.sh                                # 14단계
uv run python scripts/canonical_manifest.py
```

`canonical.sh`는 작업 트리가 더러우면 시작하지 않는다.

## 공개 상태

### 공개된 것

- **측정값** `experiments/results/` — 논문의 모든 숫자의 유일한 출처
- **표·그림** `experiments/tables/`, `experiments/figures/`
- **실험 코드** `experiments/src/kpx/`, `experiments/scripts/`
- **계약(Silver spec)** `experiments/scripts/<dataset>_spec.py`
- **기준선 구현** monolithic 조건 — 별도 경로가 아니라 같은 변환 헬퍼를 쓰는 일반 조건
- **스냅샷 메타데이터** `experiments/snapshots/*/metadata.json` (기간·행 수·내용 다이제스트)
- **빌드 provenance** `experiments/datasets/*/provenance.json`
- **빌더** [kpubdata-builder](https://github.com/yeongseon/kpubdata-builder) `096d023`

### 아직 공개되지 않은 것

**스냅샷 바이트.** 메타데이터만 커밋되어 있고 실제 바이트는 저장소에 없다.
크기는 다음과 같다.

| 형식 | 크기 |
|---|---|
| Bronze JSONL (원본 그대로) | 2.29 GB |
| Bronze Parquet (zstd(3)) | 97 MB |
| Silver Parquet (zstd(3)) | 100 MB |

Git 저장소에 넣기에는 크고, 없으면 L2 재현이 불가능하다. Hugging Face Datasets에
Parquet(약 197 MB)을 올리는 것이 적절하다 — 크기가 문제되지 않고, 스냅샷 id가
내용 다이제스트를 담고 있어 업로드본의 동일성을 `snapshot verify`로 검증할 수
있다. Bronze JSONL 2.29 GB까지 올릴지는 별도 판단이 필요하다.

> **결정 필요.** 게시 위치와 Bronze JSONL 포함 여부. 정해지면 이 표에 URL을
> 채우고 논문 참고문헌 [7]도 함께 채운다.

### 쓰이지 않은 것

`experiments/snapshots/reference-jeonse-ratio/`는 수집만 해두었고 **어떤 결과에도
쓰이지 않았다.** 외부 통계 대조는 최종 설계에서 제외됐다 — 전세가율은 분모 정의·
시점·거래 필터에 따라 값이 3.6%p 움직여, 차이가 파이프라인에서 왔는지 정의에서
왔는지 분리할 수 없기 때문이다. 근거는
[`experiments/docs/experiment-design-revisions.md`](experiments/docs/experiment-design-revisions.md).

## 라이선스와 출처

재배포 조건을 데이터셋별로 확인했다 (2026-09-25). **세 데이터셋 모두 재배포할 수
있다.**

| 데이터셋 | 제공 | 이용허락범위 | 재배포 |
|---|---|---|---|
| 아파트 매매 실거래가 | 국토교통부 / data.go.kr | 제한 없음 | 가능 |
| 아파트 전월세 실거래가 | 국토교통부 / data.go.kr | 제한 없음 | 가능 |
| 따릉이 대여이력 | 서울특별시 / data.seoul.go.kr | 공공누리 **제1유형** (출처표시, 상업적 이용·변경 가능) | 가능, **출처표시 필수** |

공공누리 제2~4유형(상업적 이용 금지, 변형 금지)에 해당하는 것은 없다. 따릉이
데이터를 게시할 때는 출처를 "서울특별시"로 표시한다.

코드의 라이선스는 [`LICENSE`](LICENSE)에 있고, 데이터에는 적용되지 않는다.

## 알려진 한계

재현을 시도하기 전에 알아야 할 것들이다. 논문 4절과 같은 내용이되, 여기서는
재현자 관점으로 적는다.

- **L3는 재현되지 않을 수 있다.** 원천 API는 과거 기간의 응답도 갱신한다.
  같은 질의가 같은 바이트를 준다는 보장이 없어서 스냅샷을 동결한 것이다.
- **시간 측정은 장비에 의존한다.** `results/timing_environment_*.json`에 측정
  환경이 기록되어 있다. 조건당 5쌍, warm-up 1회이며 추론 통계는 내지 않았다.
  S3·S4에서 관측된 역전은 방향이 4개 셀 전부에서 같았다는 것까지가 근거다.
- **빌더와 하비스트는 같은 환경에서 import되지 않는다.** 빌더는 polars, 하비스트는
  pandas에 묶여 있어 가상환경 두 개가 필요하다.
- **LOC에는 계측 행이 섞여 있다.** `prepare()` 안의 `ctx.step(...)`이 조건마다
  0~7행 포함되며 변환 단계 수에 비례한다. 논문 3.2절은 원시 값과 이를 뺀 값을
  함께 보고한다.
