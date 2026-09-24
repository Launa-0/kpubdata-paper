#!/usr/bin/env bash
# 최종 결과 1회 생성 — 한 commit에서 정해진 순서로. 실패하면 거기서 멈춘다.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
KPX=.venv/Scripts/python.exe
BUILDER=../../kpubdata-builder/.venv/Scripts/python.exe
TRADES=seoul-apartment-trades/20260922-6660c8e25162
RENT=seoul-apartment-rent/20260923-a0ed9577c41a
BIKE=seoul-bike-rent-month/20260923-637ec21bb5b1
LOG=.build/canonical
mkdir -p $LOG
test -z "$(git status --porcelain --untracked-files=no)" || { echo "dirty paper tree"; exit 1; }
test -z "$(git -C ../../kpubdata-builder status --porcelain)" || { echo "dirty builder tree"; exit 1; }
echo "paper $(git rev-parse --short HEAD) builder $(git -C ../../kpubdata-builder rev-parse --short HEAD)" > $LOG/00_identity.txt
step() { local name=$1; shift; echo "[$(date +%H:%M:%S)] start $name"; "$@" > "$LOG/$name.log" 2>&1; echo "[$(date +%H:%M:%S)] done  $name"; }
step 01_silver_trades $BUILDER scripts/build_silver.py $TRADES --spec trades
step 02_silver_rent   $BUILDER scripts/build_silver.py $RENT --spec rent
step 03_r2_build      $BUILDER scripts/r2_build.py
step 04_record_trades $KPX scripts/record_builds.py $TRADES --spec trades
step 05_record_rent   $KPX scripts/record_builds.py $RENT --spec rent
step 06_record_bike   $KPX scripts/record_builds.py $BIKE --spec bike --run-id bike-t4-silver
step 07_r2_report     $KPX scripts/r2_report.py
step 08_rq1           $KPX scripts/quality_spectrum.py
step 09_task01        $KPX scripts/run_task01.py $TRADES --fresh
step 10_task03        $KPX scripts/run_task03.py $TRADES $RENT --fresh
step 11_storage       $KPX scripts/storage_footprint.py
step 12_perturbation  $BUILDER scripts/perturbation.py
step 13_r1_rebuild    $BUILDER scripts/r1_rebuild.py $TRADES --repeats 10
step 14_r1_report     $KPX scripts/r1_report.py
echo "[$(date +%H:%M:%S)] ALL DONE"
