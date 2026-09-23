"""소스의 정형화 수준에 따라 RQ1 효과가 달라지는가 (#23 표 2).

같은 잣대를 네 데이터셋에 적용한다. 계층화가 품질을 얼마나 개선하는지는 데이터마다
다를 것이고, 그 차이가 원천의 표현 방식으로 설명되는지가 이 표가 묻는 것이다.

## 측정 대상 컬럼을 사람이 고르지 않는다

이전 판은 데이터셋마다 컬럼 다섯 개를 손으로 골랐다. 그러면 표가 데이터가 아니라
**고른 사람**을 재게 된다 — 쉼표 낀 금액 컬럼을 넣으면 Bronze 적합률이 0이 되고,
빼면 0.94가 된다. 같은 데이터에서 둘 다 나온다.

그래서 컬럼은 **각 데이터셋의 Silver 계약에서 자동으로 유도한다.**

- ``rename``/``coalesce``/``derived``가 각 role을 Bronze에서 어떻게 얻는지 준다.
- ``casts``가 선언된 필드는 **그 캐스팅이 기대 타입**이다 (``int``/``float``/
  ``int_comma``/``float_comma`` → numeric, ``date``/``datetime`` → date).
- 어느 쪽에서도 얻을 수 없는 role은 빼지 않고 **멈춘다**. 조용히 빠지면 두 계층의
  분모가 달라지고 표는 그대로 찍힌다 — 실제로 그렇게 따릉이를 required 2개 대
  3개로 재고 있었다.

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

## Bronze를 두 번 읽는다

계층을 하나 더 만드는 것이 아니다. **같은 Bronze artifact에 대한 두 개의 view**다.

``Bronze (semantic)``  계약이 선언한 캐스팅을 Bronze에도 준다. ``pd.to_numeric``
                       으로 ``"120,000"``을 실패 처리하면 H1이 아니라 우리가
                       Bronze에 얼마나 적대적이었는가를 재게 된다. **H1 primary.**
``Bronze (stored)``    해석 없이 저장 표현 그대로. 별도 전처리 없이 raw를 바로
                       읽는 분석자가 무엇을 마주하는가를 본다. 이것은 데이터
                       품질이라기보다 **준비 비용**이고, RQ2와 함께 읽는다.

정의를 결과를 보고 고르지 않으려면 둘 다 내놓고 질문을 다르게 붙여야 한다.

## 비교 대상은 컬럼이 아니라 role이다

Bronze와 Silver는 컬럼 이름도, 개수도, 존재 여부도 다르다. ``ym_raw``는 Bronze에
없고 ``대여일자``/``대여년월`` 중 하나에서 온다. ``deal_date``는 세 조각에서
만들어진다. 그래서 ``kpx.metrics.roles``가 계약에서 role을 세우고 두 계층을 같은
role 집합으로 **투영**한다. 투영 후 비대칭이 남으면 선언 버그이므로 멈춘다.

**harness 가상환경에서 실행한다.** 전수를 읽으므로 rent에서 3 GiB 가까이 쓴다 —
데이터셋을 하나씩 처리하고 사이에서 해제한다.
"""

from __future__ import annotations

import argparse
import gc
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import DEFAULT_WORK_ROOT, SNAPSHOTS  # noqa: E402

from kpx.datasets import read_artifact  # noqa: E402
from kpx.metrics.quality import (  # noqa: E402
    H1_COMPARABLE_METRICS,
    H1_DIAGNOSTIC_METRICS,
    TABLE2_METRICS,
    ColumnSpec,
    QualityReport,
    QualitySpec,
    measure_quality,
)
from kpx.metrics.roles import (  # noqa: E402
    Role,
    assert_symmetric,
    interpreter_for,
    plan_roles,
    project,
)
from kpx.pipeline import bind_measured_artifact  # noqa: E402
from kpx.provenance import ProvenanceStore  # noqa: E402

SPEC_MODULES = ("trades_spec", "rent_spec", "bike_spec")


