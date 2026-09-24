"""Command-line entry point for the experiment harness."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from kpx import __version__
from kpx.contract import CONDITIONS, LAYERS, Layer
from kpx.datasets import DatasetNotBuilt, LayerStore, read_artifact, schema_report
from kpx.provenance import Environment, ProvenanceError, ProvenanceStore
from kpx.results import default_store as default_result_store
from kpx.snapshot import SnapshotError, SnapshotStore, default_store, scan_jsonl


class RunError(RuntimeError):
    """Raised when `kpx run` is asked for something it cannot do."""


def _store(args: argparse.Namespace) -> SnapshotStore:
    return default_store(args.snapshots)


def _builds(args: argparse.Namespace) -> ProvenanceStore:
    root = args.datasets or Path(__file__).resolve().parents[2] / "datasets"
    return ProvenanceStore(root)


#: 실행할 수 있는 과제. 모듈 경로만 두고 import는 실행 시점에 한다 — CLI가 뜨는
#: 데에 pandas와 과제 코드 전부가 필요하지는 않다.
TASKS = {"task01": "kpx.tasks.task01_price_analysis"}


def _layer_store(specifications: Sequence[str]) -> LayerStore:
    """``dataset=layer=path`` 들을 러너가 읽을 resolver로 만든다.

    러너는 자기 입력이 어디 있는지 모른 채로 있어야 하므로, 경로는 명령줄에서
    들어와 여기서 한 번만 해석된다.
    """
    paths: dict[tuple[str, Layer], Path] = {}
    for specification in specifications:
        parts = specification.split("=", 2)
        if len(parts) != 3:
            raise RunError(f"--layer wants dataset=layer=path, got {specification!r}")
        dataset, layer, path = parts
        if layer not in LAYERS:
            raise RunError(f"unknown layer: {layer!r} (known: {', '.join(LAYERS)})")
        paths[(dataset, layer)] = Path(path)
    return LayerStore(paths=paths)


def _cmd_run(args: argparse.Namespace) -> int:
    """한 조건을 실행하고 결과를 저장소에 남긴다 (#13).

    경로가 아니라 이름으로 부른다. 재현하려는 사람이 레포의 디렉터리 구조를 몰라도
    결과를 다시 만들 수 있어야 한다.
    """
    import importlib

    from kpx.runner import run_condition

    if args.list:
        for name in sorted(TASKS):
            print(name)
        return 0

    if args.task not in TASKS:
        raise RunError(f"unknown task: {args.task!r} (known: {', '.join(sorted(TASKS))})")
    if args.condition not in CONDITIONS:
        raise RunError(f"unknown condition: {args.condition!r} (known: {', '.join(CONDITIONS)})")
    if not args.layer:
        raise RunError(
            "kpx run needs the built layers. Pass --layer dataset=layer=path once per "
            "layer, or use scripts/run_task01.py which assembles them from a build."
        )
    # 결과 행은 어느 스냅샷의 어느 파이프라인에서 나왔는지 말해야 한다. 기본값을
    # 넣어 주면 그 자리에 추측이 기록되고, 표가 출처를 잃는다.
    missing = [name for name in ("snapshot", "pipeline_version") if getattr(args, name) is None]
    if missing:
        raise RunError(f"kpx run needs {' and '.join('--' + name for name in missing)}")

    task = importlib.import_module(TASKS[args.task]).TASK
    row = run_condition(
        task,
        args.condition,
        datasets=_layer_store(args.layer),
        snapshot_id=args.snapshot,
        pipeline_version=args.pipeline_version,
        seed=args.seed,
    )
    default_result_store(args.results).append(row)
    print(f"{row.run_id}  status={row.status}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    print(f"kpx {__version__}")
    print(f"conditions: {', '.join(CONDITIONS)}")
    print(f"layers:     {', '.join(LAYERS)}")
    print(f"snapshots:  {_store(args).root}")
    print(f"datasets:   {_builds(args).root}")
    return 0


def _cmd_env(args: argparse.Namespace) -> int:
    environment = Environment.capture()
    if args.json:
        print(json.dumps(asdict(environment), indent=2, sort_keys=True))
    else:
        versions = ", ".join(f"{name} {v}" for name, v in environment.packages.items())
        print(f"- Platform: {environment.platform}")
        print(f"- Python: {environment.python_version}")
        print(f"- Libraries: {versions}")
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    if not args.artifact.exists():
        raise DatasetNotBuilt(f"no artifact at {args.artifact}")
    report = schema_report(read_artifact(args.artifact))
    report["Non-null"] = report["Non-null"].map("{:.1%}".format)
    print(report.to_string(index=False))
    return 0


def _cmd_snapshot_register(args: argparse.Namespace) -> int:
    scan = scan_jsonl(args.source)
    snapshot = _store(args).register(
        args.source,
        dataset=args.dataset,
        source_url=args.source_url,
        row_count=scan.row_count,
        columns=scan.columns,
        data_schema_version=args.schema_version,
        period=tuple(args.period) if args.period else None,
        builder_version=args.collector,
        notes=args.notes,
    )
    print(snapshot.snapshot_id)
    print(f"rows={snapshot.row_count:,}  cols={snapshot.column_count}")
    print(f"sha256={snapshot.checksum}")
    return 0


def _cmd_snapshot_list(args: argparse.Namespace) -> int:
    snapshots = _store(args).list_snapshots(args.dataset)
    if not snapshots:
        print("no snapshots registered")
        return 0
    for snapshot in snapshots:
        print(
            f"{snapshot.snapshot_id}  "
            f"rows={snapshot.row_count:,}  "
            f"cols={snapshot.column_count}  "
            f"retrieved={snapshot.retrieved_on.isoformat()}"
        )
    return 0


def _cmd_snapshot_show(args: argparse.Namespace) -> int:
    print(_store(args).load(args.snapshot_id).citation())
    return 0


def _cmd_snapshot_verify(args: argparse.Namespace) -> int:
    store = _store(args)
    results = [store.verify(args.snapshot_id)] if args.snapshot_id else store.verify_all(None)
    if not results:
        print("no snapshots registered")
        return 0
    failed = 0
    for result in results:
        if result.ok:
            print(f"ok     {result.snapshot_id}")
        else:
            failed += 1
            print(f"FAILED {result.snapshot_id}: {result.reason}")
    return 1 if failed else 0


def _cmd_build_list(args: argparse.Namespace) -> int:
    builds = _builds(args).list_builds(args.dataset, args.layer)
    if not builds:
        print("no builds recorded")
        return 0
    for build in builds:
        print(
            f"{build.build_id}  {build.inputs.layer:<6} {build.inputs.dataset}  "
            f"rows={build.row_count:,}  status={build.status}  "
            f"out={build.output_checksum[:12]}"
        )
    return 0


def _cmd_build_lineage(args: argparse.Namespace) -> int:
    for depth, build in enumerate(_builds(args).lineage(args.build_id)):
        indent = "  " * depth
        print(f"{indent}{build.inputs.layer:<6} {build.build_id}  out={build.output_checksum[:12]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kpx", description="Medallion evaluation harness")
    parser.add_argument("--version", action="version", version=f"kpx {__version__}")
    parser.add_argument(
        "--snapshots",
        type=Path,
        default=None,
        metavar="DIR",
        help="snapshot store root (default: experiments/snapshots)",
    )
    parser.add_argument(
        "--datasets",
        type=Path,
        default=None,
        metavar="DIR",
        help="built-dataset root (default: experiments/datasets)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="print harness configuration").set_defaults(func=_cmd_info)

    env = sub.add_parser("env", help="print the environment for the Methodology section")
    env.add_argument("--json", action="store_true", help="emit JSON instead of the markdown block")
    env.set_defaults(func=_cmd_env)

    run = sub.add_parser("run", help="run one condition of one task and record it")
    run.add_argument("--list", action="store_true", help="list the tasks this harness knows")
    run.add_argument("--task", default=None)
    run.add_argument("--condition", default=None)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--snapshot", default=None, help="the frozen source the layers came from")
    run.add_argument("--pipeline-version", default=None)
    run.add_argument("--results", type=Path, default=None)
    run.add_argument(
        "--layer",
        action="append",
        default=[],
        metavar="DATASET=LAYER=PATH",
        help="a built layer the condition may read; pass once per layer",
    )
    run.set_defaults(func=_cmd_run)

    schema = sub.add_parser("schema", help="print a built artifact's schema for the paper")
    schema.add_argument("artifact", type=Path, help="path to a .parquet or .jsonl artifact")
    schema.set_defaults(func=_cmd_schema)

    snapshot = sub.add_parser("snapshot", help="inspect frozen source snapshots")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)

    register = snapshot_sub.add_parser(
        "register", help="freeze a pull into the store and write its metadata"
    )
    register.add_argument("source", type=Path, help="directory holding the pulled .jsonl")
    register.add_argument("--dataset", required=True)
    register.add_argument("--source-url", required=True)
    register.add_argument("--schema-version", required=True, help="the source API's schema id")
    register.add_argument(
        "--period",
        nargs=2,
        metavar=("START", "END"),
        default=None,
        help="the data's own coverage, e.g. 2020-01 2024-12 (not the pull date)",
    )
    register.add_argument(
        "--collector",
        default=None,
        metavar="VERSION",
        help="version of the client that pulled these bytes, e.g. 'kpubdata 0.5.0'",
    )
    register.add_argument("--notes", default="")
    register.set_defaults(func=_cmd_snapshot_register)

    listing = snapshot_sub.add_parser("list", help="list registered snapshots, oldest first")
    listing.add_argument("--dataset", default=None, help="restrict to one dataset")
    listing.set_defaults(func=_cmd_snapshot_list)

    show = snapshot_sub.add_parser("show", help="print a snapshot's paper citation block")
    show.add_argument("snapshot_id")
    show.set_defaults(func=_cmd_snapshot_show)

    verify = snapshot_sub.add_parser("verify", help="re-digest stored bytes against the checksum")
    verify.add_argument("snapshot_id", nargs="?", default=None, help="default: verify all")
    verify.set_defaults(func=_cmd_snapshot_verify)

    build = sub.add_parser("build", help="inspect recorded layer builds")
    build_sub = build.add_subparsers(dest="build_command", required=True)

    build_list = build_sub.add_parser("list", help="list recorded builds, oldest first")
    build_list.add_argument("--dataset", default=None)
    build_list.add_argument("--layer", default=None, choices=LAYERS)
    build_list.set_defaults(func=_cmd_build_list)

    lineage = build_sub.add_parser("lineage", help="trace a build back to Bronze")
    lineage.add_argument("build_id")
    lineage.set_defaults(func=_cmd_build_lineage)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code: int = args.func(args)
    except (SnapshotError, ProvenanceError, DatasetNotBuilt, RunError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
