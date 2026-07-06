"""Generate graphs from collected log records."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402

from .schema import COMMAND_SCHEMAS

PREFIX_COLORS: dict[str, str] = {
    "video": "#0077BB",
    "test": "#EE7733",
    "emergency": "#009988",
}
DEFAULT_COLOR = "#BBBBBB"


def _require_schema_field(command: str, name: str) -> str:
    """Return a canonical metric key only if the command schema owns it.

    Plotters are downstream consumers of parser output; validating their keys
    against the schema keeps graph code from quietly reintroducing legacy
    spellings such as ``throughput`` or ``rate``.
    """
    if name not in COMMAND_SCHEMAS[command].field_names:
        raise KeyError(f"{command} schema has no field {name!r}")
    return name


CEFPUT_THROUGHPUT = _require_schema_field("cefputfile", "throughput_bps")
CEFGET_THROUGHPUT = _require_schema_field("cefgetfile", "throughput_bps")
CEFGET_GOODPUT = _require_schema_field("cefgetfile", "goodput_bps")
CEFGET_JITTER_AVE = _require_schema_field("cefgetfile", "jitter_ave_us")
CEFSUB_THROUGHPUT = _require_schema_field("cefsubfile", "throughput_bps")
CEFSUB_GOODPUT = _require_schema_field("cefsubfile", "goodput_bps")
CEFSUB_JITTER_AVE = _require_schema_field("cefsubfile", "jitter_ave_us")
CEFPUB_RATE = _require_schema_field("cefpubfile", "rate_mbps")


def _color_for(prefix: str) -> str:
    return PREFIX_COLORS.get(prefix, DEFAULT_COLOR)


def extract_uri_prefix(uri: str | None) -> str:
    """Extract the first path segment after ``ccnx:/``."""
    if not uri:
        return "unknown"
    match = re.match(r"ccnx:/([^/]+)", str(uri))
    return match.group(1) if match else "unknown"


def _safe_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _get_metric(rec: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(rec.get(key))
        if value is not None:
            return value
    return None


def _known_success(records: list[dict[str, Any]]) -> list[str]:
    # Verdict success is tri-state; unknown (empty) stays out of denominators.
    return [
        s
        for s in (str(record.get("success", "")).lower() for record in records)
        if s in ("true", "false")
    ]


def _filter_eval(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Records without a phase field (linear/mesh logs) are treated as eval records.
    return [
        record
        for record in records
        if record.get("phase") is None or str(record["phase"]).lower() == "eval"
    ]


def _group_by_prefix(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        prefix = extract_uri_prefix(record.get("uri"))
        groups.setdefault(prefix, []).append(record)
    return dict(sorted(groups.items()))


def _cycles(records: list[dict[str, Any]]) -> list[int]:
    # Records without a cycle field (linear/mesh logs) are treated as cycle 0.
    values: set[int] = set()
    for record in records:
        cycle = record.get("cycle")
        if cycle is None or cycle == "":
            values.add(0)
        else:
            try:
                values.add(int(cycle))
            except (ValueError, TypeError):
                values.add(0)
    return sorted(values)


def _build_title(records: list[dict[str, Any]], chart_name: str) -> str:
    first = records[0] if records else {}
    parts = [chart_name]
    seed = first.get("seed")
    hosts = first.get("hosts")
    exp = first.get("experiment_dir")
    if exp:
        parts.append(str(exp))
    if hosts:
        parts.append(f"hosts={hosts}")
    if seed:
        parts.append(f"seed={seed}")
    return " - ".join(parts)


def _save_fig(fig: plt.Figure, output_dir: Path, name: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ext in ("png", "pdf"):
        path = output_dir / f"{name}.{ext}"
        fig.savefig(str(path), bbox_inches="tight", dpi=150)
        paths.append(path)
    plt.close(fig)
    return paths


def _grouped_bar_by_cycle(
    records: list[dict[str, Any]],
    metric_keys: tuple[str, ...],
    ylabel: str,
    chart_name: str,
    filename: str,
    output_dir: Path,
    *,
    divisor: float = 1.0,
    is_success_rate: bool = False,
) -> list[Path]:
    eval_records = _filter_eval(records)
    if not eval_records:
        return []

    by_prefix = _group_by_prefix(eval_records)
    cycles = _cycles(eval_records)
    if not cycles:
        return []

    prefixes = list(by_prefix.keys())
    prefix_count = len(prefixes)
    bar_width = 0.8 / max(prefix_count, 1)

    fig, axis = plt.subplots(figsize=(max(6, len(cycles) * 1.5), 5))

    for index, prefix in enumerate(prefixes):
        values: list[float] = []
        for cycle in cycles:
            cycle_records = [
                record
                for record in by_prefix[prefix]
                if (_safe_int(record.get("cycle")) or 0) == cycle
            ]
            if is_success_rate:
                known = _known_success(cycle_records)
                values.append(
                    (known.count("true") / len(known) * 100) if known else 0.0
                )
            else:
                nums = [_get_metric(record, *metric_keys) for record in cycle_records]
                nums = [value / divisor for value in nums if value is not None]
                values.append(sum(nums) / len(nums) if nums else 0.0)

        x_pos = [pos + index * bar_width for pos in range(len(cycles))]
        axis.bar(x_pos, values, width=bar_width, label=prefix, color=_color_for(prefix))

    axis.set_xlabel("Cycle")
    axis.set_ylabel(ylabel)
    axis.set_title(_build_title(records, chart_name))
    axis.set_xticks(
        [pos + bar_width * (prefix_count - 1) / 2 for pos in range(len(cycles))]
    )
    axis.set_xticklabels([str(cycle) for cycle in cycles])
    axis.legend()
    axis.yaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))

    return _save_fig(fig, output_dir, filename)


def plot_cefgetfile(records: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    paths: list[Path] = []
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(),
            ylabel="Success Rate (%)",
            chart_name="cefgetfile Success Rate",
            filename="cefgetfile_success_rate",
            output_dir=output_dir,
            is_success_rate=True,
        )
    )
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(CEFGET_THROUGHPUT,),
            ylabel="Throughput (Mbps)",
            chart_name="cefgetfile Throughput",
            filename="cefgetfile_throughput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(CEFGET_GOODPUT,),
            ylabel="Goodput (Mbps)",
            chart_name="cefgetfile Goodput",
            filename="cefgetfile_goodput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(CEFGET_JITTER_AVE,),
            ylabel="Jitter (us)",
            chart_name="cefgetfile Jitter",
            filename="cefgetfile_jitter",
            output_dir=output_dir,
        )
    )
    return paths


def plot_cefputfile(records: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    if not records:
        return []

    by_uri: dict[str, list[float]] = {}
    for record in records:
        uri = record.get("uri") or "unknown"
        value = _safe_float(record.get(CEFPUT_THROUGHPUT))
        if value is not None:
            by_uri.setdefault(str(uri), []).append(value / 1e6)

    if not by_uri:
        return []

    uris = sorted(by_uri.keys())
    means = [sum(values) / len(values) for values in (by_uri[uri] for uri in uris)]
    colors = [_color_for(extract_uri_prefix(uri)) for uri in uris]
    labels = [uri.replace("ccnx:/", "") for uri in uris]

    fig, axis = plt.subplots(figsize=(max(6, len(uris) * 1.2), 5))
    axis.bar(range(len(uris)), means, color=colors)
    axis.set_xlabel("URI")
    axis.set_ylabel("Throughput (Mbps)")
    axis.set_title(_build_title(records, "cefputfile Throughput"))
    axis.set_xticks(range(len(uris)))
    axis.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)

    return _save_fig(fig, output_dir, "cefputfile_throughput")


def plot_cefsubfile(records: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    paths: list[Path] = []
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(),
            ylabel="Success Rate (%)",
            chart_name="cefsubfile Success Rate",
            filename="cefsubfile_success_rate",
            output_dir=output_dir,
            is_success_rate=True,
        )
    )
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(CEFSUB_THROUGHPUT,),
            ylabel="Throughput (Mbps)",
            chart_name="cefsubfile Throughput",
            filename="cefsubfile_throughput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(CEFSUB_GOODPUT,),
            ylabel="Goodput (Mbps)",
            chart_name="cefsubfile Goodput",
            filename="cefsubfile_goodput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=(CEFSUB_JITTER_AVE,),
            ylabel="Jitter (us)",
            chart_name="cefsubfile Jitter",
            filename="cefsubfile_jitter",
            output_dir=output_dir,
        )
    )
    return paths


def plot_cefpubfile(records: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    if not records:
        return []

    by_uri: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        uri = str(record.get("uri") or "unknown")
        by_uri.setdefault(uri, []).append(record)

    uris = sorted(by_uri.keys())
    if not uris:
        return []

    labels = [uri.replace("ccnx:/", "") for uri in uris]
    colors = [_color_for(extract_uri_prefix(uri)) for uri in uris]

    rates: list[float] = []
    success_pcts: list[float] = []
    for uri in uris:
        records_for_uri = by_uri[uri]
        rate_values = [
            _safe_float(record.get(CEFPUB_RATE)) for record in records_for_uri
        ]
        rate_values = [value for value in rate_values if value is not None]
        rates.append(sum(rate_values) / len(rate_values) if rate_values else 0.0)

        known = _known_success(records_for_uri)
        success_pcts.append((known.count("true") / len(known) * 100) if known else 0.0)

    fig, (ax_rate, ax_success) = plt.subplots(1, 2, figsize=(max(8, len(uris) * 2), 5))

    ax_rate.bar(range(len(uris)), rates, color=colors)
    ax_rate.set_ylabel("Rate (Mbps)")
    ax_rate.set_xticks(range(len(uris)))
    ax_rate.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax_rate.set_title("Rate")

    ax_success.bar(range(len(uris)), success_pcts, color=colors)
    ax_success.set_ylabel("Success (%)")
    ax_success.set_xticks(range(len(uris)))
    ax_success.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax_success.set_title("Success")

    fig.suptitle(_build_title(records, "cefpubfile Summary"))
    return _save_fig(fig, output_dir, "cefpubfile_summary")


PLOTTERS: dict[str, Any] = {
    "cefgetfile": plot_cefgetfile,
    "cefputfile": plot_cefputfile,
    "cefsubfile": plot_cefsubfile,
    "cefpubfile": plot_cefpubfile,
}


def plot_all(
    records_by_command: dict[str, list[dict[str, Any]]], output_dir: Path
) -> list[Path]:
    """Generate all graphs for all commands."""
    all_paths: list[Path] = []
    for command in sorted(records_by_command):
        plotter = PLOTTERS.get(command)
        if plotter is None:
            continue
        all_paths.extend(plotter(records_by_command[command], output_dir))
    return all_paths
