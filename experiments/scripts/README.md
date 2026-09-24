# 실험 실행 절차

논문의 숫자를 만든 스크립트들이다. 순서대로 실행하면 표 1·3과 R1·R2 결과가 재생산된다.

## 두 개의 가상환경

`kpubdata-builder`(polars)와 이 harness(pandas)는 서로 다른 환경에 설치된다. 한
프로세스에서 둘 다 import할 수 없으므로, **빌드하는 스크립트와 판정하는 스크립트가
나뉘어 있다.** 빌드 쪽은 관측을 JSON으로 남기고 판정 쪽이 그것을 읽는다.

| 스크립트 | 환경 |
|---|---|
| `build_silver.py`, `r1_rebuild.py`, `r2_build.py`, `time_polars.py` | **builder** |
| `record_builds.py`, `run_task01.py`, `r1_report.py`, `r2_report.py`, `time_pandas.py`, `timing_report.py` | **harness** |

아래에서 `$BUILDER`는 builder 가상환경의 python, `$KPX`는 harness 가상환경의
python이다.

## 0. 원천 바이트를 제자리에 둔다

스냅샷의 `metadata.json`은 커밋되지만 원천 바이트는 커밋되지 않는다(140 MiB). 수집본을
`experiments/snapshots/<dataset>/<snapshot_id>/source/raw_records.jsonl` 에 놓고
대조한다.

```
$KPX -m kpx.cli snapshot verify seoul-apartment-trades/20260922-6660c8e25162
```

새로 수집했다면 등록부터 한다.

```
$KPX -m kpx.cli snapshot register <pull-dir> \
    --dataset seoul-apartment-trades \
    --source-url https://www.data.go.kr/data/15126468/openapi.do \
    --schema-version datago.apt_trade/RTMSDataSvcAptTradeDev \
    --period 2020-01 2024-12 --collector "kpubdata 0.5.0"
```

## 1. Silver 빌드

```
$BUILDER scripts/build_silver.py seoul-apartment-trades/20260922-6660c8e25162
```

산출물은 `experiments/.build/`(git-ignored)에 쌓인다. `--work-root`로 바꿀 수 있다.

빌드된 스키마를 확인하려면:

```
$KPX -m kpx.cli schema experiments/.build/runs/trades-silver-001/silver/trades/table.parquet
```

## 2. 빌드를 provenance에 기록한다

```
$KPX scripts/record_builds.py seoul-apartment-trades/20260922-6660c8e25162
```

빌더가 남긴 `manifest.json`을 데이터로 읽어 Bronze -> Silver 사슬을 `experiments/
datasets/` 에 적는다. `run_task01.py`가 이 기록이 없으면 멈춘다 — 어떤 빌드를 읽고
측정했는지 말할 수 없는 숫자는 표에 실을 수 없기 때문이다.

Bronze는 자기 모양을 스스로 보고한다. 행 수는 빌더가 남긴 Bronze `metadata.json`,
컬럼은 얼린 스냅샷이다. manifest의 `row_counts`/`schema_summaries`는 **Silver**를
서술하므로 Bronze에 그대로 쓰면 원천에 없는 컬럼을 Bronze의 것이라 적게 된다.

## 3. Task 1 — 표 3 (Analytical Effort)

```
$KPX scripts/run_task01.py seoul-apartment-trades/20260922-6660c8e25162
```

Gold(자치구 x 월 집계)가 없거나 Silver보다 오래되었으면 먼저 만든다. 네 조건의
LOC / 단계 / 실행시간 / 메모리와 조건 간 결과 일치를 출력한다.

측정 정의가 바뀐 뒤에 다시 돌릴 때는 `--fresh`다. 이전 결과 행을 지우고 **Gold도 다시
빌드한다** — 빌드 비용을 다시 재지 않으면 손익분기(#19)가 빠진다.

```
$KPX scripts/run_task01.py <snapshot-id> --fresh
```

조건 하나만 따로 돌리려면 설치된 명령으로도 된다. 계층의 경로를 직접 주고, 결과는
같은 저장소에 쌓인다.

```
$KPX -m kpx.cli run --task task01 --condition silver \
    --layer seoul-apartment-trades=silver=experiments/.build/runs/trades-silver-001/silver/trades/table.parquet \
    --snapshot seoul-apartment-trades/20260922-6660c8e25162 \
    --pipeline-version 0.1.0+7d72b8b966e0
```

`--snapshot`과 `--pipeline-version`은 생략할 수 없다. 기본값을 두면 그 자리에 추측이
기록되고, 결과 행이 자기 출처를 잃는다. 두 값은 `kpx build list`가 알려준다.

> 실행시간과 메모리는 다른 작업이 도는 중에 재면 흔들린다. 논문에 싣는 값은 유휴
> 상태에서 한 번 더 재는 것이 좋다.

## 4. R1 — 재빌드 결정성

```
$BUILDER scripts/r1_rebuild.py seoul-apartment-trades/20260922-6660c8e25162 --repeats 10
$KPX     scripts/r1_report.py
```

빌드 쪽이 `experiments/.build/r1_observations.json`을 남기고, 판정 쪽이 그것을 읽는다.

## 5. R2 — 소스 진화 안정성

```
$BUILDER scripts/r2_build.py seoul-apartment-trades/20260922-6660c8e25162
$KPX     scripts/r2_report.py
```

스냅샷을 기간으로 잘라 T1(2020-22) / T2(2020-23) / T3(2020-24)을 만들고 **같은
BuildSpec**으로 빌드한다. hash 일치를 기대하지 않는다 — 소스가 달라졌으니 출력이 다른
것이 정상이고, 재는 것은 빌드 성공률·스키마 호환성·행 손실이다.

`r2_report.py`는 Monolithic 대조까지 돌린다(몇 분). Medallion 판정만 보려면
`--skip-monolithic`.

## 6. Timing — materialized vs monolithic

```
$BUILDER scripts/time_polars.py land       # 원천 JSONL -> 공용 Bronze Parquet
$KPX     scripts/time_pandas.py
$BUILDER scripts/time_polars.py measure
$KPX     scripts/timing_report.py
```

측정은 **커밋한 뒤에** 돌린다. 두 러너는 논문·빌더 레포의 추적 파일이 커밋과 다르면
멈춘다 — 숫자가 어느 코드에서 나왔는지 다시 애매해지지 않게 하기 위해서다. 원자료는
`results/timing_raw_{pandas,polars}.parquet`, 요약은 그것에서만 만든
`results/timing_summary.csv`다. 무엇을 어떤 순서로 재는지는 `_timing.py`에 있다.

동작만 확인하려면 두 러너에 `--pilot --repeats 1`을 주고 `timing_report.py --pilot`으로
본다. 결과는 `.build/timing/`에만 남는다.

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
