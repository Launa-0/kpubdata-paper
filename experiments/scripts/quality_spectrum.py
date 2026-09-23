"""소스의 정형화 수준에 따라 RQ1 효과가 달라지는가 (#23 표 2).

같은 잣대를 네 데이터셋에 적용한다. 계층화가 품질을 얼마나 개선하는지는 데이터마다
다를 것이고, 그 차이가 원천의 표현 방식으로 설명되는지가 이 표가 묻는 것이다.

## 측정 대상 컬럼을 사람이 고르지 않는다

이전 판은 데이터셋마다 컬럼 다섯 개를 손으로 골랐다. 그러면 표가 데이터가 아니라
**고른 사람**을 재게 된다 — 쉼표 낀 금액 컬럼을 넣으면 Bronze 적합률이 0이 되고,
빼면 0.94가 된다. 같은 데이터에서 둘 다 나온다.

그래서 컬럼은 **각 데이터셋의 Silver 계약에서 자동으로 유도한다.**

- ``rename``이 Bronze 이름 ↔ Silver 이름 대응을 준다. 역할(role)은 Silver 이름이다.
- ``casts``가 선언된 필드는 **그 캐스팅이 기대 타입**이다 (``int``/``float``/
  ``int_comma``/``float_comma`` → numeric, ``date``/``datetime`` → date).
- ``casts``에만 있고 ``rename``에 없는 필드는 양쪽에서 이름이 같다.
- ``derived`` 필드는 Bronze에 존재하지 않으므로 **짝 비교에서 빼고** Silver 단독으로
  따로 보고한다.

계약이 타입을 선언하지 않은 컬럼은 ``text``다. ``code``로 두지 않는 이유가 있다 —
``code``는 ``valid_codes`` 없이는 "문자열이 문자열로 읽히는가"만 보므로 **무조건
통과**하는데, ``TYPED_KINDS``에는 들어간다. 즉 code 컬럼을 늘릴수록
``type_consistency``의 분모가 확실히 통과하는 값으로 채워져 점수가 올라간다. 고르는
자유를 없애려고 쓴 스크립트가 다른 손잡이를 만들면 안 된다.

## 데이터셋마다 다른 규칙을 두지 않는다

predicate도, 데이터셋별 예외도 없다. 어떤 데이터셋이 나쁘게 나오도록 만드는 규칙을
하나라도 넣으면 이 표는 측정이 아니라 주장이 된다. 계약이 선언한 것만 쓴다.

## 세 가지를 따로 보고한다

``row-level``
    H1의 primary다. 계약의 모든 컬럼을 한 spec으로 재므로 ``schema_conformance``와
    ``parsing_failure_rate``가 레코드 단위로 나온다.
``per-column``
    어느 컬럼이 그 숫자를 만들었는지. 진단용이다.
``column-macro``
    컬럼별 값의 단순 평균. **diagnostic이며 H1 primary로 쓰지 않는다** — 컬럼 수와
    컬럼 구성이 데이터셋마다 달라서, 평균은 "컬럼 하나가 평균적으로 얼마나 깨끗한가"
    이지 "이 데이터셋이 얼마나 깨끗한가"가 아니다.

Bronze는 **저장된 표현 그대로** 읽는다. 과제의 파서를 Bronze에 주면 "파이프라인이
읽을 수 있는 것"을 재게 되어 Bronze가 실제보다 깨끗해 보인다.

**harness 가상환경에서 실행한다.** 전수를 읽으므로 rent에서 3 GiB 가까이 쓴다 —
데이터셋을 하나씩 처리하고 사이에서 해제한다.
"""

from __future__ import annotations

import argparse
import gc
import importlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS  # noqa: E402

from kpx.datasets import read_artifact  # noqa: E402
from kpx.metrics.quality import (  # noqa: E402
    TABLE2_METRICS,
    ColumnSpec,
    QualityReport,
    QualitySpec,
    measure_quality,
)

#: 계약이 선언할 수 있는 캐스팅 → 품질 지표가 기대할 타입.
#: 선언되지 않은 것은 text다 (모듈 docstring 참조).
CAST_KINDS: dict[str, str] = {
    "int": "numeric",
    "int64": "numeric",
    "int_comma": "numeric",
    "float": "numeric",
    "float64": "numeric",
    "float_comma": "numeric",
    "date": "date",
    "datetime": "date",
}

SPEC_MODULES = ("trades_spec", "rent_spec", "bike_spec")


