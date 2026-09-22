# 실험 실행 절차

논문의 숫자를 만든 스크립트들이다. 순서대로 실행하면 표 1·3과 R1·R2 결과가 재생산된다.

## 두 개의 가상환경

`kpubdata-builder`(polars)와 이 harness(pandas)는 서로 다른 환경에 설치된다. 한
프로세스에서 둘 다 import할 수 없으므로, **빌드하는 스크립트와 판정하는 스크립트가
나뉘어 있다.** 빌드 쪽은 관측을 JSON으로 남기고 판정 쪽이 그것을 읽는다.

| 스크립트 | 환경 |
|---|---|
| `build_silver.py`, `r1_rebuild.py`, `r2_build.py` | **builder** |
| `run_task01.py`, `r1_report.py`, `r2_report.py` | **harness** |

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

## 2. Task 1 — 표 3 (Analytical Effort)

```
$KPX scripts/run_task01.py seoul-apartment-trades/20260922-6660c8e25162
```

Gold(자치구 x 월 집계)가 없으면 먼저 만든다. 네 조건의 LOC / 단계 / 실행시간 / 메모리와
조건 간 결과 일치, 계층별 저장 크기를 출력한다.

> 실행시간과 메모리는 다른 작업이 도는 중에 재면 흔들린다. 논문에 싣는 값은 유휴
> 상태에서 한 번 더 재는 것이 좋다.

## 3. R1 — 재빌드 결정성

```
$BUILDER scripts/r1_rebuild.py seoul-apartment-trades/20260922-6660c8e25162 --repeats 10
$KPX     scripts/r1_report.py
```

빌드 쪽이 `experiments/.build/r1_observations.json`을 남기고, 판정 쪽이 그것을 읽는다.

## 4. R2 — 소스 진화 안정성

```
$BUILDER scripts/r2_build.py seoul-apartment-trades/20260922-6660c8e25162
$KPX     scripts/r2_report.py
```

스냅샷을 기간으로 잘라 T1(2020-22) / T2(2020-23) / T3(2020-24)을 만들고 **같은
BuildSpec**으로 빌드한다. hash 일치를 기대하지 않는다 — 소스가 달라졌으니 출력이 다른
것이 정상이고, 재는 것은 빌드 성공률·스키마 호환성·행 손실이다.

`r2_report.py`는 Monolithic 대조까지 돌린다(몇 분). Medallion 판정만 보려면
`--skip-monolithic`.

## Silver 계약은 한 곳에 있다

`trades_spec.py`가 rename / casts / derived / read_as를 갖는다. 세 빌드 스크립트가
이것을 공유한다 — 각자 복사해 두면 한 곳만 고쳤을 때 R1이 재는 "같은 recipe"가 더 이상
같지 않게 된다.