def layer_spec(roles: Sequence[Role], *, interpreted: bool) -> QualitySpec:
    """투영된 프레임을 읽는 방식 하나.

    두 계층이 이미 같은 role 컬럼을 갖고 있으므로 spec도 한 벌이면 된다. 차이는
    ``interpreted`` 하나다 — 계약이 선언한 캐스팅을 값 읽기에 쓸 것인가.
    """
    return QualitySpec(
        columns=tuple(
            ColumnSpec(
                column=role.name,
                role=role.name,
                kind=role.kind,  # type: ignore[arg-type]
                required=role.required,
                interpret=interpreter_for(role) if interpreted else None,
            )
            for role in roles
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
        "--datasets",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "datasets",
        help="provenance 저장소 (기본: experiments/datasets)",
    )
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
        roles = plan_roles(contract)

        silver_path = args.work_root / "runs" / spec["run_id"] / "silver" / alias / "table.parquet"
        if not silver_path.exists():
            print(f"[skip] {dataset}: Silver가 없다 ({silver_path})")
            continue

        # 경로가 맞다고 내용이 맞는 것은 아니다. 같은 run_id에 낡은 산출물이 남아
        # 있으면 선언은 옳고 바이트는 틀리다. 스냅샷·recipe·체크섬 세 축으로
        # provenance에 묶는다.
        build = bind_measured_artifact(
            silver_path.parent, spec=spec, store=ProvenanceStore(args.datasets)
        )

        source = args.snapshots / spec["snapshot_id"] / "source" / "raw_records.jsonl"
        if not source.exists():
            raise SystemExit(f"{dataset}: 선언된 스냅샷이 없다 ({source})")
        raw = pd.read_json(source, lines=True, dtype=False, convert_dates=False)
        bronze = sample(raw, args.rows)
        # 두 계층을 같은 비율로 줄인다. 한쪽만 줄이면 duplicate_rate가 표본 크기
        # 차이를 재게 된다 — 작은 표본에서 중복이 덜 잡히는 것은 데이터의 성질이
        # 아니다.
        silver = sample(read_artifact(silver_path), args.rows)

        # 두 계층을 같은 role 집합으로 투영한다. 컬럼이 없어서 조용히 빠지는 자리를
        # 없애는 것이 목적이고, 남은 비대칭은 선언 버그이므로 여기서 멈춘다.
        bronze_roles = project(bronze, roles, layer="bronze")
        silver_roles = project(silver, roles, layer="silver")
        assert_symmetric(bronze_roles, silver_roles, roles)

        print(f"\n{'=' * 78}\n{dataset}")
        print(
            f"  Bronze {len(bronze):,}행 x {bronze.shape[1]}컬럼   "
            f"Silver {len(silver):,}행 x {silver.shape[1]}컬럼   "
            f"role {len(roles)}개 (required {sum(r.required for r in roles)}개)"
        )
        print(
            f"  build {build.build_id}  {build.inputs.pipeline_version}  "
            f"checksum {build.output_checksum[:12]}…"
        )

        # 같은 투영을 두 번 읽는다. 조건이 하나 더 생긴 것이 아니라 **같은 Bronze
        # artifact에 대한 두 개의 view**다.
        #   semantic — 파이프라인이 실제로 쓰는 해석을 Bronze에도 준다. H1 primary.
        #   stored   — 해석 없이 저장 표현 그대로. 준비 비용을 보는 보조 관측이다.
        semantic = layer_spec(roles, interpreted=True)
        stored = layer_spec(roles, interpreted=False)
        reports = {
            "bronze": measure_quality(bronze_roles, semantic, layer="bronze"),
            "silver": measure_quality(silver_roles, semantic, layer="silver"),
        }
        bronze_stored = measure_quality(bronze_roles, stored, layer="bronze")
        print("\n  -- row-level (H1 comparable) --")
        print(
            pd.DataFrame(
                [
                    {
                        "Metric": m,
                        "Bronze (semantic)": reports["bronze"].metric(m),
                        "Silver": reports["silver"].metric(m),
                        "Bronze (stored)": bronze_stored.metric(m),
                    }
                    for m in H1_COMPARABLE_METRICS
                ]
            ).to_string(index=False, na_rep="—")
        )
        print(
            "     H1 primary는 Bronze (semantic) 대 Silver다 — 양쪽에 같은 해석 능력을"
            " 준다.\n"
            "     Bronze (stored)는 해석 없이 저장 표현을 그대로 읽었을 때 분석자가"
            " 마주하는 것이고,\n"
            "     데이터 품질이 아니라 준비 비용에 가깝다 (RQ2와 함께 읽는다)."
        )
        # 진단 지표는 한 표 안에 섞지 않는다. 나란히 찍으면 두 열을 빼는 읽기를
        # 부르는데, duplicate_rate는 그 읽기를 지탱하지 못한다 — key 없이 전체 행으로
        # 센다.
        print("\n  -- row-level (diagnostic, H1 증거로 쓰지 않는다) --")
        print(
            pd.DataFrame(
                [
                    {"Metric": m, **{k: r.metric(m) for k, r in reports.items()}}
                    for m in H1_DIAGNOSTIC_METRICS
                ]
            ).to_string(index=False, na_rep="—")
        )

        b_cols = per_column(bronze_roles, semantic)
        s_cols = per_column(silver_roles, semantic)
        print("\n  -- per-column (진단) --")
        print(
            pd.DataFrame(
                [
                    {
                        "Role": role.name,
                        "kind": role.kind,
                        "from": role.projection,
                        "bronze_parse_fail": b_cols[role.name].metric("parsing_failure_rate"),
                        "silver_parse_fail": s_cols[role.name].metric("parsing_failure_rate"),
                        "bronze_missing": b_cols[role.name].metric("missing_rate"),
                        "silver_missing": s_cols[role.name].metric("missing_rate"),
                    }
                    for role in roles
                ]
            ).to_string(index=False, na_rep="—")
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

        # 요약도 H1_COMPARABLE_METRICS에서 만든다. 여기에 지표를 손으로 적어 두면
        # 비교 지표를 고쳐도 최종 표에서 다시 깨진다 — 실제로 한 번 깨졌다.
        row: dict[str, Any] = {
            "Dataset": dataset,
            "Roles": len(roles),
            "Required": sum(role.required for role in roles),
        }
        for metric in H1_COMPARABLE_METRICS:
            before, after = reports["bronze"].metric(metric), reports["silver"].metric(metric)
            row[metric] = "—" if before is None or after is None else f"{before:.3f} -> {after:.3f}"
        summary.append(row)

        # raw까지 놓아야 한다 — 표본을 안 뜨면 bronze가 raw와 같은 객체라,
        # bronze만 지우면 참조가 남아 다음 데이터셋에서 메모리가 겹친다.
        del raw, bronze, silver, bronze_roles, silver_roles, b_cols, s_cols, reports
        gc.collect()

    print()
    print("=" * 78)
    print("정형화 수준 스펙트럼 — Bronze (semantic) -> Silver, H1 primary")
    print()
    print(pd.DataFrame(summary).to_string(index=False))
    print()
    print("role은 각 데이터셋의 Silver 계약에서 유도했다. 손으로 고른 것이 없다.")
    print("required는 docs/required-columns.md의 규칙(식별자 + 시점 + 주된 사실)을 따른다.")
    print("양쪽에 같은 해석 능력을 준 비교다 — Bronze를 저장 표현 그대로 읽은 값은")
    print("데이터셋별 상세표의 Bronze (stored) 열에 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
