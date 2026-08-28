import argparse
import asyncio
from pathlib import Path

from sunbench.runner import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sunbench")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run or resume an experiment")
    run_parser.add_argument("-c", "--config", required=True, type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        try:
            asyncio.run(run(args.config))
        except KeyboardInterrupt:
            print("\nInterrupted. Run the same command to resume.")
        except Exception as exc:
            raise SystemExit(f"Error: {exc}") from exc

