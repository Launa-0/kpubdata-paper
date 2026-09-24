# 실험 실행 절차

논문의 숫자를 만든 스크립트들이다. timing을 뺀 결과는 `canonical.sh` 한 번으로, 표와 그림은
그 결과에서 다시 만든다. 무엇을 재는지는 `../README.md`, 설계가 바뀐 이유는
`../docs/experiment-design-revisions.md`에 있다.

## 두 개의 가상환경

`kpubdata-builder`(polars)와 이 harness(pandas)는 서로 다른 환경에 설치된다. 한
프로세스에서 둘 다 import할 수 없으므로 **빌드하는 스크립트와 판정하는 스크립트가
나뉘어 있다.** 빌드 쪽은 관측을 JSON으로 남기고 판정 쪽이 그것을 읽는다.

| 스크립트 | 환경 |
|---|---|
| `build_silver.py`, `r1_rebuild.py`, `r2_build.py`, `perturbation.py`, `time_polars.py` | **builder** |
| `record_builds.py`, `quality_spectrum.py`, `run_task01.py`, `run_task03.py`, `r1_report.py`, `r2_report.py`, `storage_footprint.py`, `time_pandas.py`, `timing_report.py`, `canonical_manifest.py`, `paper_tables.py`, `paper_figures.py` | **harness** |

아래에서 `$BUILDER`는 builder 가상환경의 python, `$KPX`는 harness 가상환경의 python이다.
논문 결과는 빌더 `096d023`(태그 `paper-eval-builder-096d023`)에서 나왔다.

## 0. 원천 바이트를 제자리에 둔다

스냅샷의 `metadata.json`은 커밋되지만 원천 바이트는 커밋되지 않는다. 받은 바이트를
`experiments/snapshots/<dataset>/<snapshot_id>/source/`에 놓고 대조한다.

```
$KPX -m kpx.cli snapshot verify seoul-apartment-trades/20260922-6660c8e25162
```

새로 수집했다면 `kpx snapshot register`로 등록한다. 따릉이 배포 파일은
`collect_bike.py` → `ingest_bike.py`로 세대별 스냅샷을 만든다
(`../docs/bike-source-generations.md`).

## 1. canonical 결과 — `canonical.sh`

```
bash scripts/canonical.sh
```

논문·빌더 레포가 clean하지 않으면 시작하지 않는다. 단계마다 로그를
`.build/canonical/NN_<step>.log`에 남기고, 실패하면 거기서 멈춘다. 약 1시간.

| 단계 | 스크립트 | 결과 |
|---|---|---|
| 01–02 | `build_silver.py` (trades, rent) | `.build/runs/*-silver-001/` |
| 03 | `r2_build.py` | 따릉이 G1 / G2 / I1 / G3 / G4와 통합본 빌드, `.build/r2_observations.json` |
| 04–06 | `record_builds.py` (trades, rent, bike) | `datasets/**/provenance.json` |
| 07 | `r2_report.py` | `results/source_evolution.csv` |
| 08 | `quality_spectrum.py` | `results/rq1_*.parquet` (RQ1) |
| 09–10 | `run_task01.py --fresh`, `run_task03.py --fresh` | `results/experiment_results.*` (RQ2 준비 코드, equivalence gate) |
| 11 | `storage_footprint.py` | `results/storage_footprint.csv` |
| 12 | `perturbation.py` | `results/perturbation.parquet`, `perturbation_counterfactual.json` |
| 13–14 | `r1_rebuild.py --repeats 10`, `r1_report.py` | `results/r1_determinism.csv` |

각 단계에서 알아 둘 것:

- **provenance에 묶는다.** `record_builds.py`는 빌더가 남긴 manifest를 데이터로 읽어
  Bronze → Silver 사슬을 기록한다. RQ1·T1·T3는 스냅샷, `config_hash`, output checksum,
  빌더 신원이 기록과 맞는 빌드만 측정하고, 아니면 멈춘다.
- **T1·T3는 준비 코드와 결과 일치만 잰다.** 실행 시간은 여기서 재지 않는다. Gold는 매번
  다시 만든다.
- **R2는 계약을 세대마다 바꾸지 않는다.** `bike_spec.py` 한 벌로 모든 세대를 빌드하고, 멈춘
  세대는 빌더 로그에서 멈춘 단계와 이유를 가른다. 판정 쪽은 세대가 빠졌거나 빌더·커밋이
  여럿이면 표를 쓰지 않는다.
