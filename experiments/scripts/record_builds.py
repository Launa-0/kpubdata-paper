"""빌더가 남긴 산출물을 provenance 사슬로 기록한다 (#40, #51).

빌드는 builder 가상환경에서 돌지만 provenance는 harness의 것이다. 빌더는
``manifest.json``을 남기고, 이 스크립트가 그것을 **데이터로** 읽어 Bronze -> Silver
사슬을 기록한다. harness는 ``kpubdata_builder``를 import하지 않는다.

Gold는 여기서 기록하지 않는다. 과제용 Gold는 run_task01.py가 Silver에서 만들고
그 자리에서 사슬에 잇는다.

**harness 가상환경에서 실행한다.**
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS  # noqa: E402

from kpx.pipeline import record_layer_chain, transformation_recipe  # noqa: E402
from kpx.provenance import ProvenanceStore  # noqa: E402
from kpx.snapshot import SnapshotStore  # noqa: E402

SPECS = {"trades": "trades_spec", "rent": "rent_spec"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id")
    parser.add_argument("--spec", choices=sorted(SPECS), default="trades")
    parser.add_argument("--run-id", default=None, help="기본값: <spec>-silver-001")
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument(
        "--datasets",
        type=Path,
        default=None,
        help="provenance 저장소 (기본: experiments/datasets)",
    )
    args = parser.parse_args(argv)

    run_id = args.run_id or f"{args.spec}-silver-001"
    spec = importlib.import_module(SPECS[args.spec]).SPEC
    root = args.datasets or Path(__file__).resolve().parents[1] / "datasets"

    # 스냅샷 기록을 넘긴다 — Bronze의 컬럼은 manifest가 아니라 얼린 원천이 답한다.
    snapshot = SnapshotStore(args.snapshots).load(args.snapshot_id)

    recorded = record_layer_chain(
        args.work_root / "runs" / run_id,
        snapshot=snapshot,
        config=transformation_recipe(spec),
        alias=spec["source"]["alias"],
        store=ProvenanceStore(root),
    )

    for layer, provenance in recorded.items():
        print(
            f"{layer:<7} build_id={provenance.build_id}  "
            f"rows={provenance.row_count:,}  "
            f"checksum={provenance.output_checksum[:12]}…  "
            f"size={provenance.output_size_bytes / 1024 / 1024:.1f} MiB"
        )
    print(f"pipeline_version = {recorded['silver'].inputs.pipeline_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
