"""CLI for log summarization."""

import argparse
from pathlib import Path

from .summarizer import collect_records, summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize cefputfile/cefgetfile/cefpubfile/cefsubfile logs into CSV.",
    )
    parser.add_argument(
        "directories",
        nargs="+",
        type=Path,
        help="Experiment log directories to process.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for CSV files (default: parent of first directory).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write CSV to stdout instead of files.",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Generate PNG and PDF graphs alongside CSV files.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    summarize(args.directories, output_dir=args.output_dir, stdout=args.stdout)

    if args.graph and not args.stdout:
        from .plotter import plot_all

        output_dir = args.output_dir or args.directories[0].parent
        grouped = collect_records(args.directories)
        for path in plot_all(grouped, output_dir):
            print(f"{path}  (graph)")


# 2026-07-03 CLI fix: ``python3 -m src.log.cli`` silently did nothing without
# an executable module guard.
if __name__ == "__main__":
    main()