- **perturbation**은 trades 원천과 따릉이 G1을 계통 추출한 약 5,000행 fixture에 변형 51개를
  가한다. 반사실 규칙(`perturbation_counterfactual.json`)은 전체 Silver(trades, 따릉이 통합본)의 값
범위에서 만든다.
- **storage**는 Bronze와 Silver를 같은 Parquet 조건(zstd 3, row group 131,072, 같은 writer)으로
  다시 쓰고, footer가 그 조건과 다르면 보고하지 않는다.
- **R1**은 같은 스냅샷·계약·빌더로 10번 빌드한다. 판정 쪽은 관측이 한 clean commit에서
  나오지 않았으면 결과 파일을 쓰지 않는다.

## 2. manifest, 표, 그림

```
$KPX scripts/canonical_manifest.py   # results/canonical_manifest.json
$KPX scripts/paper_tables.py         # tables/*.csv, *.md
$KPX scripts/paper_figures.py        # figures/*.svg, *.png
```

새 측정은 하지 않는다. manifest는 `.build/canonical/00_identity.txt`의 논문·빌더 커밋과 결과
파일 sha256을 묶는다. 표와 그림은 결과 파일이 manifest와 다르면 만들지 않는다. 같은 입력이면
다시 만들어도 바이트가 같다.

## 3. timing — 동결됨

timing은 `920e019`(태그 `timing-measured-920e019`)에서 한 번 쟀고 다시 재지 않는다.
`canonical.sh`에 들어 있지 않다. 절차는 기록으로 남긴다.

```
$BUILDER scripts/time_polars.py land       # 원천 JSONL -> 공용 Bronze Parquet
$KPX     scripts/time_pandas.py
$BUILDER scripts/time_polars.py measure
$KPX     scripts/timing_report.py
```

두 러너는 논문·빌더 레포의 추적 파일이 커밋과 다르면 멈춘다. 무엇을 어떤 순서로 재는지는
`_timing.py`에 있다 — T1·T3, S1–S4, materialized vs monolithic, warm-up 1 + 측정 5, 같은
round 안에서 두 전략을 번갈아. 원자료는 `results/timing_raw_{pandas,polars}.parquet`,
요약(`timing_summary.csv`)과 paired 비교(`timing_comparison.csv`)는 그것에서만 만든다.
`timing_report.py`는 원자료의 모양과 모든 실행의 결과 일치를 먼저 확인하고, 어긋나면
요약을 쓰지 않는다.

동작만 확인하려면 두 러너에 `--pilot --repeats 1`을 주고 `timing_report.py --pilot`으로
본다. 결과는 `.build/timing/`에만 남는다.

## 조건 하나만 돌리기

```
$KPX -m kpx.cli run --task task01 --condition silver \
    --layer seoul-apartment-trades=silver=experiments/.build/runs/trades-silver-001/silver/trades/table.parquet \
    --snapshot seoul-apartment-trades/20260922-6660c8e25162 \
    --pipeline-version <kpx build list가 알려주는 값>
```

`--snapshot`과 `--pipeline-version`은 생략할 수 없다. 기본값을 두면 그 자리에 추측이
기록되고, 결과 행이 자기 출처를 잃는다.

## Silver 계약은 한 곳에 있다

`<dataset>_spec.py`의 `SPEC` 한 벌이 계약 전부를 선언한다. `build_spec()`이 그것으로
BuildSpec을 만들고, `kpx.pipeline.transformation_recipe`가 같은 것을 해시해
`pipeline_version`을 낸다. 선언이 두 벌이면 한쪽만 고쳤을 때 규칙은 바뀌었는데
식별자는 그대로인 상태가 된다.

해시에서 빠지는 것은 `kpx.pipeline.RUN_SCOPED_KEYS`에 이름이 적힌 것뿐이다 —
`upload_id`, `description`, `output_path`처럼 산출 바이트를 바꾸지 않고 실행마다
달라지는 값들이다. **거부 목록이지 허용 목록이 아니다.** 허용 목록이면 스펙에 새
규칙이 생길 때마다 조용히 식별자에서 빠지고, `derived`가 빠져 있던 것이 정확히 그
경로였다.
