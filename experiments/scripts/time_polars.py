"""timing — polars 엔진 (builder 가상환경).

    python scripts/time_polars.py land             # 원천 JSONL -> 공용 Bronze Parquet
    python scripts/time_polars.py measure          # 최종 측정: clean tree가 아니면 멈춘다
    python scripts/time_polars.py measure --pilot  # 동작 확인: 결과를 .build/timing에만 쓴다

**계약은 builder 코드로 적용한다.** ``normalize_table``이 레코드를 표로 바꾼 뒤에
하는 일(rename → cast audit → derived)과 ``validate_table``을 같은 순서로 부른다. 표로
바꾸는 일은 ``land``가 builder의 ``records_to_dataframe``과 ``read_as``로 미리 해 둔다 —
두 전략이 같은 Bronze Parquet을 읽어야 하기 때문이다.

Gold와 분석은 harness의 pandas 함수와 같은 규칙을 polars 식으로 옮긴 것이다. builder
환경에는 pandas가 없다. 두 엔진의 결과가 같은지는 ``timing_report.py``가 본다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _builder_identity  # noqa: E402
import _timing  # noqa: E402

try:
    import polars as pl
except ModuleNotFoundError:  # --help는 harness 환경(CI)에서도 돌아야 한다.
    pl = None
import rent_spec  # noqa: E402
import trades_spec  # noqa: E402
from _paths import SNAPSHOTS, snapshot_source  # noqa: E402

SPECS = {spec.DATASET_ID: spec.SPEC for spec in (trades_spec, rent_spec)}
SUPPORTED = frozenset({"read_as", "required", "rename", "casts", "derived"})

#: ``task03_join.transforms.AREA_EDGES``와 같은 경계. 라벨은 ``area_bucket``의 ``{:g}``.
AREA_EDGES = (40.0, 60.0, 85.0, 135.0)
NON_NAME = r"[^0-9A-Za-z가-힣]+"
KRW_PER_10K = 10_000


def land(layout: _timing.Layout) -> None:
    """두 원천을 builder가 표로 읽는 방식 그대로 Bronze Parquet으로 적는다."""
    from kpubdata_builder.tabular.convert import records_to_dataframe

    for dataset, spec in SPECS.items():
        source = snapshot_source(SNAPSHOTS, spec["snapshot_id"])
        with source.open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        frame = records_to_dataframe(records, read_as=spec["contract"]["read_as"])
        path = layout.bronze(dataset)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path, compression="zstd")
        print(f"{dataset}: {frame.height:,}행 {frame.width}열 -> {path.name}")
    landing = {
        "builder": _builder_identity.as_version(_builder_identity.capture()),
        "snapshots": {dataset: spec["snapshot_id"] for dataset, spec in SPECS.items()},
    }
    (layout.root / "bronze" / "landing.json").write_text(
        json.dumps(landing, indent=2) + "\n", encoding="utf-8"
    )


def apply_contract(bronze: pl.DataFrame, contract: dict[str, Any]) -> pl.DataFrame:
    from kpubdata_builder.errors import TabularError
    from kpubdata_builder.spec import DerivedColumn
    from kpubdata_builder.stages.silver.normalize import _apply_derived, _check_year_month
    from kpubdata_builder.stages.silver.validate import validate_table
    from kpubdata_builder.tabular.polars_helpers import cast_columns

    unsupported = set(contract) - SUPPORTED
    if unsupported:
        raise TabularError(f"이 엔진이 구현하지 않은 계약 항목: {sorted(unsupported)}")
    missing = [source for source in contract["rename"] if source not in bronze.columns]
    if missing:
        raise TabularError(f"declared rename refers to columns absent from the source: {missing}")
    table = bronze.rename(dict(contract["rename"]))
    _check_year_month(table, contract["casts"])
    result = cast_columns(table, contract["casts"], audit=True)
    if result.has_nulls_introduced:
        raise TabularError(f"declared cast dropped values to null: {result.reports}")
    table = result.df
    for rule in contract["derived"]:
        table = _apply_derived(table, DerivedColumn(**rule))
    validation = validate_table(table, required_columns=contract["required"])
    if not validation.ok:
        raise TabularError(f"validation failed: {validation.problems}")
    return table


def _year_month() -> pl.Expr:
    """``to_year_month`` — 연·월 정수를 ``YYYY-MM``으로."""
    return pl.format(
        "{}-{}",
        pl.col("deal_year").cast(pl.String).str.zfill(4),
        pl.col("deal_month").cast(pl.String).str.zfill(2),
    )


def _unit_price(amount: str) -> pl.Expr:
    """``price_per_m2``/``unit_price`` — 면적이 0 이하이면 null."""
    area = pl.col("area_m2")
    return pl.when(area > 0).then(pl.col(amount) * KRW_PER_10K / area)


def _area_bucket() -> pl.Expr:
    area = pl.col("area_m2")
    expr = pl.when(area.is_null() | (area <= 0)).then(pl.lit(None, dtype=pl.String))
    lower = 0.0
    for edge in AREA_EDGES:
        expr = expr.when(area < edge).then(pl.lit(f"{lower:g}-{edge:g}"))
        lower = edge
    return expr.otherwise(pl.lit(f"{lower:g}+"))


def _normalize_apt_name() -> pl.Expr:
    name = pl.col("apt_name").str.normalize("NFC").str.replace_all(NON_NAME, "")
    return pl.when(name != "").then(name)


def gold_task01(silver: pl.DataFrame) -> pl.DataFrame:
    district = pl.col("district_code").cast(pl.String).str.strip_chars()
    return (
        silver.with_columns(
            pl.when(district != "").then(district.str.zfill(5)).alias("district_code"),
            _year_month().alias("year_month"),
            _unit_price("price_10k_krw").alias("price_per_m2"),
        )
        # pandas groupby는 null 키를 버린다.
        .drop_nulls(["price_per_m2", "district_code", "year_month"])
        .group_by("district_code", "year_month")
        .agg(
            pl.col("price_per_m2").count().alias("n_deals"),
            pl.col("price_per_m2").mean().alias("mean_price_per_m2"),
            pl.col("price_per_m2").median().alias("median_price_per_m2"),
        )
        .sort("district_code", "year_month")
    )


def gold_task03(trades: pl.DataFrame, rents: pl.DataFrame) -> pl.DataFrame:
    keys = ["district_code", "apt_name", "year_month", "area_bucket"]

    def fold(frame: pl.DataFrame, amount: str, target: str) -> pl.DataFrame:
        return (
            frame.with_columns(
                _normalize_apt_name().alias("apt_name"),
                _year_month().alias("year_month"),
                _area_bucket().alias("area_bucket"),
                _unit_price(amount).alias(target),
            )
            .drop_nulls([*keys, target])
            .group_by(keys)
            .agg(pl.col(target).mean())
        )

    sales = fold(trades, "price_10k_krw", "sale_price_per_m2")
    jeonse = fold(
        rents.filter(pl.col("monthly_rent_10k_krw") == 0),
        "deposit_10k_krw",
        "jeonse_deposit_per_m2",
    )
    return (
        sales.join(jeonse, on=keys, how="inner")
        .group_by("district_code", "year_month")
        .agg(
            pl.col("sale_price_per_m2").count().alias("n_matched"),
            pl.col("sale_price_per_m2").mean().alias("mean_sale_price_per_m2"),
            pl.col("jeonse_deposit_per_m2").mean().alias("mean_jeonse_deposit_per_m2"),
        )
        .sort("district_code", "year_month")
    )


def _with_previous_year(frame: pl.DataFrame, value: str, alias: str) -> pl.DataFrame:
    """``previous_year_month``를 키로 전년 동월 값을 붙인다 (위치가 아니라 키로)."""
    previous = frame.select(
        "district_code",
        pl.format(
            "{}-{}",
            (pl.col("year_month").str.slice(0, 4).cast(pl.Int64) + 1).cast(pl.String).str.zfill(4),
            pl.col("year_month").str.slice(5),
        ).alias("year_month"),
        pl.col(value).alias(alias),
    )
    return frame.join(previous, on=["district_code", "year_month"], how="left")


def analyze_task01(gold: pl.DataFrame) -> pl.DataFrame:
    frame = _with_previous_year(gold, "mean_price_per_m2", "_prev_mean")
    frame = frame.with_columns(
        (pl.col("mean_price_per_m2") / pl.col("_prev_mean") - 1).alias("mean_price_yoy_change")
    ).drop("_prev_mean")
    ranking = (
        frame.filter(pl.col("year_month") == pl.col("year_month").max())
        .sort("mean_price_per_m2", descending=True)
        .select("district_code", pl.int_range(1, pl.len() + 1).alias("price_rank"))
    )
    return frame.join(ranking, on="district_code", how="left").sort("district_code", "year_month")


def analyze_task03(gold: pl.DataFrame) -> pl.DataFrame:
    sale = pl.col("mean_sale_price_per_m2")
    frame = gold.with_columns(
        (pl.col("mean_jeonse_deposit_per_m2") / pl.when(sale > 0).then(sale)).alias("jeonse_ratio")
    )
    frame = _with_previous_year(frame, "jeonse_ratio", "_prev_ratio")
    return (
        frame.with_columns(
            (pl.col("jeonse_ratio") - pl.col("_prev_ratio")).alias("jeonse_ratio_yoy_change")
        )
        .drop("_prev_ratio")
        .sort("district_code", "year_month")
    )


class PolarsEngine:
    name = "polars"

    def read(self, path: Path) -> pl.DataFrame:
        return pl.read_parquet(path)

    def write(self, frame: pl.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path, compression="zstd")

    def contract(self, bronze: pl.DataFrame, dataset: str) -> pl.DataFrame:
        return apply_contract(bronze, SPECS[dataset]["contract"])

    def gold(self, task: str, silvers: dict[str, pl.DataFrame]) -> pl.DataFrame:
        if task == "task01":
            return gold_task01(silvers[_timing.TRADES])
        return gold_task03(silvers[_timing.TRADES], silvers[_timing.RENTS])

    def analyze(self, task: str, gold: pl.DataFrame) -> pl.DataFrame:
        return analyze_task01(gold) if task == "task01" else analyze_task03(gold)

    def digest(self, result: pl.DataFrame) -> str:
        return hashlib.sha256(result.write_csv().encode("utf-8")).hexdigest()


def measure(args: argparse.Namespace, layout: _timing.Layout) -> int:
    from polars.testing import assert_frame_equal

    if not args.pilot and (
        args.repeats != _timing.MEASURED_RUNS or args.tasks != list(_timing.TASKS)
    ):
        raise SystemExit("최종 측정은 프로토콜 그대로만 돈다 — 줄여 돌리려면 --pilot")
    landing = json.loads((layout.root / "bronze" / "landing.json").read_text(encoding="utf-8"))
    builder = _builder_identity.as_version(_builder_identity.capture())
    if builder != landing["builder"]:
        raise SystemExit(
            f"Bronze를 적재한 빌더({landing['builder']})와 지금 빌더({builder})가 다르다"
        )
    paper_sha, paper_dirty = _timing.git_head(_timing.EXPERIMENTS.parent)
    if not args.pilot and (paper_dirty or ".dirty" in str(builder)):
        raise SystemExit("논문 또는 빌더 레포가 커밋과 다르다 — 커밋한 뒤 측정하라")
    environment_id, environment = _timing.environment(polars=pl.__version__)
    engine = PolarsEngine()

    reference = {}
    for task in args.tasks:
        # S1·S2가 읽을 Silver·Gold를 만들어 두고, 엔진 간 대조용 결과를 남긴다(타이머 밖).
        reference[task] = _timing.materialized(engine, layout, task, "S3")
        reference[task].write_parquet(layout.root / engine.name / f"{task}_result.parquet")

    def equivalent(task: str, result: pl.DataFrame) -> bool:
        # 허용오차는 부동소수 컬럼에만 걸린다. 행 순서·키·정수·문자열·null 위치는 정확히.
        try:
            assert_frame_equal(
                result, reference[task], check_exact=False, rel_tol=_timing.RTOL, abs_tol=0.0
            )
        except AssertionError:
            return False
        return True

    rows = _timing.measure(
        engine,
        layout,
        _timing.schedule(tuple(args.tasks), repeats=args.repeats),
        {"paper_sha": paper_sha, "builder_sha": builder, "environment_id": environment_id},
        equivalent,
    )
    wrong = [row for row in rows if not row["equivalent"]]
    out = layout.root if args.pilot else _timing.RESULTS
    prefix = "pilot_" if args.pilot else ""
    pl.DataFrame(rows).write_parquet(out / f"{prefix}timing_raw_polars.parquet")
    (out / f"{prefix}timing_environment_polars.json").write_text(
        json.dumps({"environment_id": environment_id, **environment}, indent=2) + "\n",
        encoding="utf-8",
    )
    if wrong:
        raise SystemExit(f"{len(wrong)}개 실행의 결과가 준비 실행과 다르다 — 측정을 쓰지 마라")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("land")
    run = commands.add_parser("measure")
    run.add_argument("--pilot", action="store_true", help="dirty tree 허용, 결과는 .build에만")
    run.add_argument("--tasks", nargs="+", default=list(_timing.TASKS))
    run.add_argument("--repeats", type=int, default=_timing.MEASURED_RUNS)
    args = parser.parse_args(argv)

    if pl is None:
        raise SystemExit("polars가 없다 — builder 가상환경에서 실행하라")
    layout = _timing.Layout(_timing.WORK)
    if args.command == "land":
        land(layout)
        return 0
    return measure(args, layout)


if __name__ == "__main__":
    raise SystemExit(main())
