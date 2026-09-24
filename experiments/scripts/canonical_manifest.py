"""canonical run이 끝난 뒤 결과 파일의 provenance를 파일 단위로 고정한다.

실험을 다시 돌리지 않는다. ``canonical.sh``가 남긴 ``.build/canonical/00_identity.txt``
(논문·빌더 커밋)와 결과 파일의 sha256을 읽어 ``results/canonical_manifest.json``에 쓴다.

``experiment_results``와 ``rq1_*``는 행 안에 builder·config·build id만 있고 논문 커밋이
없다. 논문 커밋은 이 manifest가 파일 hash와 함께 묶는다. 행에 builder가 있는 결과는
그 값이 모두 하나인지도 확인한다.

**harness 가상환경에서 실행한다.** timing 결과는 별도 측정이라 여기 넣지 않는다.

    $KPX scripts/canonical_manifest.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import DEFAULT_WORK_ROOT, EXPERIMENTS  # noqa: E402

RESULTS = EXPERIMENTS / "results"
BUILDER_REPO = EXPERIMENTS.parents[1] / "kpubdata-builder"
BUILDER_TAG = "paper-eval-builder-096d023"

#: canonical.sh가 만드는 결과 전부 (timing 제외).
FILES = (
    "experiment_results.parquet",
    "experiment_results.csv",
    "rq1_layer_quality.parquet",
    "rq1_role_pair.parquet",
    "rq1_role_transition.parquet",
    "rq1_coalesce_source.parquet",
    "source_evolution.csv",
    "storage_footprint.csv",
    "perturbation.parquet",
    "perturbation_counterfactual.json",
    "r1_determinism.csv",
)

#: 행에 builder 신원을 담는 결과와 그 컬럼.
BUILDER_COLUMNS = {
    "source_evolution.csv": "builder",
    "storage_footprint.csv": "silver_builder",
    "perturbation.parquet": "builder",
    "r1_determinism.csv": "builder",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rev_parse(repo: Path, rev: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{rev}^{{commit}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def builders(results: Path) -> set[str]:
    import pandas as pd

    seen: set[str] = set()
    for name, column in BUILDER_COLUMNS.items():
        path = results / name
        frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        seen |= set(frame[column].astype(str))
    return seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--identity", type=Path, default=DEFAULT_WORK_ROOT / "canonical" / "00_identity.txt"
    )
    parser.add_argument("--out", type=Path, default=RESULTS / "canonical_manifest.json")
    args = parser.parse_args(argv)

    # "paper 4fcca24 builder 096d023"
    fields = args.identity.read_text(encoding="utf-8").split()
    identity = dict(zip(fields[::2], fields[1::2], strict=True))

    missing = [name for name in FILES if not (RESULTS / name).exists()]
    if missing:
        raise SystemExit(f"결과 파일이 없다: {missing}")
    seen = builders(RESULTS)
    if len(seen) != 1:
        raise SystemExit(f"결과마다 builder가 다르다: {sorted(seen)}")

    manifest = {
        "paper_sha": rev_parse(EXPERIMENTS, identity["paper"]),
        "builder_sha": rev_parse(BUILDER_REPO, identity["builder"]),
        "builder_identity": seen.pop(),
        "builder_tag": BUILDER_TAG,
        "generated_by": "scripts/canonical.sh",
        "results": {name: sha256(RESULTS / name) for name in FILES},
    }
    if rev_parse(BUILDER_REPO, BUILDER_TAG) != manifest["builder_sha"]:
        raise SystemExit(f"{BUILDER_TAG}가 실행한 빌더 커밋을 가리키지 않는다")

    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
