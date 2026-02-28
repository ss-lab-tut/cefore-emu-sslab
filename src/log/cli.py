"""CLI for log summarization."""

import argparse
from pathlib import Path

from .summarizer import summarize


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
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    summarize(args.directories, output_dir=args.output_dir, stdout=args.stdout)
