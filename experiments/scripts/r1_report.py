"""r1_rebuild.py가 남긴 관측을 읽어 R1 판정을 낸다 (#17).

**harness 가상환경에서 실행한다** (pandas 필요).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
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
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "results" / "r1_determinism.csv",
        help="빌드마다 한 행 (기본: experiments/results/r1_determinism.csv)",
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

    # 관측 전부를 남긴다 — 판정 한 줄만 남기면 무엇으로 판정했는지 다시 볼 수 없다.
    frame = pd.DataFrame(raw)
    identities = frame[["builder", "paper_sha", "paper_dirty"]].drop_duplicates()
    if (
        len(identities) != 1
        or bool(identities["paper_dirty"].iloc[0])
        or ".dirty" in str(identities["builder"].iloc[0])
    ):
        print("\n  [!] 한 clean commit에서 나온 관측이 아니다 — 결과 파일을 쓰지 않는다")
        print(identities.to_string(index=False))
        return 1
    frame["schema"] = frame["schema"].map(json.dumps)
    frame.to_csv(args.out, index=False, lineterminator="\n")
    print(f"\n-> {args.out}")

    if report.distinct_digests > 1:
        print("\n  [!] digest가 갈렸다 — 분포:")
        for digest, count in digest_distribution(outcomes).items():
            print(f"    {digest[:24]}… x {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
