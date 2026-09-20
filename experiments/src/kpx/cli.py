"""Command-line entry point for the experiment harness.

The CLI grows with the experiments; at this stage it only reports what the
harness knows about itself, which is enough to verify an installation.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from kpx import __version__
from kpx.contract import CONDITIONS, LAYERS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kpx", description=__doc__)
    parser.add_argument("--version", action="version", version=f"kpx {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="print harness configuration")

    args = parser.parse_args(argv)
    if args.command == "info":
        print(f"kpx {__version__}")
        print(f"conditions: {', '.join(CONDITIONS)}")
        print(f"layers:     {', '.join(LAYERS)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
