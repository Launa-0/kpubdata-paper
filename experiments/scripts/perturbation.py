"""RQ3 계약 경계 — 고정 계약에 통제된 표현 섭동을 주입하고 빌드의 행동을 잰다.

**builder 가상환경**에서 실행한다. 계약(trades_spec/bike_spec)은 건드리지 않는다.

    $BUILDER scripts/perturbation.py                      # 최종: clean tree가 아니면 멈춘다
    $BUILDER scripts/perturbation.py --pilot --only T-P00  # 동작 확인

두 가지를 남긴다.

- ``results/perturbation.parquet`` — mutation마다 빌드가 거부했는가, 수용했다면 기준
  Silver와 같은가, 경고가 있었는가, 같은 계약을 메모리에서 적용한 대조(``run_mono``)가
  같은 판정을 냈는가.
- ``results/perturbation_counterfactual.json`` — 계약 언어가 **이미 지원하는** 규칙(범위,
  ``max_null_ratio``, 컬럼 비교)을 추가로 선언했다면 무엇이 표시됐을지. 규칙은 실행 전에
  아래 ``POLICY``에 고정했고, 계약 자체는 바꾸지 않는다. 이것이 "선언된 제약 / 표현
  가능하지만 선언하지 않은 제약 / 표현할 수 없는 제약"을 가르는 근거다.

mutation 집합, 표본 추출, 판정 규칙, 반사실 규칙은 설계를 확정한 그대로다.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
sys.path.insert(0, str(HERE))

import _builder_identity  # noqa: E402
import bike_spec  # noqa: E402
import trades_spec  # noqa: E402

try:
    import polars as pl
except ModuleNotFoundError:  # --help는 harness 환경(CI)에서도 돌아야 한다.
    pl = None

WORK = EXPERIMENTS / ".build" / "perturbation"
RESULTS = EXPERIMENTS / "results"
MAX_ROWS = 5000
SOURCES = {
    "trades": (
        EXPERIMENTS
        / "snapshots/seoul-apartment-trades/20260922-6660c8e25162/source/raw_records.jsonl",
        233_596,
    ),
    "bike": (
        EXPERIMENTS
        / "snapshots/seoul-bike-rent-month-g1/20260923-e91d2c485eaf/source/raw_records.jsonl",
        327_231,
    ),
}
SPECS = {"trades": trades_spec, "bike": bike_spec}


# ---------------------------------------------------------------- fixtures
def fixture(name: str) -> list[dict]:
    path = WORK / "fixtures" / f"{name}.jsonl"
    if not path.exists():
        source, total = SOURCES[name]
        step = math.ceil(total / MAX_ROWS)
        path.parent.mkdir(parents=True, exist_ok=True)
        with source.open(encoding="utf-8") as src, path.open("w", encoding="utf-8") as out:
            for i, line in enumerate(src):  # 스트리밍 — 원천 전체를 메모리에 올리지 않는다
                if i % step == 0:
                    out.write(line if line.endswith("\n") else line + "\n")
    return [json.loads(line) for line in path.open(encoding="utf-8")]


# ---------------------------------------------------------------- mutations
# 각 함수는 레코드 사본 리스트를 받아 제자리에서 바꾸고, 바뀐 셀 수를 돌려준다.
def _map(rows, cols, fn):
    n = 0
    for r in rows:
        for c in cols:
            if c in r:
                new = fn(r[c])
                if new is not _SKIP and (new != r[c] or type(new) is not type(r[c])):
                    r[c] = new
                    n += 1
    return n


_SKIP = object()


def _rename(rows, old, new):
    n = 0
    for r in rows:
        if old in r:
            r[new] = r.pop(old)
            n += 1
    return n


def _drop(rows, *cols):
    return sum(1 for r in rows for c in cols if r.pop(c, _SKIP) is not _SKIP)


def _swap(rows, a, b):
    for r in rows:
        r[a], r[b] = r[b], r[a]
    return sum(1 for r in rows if r[a] != r[b])


def _alternate(rows, col, fn):
    n = 0
    for i, r in enumerate(rows):
        if i % 2 == 0 and r.get(col) is not None:
            r[col] = fn(r[col])
            n += 1
    return n


def _reverse_keys(rows):
    for i, r in enumerate(rows):
        rows[i] = dict(reversed(list(r.items())))
    return len(rows)


def _add_rnum(rows):
    for i, r in enumerate(rows):
        r["RNUM"] = str(i + 1)
    return len(rows)


def _nth_null(rows, col, token):
    n = 0
    for i, r in enumerate(rows):
        if i % 10 == 0:
            r[col] = token
            n += 1
    return n


def _scale_comma(factor):
    return lambda v: f"{int(v.replace(',', '')) * factor:,}" if isinstance(v, str) else _SKIP


def _num(v):
    if isinstance(v, str) and v not in ("", "\\N"):
        return float(v)
    return _SKIP


def _int_str(v):
    return int(v) if isinstance(v, str) and v.isdigit() else _SKIP


def _to_str(v):
    return str(v) if isinstance(v, int) and not isinstance(v, bool) else _SKIP


TEXT_NULLABLE = (
    "aptDong",
    "cdealType",
    "cdealDay",
    "dealingGbn",
    "estateAgentSggNm",
    "rgstDate",
    "slerGbn",
    "buyerGbn",
)


def _g4_split(rows):
    for r in rows:
        v = r.pop("이용건수")
        r["대여건수"] = v
        r["반납건수"] = v
    return len(rows)


def _alias_into(rows):
    for r in rows:
        r.pop("이동거리")
        r["이동거리(M)"] = r["운동량"]
    return len(rows)


def _next_month(v):
    y, m = int(v[:4]), int(v[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}"


def _alias_conflict(rows):
    for r in rows:
        r["대여년월"] = _next_month(r["대여일자"])
    return len(rows)


MUTATIONS = {
    # ------------------------------------------------ trades
    "T-P00": ("trades", "P", lambda rs: len(rs)),  # identity: 재직렬화만
    "T-P01": (
        "trades",
        "P",
        lambda rs: _map(rs, ["dealAmount"], lambda v: int(v.replace(",", ""))),
    ),
    "T-P02": ("trades", "P", lambda rs: _map(rs, ["dealAmount"], lambda v: v.replace(",", ""))),
    "T-P03": (
        "trades",
        "P",
        lambda rs: _alternate(rs, "dealAmount", lambda v: int(v.replace(",", ""))),
    ),
    "T-P04": ("trades", "P", lambda rs: _map(rs, ["floor"], _to_str)),
    "T-P05": ("trades", "P", lambda rs: _alternate(rs, "floor", str)),
    "T-P06": ("trades", "P", lambda rs: _map(rs, ["dealYear", "dealMonth", "dealDay"], _to_str)),
    "T-P07": ("trades", "P", lambda rs: _map(rs, ["excluUseAr"], _num)),
    "T-P08": ("trades", "P", lambda rs: _map(rs, ["sggCd", "umdCd"], _to_str)),
    "T-P09": ("trades", "P", lambda rs: _map(rs, ["jibun"], _int_str)),
    "T-P10": (
        "trades",
        "P",
        lambda rs: _map(rs, TEXT_NULLABLE, lambda v: "" if v is None else _SKIP),
    ),
    "T-P11": ("trades", "P", _reverse_keys),
    "T-P12": ("trades", "P", _add_rnum),
    "T-B01": ("trades", "B", lambda rs: _drop(rs, "dealAmount")),
    "T-B02": ("trades", "B", lambda rs: _drop(rs, "dealDay")),
    "T-B03": ("trades", "B", lambda rs: _drop(rs, "sggCd")),
    "T-B04": ("trades", "B", lambda rs: _map(rs, ["dealAmount"], _scale_comma(10))),
    "T-B05": ("trades", "B", lambda rs: _map(rs, ["dealAmount"], _scale_comma(10_000))),
    "T-B06": (
        "trades",
        "B",
        lambda rs: _map(rs, ["excluUseAr"], lambda v: f"{float(v) / 3.305785:.2f}"),
    ),
    "T-B07": ("trades", "B", lambda rs: _swap(rs, "dealAmount", "excluUseAr")),
    "T-B08": ("trades", "B", lambda rs: _rename(rs, "dealAmount", "deposit")),
    "T-B09": ("trades", "B", lambda rs: _swap(rs, "dealMonth", "dealDay")),
    "T-B10": ("trades", "B", lambda rs: _nth_null(rs, "dealAmount", None)),
    # ------------------------------------------------ bike (G1)
    "B-P00": ("bike", "P", lambda rs: len(rs)),
    "B-P01": ("bike", "P", lambda rs: _map(rs, ["성별"], lambda v: "" if v == "\\N" else _SKIP)),
    "B-P02": ("bike", "P", lambda rs: _map(rs, ["성별"], lambda v: "\\N" if v == "" else _SKIP)),
    "B-P03": (
        "bike",
        "P",
        lambda rs: _map(
            rs, ["성별", "운동량", "탄소량"], lambda v: None if v in ("\\N", "") else _SKIP
        ),
    ),
    "B-P04": (
        "bike",
        "P",
        lambda rs: _map(rs, ["운동량", "탄소량"], lambda v: "" if v == "\\N" else _SKIP),
    ),
    "B-P05": ("bike", "P", lambda rs: _map(rs, ["대여소번호"], lambda v: v.zfill(5))),
    "B-P06": ("bike", "P", lambda rs: _map(rs, ["대여소번호"], lambda v: v.lstrip("0") or "0")),
    "B-P07": ("bike", "P", lambda rs: _map(rs, ["대여소번호"], int)),
    "B-P08": ("bike", "P", lambda rs: _map(rs, ["대여일자"], lambda v: v.replace("-", ""))),
    "B-P09": ("bike", "P", lambda rs: _map(rs, ["대여일자"], lambda v: int(v.replace("-", "")))),
    "B-P10": ("bike", "P", lambda rs: _alternate(rs, "대여일자", lambda v: v.replace("-", ""))),
    "B-P11": ("bike", "P", lambda rs: _rename(rs, "대여일자", "대여년월")),
    "B-P12": (
        "bike",
        "P",
        lambda rs: _rename(rs, "이동거리", "이동거리(M)") + _rename(rs, "이용시간", "이용시간(분)"),
    ),
    "B-P13": (
        "bike",
        "P",
        lambda rs: _rename(rs, "이동거리", "이용거리(M)") + _rename(rs, "이용시간", "이용시간(본)"),
    ),
    "B-P14": ("bike", "P", _reverse_keys),
    "B-P15": ("bike", "P", _add_rnum),
    "B-P16": ("bike", "P", lambda rs: _map(rs, ["이용건수"], int)),
    "B-P17": ("bike", "P", lambda rs: _map(rs, ["이동거리", "이용시간"], _num)),
    "B-B01": ("bike", "B", lambda rs: _drop(rs, "이용건수")),
    "B-B02": ("bike", "B", lambda rs: _drop(rs, "대여소번호")),
    "B-B03": ("bike", "B", lambda rs: _drop(rs, "성별", "연령대코드")),
    "B-B04": ("bike", "B", _g4_split),
    "B-B05": ("bike", "B", lambda rs: _map(rs, ["이동거리"], lambda v: f"{float(v) / 1000:g}")),
    "B-B06": ("bike", "B", lambda rs: _swap(rs, "이동거리", "이용시간")),
    "B-B07": ("bike", "B", _alias_into),
    "B-B08": ("bike", "B", lambda rs: _map(rs, ["대여일자"], lambda v: f"{v}-15")),
    "B-B09": ("bike", "B", _alias_conflict),
    "B-B10": ("bike", "B", lambda rs: _nth_null(rs, "이용건수", "\\N")),
}


# ---------------------------------------------------------------- build
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def emit(self, record):
        msg = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            msg += f" | {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        (self.errors if record.levelno >= logging.ERROR else self.warnings).append(msg)


STAGES = [
    ("heterogeneous column types", "silver/tabularize"),
    ("integer precision loss", "silver/tabularize"),
    ("column_null_tokens", "silver/null_tokens"),
    ("coalesce", "silver/coalesce"),
    ("declared rename", "silver/rename"),
    ("zfill", "silver/zfill"),
    ("year_month", "silver/cast"),
    ("declared cast dropped", "silver/cast"),
    ("Cannot cast missing column", "silver/cast"),
    ("derived column", "silver/derived"),
    ("필수 컬럼", "silver/validation"),
    ("quality check failed", "quality"),
]


def classify(message: str, completed: tuple[str, ...]) -> str:
    for needle, stage in STAGES:
        if needle in message:
            return stage
    if "bronze" not in completed:
        return "bronze"
    if "silver" in completed:
        return "gold/export"
    return "other"


def run_one(ds: str, run_id: str, rows: list[dict]) -> dict:
    from _upload_store import FileUploadRepository
    from kpubdata_builder.pipeline import run_build

    spec_mod = SPECS[ds]
    root = WORK / "runs" / ds
    run_dir = root / "runs" / run_id
    uploads = root / "uploads" / run_id
    for stale in (run_dir, uploads):
        if stale.exists():
            shutil.rmtree(stale)
    content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
    repo = FileUploadRepository(uploads)
    upload = repo.put(
        "paper-experiment",
        content=content,
        format="jsonl",
        encoding="utf-8",
        original_filename="raw_records.jsonl",
    )
    cap = _Capture()
    log = logging.getLogger("kpubdata_builder")
    log.addHandler(cap)
    started = time.perf_counter()
    try:
        result = run_build(
            spec_mod.build_spec(upload.upload_id, description=f"C2 {run_id}"),
            client=None,
            output_root=root / "runs",
            run_id=run_id,
            owner_id="paper-experiment",
            upload_repository=repo,
        )
    finally:
        log.removeHandler(cap)
    outcome = result.outcomes[0]
    silver_path = run_dir / "silver" / spec_mod.ALIAS / "table.parquet"
    table = (
        pl.read_parquet(silver_path) if outcome.status == "ok" and silver_path.exists() else None
    )
    message = " || ".join([outcome.error or ""] + cap.errors)
    return {
        "status": outcome.status,
        "stages_completed": ",".join(outcome.stages_completed),
        "failure_stage": None
        if outcome.status == "ok"
        else classify(message, outcome.stages_completed),
        "error": None if outcome.status == "ok" else message[:600],
        "warnings": " || ".join(cap.warnings)[:1200] or None,
        "seconds": round(time.perf_counter() - started, 2),
        "_table": table,
        "_run_dir": run_dir,
        "_uploads": uploads,
    }


def run_mono(ds: str, rows: list[dict]):
    """monolithic 대조군: Bronze 영속화·manifest·drift 없이 같은 계약으로 메모리에서 정규화."""
    from kpubdata_builder.stages.silver.build import build_silver_dataset

    spec = SPECS[ds].build_spec("mono", description="mono")
    s = spec.sources[0].schema
    try:
        silver = build_silver_dataset(
            SimpleNamespace(raw_records=rows, source_key=SPECS[ds].ALIAS),
            required_columns=s.required,
            casts=s.casts,
            rename=s.rename,
            derived=s.derived,
            read_as=s.read_as,
            null_tokens=s.null_tokens,
            column_null_tokens=s.column_null_tokens,
            coalesce=s.coalesce,
            zfill=s.zfill,
            column_dtypes=s.dtypes,
        )
    except Exception as exc:  # noqa: BLE001 — 판정 자체가 측정값이다
        return "failed", None, f"{type(exc).__name__}: {exc}"[:600]
    if not silver.validation.ok:
        return "failed", None, "; ".join(p.message for p in silver.validation.problems)
    return "ok", silver.table, None


def compare(base: pl.DataFrame, other: pl.DataFrame) -> dict:
    missing = [c for c in base.columns if c not in other.columns]
    diff_cols, diff_cells = list(missing), 0
    if other.height != base.height:
        return {
            "equivalent": False,
            "diff_columns": ",".join(base.columns),
            "diff_cells": None,
            "extra_columns": ",".join(c for c in other.columns if c not in base.columns),
            "column_order_same": False,
            "rows_out": other.height,
        }
    for c in base.columns:
        if c in missing:
            continue
        a, b = base[c], other[c]
        if a.dtype != b.dtype:
            diff_cols.append(f"{c}[{a.dtype}->{b.dtype}]")
            diff_cells += base.height
            continue
        n = int((~(a.eq_missing(b))).sum())
        if n:
            diff_cols.append(c)
            diff_cells += n
    return {
        "equivalent": not diff_cols,
        "diff_columns": ",".join(diff_cols) or None,
        "diff_cells": diff_cells,
        "extra_columns": ",".join(c for c in other.columns if c not in base.columns) or None,
        "column_order_same": [c for c in other.columns if c in base.columns] == base.columns,
        "rows_out": other.height,
    }


def observed_class(r: dict) -> str:
    if r["status"] != "ok":
        return "reject"
    return ("accept_equiv" if r["equivalent"] else "accept_nonequiv") + (
        "_warn" if r["warnings"] else ""
    )


def verdict(kind: str, obs: str) -> str:
    if kind == "P":
        return {"reject": "false_reject"}.get(
            obs, "correct_accept" if obs.startswith("accept_equiv") else "silent_corruption"
        )
    if obs == "reject":
        return "correct_reject"
    return "warned" if obs.endswith("_warn") else "false_accept"


# ---------------------------------------------------------------- counterfactual
def _policy() -> dict:
    """계약 언어가 이미 지원하는 규칙. 실행 전에 고정한 그대로다.

    - 범위 = 동결된 전체 Silver의 min/max(데이터에 맞춰 규칙을 쓰는 저자가 쓸 값)와
      ``deal_month``/``deal_day``의 달력 범위
    - 전체 Silver에서 0% null인 required 사실에 ``max_null_ratio`` 0
    - 따릉이에 컬럼 비교 하나(``distance_m >= duration_min``) — 기준 위반율과 함께 본다
    """
    from kpubdata_builder.spec.models import CompareColumnsRule, QualityPolicy, RangeRule

    full_t = pl.read_parquet(
        EXPERIMENTS / ".build/runs/trades-silver-001/silver/trades/table.parquet"
    )
    full_b = pl.read_parquet(EXPERIMENTS / ".build/runs/bike-t4-silver/silver/bike/table.parquet")

    def rng(df, c):
        return RangeRule(column=c, min=float(df[c].min()), max=float(df[c].max()))

    return {
        "trades": QualityPolicy(
            range=(
                rng(full_t, "price_10k_krw"),
                rng(full_t, "area_m2"),
                RangeRule(column="deal_month", min=1, max=12),
                RangeRule(column="deal_day", min=1, max=31),
            ),
            max_null_ratio={"price_10k_krw": 0.0, "area_m2": 0.0, "deal_date": 0.0},
        ),
        "bike": QualityPolicy(
            range=(
                rng(full_b, "use_count"),
                rng(full_b, "distance_m"),
                rng(full_b, "duration_min"),
            ),
            max_null_ratio={"use_count": 0.0, "station_code": 0.0, "ym_raw": 0.0},
            compare_columns=(
                CompareColumnsRule(left="distance_m", operator="gte", right="duration_min"),
            ),
        ),
    }


def _silver_of(ds, rows):
    from kpubdata_builder.stages.silver.build import build_silver_dataset

    s = SPECS[ds].build_spec("cf", description="cf").sources[0].schema
    return build_silver_dataset(
        SimpleNamespace(raw_records=rows, source_key=SPECS[ds].ALIAS),
        required_columns=s.required,
        casts=s.casts,
        rename=s.rename,
        derived=s.derived,
        read_as=s.read_as,
        null_tokens=s.null_tokens,
        column_null_tokens=s.column_null_tokens,
        coalesce=s.coalesce,
        zfill=s.zfill,
        column_dtypes=s.dtypes,
    )


def counterfactual(selected: list[str], fixtures: dict) -> dict:
    from kpubdata_builder.quality import evaluate_quality

    policy = _policy()
    out = {"policy": {k: repr(v) for k, v in policy.items()}, "results": {}}
    for mid in selected:
        ds, kind, fn = MUTATIONS[mid]
        rows = [dict(r) for r in fixtures[ds]]
        fn(rows)
        try:
            silver = _silver_of(ds, rows)
        except Exception as exc:  # noqa: BLE001
            out["results"][mid] = {"kind": kind, "status": "rejected", "error": str(exc)[:160]}
            continue
        res = evaluate_quality(silver, policy[ds], source_key=ds)
        flagged = [
            f"{r.rule}:{r.column}:{r.affected_rows if r.affected_rows is not None else r.actual}"
            for r in res
            if r.status != "pass"
        ]
        rec = {"kind": kind, "status": "accepted", "flags": flagged}
        if mid == "T-B09":
            t = silver.table
            base = _silver_of("trades", [dict(r) for r in fixtures["trades"]]).table
            mutated = ~(base["deal_month"] == base["deal_day"])
            rec["deal_date_null"] = int(t["deal_date"].null_count())
            rec["deal_date_wrong_nonnull"] = int(
                (t["deal_date"].is_not_null() & (t["deal_date"] != base["deal_date"])).sum()
            )
            rec["unchanged_because_month_eq_day"] = int((~mutated).sum())
            rec["null_but_both_le_12"] = int(
                (t["deal_date"].is_null() & (t["deal_month"] <= 12)).sum()
            )
        out["results"][mid] = rec
        print(mid, kind, rec, flush=True)
    return out


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="", help="쉼표로 구분한 mutation id (파일럿)")
    parser.add_argument("--pilot", action="store_true", help="dirty tree 허용, 결과는 .build에만")
    parser.add_argument("--determinism", action="store_true", help="기준 빌드를 두 번 돌려 비교")
    args = parser.parse_args(argv)
    if pl is None:
        raise SystemExit("polars가 없다 — builder 가상환경에서 실행하라")
    if args.only and not args.pilot:
        raise SystemExit("최종 실행은 전체 mutation으로만 돈다 — 줄여 돌리려면 --pilot")

    import _timing

    builder = _builder_identity.as_version(_builder_identity.capture())
    paper_sha, paper_dirty = _timing.git_head(EXPERIMENTS.parent)
    if not args.pilot and (paper_dirty or ".dirty" in str(builder)):
        raise SystemExit("논문 또는 빌더 레포가 커밋과 다르다 — 커밋한 뒤 실행하라")
    for run in ("trades-silver-001", "bike-t4-silver"):
        built_by = _builder_identity.as_version(
            _builder_identity.read(EXPERIMENTS / ".build/runs" / run)
        )
        if built_by != builder and not args.pilot:
            raise SystemExit(
                f"반사실 범위를 정하는 {run}이 다른 빌더({built_by})로 빌드됐다 — 다시 빌드하라"
            )

    selected = [m for m in MUTATIONS if not args.only or m in args.only.split(",")]
    datasets = sorted({MUTATIONS[m][0] for m in selected})
    fixtures = {ds: fixture(ds) for ds in datasets}
    baselines = {}
    for ds in datasets:
        print(f"[{ds}] fixture rows={len(fixtures[ds])}", flush=True)
        # 기준 run은 지우지 않는다 — drift 감지의 비교 상대가 된다.
        base = run_one(ds, "baseline", [dict(r) for r in fixtures[ds]])
        assert base["status"] == "ok", base["error"]
        baselines[ds] = base["_table"]
        print(
            f"[{ds}] baseline ok rows={base['_table'].height} warnings={base['warnings']}",
            flush=True,
        )
        if args.determinism:
            again = run_one(ds, "baseline-again", [dict(r) for r in fixtures[ds]])
            print(
                f"[{ds}] determinism equal={again['_table'].equals(base['_table'])} "
                f"warnings={again['warnings']}",
                flush=True,
            )
            shutil.rmtree(again["_run_dir"])
            shutil.rmtree(again["_uploads"])

    records = []
    for mid in selected:
        ds, kind, fn = MUTATIONS[mid]
        rows = [dict(r) for r in fixtures[ds]]
        try:
            n_mut = fn(rows)
        except Exception:  # 하네스 버그는 숨기지 않는다
            traceback.print_exc()
            raise
        r = run_one(ds, mid, rows)
        table = r.pop("_table")
        rec = {
            "mutation": mid,
            "dataset": ds,
            "kind": kind,
            "n_rows_in": len(rows),
            "n_cells_mutated": n_mut,
            "vacuous": n_mut == 0,
            **{k: v for k, v in r.items() if not k.startswith("_")},
        }
        if table is not None:
            rec.update(compare(baselines[ds], table))
        else:
            rec.update(
                {
                    "equivalent": None,
                    "diff_columns": None,
                    "diff_cells": None,
                    "extra_columns": None,
                    "column_order_same": None,
                    "rows_out": 0,
                }
            )
        rec["observed"] = observed_class(rec)
        rec["verdict"] = verdict(kind, rec["observed"])
        mono_status, mono_table, mono_error = run_mono(ds, [dict(x) for x in rows])
        rec["mono_status"] = mono_status
        rec["mono_error"] = mono_error
        same_status = mono_status == rec["status"]
        rec["mono_equals_build"] = same_status and (
            mono_table is None or table is None or mono_table.equals(table)
        )
        shutil.rmtree(r["_run_dir"], ignore_errors=True)
        shutil.rmtree(r["_uploads"], ignore_errors=True)
        records.append(rec)
        print(
            f"{mid} {kind} n_mut={n_mut} status={rec['status']} stage={rec['failure_stage']} "
            f"equiv={rec['equivalent']} obs={rec['observed']} verdict={rec['verdict']} "
            f"mono={mono_status}/{rec['mono_equals_build']}\n    diff={rec['diff_columns']} "
            f"extra={rec['extra_columns']}\n    warn={rec['warnings']}\n    err={rec['error']}",
            flush=True,
        )
        del table

    out = WORK if args.pilot else RESULTS
    prefix = "pilot_" if args.pilot else ""
    df = pl.DataFrame(records, infer_schema_length=None).with_columns(
        pl.lit(builder).alias("builder"), pl.lit(paper_sha).alias("paper_sha")
    )
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / f"{prefix}perturbation.parquet")
    print(f"wrote {out / f'{prefix}perturbation.parquet'} ({df.height} rows)")

    cf = counterfactual(selected, fixtures)
    cf.update({"builder": builder, "paper_sha": paper_sha})
    (out / f"{prefix}perturbation_counterfactual.json").write_text(
        json.dumps(cf, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
