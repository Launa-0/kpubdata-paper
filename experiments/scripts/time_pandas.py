"""timing — pandas 엔진 (harness 가상환경).

    python scripts/time_pandas.py            # 최종 측정: clean tree가 아니면 멈춘다
    python scripts/time_pandas.py --pilot    # 동작 확인: 결과를 .build/timing에만 쓴다

Bronze Parquet은 ``time_polars.py land``가 먼저 만들어 둬야 한다 — 두 엔진이 같은
파일을 읽는다. 무엇을 어떤 순서로 재는지는 ``_timing``에 있다.

Gold 변환은 ``run_task01.build_gold``/``run_task03.build_gold``의 본문과 같다. 그 함수들은
파일을 읽고 쓰기까지 하므로 monolithic이 쓸 수 없고, 고치면 Gold의 ``build_id``가
움직인다(``gold_recipe``가 그 소스를 해시한다). 그래서 frame 단위로 옮겨 두고, 같은
결과를 내는지는 테스트가 고정한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _timing  # noqa: E402
import pandas as pd  # noqa: E402
import rent_spec  # noqa: E402
import trades_spec  # noqa: E402

from kpx.contract import AnalysisInput  # noqa: E402
from kpx.results import output_digest  # noqa: E402
from kpx.tasks.task01_price_analysis import TASK as TASK01  # noqa: E402
from kpx.tasks.task01_price_analysis import transforms as tf1  # noqa: E402
from kpx.tasks.task03_join import TASK as TASK03  # noqa: E402
from kpx.tasks.task03_join import transforms as tf3  # noqa: E402

CONTRACTS = {spec.DATASET_ID: spec.SPEC["contract"] for spec in (trades_spec, rent_spec)}
ANALYZE = {"task01": TASK01.analyze, "task03": TASK03.analyze}

#: 이 엔진이 구현한 계약 항목. ``read_as``는 Bronze 적재 때 builder가 이미 적용했다.
SUPPORTED = frozenset({"read_as", "required", "rename", "casts", "derived"})


class ContractError(Exception):
    """builder라면 빌드를 세웠을 입력."""


def _integral(values: pd.Series) -> pd.Series:
    fractional = values.notna() & (values % 1 != 0)
    return values.mask(fractional).astype("Int64")


#: builder ``cast_columns``와 같은 규칙. 실패한 값은 null이 되고, 호출자가 null 증가로
#: 손실을 잡는다. ``int_comma``만 구분자를 지우고 양끝 공백을 벗긴다 — builder도 그렇다.
CASTS = {
    "float": lambda s: pd.to_numeric(s, errors="coerce").astype("float64"),
    "int": lambda s: _integral(pd.to_numeric(s, errors="coerce")),
    "int_comma": lambda s: _integral(
        pd.to_numeric(s.astype("string").str.replace(",", "").str.strip(), errors="coerce")
    ),
}


def apply_contract(bronze: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    """전체 계약을 builder의 순서(rename → casts → derived → required)로 적용한다."""
    unsupported = set(contract) - SUPPORTED
    if unsupported:
        raise ContractError(f"이 엔진이 구현하지 않은 계약 항목: {sorted(unsupported)}")
    missing = [source for source in contract["rename"] if source not in bronze.columns]
    if missing:
        raise ContractError(f"rename이 가리키는 컬럼이 원천에 없다: {missing}")
    table = bronze.rename(columns=contract["rename"])
    for column, cast in contract["casts"].items():
        before = int(table[column].isna().sum())
        table[column] = CASTS[cast](table[column])
        lost = int(table[column].isna().sum()) - before
        if lost:
            raise ContractError(f"{column!r} cast가 값 {lost}개를 null로 만들었다")
    for rule in contract["derived"]:
        if rule["kind"] != "date_parts":
            raise ContractError(f"이 엔진이 구현하지 않은 파생 규칙: {rule['kind']!r}")
        parts = table[list(rule["columns"])]
        parts.columns = ["year", "month", "day"]
        date = pd.to_datetime(parts, errors="coerce")
        lost = int((parts.notna().all(axis=1) & date.isna()).sum())
        if lost:
            raise ContractError(f"{rule['name']!r} 파생이 값 {lost}개를 null로 만들었다")
        table[rule["name"]] = date
    absent = [column for column in contract["required"] if column not in table.columns]
    if absent:
        raise ContractError(f"필수 컬럼이 없다: {absent}")
    return table


def gold_task01(silver: pd.DataFrame) -> pd.DataFrame:
    """``run_task01.build_gold``의 본문."""
    silver["district_code"] = silver["district_code"].map(tf1.parse_district_code)
    silver["year_month"] = [
        tf1.to_year_month(year, month)
        for year, month in zip(silver["deal_year"], silver["deal_month"], strict=True)
    ]
    silver["price_per_m2"] = tf1.price_per_m2(silver["price_10k_krw"], silver["area_m2"])
    return tf1.aggregate_by_district_month(silver)


def gold_task03(trades: pd.DataFrame, rents: pd.DataFrame) -> pd.DataFrame:
    """``run_task03.build_gold``의 본문."""
    rents = rents[tf3.is_jeonse(rents["monthly_rent_10k_krw"])].copy()
    for frame, amount, target in (
        (trades, "price_10k_krw", "sale_price_per_m2"),
        (rents, "deposit_10k_krw", "jeonse_deposit_per_m2"),
    ):
        frame["apt_name"] = frame["apt_name"].map(tf3.normalize_apt_name)
        frame["year_month"] = [
            tf3.to_year_month(year, month)
            for year, month in zip(frame["deal_year"], frame["deal_month"], strict=True)
        ]
        frame["area_bucket"] = frame["area_m2"].map(tf3.area_bucket)
        frame[target] = tf3.unit_price(frame[amount], frame["area_m2"])
    sales = tf3.fold_to_join_keys(trades, "sale_price_per_m2", "sale_price_per_m2")
    jeonse = tf3.fold_to_join_keys(rents, "jeonse_deposit_per_m2", "jeonse_deposit_per_m2")
    return tf3.aggregate_by_district_month(tf3.join_sales_and_jeonse(sales, jeonse))


class PandasEngine:
    name = "pandas"

    def read(self, path: Path) -> pd.DataFrame:
        return pd.read_parquet(path)

    def write(self, frame: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False, compression="zstd")

    def contract(self, bronze: pd.DataFrame, dataset: str) -> pd.DataFrame:
        return apply_contract(bronze, CONTRACTS[dataset])

    def gold(self, task: str, silvers: dict[str, pd.DataFrame]) -> pd.DataFrame:
        if task == "task01":
            return gold_task01(silvers[_timing.TRADES])
        return gold_task03(silvers[_timing.TRADES], silvers[_timing.RENTS])

    def analyze(self, task: str, gold: pd.DataFrame) -> pd.DataFrame:
        return ANALYZE[task](AnalysisInput(frame=gold)).result

    def digest(self, result: pd.DataFrame) -> str:
        return output_digest(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true", help="dirty tree 허용, 결과는 .build에만")
    parser.add_argument("--tasks", nargs="+", default=list(_timing.TASKS))
    parser.add_argument("--repeats", type=int, default=_timing.MEASURED_RUNS)
    args = parser.parse_args(argv)
    if not args.pilot and (
        args.repeats != _timing.MEASURED_RUNS or args.tasks != list(_timing.TASKS)
    ):
        raise SystemExit("최종 측정은 프로토콜 그대로만 돈다 — 줄여 돌리려면 --pilot")

    layout = _timing.Layout(_timing.WORK)
    landing = json.loads((layout.root / "bronze" / "landing.json").read_text(encoding="utf-8"))
    paper_sha, paper_dirty = _timing.git_head(_timing.EXPERIMENTS.parent)
    if not args.pilot and (paper_dirty or ".dirty" in landing["builder"]):
        raise SystemExit("논문 또는 빌더 레포가 커밋과 다르다 — 커밋한 뒤 측정하라")
    environment_id, environment = _timing.environment(pandas=pd.__version__)
    engine = PandasEngine()

    for task in args.tasks:
        # S1·S2가 읽을 Silver·Gold를 이 엔진으로 만들어 둔다. 기준과 다르면 잴 이유가 없다.
        digest = engine.digest(_timing.materialized(engine, layout, task, "S3"))
        if digest != _timing.REFERENCE_HASH[task]:
            raise SystemExit(f"{task}: 결과가 기준과 다르다 ({digest[:16]})")

    rows = _timing.measure(
        engine,
        layout,
        _timing.schedule(tuple(args.tasks), repeats=args.repeats),
        {
            "paper_sha": paper_sha,
            "builder_sha": landing["builder"],
            "environment_id": environment_id,
        },
        lambda task, result: engine.digest(result) == _timing.REFERENCE_HASH[task],
    )
    wrong = [row for row in rows if not row["equivalent"]]
    out = layout.root if args.pilot else _timing.RESULTS
    prefix = "pilot_" if args.pilot else ""
    pd.DataFrame(rows).to_parquet(out / f"{prefix}timing_raw_pandas.parquet", index=False)
    (out / f"{prefix}timing_environment_pandas.json").write_text(
        json.dumps({"environment_id": environment_id, **environment}, indent=2) + "\n",
        encoding="utf-8",
    )
    if wrong:
        raise SystemExit(f"{len(wrong)}개 실행의 결과가 기준과 다르다 — 측정을 쓰지 마라")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
