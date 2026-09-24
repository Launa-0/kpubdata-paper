"""r2_build.py가 남긴 관측을 읽어 R2 결과표를 만든다 (#18, RQ3).

**harness 가상환경에서 실행한다.**

    $KPX scripts/r2_report.py    # -> results/source_evolution.csv

모든 세대가 **같은 계약**으로 빌드됐다는 것을 기록에서 확인한다. ``config_hash``는
``bike_spec.SPEC`` 한 벌에서 나오므로 세대마다 같아야 하고, 빌더 신원도 하나여야 한다.
어긋나면 표를 쓰지 않는다 — 세대 간 차이를 원천이 아니라 계약이나 빌더가 만들었을 수
있기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bike_spec  # noqa: E402
import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT  # noqa: E402
from r2_build import GENERATIONS  # noqa: E402

from kpx.pipeline import config_hash, transformation_recipe  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
COLUMNS = [
    "generation",
    "snapshot_id",
    "rows_in",
    "status",
    "failed_stage",
    "error",
    "rows_out",
    "config_hash",
    "builder",
    "paper_sha",
]


def table(observations: list[dict[str, object]]) -> pd.DataFrame:
    """세대 순서대로, 같은 계약에서 나온 관측만."""
    problems = []
    seen = [str(item["generation"]) for item in observations]
    if sorted(seen) != sorted(GENERATIONS):
        problems.append(f"세대가 빠지거나 겹쳤다: {seen}")
    for key in ("builder", "paper_sha"):
        values = {item[key] for item in observations}
        if len(values) != 1:
            problems.append(f"{key}가 여럿이다: {sorted(map(str, values))}")
    if problems:
        raise SystemExit("표를 만들지 않는다:\n  " + "\n  ".join(problems))

    frame = pd.DataFrame(observations)
    frame["config_hash"] = config_hash(transformation_recipe(bike_spec.SPEC))
    order = {generation: index for index, generation in enumerate(GENERATIONS)}
    frame = frame.sort_values("generation", key=lambda s: s.map(order))
    return frame[COLUMNS].reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observations", type=Path, default=DEFAULT_WORK_ROOT / "r2_observations.json"
    )
    parser.add_argument("--out", type=Path, default=RESULTS / "source_evolution.csv")
    args = parser.parse_args(argv)

    result = table(json.loads(args.observations.read_text(encoding="utf-8")))
    result.to_csv(args.out, index=False, lineterminator="\n")
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(result.drop(columns=["snapshot_id", "paper_sha"]).to_string(index=False))
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
