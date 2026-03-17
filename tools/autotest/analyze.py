#!/usr/bin/env python3
"""Analyze autotest results.json files and generate summaries."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

COMPLETED_MARKER = "Completed to get all the chunks."


def discover_results(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        if p.is_file():
            if p.name == "results.json":
                found.append(p)
            continue
        if p.is_dir():
            found.extend(sorted(p.rglob("results.json")))
    unique = []
    seen = set()
    for p in found:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        unique.append(rp)
    return unique


def _has_completed_log(record: dict) -> bool:
    if isinstance(record.get("has_completed_log"), bool):
        return record["has_completed_log"]
    log_file = record.get("log_file")
    if not log_file:
        return False
    path = Path(log_file)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return COMPLETED_MARKER in text


def _has_output_file(record: dict) -> bool:
    if isinstance(record.get("has_output_file"), bool):
        return record["has_output_file"]
    out_file = record.get("out_file")
    if not out_file:
        return False
    path = Path(out_file)
    return path.exists() and path.stat().st_size > 0


def classify(record: dict) -> tuple[bool, dict[str, int]]:
    exit_code = int(record.get("exit_code", 1))
    has_completed = _has_completed_log(record)
    has_output = _has_output_file(record)
    success = (
        bool(record.get("success"))
        if "success" in record
        else (exit_code == 0 and has_completed and has_output)
    )
    reasons = {
        "exit_code_nonzero": 1 if exit_code != 0 else 0,
        "missing_completed_log": 1 if not has_completed else 0,
        "missing_output_file": 1 if not has_output else 0,
    }
    return success, reasons


def summarize(records: list[dict]) -> list[dict]:
    by_uri: dict[str, dict] = defaultdict(
        lambda: {
            "uri": "",
            "eval_total": 0,
            "eval_success": 0,
            "eval_pubdown_total": 0,
            "eval_pubdown_success": 0,
            "fail_exit_code_nonzero": 0,
            "fail_missing_completed_log": 0,
            "fail_missing_output_file": 0,
        }
    )

    for rec in records:
        uri = rec.get("uri", "")
        if not uri:
            continue
        row = by_uri[uri]
        row["uri"] = uri
        phase = rec.get("phase", "eval")
        success, reasons = classify(rec)
        if phase == "warmup":
            continue

        row["eval_total"] += 1
        row["eval_success"] += int(success)
        row["fail_exit_code_nonzero"] += reasons["exit_code_nonzero"]
        row["fail_missing_completed_log"] += reasons["missing_completed_log"]
        row["fail_missing_output_file"] += reasons["missing_output_file"]

        publisher_down = rec.get("publisher_down")
        if publisher_down is None:
            ph = rec.get("publisher_host")
            dh = rec.get("down_hosts", []) or []
            publisher_down = ph in dh if ph is not None else False
        if publisher_down:
            row["eval_pubdown_total"] += 1
            row["eval_pubdown_success"] += int(success)

    rows = []
    for _, row in sorted(by_uri.items(), key=lambda item: item[0]):
        row["eval_success_rate"] = (
            row["eval_success"] / row["eval_total"] if row["eval_total"] else None
        )
        row["eval_success_rate_when_publisher_down"] = (
            row["eval_pubdown_success"] / row["eval_pubdown_total"]
            if row["eval_pubdown_total"]
            else None
        )
        rows.append(row)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "uri",
        "eval_total",
        "eval_success",
        "eval_success_rate",
        "eval_pubdown_total",
        "eval_pubdown_success",
        "eval_success_rate_when_publisher_down",
        "fail_exit_code_nonzero",
        "fail_missing_completed_log",
        "fail_missing_output_file",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _fmt_rate(v) -> str:
    return "N/A" if v is None else f"{v:.3f}"


def write_md(rows: list[dict], path: Path, input_files: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# Autotest Summary")
    lines.append("")
    lines.append(f"- input_files: {len(input_files)}")
    lines.append(f"- uris: {len(rows)}")
    lines.append("")
    lines.append("| uri | eval_success_rate | eval_success_rate_when_publisher_down |")
    lines.append("|---|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['uri']} | {_fmt_rate(row['eval_success_rate'])} | "
            f"{_fmt_rate(row['eval_success_rate_when_publisher_down'])} |"
        )
    lines.append("")
    lines.append("## Failure Reasons (Eval)")
    lines.append("")
    lines.append("| uri | exit_code_nonzero | missing_completed_log | missing_output_file |")
    lines.append("|---|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['uri']} | {row['fail_exit_code_nonzero']} | "
            f"{row['fail_missing_completed_log']} | {row['fail_missing_output_file']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze cefore autotest results.")
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="results.json files and/or directories containing them",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="output directory for summary.csv and summary.md",
    )
    args = parser.parse_args()

    input_paths = [Path(p) for p in args.inputs]
    result_files = discover_results(input_paths)
    if not result_files:
        raise SystemExit("no results.json files found")

    records = []
    for path in result_files:
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, list):
            records.extend(content)

    rows = summarize(records)
    out_dir = Path(args.out_dir)
    write_csv(rows, out_dir / "summary.csv")
    write_md(rows, out_dir / "summary.md", result_files)


if __name__ == "__main__":
    main()
