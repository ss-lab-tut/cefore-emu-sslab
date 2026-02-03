"""Collect log records from experiment directories and write CSV."""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from .filename import parse_filename
from .parser import PARSERS

# Metadata columns from meta.json
META_KEYS = (
    "num",
    "hosts",
    "switches",
    "seed",
    "k",
    "down_interval",
    "down_duration",
    "down_count",
    "down_stagger",
    "down_exclude",
    "cache_count",
    "get_interval",
)

# Filename-derived columns
FILENAME_KEYS = (
    "filename",
    "host_id",
    "content_id",
    "file_seed",
    "down_hosts",
    "get_idx",
)

# Command-specific ordered columns
_PUTFILE_COLS = (
    "timestamp",
    "uri",
    "file",
    "rate_mbps",
    "block_size_bytes",
    "cache_time_sec",
    "expiration_sec",
    "tx_frames",
    "tx_bytes",
    "duration_sec",
    "throughput_bps",
    "success",
)

_GETFILE_COLS = (
    "timestamp",
    "uri",
    "rx_frames_all",
    "rx_frames_content",
    "rx_bytes_all",
    "rx_bytes_content",
    "duration_sec",
    "throughput_bps",
    "goodput_bps",
    "jitter_ave_us",
    "jitter_max_us",
    "jitter_var_us",
    "success",
)

COMMAND_COLS: dict[str, tuple[str, ...]] = {
    "cefputfile": _PUTFILE_COLS,
    "cefgetfile": _GETFILE_COLS,
}


def _load_meta(directory: Path) -> dict[str, Any]:
    """Load meta.json from an experiment directory."""
    meta_path = directory / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def collect_records(
    directories: list[Path],
) -> dict[str, list[dict[str, Any]]]:
    """Walk directories, parse logs, return records grouped by command.

    Returns:
        Mapping from command name to list of record dicts.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for dirpath in directories:
        dirpath = Path(dirpath)
        if not dirpath.is_dir():
            print(f"warning: skipping non-directory {dirpath}", file=sys.stderr)
            continue

        meta = _load_meta(dirpath)
        meta_row = {k: meta.get(k) for k in META_KEYS}
        meta_row["experiment_dir"] = dirpath.name

        for logfile in sorted(dirpath.glob("*.log")):
            fmeta = parse_filename(logfile)
            if fmeta is None:
                continue

            parser = PARSERS.get(fmeta.command)
            if parser is None:
                continue

            text = logfile.read_text(encoding="utf-8", errors="replace")
            record = parser(text)

            # Prepend metadata columns
            row: dict[str, Any] = {}
            row["experiment_dir"] = meta_row["experiment_dir"]
            row.update(meta_row)

            # Filename-derived columns
            row["filename"] = logfile.name
            row["host_id"] = fmeta.host_id
            row["content_id"] = fmeta.content_id
            row["file_seed"] = fmeta.seed
            row["down_hosts"] = fmeta.down_hosts
            row["get_idx"] = fmeta.idx

            row.update(record)
            grouped[fmeta.command].append(row)

    return dict(grouped)


def _build_fieldnames(command: str, records: list[dict[str, Any]]) -> list[str]:
    """Build ordered fieldnames for CSV output."""
    fields: list[str] = ["experiment_dir"]
    fields.extend(META_KEYS)
    fields.extend(FILENAME_KEYS)

    if command in COMMAND_COLS:
        fields.extend(COMMAND_COLS[command])
    else:
        # Dynamic: collect all keys from records
        seen: set[str] = set(fields)
        for rec in records:
            for k in rec:
                if k not in seen:
                    fields.append(k)
                    seen.add(k)

    return fields


def write_csv(
    records: list[dict[str, Any]],
    command: str,
    output: Path | None = None,
    stdout: bool = False,
) -> Path | None:
    """Write records to CSV.

    Args:
        records: List of record dicts.
        command: Command name (used for filename and column ordering).
        output: Output file path. Ignored if stdout is True.
        stdout: If True, write to sys.stdout.

    Returns:
        Path written, or None if stdout.
    """
    if not records:
        return None

    fieldnames = _build_fieldnames(command, records)

    if stdout:
        writer = csv.DictWriter(
            sys.stdout, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
        return None

    if output is None:
        return None

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

    return output


def summarize(
    directories: list[Path],
    output_dir: Path | None = None,
    stdout: bool = False,
) -> list[Path]:
    """Main entry: collect records and write per-command CSVs.

    Args:
        directories: Experiment directories to process.
        output_dir: Directory for CSV output. Defaults to parent of first directory.
        stdout: If True, write all CSVs to stdout (separated by blank line).

    Returns:
        List of written CSV paths (empty if stdout).
    """
    grouped = collect_records(directories)

    if not grouped:
        print("No log files found.", file=sys.stderr)
        return []

    if output_dir is None and not stdout:
        output_dir = directories[0].parent

    written: list[Path] = []

    for command in sorted(grouped):
        records = grouped[command]
        if stdout:
            print(f"# {command} ({len(records)} records)")
            write_csv(records, command, stdout=True)
            print()
        else:
            csv_path = output_dir / f"{command}.csv"
            result = write_csv(records, command, output=csv_path)
            if result:
                written.append(result)
                print(f"{result}  ({len(records)} records)")

    return written
