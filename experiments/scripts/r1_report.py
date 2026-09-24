"""r1_rebuild.py가 남긴 관측을 읽어 R1 판정을 낸다 (#17).

**harness 가상환경에서 실행한다** (pandas 필요).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import DEFAULT_WORK_ROOT  # noqa: E402

from kpx.metrics.reproducibility import (  # noqa: E402
    BuildOutcome,
    digest_distribution,
    measure_reproducibility,
    reproducibility_table,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observations",
        type=Path,
        default=DEFAULT_WORK_ROOT / "r1_observations.json",
        help="r1_rebuild.py가 남긴 파일",
    )
    args = parser.parse_args(argv)

    raw = json.loads(args.observations.read_text(encoding="utf-8"))
    outcomes = [
        BuildOutcome(
            status=item["status"],
            output_digest=item["output_digest"],
            row_count=item["row_count"],
            schema=tuple(tuple(pair) for pair in item["schema"]) if item["schema"] else None,
        )
        for item in raw
    ]

    report = measure_reproducibility(outcomes)
    seconds = sorted(item["seconds"] for item in raw)

    print("=== R1 — 고정 소스 재빌드 (Medallion) ===")
    print(f"  build success rate : {report.successes}/{report.repeats}")
    print(f"  SHA-256 equality   : {report.digest_equality}  (digest {report.distinct_digests}종)")
    print(f"  row count equality : {report.row_count_equality}")
    print(f"  schema equality    : {report.schema_equality}")
    print(f"  build time 중앙값  : {seconds[len(seconds) // 2]:.1f}s")
    print()
    print(reproducibility_table({"medallion": report}).to_string(index=False))

    if report.distinct_digests > 1:
        print("\n  [!] digest가 갈렸다 — 분포:")
        for digest, count in digest_distribution(outcomes).items():
            print(f"    {digest[:24]}… x {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