def column_plan(contract: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """계약에서 ``{Bronze 이름: Silver 이름}``, ``{Silver 이름: kind}``, derived를 얻는다."""
    rename: dict[str, str] = dict(contract.get("rename", {}))
    casts: dict[str, str] = dict(contract.get("casts", {}))
    derived = {str(column["name"]) for column in contract.get("derived", ())}

    pairs = dict(rename)
    # 캐스팅만 선언되고 이름은 그대로인 컬럼 (예: trades의 floor).
    for name in casts:
        if name not in derived and name not in pairs.values():
            pairs[name] = name

    kinds = {silver: CAST_KINDS.get(casts.get(silver, ""), "text") for silver in pairs.values()}
    kinds.update({name: CAST_KINDS.get(casts.get(name, ""), "text") for name in derived})
    return pairs, kinds, derived


def layer_spec(
    names: dict[str, str], kinds: dict[str, str], required: set[str], present: set[str]
) -> QualitySpec:
    """``{역할: 이 계층에서의 컬럼명}``을 QualitySpec으로.

    ``required``는 Silver 이름으로 선언되므로 역할과 같은 축에서 읽는다.
    """
    return QualitySpec(
        columns=tuple(
            ColumnSpec(
                column=column,
                role=role,
                kind=kinds.get(role, "text"),  # type: ignore[arg-type]
                required=role in required,
            )
            for role, column in sorted(names.items())
            if column in present
        )
    )


def per_column(frame: pd.DataFrame, spec: QualitySpec) -> dict[str, QualityReport]:
    """컬럼 하나짜리 spec을 반복해 컬럼별 지표를 낸다."""
    reports: dict[str, QualityReport] = {}
    for column in spec.columns:
        single = QualitySpec(columns=(ColumnSpec(**{**column.__dict__, "required": True}),))
        reports[column.role] = measure_quality(frame, single, layer="bronze")
    return reports


def macro(reports: dict[str, QualityReport]) -> dict[str, float | None]:
    """컬럼별 값의 단순 평균 — diagnostic."""
    out: dict[str, float | None] = {}
    for metric in TABLE2_METRICS:
        values = [r.metric(metric) for r in reports.values()]
        kept = [v for v in values if v is not None]
        out[metric] = sum(kept) / len(kept) if kept else None
    return out


def sample(frame: pd.DataFrame, rows: int | None) -> pd.DataFrame:
    """계통 표본. 앞에서 자르지 않는다.

    원천은 수집 순서(자치구 x 월)로 쌓여 있어 앞부분이 표본이 아니다. 간격을 두고
    뽑으면 그 치우침이 없다. ``rows``가 없으면 전수다.
    """
    if not rows or len(frame) <= rows:
        return frame
    return frame.iloc[:: max(1, len(frame) // rows)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument(
        "--rows",
        type=int,
        default=None,
        metavar="N",
        help="계통 표본으로 N행만 읽는다 (기본: 전수). 메모리가 모자랄 때만 쓴다.",
    )
    args = parser.parse_args(argv)

    summary: list[dict[str, Any]] = []
    for module_name in SPEC_MODULES:
        try:
            spec_module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            print(f"[skip] {module_name}: 모듈이 없다")
            continue
        spec = spec_module.SPEC
        dataset, alias = spec["dataset_id"], spec["source"]["alias"]
        contract = spec["contract"]
        required = set(contract.get("required", ()))
        pairs, kinds, derived = column_plan(contract)

        silver_path = args.work_root / "runs" / spec["run_id"] / "silver" / alias / "table.parquet"
        if not silver_path.exists():
            print(f"[skip] {dataset}: Silver가 없다 ({silver_path})")
            continue

        source = args.snapshots / spec["snapshot_id"] / "source" / "raw_records.jsonl"
        if not source.exists():
            raise SystemExit(f"{dataset}: 선언된 스냅샷이 없다 ({source})")
        raw = pd.read_json(source, lines=True, dtype=False, convert_dates=False)
        bronze = sample(raw, args.rows)
        # 두 계층을 같은 비율로 줄인다. 한쪽만 줄이면 duplicate_rate가 표본 크기
        # 차이를 재게 된다 — 작은 표본에서 중복이 덜 잡히는 것은 데이터의 성질이
        # 아니다.
        silver = sample(read_artifact(silver_path), args.rows)

        bronze_names = {silver_name: b for b, silver_name in pairs.items()}
        silver_names = {silver_name: silver_name for silver_name in pairs.values()}
        b_spec = layer_spec(bronze_names, kinds, required, set(bronze.columns))
        s_spec = layer_spec(silver_names, kinds, required, set(silver.columns))

        print(f"\n{'=' * 78}\n{dataset}")
        print(
            f"  Bronze {len(bronze):,}행 x {bronze.shape[1]}컬럼   "
            f"Silver {len(silver):,}행 x {silver.shape[1]}컬럼   "
            f"짝지은 컬럼 {len(b_spec.columns)}개"
            + (f", derived {len(derived)}개" if derived else "")
        )

        reports = {
            "bronze": measure_quality(bronze, b_spec, layer="bronze"),
            "silver": measure_quality(silver, s_spec, layer="silver"),
        }
        print("\n  -- row-level (H1 primary) --")
        print(
            pd.DataFrame(
                [
                    {"Metric": m, **{k: r.metric(m) for k, r in reports.items()}}
                    for m in TABLE2_METRICS
                ]
            ).to_string(index=False, na_rep="—")
        )
        # duplicate_rate는 key 없이 전체 행으로 센다. 두 계층의 컬럼 집합이 다르면
        # 계층 간 차이를 그대로 품질 변화로 읽을 수 없다 — 컬럼이 줄어드는 것만으로도
        # 중복은 늘 수 있다. 진단값이라는 사실을 표 옆에 적어 둔다. 표만 보는 사람에게
        # docstring은 닿지 않는다.
        if bronze.shape[1] != silver.shape[1]:
            print(
                f"     [!] duplicate_rate는 진단값이다 — 전체 행으로 세는데 Bronze "
                f"{bronze.shape[1]}컬럼 / Silver {silver.shape[1]}컬럼으로 잣대가 다르다. "
                "차이는 레코드 쌍을 직접 확인하고 해석한다."
            )

        b_cols = per_column(bronze, b_spec)
        s_cols = per_column(silver, s_spec)
        print("\n  -- per-column (진단) --")
        print(
            pd.DataFrame(
                [
                    {
                        "Column": role,
                        "kind": kinds.get(role, "text"),
                        "bronze_parse_fail": b_cols[role].metric("parsing_failure_rate"),
                        "silver_parse_fail": s_cols[role].metric("parsing_failure_rate"),
                        "bronze_missing": b_cols[role].metric("missing_rate"),
                        "silver_missing": s_cols[role].metric("missing_rate"),
                    }
                    for role in sorted(b_cols)
                    if role in s_cols
                ]
            ).to_string(index=False, na_rep="—")
        )

        if derived:
            present = {name: name for name in derived}
            d_spec = layer_spec(present, kinds, required, set(silver.columns))
            if d_spec.columns:
                d_report = measure_quality(silver, d_spec, layer="silver")
                print("\n  -- derived-only (Bronze에 대응 없음, 짝 비교에서 제외) --")
                print(
                    f"     {sorted(derived)}: "
                    + ", ".join(
                        f"{m}={d_report.metric(m)}"
                        for m in ("missing_rate", "parsing_failure_rate")
                    )
                )

        b_macro, s_macro = macro(b_cols), macro(s_cols)
        print("\n  -- column-macro (diagnostic, H1 primary 아님) --")
        print(
            "     "
            + "  ".join(
                f"{m}: {b_macro[m]:.3f}->{s_macro[m]:.3f}"
                for m in ("parsing_failure_rate", "type_consistency", "schema_conformance")
                if b_macro[m] is not None and s_macro[m] is not None
            )
        )

        row: dict[str, Any] = {
            "Dataset": dataset,
            "Columns": len(b_spec.columns),
            "Required": len(b_spec.required),
        }
        for metric in ("parsing_failure_rate", "type_consistency", "schema_conformance"):
            before, after = reports["bronze"].metric(metric), reports["silver"].metric(metric)
            row[metric] = "—" if before is None or after is None else f"{before:.3f} -> {after:.3f}"
        summary.append(row)

        # raw까지 놓아야 한다 — 표본을 안 뜨면 bronze가 raw와 같은 객체라,
        # bronze만 지우면 참조가 남아 다음 데이터셋에서 메모리가 겹친다.
        del raw, bronze, silver, b_cols, s_cols, reports
        gc.collect()

    print()
    print("=" * 78)
    print("정형화 수준 스펙트럼 — row-level (H1 primary)")
    print()
    print(pd.DataFrame(summary).to_string(index=False))
    print()
    print("컬럼은 각 데이터셋의 Silver 계약에서 유도했다. 손으로 고른 것이 없다.")
    print("required는 docs/required-columns.md의 규칙(식별자 + 시점 + 주된 사실)을 따른다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
