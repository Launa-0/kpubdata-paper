"""따릉이 배포 CSV를 스냅샷 원천으로 들인다 (#16, #18).

고정 파이프라인 **바깥**의 단계다. 파일마다 인코딩이 다르고 G2 안에서도 섞이는데
(cp949 20 + utf-8-sig 5), 세대마다 ``SourceRef.encoding``을 바꾸면 BuildSpec이 달라져
R2의 same-pipeline 전제가 깨진다. 단일 선언으로는 G2 내부 혼재를 표현할 수도 없다.
그래서 decode를 여기서 하고, R2가 평가하는 것은 **decode 이후의 스키마·값 표현 진화에
대한 계약 안정성**이 된다. 자세한 근거는 docs/bike-source-generations.md.

## 세대는 파일명이 아니라 헤더로 가른다

파일명은 배포자가 붙인 것이고 규칙이 일정하지 않다(``_23.1-6``, ``_23.7-12``,
``_22.07_22.12``). 헤더는 그 파일이 실제로 무엇인지 말한다. 문서의 세대 표와 어긋나면
즉시 드러나므로, 이 분류 자체가 문서에 대한 검증이다.

## 원본 바이트

스냅샷에 CSV를 그대로 복사하지는 않는다 — harness의 다른 스냅샷과 같은 규약이다.
대신 파일별 SHA-256과 인코딩과 행 수를 ``ingest_manifest.json``에 적어 원천 안에
함께 넣는다. 재현하려는 사람은 자기 사본을 그 해시로 대조한다.

시각·절대경로·hostname은 적지 않는다. 매번 달라지는 값이 들어가면 스냅샷 digest가
흔들려 R1이 재려는 결정성을 스스로 깬다.

## 실행

    python ingest_bike.py --data <csv 디렉터리> --out <원천 디렉터리> --generation G1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

#: 시도 순서. utf-8-sig가 먼저인 이유는 cp949가 거의 모든 바이트열을 오류 없이
#: 읽어내기 때문이다 — 반대로 두면 utf-8 파일이 조용히 깨진 한글이 된다.
ENCODINGS = ("utf-8-sig", "cp949")

#: 헤더 지문 → 세대. docs/bike-source-generations.md의 표와 같은 내용이다.
GENERATIONS: dict[str, tuple[str, ...]] = {
    "G1": (
        "대여일자",
        "대여소번호",
        "대여소명",
        "대여구분코드",
        "성별",
        "연령대코드",
        "이용건수",
        "운동량",
        "탄소량",
        "이동거리",
        "이용시간",
    ),
    "G2": (
        "대여일자",
        "대여소번호",
        "대여소명",
        "대여구분코드",
        "성별",
        "연령대코드",
        "이용건수",
        "운동량",
        "탄소량",
        "이동거리(M)",
        "이용시간(분)",
    ),
    "I1": (
        "대여일자",
        "대여소번호",
        "대여소명",
        "대여구분코드",
        "성별",
        "연령대코드",
        "이용건수",
        "운동량",
        "탄소량",
        "이용거리(M)",
        "이용시간(본)",
    ),
    "G3": (
        "대여년월",
        "대여소번호",
        "대여소명",
        "대여구분코드",
        "성별",
        "연령대코드",
        "이용건수",
        "운동량",
        "탄소량",
        "이용거리(M)",
        "이용시간(분)",
    ),
    "G4": ("자치구", "대여소명", "기준년월", "대여건수", "반납건수"),
}

#: T4가 쓰는 통합 스냅샷. G4는 의미가 끊겨 여기 들어가지 않는다.
T4 = ("G1", "G2", "I1", "G3")


def decode(raw: bytes) -> tuple[str, str]:
    """(텍스트, 인코딩). 어느 것으로도 못 읽으면 실패한다 — 조용히 대체하지 않는다."""
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"어느 인코딩으로도 읽히지 않는다: {ENCODINGS}")


def classify(header: tuple[str, ...]) -> str:
    for name, signature in GENERATIONS.items():
        if header == signature:
            return name
    raise SystemExit(f"문서에 없는 헤더다 — 세대 표를 다시 봐야 한다: {list(header)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="CSV가 있는 디렉터리")
    parser.add_argument("--out", type=Path, required=True, help="스냅샷 source 디렉터리")
    parser.add_argument(
        "--generation",
        default="T4",
        help="G1/G2/I1/G3/G4 하나, 또는 T4(=G1+G2+I1+G3). 기본: T4",
    )
    parser.add_argument("--dry-run", action="store_true", help="분류만 하고 쓰지 않는다")
    args = parser.parse_args(argv)

    wanted = set(T4) if args.generation == "T4" else {args.generation}
    unknown = wanted - set(GENERATIONS)
    if unknown:
        raise SystemExit(f"모르는 세대: {sorted(unknown)}")

    entries: list[dict[str, object]] = []
    selected: list[tuple[Path, str, str, list[dict[str, str]]]] = []
    for path in sorted(args.data.rglob("*.csv")):
        text, encoding = decode(path.read_bytes())
        rows = list(csv.reader(io.StringIO(text)))
        header = tuple(rows[0])
        generation = classify(header)
        if generation not in wanted:
            continue
        records = [dict(zip(header, row, strict=True)) for row in rows[1:] if row]
        entries.append(
            {
                "file": path.name,
                "generation": generation,
                "encoding": encoding,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "row_count": len(records),
                "header": list(header),
            }
        )
        selected.append((path, generation, encoding, records))
        print(f"{generation}  {encoding:<10} {len(records):>7,}  {path.name}", flush=True)

    if not selected:
        raise SystemExit(f"{args.generation}에 해당하는 파일이 없다")

    total = sum(len(records) for *_, records in selected)
    print(f"\n파일 {len(selected)}개, {total:,}행")
    if args.dry_run:
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "raw_records.jsonl"
    with target.open("w", encoding="utf-8", newline="\n") as sink:
        for *_, records in selected:
            for record in records:
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
    (args.out / "ingest_manifest.json").write_text(
        json.dumps(
            {
                "source": "https://data.seoul.go.kr/dataList/OA-15249/F/1/datasetView.do",
                "generation": args.generation,
                "file_count": len(entries),
                "row_count": total,
                "files": entries,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{target}  ({target.stat().st_size / 1024 / 1024:.1f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
