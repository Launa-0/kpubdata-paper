"""확정된 canonical 결과에서 논문 표를 만든다. 새 측정은 하지 않는다.

**harness 가상환경에서 실행한다.**

    $KPX scripts/paper_tables.py     # -> tables/*.csv, tables/*.md

입력은 ``results/``의 커밋된 파일과 스냅샷 ``metadata.json``뿐이다. 먼저
``results/canonical_manifest.json``의 hash와 결과 파일이 같은지 확인하고, 다르면 멈춘다.
CSV가 기계가 읽는 원본이고, 같은 내용의 Markdown은 사람이 검토하는 판이다.

| 파일 | 표 |
|---|---|
| ``dataset_scope`` | 데이터셋·기간·행 수·역할·RQ |
| ``rq1_transition_by_dataset`` | RQ1 본문 — dataset × 전이 원인 (role × 원인의 집계) |
| ``rq1_role_transition`` | RQ1 부록 — role × 전이 원인 전체 |
| ``rq2_preparation`` | RQ2 — T1/T3 × 조건의 준비 코드 규모와 equivalence gate |
| ``rq2_timing`` | RQ2 — S1–S4 paired 비교 |
| ``rq3_determinism`` / ``rq3_source_evolution`` / ``rq3_perturbation`` | RQ3 panel A/B/C |
| ``appendix_perturbation`` | 변형 51개의 판정 |
| ``appendix_storage`` | 같은 Parquet 조건의 저장 크기 |
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, EXPERIMENTS, SNAPSHOTS  # noqa: E402
from r2_build import GENERATIONS  # noqa: E402

RESULTS = EXPERIMENTS / "results"
TABLES = EXPERIMENTS / "tables"

CAUSES = [
    "primitive_type_normalization",
    "numeric_formatting",
    "identifier_padding",
    "date_year_month_normalization",
    "null_canonicalization",
    "derived_field",
    "unchanged",
]

#: 데이터셋 → (역할, RQ). 스냅샷 id는 결과 파일에서 읽는다.
SCOPE = {
    "seoul-apartment-trades": ("T1·T3 입력, RQ1, R1, perturbation", "RQ1·RQ2·RQ3"),
    "seoul-apartment-rent": ("T3 입력, RQ1", "RQ1·RQ2"),
    "seoul-bike-rent-month": ("RQ1, R2 통합본(G1+G2+I1+G3)", "RQ1·RQ3"),
    "seoul-bike-rent-month-g1": ("R2 세대, perturbation", "RQ3"),
    "seoul-bike-rent-month-g2": ("R2 세대", "RQ3"),
    "seoul-bike-rent-month-i1": ("R2 세대", "RQ3"),
    "seoul-bike-rent-month-g3": ("R2 세대", "RQ3"),
    "seoul-bike-rent-month-g4": ("R2 세대 (관측 단위 변경)", "RQ3"),
}

#: 계약이 통과시킨 의미 파괴 변형의 분류. 판정 규칙이 아니라 사람이 읽은 분류다
#: (``overnight/recomputed/perturbation/REPORT.md`` 1.4절). 결과가 이 집합과 다르면 멈춘다.
SILENT_PASS = {
    "T-B04": "undeclared_but_expressible",  # 가격 ×10 — 범위 규칙
    "T-B05": "undeclared_but_expressible",  # 원 단위 가격 — 범위 규칙
    "T-B06": "undeclared_but_expressible",  # 평 단위 면적 — 범위 규칙
    "T-B10": "undeclared_but_expressible",  # 가격 10% null — max_null_ratio
    "B-B10": "undeclared_but_expressible",  # 이용건수 10% null — max_null_ratio
    "B-B05": "not_expressible",  # 거리 m→km
    "B-B06": "not_expressible",  # 거리↔시간
    "B-B07": "not_expressible",  # alias 아래 다른 필드
}

#: canonical Silver(``trades-silver-001``) 디렉터리의 ``r1_rebuild.digest_tree``.
#: 실행 뒤 로컬에서 확인한 값이다. 빌드 디렉터리가 있으면 다시 확인한다.
CANONICAL_SILVER_DIGEST = "68409d83cc4d528cd78dd94f25c299f90a5349c4e19fe7266ff6fb80763bbb02"


def read(name: str) -> pd.DataFrame:
    path = RESULTS / name
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def check_manifest() -> None:
    manifest = json.loads((RESULTS / "canonical_manifest.json").read_text(encoding="utf-8"))
    stale = [
        name
        for name, digest in manifest["results"].items()
        if hashlib.sha256((RESULTS / name).read_bytes()).hexdigest() != digest
    ]
    if stale:
        raise SystemExit(f"manifest와 다른 결과 파일: {stale}")


def dataset_scope() -> pd.DataFrame:
    snapshots = {
        **{g: s for g, s in GENERATIONS.items()},
        "trades": "seoul-apartment-trades/20260922-6660c8e25162",
        "rent": "seoul-apartment-rent/20260923-a0ed9577c41a",
    }
    rows = []
    for snapshot_id in dict.fromkeys(snapshots.values()):
        meta = json.loads((SNAPSHOTS / snapshot_id / "metadata.json").read_text(encoding="utf-8"))
        role, rqs = SCOPE[meta["dataset"]]
        rows.append(
            {
                "dataset": meta["dataset"],
                "snapshot_id": snapshot_id,
                "period": f"{meta['period'][0]}~{meta['period'][1]}",
                "rows": meta["row_count"],
                "role": role,
                "rq": rqs,
            }
        )
    order = {name: index for index, name in enumerate(SCOPE)}
    return pd.DataFrame(rows).sort_values("dataset", key=lambda s: s.map(order))


def rq1_by_dataset(transition: pd.DataFrame) -> pd.DataFrame:
    unknown = set(transition["category"]) - set(CAUSES)
    if unknown:
        raise SystemExit(f"표에 없는 전이 원인: {unknown}")
    table = transition.pivot_table(
        index="dataset", columns="category", values="cells", aggfunc="sum", fill_value=0
    ).reindex(columns=CAUSES, fill_value=0)
    table.insert(0, "role_cells", table.sum(axis=1))
    table.insert(1, "changed_cells", table["role_cells"] - table["unchanged"])
    table.insert(2, "changed_rate", table["changed_cells"] / table["role_cells"])
    return table.reindex(list(SCOPE)[:3]).reset_index()


def rq1_by_role(transition: pd.DataFrame) -> pd.DataFrame:
    return (
        transition.pivot_table(
            index=["dataset", "role", "required"],
            columns="category",
            values="cells",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=CAUSES, fill_value=0)
        .reset_index()
    )


def rq2_preparation(results: pd.DataFrame) -> pd.DataFrame:
    reference = results[results["condition"] == "silver"].set_index("task")["output_hash"]
    frame = results.assign(
        equivalence=[
            "PASS" if h == reference[t] else "FAIL"
            for t, h in zip(results["task"], results["output_hash"], strict=True)
        ],
        output_hash=results["output_hash"].str[:12],
    )
    return frame[
        [
            "task",
            "condition",
            "rows",
            "preprocessing_loc",
            "function_count",
            "transformation_steps",
            "output_hash",
            "equivalence",
            "join_matching_rate",
        ]
    ]


def rq2_timing() -> pd.DataFrame:
    return read("timing_comparison.csv")[
        [
            "task",
            "engine",
            "scenario",
            "n_pairs",
            "materialized_median",
            "monolithic_median",
            "median_paired_ratio",
            "median_paired_delta_seconds",
        ]
    ]


def rq3_determinism(r1: pd.DataFrame) -> pd.DataFrame:
    silver = DEFAULT_WORK_ROOT / "runs" / "trades-silver-001" / "silver" / "trades"
    if silver.exists():
        from r1_rebuild import digest_tree

        if digest_tree(silver) != CANONICAL_SILVER_DIGEST:
            raise SystemExit("canonical Silver digest가 기록과 다르다")
    return pd.DataFrame(
        [
            {
                "builds": len(r1),
                "successful": int((r1["status"] == "ok").sum()),
                "distinct_digests": r1["output_digest"].nunique(),
                "rows_identical": r1["row_count"].nunique() == 1,
                "schema_identical": r1["schema"].nunique() == 1,
                "identical_to_canonical_silver": bool(
                    (r1["output_digest"] == CANONICAL_SILVER_DIGEST).all()
                ),
                "rows": int(r1["row_count"].iloc[0]),
                "digest": r1["output_digest"].iloc[0][:12],
            }
        ]
    )


def rq3_source_evolution(r2: pd.DataFrame) -> pd.DataFrame:
    frame = r2.assign(
        result=r2["status"].map({"ok": "accepted", "failed": "rejected"}),
        config_hash=r2["config_hash"].str[:12],
    )
    return frame[
        ["generation", "rows_in", "result", "failed_stage", "rows_out", "config_hash"]
    ].fillna({"failed_stage": "—"})


def classify_breaks(perturbation: pd.DataFrame) -> pd.DataFrame:
    breaks = perturbation[perturbation["kind"] == "B"].copy()
    silent = set(breaks.loc[breaks["verdict"] != "correct_reject", "mutation"])
    if silent != set(SILENT_PASS):
        raise SystemExit(f"통과한 변형이 분류표와 다르다: {sorted(silent ^ set(SILENT_PASS))}")
    breaks["contract_class"] = breaks["mutation"].map(SILENT_PASS).fillna("declared_or_covered")
    return breaks


def rq3_perturbation(breaks: pd.DataFrame) -> pd.DataFrame:
    table = (
        breaks.groupby("contract_class", sort=False)
        .agg(
            mutations=("mutation", "count"),
            rejected=("verdict", lambda v: int((v == "correct_reject").sum())),
            silent_pass=("verdict", lambda v: int((v != "correct_reject").sum())),
        )
        .reindex(["declared_or_covered", "undeclared_but_expressible", "not_expressible"])
        .reset_index()
    )
    total = {"contract_class": "total", **table.drop(columns="contract_class").sum().to_dict()}
    return pd.concat([table, pd.DataFrame([total])], ignore_index=True)


def appendix_perturbation(perturbation: pd.DataFrame, breaks: pd.DataFrame) -> pd.DataFrame:
    frame = perturbation.merge(breaks[["mutation", "contract_class"]], on="mutation", how="left")
    return frame[
        [
            "mutation",
            "dataset",
            "kind",
            "n_cells_mutated",
            "observed",
            "verdict",
            "failure_stage",
            "contract_class",
        ]
    ].fillna({"failure_stage": "—", "contract_class": "—"})


def appendix_storage(storage: pd.DataFrame) -> pd.DataFrame:
    controlled = storage.pivot(index="dataset", columns="layer", values="controlled_bytes")
    observed = storage.pivot(index="dataset", columns="layer", values="observed_bytes")
    table = pd.DataFrame(
        {
            "rows": storage[storage["layer"] == "silver"].set_index("dataset")["rows"],
            "bronze_jsonl_bytes": observed["bronze"],
            "bronze_parquet_bytes": controlled["bronze"],
            "silver_parquet_bytes": controlled["silver"],
            "bronze_to_silver": controlled["bronze"] / controlled["silver"],
            "bronze_plus_silver_to_silver": (controlled["bronze"] + controlled["silver"])
            / controlled["silver"],
        }
    )
    return table.reindex(list(SCOPE)[:3]).reset_index()


def to_markdown(frame: pd.DataFrame) -> str:
    def cell(value: object) -> str:
        if isinstance(value, float):
            return f"{value:,.4g}" if abs(value) < 1000 else f"{value:,.0f}"
        if pd.api.types.is_integer(value) and not isinstance(value, bool):
            return f"{int(value):,}"
        return "—" if pd.isna(value) else str(value)  # type: ignore[call-overload]

    lines = [
        "| " + " | ".join(frame.columns) + " |",
        "|" + "|".join("---" for _ in frame.columns) + "|",
    ]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines)


def write(name: str, frame: pd.DataFrame, caption: str, out: Path) -> None:
    frame.to_csv(out / f"{name}.csv", index=False, lineterminator="\n")
    text = f"# {name}\n\n{caption}\n\n{to_markdown(frame)}\n"
    (out / f"{name}.md").write_text(text, encoding="utf-8", newline="\n")
    print(f"{name}: {len(frame)}행")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=TABLES)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    check_manifest()
    transition = read("rq1_role_transition.parquet")
    perturbation = read("perturbation.parquet")
    breaks = classify_breaks(perturbation)

    tables = [
        ("dataset_scope", dataset_scope(), "스냅샷 metadata.json의 기간과 원천 행 수."),
        (
            "rq1_transition_by_dataset",
            rq1_by_dataset(transition),
            "계산 단위는 role × transition cause이며, 이 표는 가독성을 위해 dataset "
            "수준으로 집계한 것이다. 원자료: `rq1_role_transition.parquet`.",
        ),
        ("rq1_role_transition", rq1_by_role(transition), "role × transition cause 셀 수 전체."),
        (
            "rq2_preparation",
            rq2_preparation(read("experiment_results.parquet")),
            "equivalence는 Silver 조건의 output_hash와 같은지다.",
        ),
        (
            "rq2_timing",
            rq2_timing(),
            "같은 round의 쌍 5개. ratio = monolithic ÷ materialized, "
            "Δ = monolithic − materialized (초). 1·0보다 크면 materialized가 빠르다.",
        ),
        (
            "rq3_determinism",
            rq3_determinism(read("r1_determinism.csv")),
            "Panel A — 같은 스냅샷·계약·빌더로 10회 재빌드.",
        ),
        (
            "rq3_source_evolution",
            rq3_source_evolution(read("source_evolution.csv")),
            "Panel B — 고정 계약 하나로 따릉이 원천 세대를 빌드.",
        ),
        (
            "rq3_perturbation",
            rq3_perturbation(breaks),
            "Panel C — 의미 파괴 변형 20개. 분류는 계약이 그 변형을 선언했는지/표현할 수 있는지다.",
        ),
        (
            "appendix_perturbation",
            appendix_perturbation(perturbation, breaks),
            "변형 51개 (P: 의미 보존 31, B: 의미 파괴 20). fixture는 원천의 계통 추출 약 5,000행.",
        ),
        (
            "appendix_storage",
            appendix_storage(read("storage_footprint.csv")),
            "Bronze와 Silver를 같은 조건(Parquet zstd(3), row group 131,072, 같은 writer)으로 "
            "다시 쓴 크기.",
        ),
    ]
    for name, frame, caption in tables:
        write(name, frame, caption, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
