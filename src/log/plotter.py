"""Generate graphs from collected log records."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

PREFIX_COLORS: dict[str, str] = {
    "video": "#0077BB",
    "test": "#EE7733",
    "emergency": "#009988",
}
DEFAULT_COLOR = "#BBBBBB"


def _color_for(prefix: str) -> str:
    return PREFIX_COLORS.get(prefix, DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_uri_prefix(uri: str | None) -> str:
    """Extract the first path segment after ``ccnx:/``.

    >>> extract_uri_prefix("ccnx:/video/stream/c1")
    'video'
    >>> extract_uri_prefix("ccnx:/test/data/content2")
    'test'
    """
    if not uri:
        return "unknown"
    m = re.match(r"ccnx:/([^/]+)", str(uri))
    return m.group(1) if m else "unknown"


def _safe_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_metric(rec: dict[str, Any], *keys: str) -> float | None:
    """Return the first non-None metric value from *keys*."""
    for k in keys:
        v = _safe_float(rec.get(k))
        if v is not None:
            return v
    return None


def _filter_eval(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if str(r.get("phase", "")).lower() == "eval"]


def _group_by_prefix(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        pfx = extract_uri_prefix(r.get("uri"))
        groups.setdefault(pfx, []).append(r)
    return dict(sorted(groups.items()))


def _cycles(records: list[dict[str, Any]]) -> list[int]:
    vals: set[int] = set()
    for r in records:
        c = r.get("cycle")
        if c is not None and c != "":
            try:
                vals.add(int(c))
            except (ValueError, TypeError):
                pass
    return sorted(vals)


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
    return "  —  ".join(parts)


def _save_fig(
    fig: plt.Figure, output_dir: Path, name: str
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ext in ("png", "pdf"):
        p = output_dir / f"{name}.{ext}"
        fig.savefig(str(p), bbox_inches="tight", dpi=150)
        paths.append(p)
    plt.close(fig)
    return paths


# ---------------------------------------------------------------------------
# Grouped bar chart (cycle × URI prefix)
# ---------------------------------------------------------------------------


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
    evals = _filter_eval(records)
    if not evals:
        return []

    by_prefix = _group_by_prefix(evals)
    cycles = _cycles(evals)
    if not cycles:
        return []

    prefixes = list(by_prefix.keys())
    n_prefix = len(prefixes)
    bar_width = 0.8 / max(n_prefix, 1)

    fig, ax = plt.subplots(figsize=(max(6, len(cycles) * 1.5), 5))

    for i, pfx in enumerate(prefixes):
        vals: list[float] = []
        for cyc in cycles:
            cyc_recs = [r for r in by_prefix[pfx] if _safe_int(r.get("cycle")) == cyc]
            if is_success_rate:
                total = len(cyc_recs)
                ok = sum(1 for r in cyc_recs if str(r.get("success", "")).lower() == "true")
                vals.append((ok / total * 100) if total > 0 else 0.0)
            else:
                nums = [_get_metric(r, *metric_keys) for r in cyc_recs]
                nums = [v / divisor for v in nums if v is not None]
                vals.append(sum(nums) / len(nums) if nums else 0.0)

        x_pos = [c + i * bar_width for c in range(len(cycles))]
        ax.bar(x_pos, vals, width=bar_width, label=pfx, color=_color_for(pfx))

    ax.set_xlabel("Cycle")
    ax.set_ylabel(ylabel)
    ax.set_title(_build_title(records, chart_name))
    ax.set_xticks([c + bar_width * (n_prefix - 1) / 2 for c in range(len(cycles))])
    ax.set_xticklabels([str(c) for c in cycles])
    ax.legend()
    ax.yaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))

    return _save_fig(fig, output_dir, filename)


def _safe_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# cefgetfile — 4 graphs
# ---------------------------------------------------------------------------


def plot_cefgetfile(
    records: list[dict[str, Any]], output_dir: Path
) -> list[Path]:
    paths: list[Path] = []

    # 1. Success rate
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

    # 2. Throughput
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=("throughput_bps",),
            ylabel="Throughput (Mbps)",
            chart_name="cefgetfile Throughput",
            filename="cefgetfile_throughput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )

    # 3. Goodput
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=("goodput_bps",),
            ylabel="Goodput (Mbps)",
            chart_name="cefgetfile Goodput",
            filename="cefgetfile_goodput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )

    # 4. Jitter
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=("jitter_ave_us",),
            ylabel="Jitter (us)",
            chart_name="cefgetfile Jitter",
            filename="cefgetfile_jitter",
            output_dir=output_dir,
        )
    )

    return paths


# ---------------------------------------------------------------------------
# cefputfile — 1 graph (no cycle, URI-based bar chart)
# ---------------------------------------------------------------------------


def plot_cefputfile(
    records: list[dict[str, Any]], output_dir: Path
) -> list[Path]:
    if not records:
        return []

    by_uri: dict[str, list[float]] = {}
    for r in records:
        uri = r.get("uri") or "unknown"
        v = _safe_float(r.get("throughput_bps"))
        if v is not None:
            by_uri.setdefault(str(uri), []).append(v / 1e6)

    if not by_uri:
        return []

    uris = sorted(by_uri.keys())
    means = [sum(vs) / len(vs) for vs in (by_uri[u] for u in uris)]
    colors = [_color_for(extract_uri_prefix(u)) for u in uris]
    labels = [u.replace("ccnx:/", "") for u in uris]

    fig, ax = plt.subplots(figsize=(max(6, len(uris) * 1.2), 5))
    ax.bar(range(len(uris)), means, color=colors)
    ax.set_xlabel("URI")
    ax.set_ylabel("Throughput (Mbps)")
    ax.set_title(_build_title(records, "cefputfile Throughput"))
    ax.set_xticks(range(len(uris)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)

    return _save_fig(fig, output_dir, "cefputfile_throughput")


# ---------------------------------------------------------------------------
# cefsubfile — 4 graphs
# ---------------------------------------------------------------------------


def plot_cefsubfile(
    records: list[dict[str, Any]], output_dir: Path
) -> list[Path]:
    paths: list[Path] = []

    # 1. Success rate
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

    # 2. Throughput (cefsubfile uses "throughput" not "throughput_bps")
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=("throughput", "throughput_bps"),
            ylabel="Throughput (Mbps)",
            chart_name="cefsubfile Throughput",
            filename="cefsubfile_throughput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )

    # 3. Goodput
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=("goodput", "goodput_bps"),
            ylabel="Goodput (Mbps)",
            chart_name="cefsubfile Goodput",
            filename="cefsubfile_goodput",
            output_dir=output_dir,
            divisor=1e6,
        )
    )

    # 4. Jitter
    paths.extend(
        _grouped_bar_by_cycle(
            records,
            metric_keys=("jitter_ave", "jitter_ave_us"),
            ylabel="Jitter (us)",
            chart_name="cefsubfile Jitter",
            filename="cefsubfile_jitter",
            output_dir=output_dir,
        )
    )

    return paths


# ---------------------------------------------------------------------------
# cefpubfile — 1 graph (rate + success 2-panel)
# ---------------------------------------------------------------------------


def plot_cefpubfile(
    records: list[dict[str, Any]], output_dir: Path
) -> list[Path]:
    if not records:
        return []

    by_uri: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        uri = str(r.get("uri") or "unknown")
        by_uri.setdefault(uri, []).append(r)

    uris = sorted(by_uri.keys())
    if not uris:
        return []

    labels = [u.replace("ccnx:/", "") for u in uris]
    colors = [_color_for(extract_uri_prefix(u)) for u in uris]

    rates: list[float] = []
    success_pcts: list[float] = []
    for u in uris:
        recs = by_uri[u]
        r_vals = [_safe_float(r.get("rate")) for r in recs]
        r_vals = [v for v in r_vals if v is not None]
        rates.append(sum(r_vals) / len(r_vals) if r_vals else 0.0)

        total = len(recs)
        ok = sum(1 for r in recs if str(r.get("success", "")).lower() == "true")
        success_pcts.append((ok / total * 100) if total > 0 else 0.0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(max(8, len(uris) * 2), 5))

    ax1.bar(range(len(uris)), rates, color=colors)
    ax1.set_ylabel("Rate (Mbps)")
    ax1.set_xticks(range(len(uris)))
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax1.set_title("Rate")

    ax2.bar(range(len(uris)), success_pcts, color=colors)
    ax2.set_ylabel("Success (%)")
    ax2.set_xticks(range(len(uris)))
    ax2.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax2.set_title("Success")

    fig.suptitle(_build_title(records, "cefpubfile Summary"))

    return _save_fig(fig, output_dir, "cefpubfile_summary")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

PLOTTERS: dict[str, Any] = {
    "cefgetfile": plot_cefgetfile,
    "cefputfile": plot_cefputfile,
    "cefsubfile": plot_cefsubfile,
    "cefpubfile": plot_cefpubfile,
}


def plot_all(
    records_by_command: dict[str, list[dict[str, Any]]], output_dir: Path
) -> list[Path]:
    """Generate all graphs for all commands.

    Args:
        records_by_command: Mapping from command name to list of record dicts.
        output_dir: Directory for graph output.

    Returns:
        List of written file paths.
    """
    all_paths: list[Path] = []
    for cmd in sorted(records_by_command):
        plotter = PLOTTERS.get(cmd)
        if plotter is None:
            continue
        paths = plotter(records_by_command[cmd], output_dir)
        all_paths.extend(paths)
    return all_paths
