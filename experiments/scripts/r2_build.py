"""R2 — 고정 계약 하나로 따릉이 원천 세대를 빌드한다 (#18, RQ3).

``bike_spec.py`` **한 벌**을 세대마다 다시 선언하지 않고 그대로 돌린다. 계약이 무엇을
흡수하고 무엇에서 멈추는지가 R2의 관측값이다. 세대 정의는
``docs/bike-source-generations.md``.

- G1 / G2 / I1 / G3 — 표현이 바뀌지만 계약이 선언한 범위 안이다.
- G4 — 관측 단위가 바뀌고 측정값이 사라진다. fail-closed로 멈춰야 한다.
- 통합 스냅샷(G1+G2+I1+G3) — RQ1과 perturbation 반사실 규칙이 쓰는 Silver다.

hash 일치를 기대하지 않는다. 세대마다 원천이 다르니 출력도 다르다. 재는 것은 빌드
결과, 멈춘 단계와 이유, 행 수다. monolithic 대조는 없다 — 같은 계약을 적용하면 같은
판정이 나오므로 빌드 성공의 우위를 주장하지 않는다.

**builder 가상환경에서 실행한다.** 판정은 ``r2_report.py``가 harness 환경에서 한다.

    $BUILDER scripts/r2_build.py            # 최종: clean tree가 아니면 멈춘다
    $BUILDER scripts/r2_build.py --pilot --only G4
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _builder_identity  # noqa: E402
import _timing  # noqa: E402
import bike_spec  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS, snapshot_source  # noqa: E402

#: 세대 → 스냅샷. 통합본의 스냅샷은 계약이 선언한 것이다.
GENERATIONS = {
    "G1": "seoul-bike-rent-month-g1/20260923-e91d2c485eaf",
    "G2": "seoul-bike-rent-month-g2/20260923-ba6abb36ac55",
    "I1": "seoul-bike-rent-month-i1/20260923-073f1cc75897",
    "G3": "seoul-bike-rent-month-g3/20260923-43082467e187",
    "G4": "seoul-bike-rent-month-g4/20260923-1e55bf10ac1d",
    "G1+G2+I1+G3": bike_spec.SPEC["snapshot_id"],
}

#: 통합본은 RQ1·perturbation이 읽는 run 디렉터리에 빌드한다 — 같은 빌드를 두 번 하지 않는다.
INTEGRATED_RUN = bike_spec.SPEC["run_id"]


def build(generation: str, work_root: Path) -> dict[str, object]:
    import logging

    import polars as pl
    from _upload_store import FileUploadRepository
    from kpubdata_builder.pipeline import run_build
    from perturbation import _Capture, classify

    snapshot_id = GENERATIONS[generation]
    source = snapshot_source(SNAPSHOTS, snapshot_id)
    content = source.read_bytes()
    rows_in = content.count(b"\n") + (0 if content.endswith(b"\n") else 1)

    run_id = INTEGRATED_RUN if generation == "G1+G2+I1+G3" else f"r2-{generation.lower()}"
    runs = work_root / "runs"
    if (runs / run_id).exists():
        shutil.rmtree(runs / run_id)
    repository = FileUploadRepository(work_root / "uploads")
    upload = repository.put(
        "paper-experiment",
        content=content,
        format="jsonl",
        encoding="utf-8",
        original_filename="raw_records.jsonl",
    )
    # 빌더는 멈춘 이유를 outcome이 아니라 로그로 남긴다("pipeline failed for source").
    # perturbation과 같은 방식으로 잡아 멈춘 단계를 가른다.
    capture = _Capture()
    log = logging.getLogger("kpubdata_builder")
    log.addHandler(capture)
    started = time.perf_counter()
    try:
        result = run_build(
            bike_spec.build_spec(upload.upload_id, description=f"R2 {generation}"),
            client=None,
            output_root=runs,
            run_id=run_id,
            owner_id="paper-experiment",
            upload_repository=repository,
        )
    finally:
        log.removeHandler(capture)
    identity = _builder_identity.write(runs / run_id)
    outcome = result.outcomes[0]
    silver = runs / run_id / "silver" / bike_spec.ALIAS / "table.parquet"
    ok = outcome.status == "ok" and silver.exists()
    message = " || ".join([outcome.error or "", *capture.errors])
    return {
        "generation": generation,
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "rows_in": rows_in,
        "status": outcome.status,
        "stages_completed": ",".join(outcome.stages_completed),
        "failed_stage": None if ok else classify(message, outcome.stages_completed),
        "error": None if ok else message[:600],
        "rows_out": pl.scan_parquet(silver).select(pl.len()).collect().item() if ok else 0,
        "builder": _builder_identity.as_version(identity),
        "seconds": round(time.perf_counter() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--only", nargs="+", choices=list(GENERATIONS), default=None)
    parser.add_argument("--pilot", action="store_true", help="dirty tree 허용")
    args = parser.parse_args(argv)
    if args.only and not args.pilot:
        raise SystemExit("최종 실행은 모든 세대로만 돈다 — 줄여 돌리려면 --pilot")

    builder = _builder_identity.as_version(_builder_identity.capture())
    paper_sha, paper_dirty = _timing.git_head(_timing.EXPERIMENTS.parent)
    if not args.pilot and (paper_dirty or ".dirty" in str(builder)):
        raise SystemExit("논문 또는 빌더 레포가 커밋과 다르다 — 커밋한 뒤 실행하라")

    observations = []
    for generation in args.only or GENERATIONS:
        record = build(generation, args.work_root)
        record["paper_sha"] = paper_sha
        observations.append(record)
        print(
            f"{generation:>12}: {record['status']:<6} rows {record['rows_in']:,} -> "
            f"{record['rows_out']:,}  stage={record['failed_stage']}  ({record['seconds']}s)",
            flush=True,
        )

    target = args.work_root / (
        "pilot_r2_observations.json" if args.pilot else "r2_observations.json"
    )
    target.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"관측 {len(observations)}건 -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
