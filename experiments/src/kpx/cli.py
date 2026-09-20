"""Command-line entry point for the experiment harness."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from kpx import __version__
from kpx.contract import CONDITIONS, LAYERS
from kpx.snapshot import SnapshotError, SnapshotStore, default_store


def _store(args: argparse.Namespace) -> SnapshotStore:
    return default_store(args.snapshots)


def _cmd_info(args: argparse.Namespace) -> int:
    print(f"kpx {__version__}")
    print(f"conditions: {', '.join(CONDITIONS)}")
    print(f"layers:     {', '.join(LAYERS)}")
    print(f"snapshots:  {_store(args).root}")
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
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="print harness configuration").set_defaults(func=_cmd_info)

    snapshot = sub.add_parser("snapshot", help="inspect frozen source snapshots")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)

    listing = snapshot_sub.add_parser("list", help="list registered snapshots, oldest first")
    listing.add_argument("--dataset", default=None, help="restrict to one dataset")
    listing.set_defaults(func=_cmd_snapshot_list)

    show = snapshot_sub.add_parser("show", help="print a snapshot's paper citation block")
    show.add_argument("snapshot_id")
    show.set_defaults(func=_cmd_snapshot_show)

    verify = snapshot_sub.add_parser("verify", help="re-digest stored bytes against the checksum")
    verify.add_argument("snapshot_id", nargs="?", default=None, help="default: verify all")
    verify.set_defaults(func=_cmd_snapshot_verify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code: int = args.func(args)
    except SnapshotError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
