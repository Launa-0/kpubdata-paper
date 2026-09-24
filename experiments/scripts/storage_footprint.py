"""RQ2 저장 — 관측된 footprint와, 세 계층을 같은 포맷·코덱으로 다시 쓴 통제 비교.

**harness 가상환경에서 실행한다.** 원본은 읽기만 하고, 복사본은 ``.build/storage/``에 쓴다.

    $KPX scripts/storage_footprint.py        # -> results/storage_footprint.csv

관측 footprint에서 Bronze(JSONL)가 Silver(Parquet)보다 훨씬 큰 것은 계층화가 아니라
직렬화 형식의 차이다. 그래서 세 계층을 **같은 writer·codec·row group**으로 다시 써서
행당 바이트를 비교한다.

- 모든 계층: pyarrow Parquet, zstd level 3, row group 131,072행, dictionary 기본값
- Bronze: JSONL을 값 그대로 옮긴다. JSON 타입이 섞인 필드는 JSON 텍스트로 저장해 ``0``과
  ``"0"``을 구별한다
- Silver·Gold: 빌드된 파일을 다시 인코딩하고 값이 같은지 확인한다

통제 조건이 실제로 지켜졌는지는 쓰고 나서 footer에서 다시 확인한다 — 모든 컬럼 청크의
codec, 마지막을 뺀 row group 크기, writer가 세 계층에서 같아야 한다. 하나라도 어긋나면
결과를 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
sys.path.insert(0, str(HERE))

import _builder_identity  # noqa: E402

WORK = EXPERIMENTS / ".build" / "storage"
RESULTS = EXPERIMENTS / "results"
WRITE = {"compression": "zstd", "compression_level": 3}
ROW_GROUP = 131_072
SPECS = ("trades_spec", "rent_spec", "bike_spec")
GOLD = {"seoul-apartment-trades": EXPERIMENTS / ".build/gold/task01/trades_district_month.parquet"}
JSON_TYPE = {bool: pa.bool_(), int: pa.int64(), float: pa.float64(), str: pa.string()}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def field_types(source: Path) -> tuple[dict[str, set[type]], int]:
    seen: dict[str, set[type]] = {}
    rows = 0
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            rows += 1
            for key, value in json.loads(line).items():
                kinds = seen.setdefault(key, set())
                if value is not None:
                    kinds.add(type(value))
    return seen, rows


def schema_for(seen: dict[str, set[type]]) -> tuple[pa.Schema, set[str]]:
    """단일 JSON 타입이면 native, 섞이면 JSON 텍스트 — 0과 "0"을 구별해 둔다."""
    fields, mixed = [], set()
    for key, kinds in seen.items():
        if len(kinds) == 1 and next(iter(kinds)) in JSON_TYPE:
            fields.append(pa.field(key, JSON_TYPE[next(iter(kinds))]))
        elif not kinds:
            fields.append(pa.field(key, pa.string()))
        else:
            fields.append(pa.field(key, pa.string()))
            mixed.add(key)
    return pa.schema(fields), mixed


def bronze_to_parquet(source: Path, target: Path) -> dict[str, object]:
    seen, rows = field_types(source)
    schema, mixed = schema_for(seen)
    names = schema.names
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(target, schema, **WRITE) as writer, source.open(encoding="utf-8") as fh:
        batch: dict[str, list[object]] = {name: [] for name in names}

        def flush() -> None:
            nonlocal written
            if batch[names[0]] or any(batch.values()):
                table = pa.table(batch, schema=schema)
                writer.write_table(table, row_group_size=ROW_GROUP)
                written += table.num_rows
                for name in names:
                    batch[name] = []

        for count, line in enumerate(fh, 1):
            record = json.loads(line)
            for name in names:
                value = record.get(name)
                if name in mixed and value is not None:
                    value = json.dumps(value, ensure_ascii=False)
                batch[name].append(value)
            if count % ROW_GROUP == 0:
                flush()
        flush()
    assert written == rows, (written, rows)
    return {"rows": rows, "mixed_fields": sorted(mixed), "columns": len(names)}


def reencode(source: Path, target: Path) -> int:
    table = pq.read_table(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target, row_group_size=ROW_GROUP, **WRITE)
    assert pq.read_table(target).equals(table)
    return table.num_rows


def footer(path: Path) -> dict[str, object]:
    """통제 조건을 파일에서 다시 읽는다 — 쓰기 인자를 믿지 않는다."""
    metadata = pq.ParquetFile(path).metadata
    groups = [metadata.row_group(g) for g in range(metadata.num_row_groups)]
    return {
        "codecs": sorted({g.column(c).compression for g in groups for c in range(g.num_columns)}),
        "row_groups": [g.num_rows for g in groups],
        "created_by": metadata.created_by,
    }


def check_controlled(footers: dict[tuple[str, str], dict[str, object]]) -> list[str]:
    problems = []
    for (dataset, layer), info in footers.items():
        if info["codecs"] != ["ZSTD"]:
            problems.append(f"{dataset}/{layer}: codec {info['codecs']}")
        sizes = list(info["row_groups"])  # type: ignore[call-overload]
        if any(size != ROW_GROUP for size in sizes[:-1]) or sizes[-1] > ROW_GROUP:
            problems.append(f"{dataset}/{layer}: row group {sizes}")
    writers = {str(info["created_by"]) for info in footers.values()}
    if len(writers) != 1:
        problems.append(f"writer가 여럿이다: {sorted(writers)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    rows: list[dict[str, object]] = []
    footers: dict[tuple[str, str], dict[str, object]] = {}
    for module in SPECS:
        spec = importlib.import_module(module).SPEC
        dataset, alias = spec["dataset_id"], spec["source"]["alias"]
        raw = EXPERIMENTS / "snapshots" / spec["snapshot_id"] / "source" / "raw_records.jsonl"
        silver_dir = EXPERIMENTS / ".build/runs" / spec["run_id"] / "silver" / alias
        silver = silver_dir / "table.parquet"
        layers = {"bronze": raw, "silver": silver}
        if dataset in GOLD:
            layers["gold"] = GOLD[dataset]
        before = {layer: sha256(path) for layer, path in layers.items()}

        out = WORK / dataset
        info = bronze_to_parquet(raw, out / "bronze.parquet")
        print(f"{dataset} bronze: {info}", flush=True)
        counts = {"bronze": info["rows"]}
        for layer in ("silver", "gold"):
            if layer in layers:
                counts[layer] = reencode(layers[layer], out / f"{layer}.parquet")

        builder = _builder_identity.as_version(_builder_identity.read(silver_dir.parents[1]))
        for layer, path in layers.items():
            observed = path.stat().st_size
            controlled = (out / f"{layer}.parquet").stat().st_size
            footers[(dataset, layer)] = footer(out / f"{layer}.parquet")
            rows.append(
                {
                    "dataset": dataset,
                    "layer": layer,
                    "rows": counts[layer],
                    "observed_format": "jsonl" if layer == "bronze" else "parquet(as built)",
                    "observed_bytes": observed,
                    "observed_bytes_per_row": observed / counts[layer],
                    "silver_dir_bytes": (
                        sum(p.stat().st_size for p in silver_dir.rglob("*") if p.is_file())
                        if layer == "silver"
                        else None
                    ),
                    "controlled_format": "parquet zstd(3) rg=131072",
                    "controlled_bytes": controlled,
                    "controlled_bytes_per_row": controlled / counts[layer],
                    "mixed_fields": ",".join(info["mixed_fields"]) if layer == "bronze" else "",
                    "source_sha256": before[layer],
                    "silver_builder": builder,
                }
            )
            assert sha256(path) == before[layer], f"{path} changed"
        print(f"{dataset} done", flush=True)

    problems = check_controlled(footers)
    if len({row["silver_builder"] for row in rows}) != 1:
        problems.append("Silver들이 서로 다른 빌더로 빌드됐다")
    if problems:
        raise SystemExit(
            "통제 조건이 지켜지지 않았다 — 결과를 쓰지 않는다:\n  " + "\n  ".join(problems)
        )

    frame = pd.DataFrame(rows)
    frame.to_csv(RESULTS / "storage_footprint.csv", index=False, lineterminator="\n")
    print(frame.drop(columns=["source_sha256"]).to_string(index=False))
    print(f"writer: {next(iter(footers.values()))['created_by']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
