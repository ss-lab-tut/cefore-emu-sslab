#!/usr/bin/env python3
"""Render slide-ready figures for the workshop measurement campaign (M1-M5).

Usage:
    .venv/bin/python3 tools/workshop/plots.py \\
        --campaign-dir logs/workshop_20260707/smoke \\
        --out logs/workshop_20260707/smoke/figures

``--campaign-dir`` is the ``--out`` a campaign.py invocation was given: a
directory that directly contains one subdirectory per job id plus a
``campaign_state.jsonl`` journal (see logs/workshop_20260707/{smoke,probe}/
in this repo for real examples). Each job's own layout is:

    <campaign-dir>/<job_id>/run_0001/config.used.json
    <campaign-dir>/<job_id>/run_0001/logs/ex{num}_seed{seed}/results.json

By repo-wide convention (matched by report.py) figures land in
``<campaign-dir>/figures`` and cached aggregates in
``<campaign-dir>/analysis`` -- callers that pass a different ``--out`` still
get correct figures, just at a non-default path report.py won't discover
automatically.

The overnight campaign this tool reads is still running while it is being
developed: every figure function is independent and degrades gracefully (logs
a one-line reason to stderr and returns without writing a PNG) when its job
family isn't present yet, so re-running this tool as data lands never fails
the whole batch for one missing figure. The process always exits 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")  # headless: no X server / display in this environment
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# This script lives at tools/workshop/plots.py; two parents up is the repo
# root, needed on sys.path so "src.*" imports resolve regardless of the
# caller's cwd (mirrors topo_fingerprint.py's own bootstrap, one directory
# over).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# tools/workshop has no __init__.py (it is a flat script directory, not a
# package) -- adding this directory itself to sys.path lets us import the
# sibling topo_fingerprint.py module the same way a direct script invocation
# would (Python auto-adds argv[0]'s directory, but we do it explicitly so
# `import plots` from a test/agent context also works).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from src.core.verdict import from_record  # noqa: E402
from src.log.summarizer import collect_records  # noqa: E402

import topo_fingerprint  # noqa: E402


# =============================================================================
# Workshop deck palette -- monochrome base + one accent. The deck these
# figures land in is white background / black text with Toyohashi Tech logo
# red (#B6261D) as the single emphasis color, and the figures must read as
# part of the same system: blacks/grays carry every baseline or "normal"
# series, and #B6261D is reserved for THE semantically emphasized series of a
# figure (failure markers, publisher-down bars, the headline cache-hit
# series). Never use red for a second series in the same figure -- if two
# things compete for emphasis, neither is emphasized.
# =============================================================================
CATEGORICAL = [
    "#B6261D",  # 1 TUT red -- emphasis only (index 0 by design: grep-able)
    "#1a1a1a",  # 2 near-black -- primary neutral series
    "#6b6b6b",  # 3 mid gray
    "#a8a8a8",  # 4 light gray
    "#3d3d3d",  # 5 dark gray
    "#8a2420",  # 6 muted dark red (serious-but-not-headline)
    "#555555",  # 7 gray
    "#c9c9c9",  # 8 lightest gray
]
STATUS = {
    "good": "#1a1a1a",  # "normal/ok" is neutral near-black, not green: only
    "warning": "#8a8a8a",  # failure states earn color in this deck
    "serious": "#8a2420",
    "critical": "#B6261D",  # the one accent: TUT logo red
}
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#525252"
TEXT_MUTED = "#8a8a8a"
GRIDLINE = "#e5e5e5"
BASELINE = "#c4c4c4"
SURFACE = "#FFFFFF"  # pure white to match the deck background exactly


def _style_axes(ax, *, horizontal_grid: bool = True) -> None:
    """Apply the dataviz skill's chrome rules: hairline solid grid, recessive
    spines, muted ticks, no dashed lines, no heavy borders.
    """
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color(BASELINE)
        ax.spines[spine_name].set_linewidth(1)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9)
    if horizontal_grid:
        ax.yaxis.grid(True, color=GRIDLINE, linewidth=1, linestyle="-")
        ax.xaxis.grid(False)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(TEXT_SECONDARY)
    ax.yaxis.label.set_color(TEXT_SECONDARY)
    ax.title.set_color(TEXT_PRIMARY)


def _new_figure(figsize: tuple[float, float] = (8, 5)):
    fig, ax = plt.subplots(figsize=figsize, dpi=200)
    return fig, ax


def _save(fig, out_dir: Path, stem: str) -> None:
    """Write both PNG (200dpi, per spec) and PDF twins of one figure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_dir / f"{stem}.png", dpi=200, facecolor=SURFACE)
    fig.savefig(out_dir / f"{stem}.pdf", facecolor=SURFACE)
    plt.close(fig)


def _write_json(analysis_dir: Path, stem: str, payload: dict) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / f"{stem}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _skip(figure: str, reason: str) -> None:
    """Log why a figure was skipped and move on; the tool must still exit 0."""
    print(f"[plots] skip {figure}: {reason}", file=sys.stderr)


# =============================================================================
# Campaign discovery: read campaign_state.jsonl + per-job config.used.json /
# results.json without assuming which job families are present yet.
# =============================================================================


@dataclass
class Job:
    """One job's resolved location + latest campaign_state.jsonl attempt.

    ``manifest`` is the raw manifest entry (config path, seed, kind, ...) when
    discoverable; figures that need the source config (topology fingerprint,
    reproduction commands) degrade gracefully when it is empty.
    """

    job_id: str
    job_dir: Path
    status: str | None
    run_dir: Path | None
    wall_seconds: float | None
    peak_mem_used_kb: float | None
    manifest: dict = field(default_factory=dict)

    @property
    def config_used(self) -> dict:
        path = self.job_dir / "run_0001" / "config.used.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @property
    def results(self) -> list[dict]:
        """Content/event records from results.json, or [] if unavailable.

        Missing results.json (a crashed/incomplete attempt, or a `linear`
        scenario which never writes one) is not an error here -- callers
        treat an empty list the same as "no data for this job".
        """
        if self.run_dir is None:
            return []
        path = self.run_dir / "results.json"
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return raw if isinstance(raw, list) else []


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def load_campaign_state(campaign_dir: Path) -> list[dict]:
    """Every attempt line from campaign_state.jsonl, in file order."""
    return _read_jsonl(campaign_dir / "campaign_state.jsonl")


def _final_attempt_by_job(state_rows: list[dict]) -> dict[str, dict]:
    """Last recorded attempt per job_id (a resumed campaign retries in place,
    appending new lines for the same job_id) -- last line wins.
    """
    last: dict[str, dict] = {}
    for row in state_rows:
        job_id = row.get("job_id")
        if job_id is not None:
            last[job_id] = row
    return last


def _load_manifest_index(campaign_dir: Path) -> dict[str, dict]:
    """Best-effort job_id -> manifest job entry (config/seed/kind/hosts).

    campaign_state.jsonl and the job directories are always enough to locate
    results.json, but reproducing a job (topology fingerprint, "how do I
    re-run this") needs the source config path + seed, which campaign.py
    reads from a manifest file that lives *next to*, not inside, the
    campaign-dir it produces (see logs/workshop_20260707/manifests/*.json in
    this repo). Missing manifest just means those figures/commands fall back
    to "manifest unavailable" rather than fabricating a config path.
    """
    candidates = [
        campaign_dir / "manifest.json",
        campaign_dir.parent / "manifests" / f"{campaign_dir.name}.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        jobs = data.get("jobs", [])
        return {j["id"]: j for j in jobs if "id" in j}
    return {}


def discover_jobs(campaign_dir: Path) -> dict[str, Job]:
    """One Job per immediate subdirectory of campaign_dir."""
    state_rows = load_campaign_state(campaign_dir)
    last_attempt = _final_attempt_by_job(state_rows)
    manifest_index = _load_manifest_index(campaign_dir)

    jobs: dict[str, Job] = {}
    for job_dir in sorted(p for p in campaign_dir.iterdir() if p.is_dir()):
        job_id = job_dir.name
        attempt = last_attempt.get(job_id)
        run_dir = None
        if attempt and attempt.get("run_dir"):
            candidate = Path(attempt["run_dir"])
            if candidate.exists():
                run_dir = candidate
        jobs[job_id] = Job(
            job_id=job_id,
            job_dir=job_dir,
            status=attempt.get("status") if attempt else None,
            run_dir=run_dir,
            wall_seconds=attempt.get("wall_seconds") if attempt else None,
            peak_mem_used_kb=attempt.get("peak_mem_used_kb") if attempt else None,
            manifest=manifest_index.get(job_id, {}),
        )
    return jobs


def _match(jobs: dict[str, Job], pattern: str) -> list[Job]:
    """Jobs whose id fully matches ``pattern`` (anchored), sorted by id."""
    rx = re.compile(pattern)
    return sorted(
        (j for j in jobs.values() if rx.fullmatch(j.job_id)), key=lambda j: j.job_id
    )


def _contains_token(jobs: dict[str, Job], token: str) -> list[Job]:
    """Jobs whose id contains ``token`` as an underscore-delimited word.

    Used for the M1/M5a families, which need to keep working against the ad
    hoc smoke/probe job ids (``smoke_m1``) as well as the real campaign's
    (``m1_same_r0``, ``m1_seed101``) -- see module docstring on graceful
    degradation. Grouping by *observed* seed/config data rather than by a
    strict job_id regex is what makes both naming schemes work unmodified.
    """
    rx = re.compile(rf"(?:^|_){token}(?:_|$)")
    return sorted((j for j in jobs.values() if rx.search(j.job_id)), key=lambda j: j.job_id)


def eval_success(record: dict) -> bool:
    """True only for a definitive success Verdict (mirrors tools/autotest/analyze.py)."""
    return from_record(record).success is True


# =============================================================================
# M1: reproducibility (same-seed determinism + distinct-seed diversity)
# =============================================================================


def _m1_jobs_by_seed(jobs: dict[str, Job]) -> dict[int, list[Job]]:
    """All M1-family jobs, grouped by their *observed* seed (config.used.json).

    The seed groups are discovered from data, not job-id parsing: the
    reproducibility set is whichever seed the most jobs share (10 in the real
    campaign, 1 in the smoke sample); every other M1 job is a distinct-seed
    diversity sample. This makes the same code correct for both the
    production job ids (m1_same_r0.., m1_seed101..) and the ad hoc smoke id
    (smoke_m1) without special-casing either.
    """
    by_seed: dict[int, list[Job]] = {}
    for job in _contains_token(jobs, "m1"):
        seed = job.config_used.get("seed")
        if seed is None:
            seed = job.manifest.get("seed")
        if seed is None:
            continue
        by_seed.setdefault(int(seed), []).append(job)
    return by_seed


def _m1_groups(jobs: dict[str, Job]) -> tuple[list[Job], list[Job]]:
    """(same_seed_group, distinct_seed_group) picked by observed seed counts."""
    by_seed = _m1_jobs_by_seed(jobs)
    if not by_seed:
        return [], []
    same_seed_value = max(by_seed, key=lambda seed: len(by_seed[seed]))
    same_group = by_seed[same_seed_value]
    distinct_group = [j for seed, js in by_seed.items() if seed != same_seed_value for j in js]
    return same_group, distinct_group


def fig_m1_structure(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m1_structure"
    same_group, distinct_group = _m1_groups(jobs)
    if not same_group and not distinct_group:
        _skip(name, "no m1-family jobs found")
        return

    def _fingerprint(job: Job) -> str | None:
        config_path = job.manifest.get("config")
        seed = job.config_used.get("seed", job.manifest.get("seed"))
        if not config_path or seed is None:
            return None
        try:
            return topo_fingerprint.build_fingerprint(config_path, int(seed))["fingerprint"]
        except Exception as exc:  # noqa: BLE001 -- a bad/rotated config must not crash the batch
            print(f"[plots] {name}: fingerprint failed for {job.job_id}: {exc}", file=sys.stderr)
            return None

    same_fps = [fp for fp in (_fingerprint(j) for j in same_group) if fp is not None]
    distinct_fps = [fp for fp in (_fingerprint(j) for j in distinct_group) if fp is not None]

    if not same_fps and not distinct_fps:
        _skip(name, "manifest lookup unavailable for m1 jobs (no config/seed to fingerprint)")
        return

    n_identical = max((same_fps.count(fp) for fp in set(same_fps)), default=0)
    n_unique = len(set(distinct_fps))

    payload = {
        "same_seed": {"n_jobs": len(same_fps), "n_identical": n_identical},
        "distinct_seed": {"n_jobs": len(distinct_fps), "n_unique": n_unique},
    }
    _write_json(analysis_dir, name, payload)

    fig, ax = _new_figure((7, 4.5))
    categories = ["Same-seed\n(reproducibility)", "Distinct-seed\n(diversity)"]
    fractions = [
        (n_identical / len(same_fps)) if same_fps else 0.0,
        (n_unique / len(distinct_fps)) if distinct_fps else 0.0,
    ]
    labels = [
        f"{n_identical}/{len(same_fps)} identical" if same_fps else "no data",
        f"{n_unique}/{len(distinct_fps)} distinct" if distinct_fps else "no data",
    ]
    # Neutral single-series result (no failure/baseline contrast to draw):
    # near-black, keeping red available for figures with a real emphasis.
    bars = ax.bar(categories, fractions, width=0.5, color=CATEGORICAL[1])
    for bar, label in zip(bars, labels):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.03,
            label,
            ha="center",
            va="bottom",
            fontsize=9,
            color=TEXT_PRIMARY,
        )
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Fraction of expected outcome")
    ax.set_title("M1: topology build is deterministic per seed, diverse across seeds")
    _style_axes(ax)
    _save(fig, out_dir, name)


def fig_m1_verdict_agreement(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m1_verdict_agreement"
    same_group, _ = _m1_groups(jobs)
    if not same_group:
        _skip(name, "no same-seed m1 jobs found")
        return

    # Per-run content-op sequences (event records excluded), in ts order.
    run_sequences: list[list[dict]] = []
    for job in same_group:
        seq = [r for r in job.results if r.get("op_type") in ("put", "get", "pub", "sub")]
        if seq:
            run_sequences.append(seq)
    if not run_sequences:
        _skip(name, "no content records in same-seed m1 runs")
        return

    n_ops = min(len(seq) for seq in run_sequences)
    op_labels: list[str] = []
    agreement: list[float] = []
    for i in range(n_ops):
        slot = [seq[i] for seq in run_sequences]
        first = slot[0]
        op_labels.append(f"{first.get('op_type')}:h{first.get('host')}")
        successes = [eval_success(r) for r in slot]
        majority = sum(successes) >= len(successes) / 2
        agreement.append(sum(1 for s in successes if s == majority) / len(successes))

    payload = {
        "n_runs": len(run_sequences),
        "n_ops": n_ops,
        "op_labels": op_labels,
        "agreement": agreement,
    }
    _write_json(analysis_dir, name, payload)

    fig, ax = _new_figure((max(7, n_ops * 0.6), 4.5))
    ax.bar(range(n_ops), agreement, color=CATEGORICAL[1], width=0.6)
    ax.set_xticks(range(n_ops))
    ax.set_xticklabels(op_labels, rotation=45, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Success-vector agreement")
    title = f"M1: per-op verdict agreement across {len(run_sequences)} same-seed runs"
    if len(run_sequences) == 1:
        # Long caveat as its own title line (not appended inline) so it wraps
        # within the figure width instead of overflowing the canvas edge.
        title += "\n(n=1 sample: trivially 1.0, not yet a determinism signal)"
    ax.set_title(title, fontsize=11)
    _style_axes(ax)
    _save(fig, out_dir, name)


def fig_m1_perf_cv(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m1_perf_cv"
    same_group, _ = _m1_groups(jobs)
    if not same_group:
        _skip(name, "no same-seed m1 jobs found")
        return

    # filename -> list of (throughput_bps, duration_sec) across runs. Using
    # the deterministic content-log filename (cmd_phase_hHOST_uri.log) as the
    # cross-run join key is valid here because same-seed runs replay the same
    # config, hence the same schedule of log filenames (see summarizer.py's
    # last-wins docstring for why a repeated event still yields one filename).
    by_filename: dict[str, list[tuple[float, float]]] = {}
    for job in same_group:
        if job.run_dir is None:
            continue
        grouped = collect_records([job.run_dir])
        for row in grouped.get("cefgetfile", []):
            throughput = row.get("throughput_bps")
            duration = row.get("duration_sec")
            if not isinstance(throughput, (int, float)) or not isinstance(duration, (int, float)):
                continue
            by_filename.setdefault(row["filename"], []).append((throughput, duration))

    if not by_filename:
        _skip(name, "no parsed cefgetfile logs in same-seed m1 runs")
        return

    op_names = sorted(by_filename)
    throughput_series = [[t for t, _ in by_filename[name_]] for name_ in op_names]
    duration_series = [[d for _, d in by_filename[name_]] for name_ in op_names]

    def _cv_pct(samples: list[float]) -> float | None:
        if len(samples) < 2 or mean(samples) == 0:
            return None
        return 100.0 * pstdev(samples) / mean(samples)

    payload = {
        "n_runs": len(same_group),
        "ops": op_names,
        "throughput_bps_cv_pct": [_cv_pct(s) for s in throughput_series],
        "duration_sec_cv_pct": [_cv_pct(s) for s in duration_series],
    }
    _write_json(analysis_dir, name, payload)

    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(max(7, len(op_names) * 0.7), 7), dpi=200)
    for ax, series, ylabel, cvs in (
        (ax_top, throughput_series, "Throughput (bps)", payload["throughput_bps_cv_pct"]),
        (ax_bottom, duration_series, "Duration (s)", payload["duration_sec_cv_pct"]),
    ):
        bp = ax.boxplot(series, tick_labels=[o.replace(".log", "") for o in op_names], patch_artist=True)
        for patch in bp["boxes"]:
            patch.set_facecolor(CATEGORICAL[1])
            patch.set_alpha(0.35)
            patch.set_edgecolor(CATEGORICAL[1])
        for median in bp["medians"]:
            median.set_color(TEXT_PRIMARY)
        for i, cv in enumerate(cvs):
            label = f"CV={cv:.1f}%" if cv is not None else "n=1"
            ax.text(i + 1, max(series[i]), label, ha="center", va="bottom", fontsize=8, color=TEXT_SECONDARY)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        _style_axes(ax)
    ax_top.set_title(f"M1: per-op performance spread across {len(same_group)} same-seed runs")
    _save(fig, out_dir, name)


# =============================================================================
# M5a: THE HEADLINE -- get success rate, publisher up vs down, cache vs nocache
# =============================================================================


def _m5a_bucket(job: Job) -> str:
    """"cache" if the job's merged config carries a cache_config block, else
    "nocache" (the m5a_pubdown_nocache.yaml convention: no cache_config, just
    cache_count/down_count floors -- see that file's own comment for why
    there is no config that yields literally zero cache nodes).
    """
    return "cache" if job.config_used.get("cache_config") else "nocache"


def fig_m5a_pubdown(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m5a_pubdown"
    m5a_jobs = _contains_token(jobs, "m5a")
    if not m5a_jobs:
        _skip(name, "no m5a-family jobs found")
        return

    # cell = (bucket, publisher_state) -> [success bools]
    cells: dict[tuple[str, str], list[bool]] = {}
    for job in m5a_jobs:
        bucket = _m5a_bucket(job)
        for record in job.results:
            if record.get("op_type") != "get" or record.get("phase") == "warmup":
                continue
            state = "down" if record.get("publisher_down") else "up"
            cells.setdefault((bucket, state), []).append(eval_success(record))

    if not cells:
        _skip(name, "no eval get records found across m5a jobs")
        return

    buckets = [b for b in ("cache", "nocache") if any(k[0] == b for k in cells)]
    payload = {
        "buckets": {
            bucket: {
                state: {
                    "n": len(cells.get((bucket, state), [])),
                    "success_rate": (
                        sum(cells[(bucket, state)]) / len(cells[(bucket, state)])
                        if cells.get((bucket, state))
                        else None
                    ),
                }
                for state in ("up", "down")
            }
            for bucket in buckets
        }
    }
    _write_json(analysis_dir, name, payload)

    fig, ax = _new_figure((7, 5))
    x = range(len(buckets))
    width = 0.32
    # Emphasis lands on the "down" bars (TUT red via STATUS["critical"]):
    # the headline claim is what happens WHILE the publisher is down; the
    # "up" bars are the neutral near-black baseline (STATUS["good"]).
    for offset, state, color, state_label in (
        (-width / 2, "up", STATUS["good"], "Publisher up"),
        (width / 2, "down", STATUS["critical"], "Publisher down"),
    ):
        rates = [
            payload["buckets"][b][state]["success_rate"] or 0.0 for b in buckets
        ]
        ns = [payload["buckets"][b][state]["n"] for b in buckets]
        bars = ax.bar(
            [xi + offset for xi in x], rates, width=width, color=color, label=state_label,
        )
        for bar, n, rate in zip(bars, ns, rates):
            label = f"{rate:.0%}\n(n={n})" if n else "n=0"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.02,
                label,
                ha="center",
                va="bottom",
                fontsize=8,
                color=TEXT_PRIMARY,
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(["csmgrd x3 (k_centers)" if b == "cache" else "csmgrd x1 (minimum)" for b in buckets])  # 2026-07-07: local CS confound -> honest labels
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("Get eval success rate")
    ax.set_title("M5a: get success while the publisher is up vs down")
    ax.legend(frameon=False, loc="upper right", labelcolor=TEXT_SECONDARY)
    _style_axes(ax)
    _save(fig, out_dir, name)


# =============================================================================
# M2: topology x command success-rate matrix
# =============================================================================


def fig_m2_matrix(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m2_matrix"
    families = {
        ("linear", "putget"): _match(jobs, r"m2_linear_r\d+"),
        ("mesh", "putget"): _match(jobs, r"m2_putget_s\d+"),
        ("mesh", "pubsub"): _match(jobs, r"m2_pubsub_s\d+"),
        ("disaster", "putget"): _match(jobs, r"m2_disaster_s\d+"),
    }
    if not any(families.values()):
        _skip(name, "no m2-family jobs found")
        return

    def _rate(job_list: list[Job], op_types: tuple[str, ...]) -> tuple[float | None, int]:
        successes = 0
        total = 0
        for job in job_list:
            for record in job.results:
                if record.get("op_type") not in op_types or record.get("phase") == "warmup":
                    continue
                total += 1
                successes += int(eval_success(record))
        return (successes / total if total else None, total)

    rows = ["linear", "mesh", "disaster"]
    cols = ["put/get", "pubsub"]
    cells: dict[str, dict[str, Any]] = {}
    for topo in rows:
        cells[topo] = {}
        for col in cols:
            if topo == "linear" and col == "pubsub":
                cells[topo][col] = {"note": "CLI demo"}
                continue
            key = (topo, "pubsub" if col == "pubsub" else "putget")
            job_list = families.get(key, [])
            op_types = ("pub", "sub") if col == "pubsub" else ("put", "get")
            rate, n = _rate(job_list, op_types)
            cells[topo][col] = {"success_rate": rate, "n": n}

    _write_json(analysis_dir, name, {"rows": rows, "cols": cols, "cells": cells})

    fig, ax = _new_figure((7, 3.5))
    ax.axis("off")
    table_data = []
    for topo in rows:
        row_cells = []
        for col in cols:
            cell = cells[topo][col]
            if "note" in cell:
                row_cells.append(cell["note"])
            elif cell["success_rate"] is None:
                row_cells.append("no data")
            else:
                row_cells.append(f"{cell['success_rate']:.0%} (n={cell['n']})")
        table_data.append(row_cells)
    table = ax.table(
        cellText=table_data,
        rowLabels=rows,
        colLabels=cols,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2)
    ax.set_title("M2: success rate by topology x command", color=TEXT_PRIMARY, pad=20)
    _save(fig, out_dir, name)


# =============================================================================
# M5b: get success/fail timeline relative to link_down/link_up
# =============================================================================


def fig_m5b_timeline(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m5b_timeline"
    m5b_jobs = _match(jobs, r"m5b_s\d+")
    if not m5b_jobs:
        _skip(name, "no m5b-family jobs found")
        return

    from datetime import datetime

    def _parse_ts(ts: str) -> float:
        return datetime.fromisoformat(ts).timestamp()

    rows_payload = []
    for job in m5b_jobs:
        records = job.results
        if not records:
            continue
        t0 = _parse_ts(records[0]["ts"])
        gets = [
            (_parse_ts(r["ts"]) - t0, eval_success(r))
            for r in records
            if r.get("op_type") == "get" and r.get("phase") != "warmup"
        ]
        link_events = [
            (_parse_ts(r["ts"]) - t0, r.get("event_type"), r.get("success"))
            for r in records
            if r.get("op_type") == "event" and r.get("event_type") in ("link_down", "link_up")
        ]
        if gets:
            rows_payload.append({"job_id": job.job_id, "gets": gets, "link_events": link_events})

    if not rows_payload:
        _skip(name, "no eval get records in m5b runs")
        return

    _write_json(analysis_dir, name, {"seeds": rows_payload})

    fig, ax = _new_figure((9, max(3, 0.6 * len(rows_payload) + 1)))
    for row_idx, entry in enumerate(rows_payload):
        for t, success in entry["gets"]:
            color = STATUS["good"] if success else STATUS["critical"]
            ax.scatter(t, row_idx, color=color, s=36, zorder=3)
        for t, event_type, success in entry["link_events"]:
            if not success:
                continue  # failed link_down/link_up outcome: topology had no such edge this seed
            # Context lines stay grayscale (dark=down, light=up) so the only
            # red on this figure is the get-failure markers -- the emphasis.
            marker_color = CATEGORICAL[4] if event_type == "link_down" else CATEGORICAL[3]
            ax.axvline(t, color=marker_color, linewidth=1, alpha=0.5, zorder=1)
    ax.set_yticks(range(len(rows_payload)))
    ax.set_yticklabels([e["job_id"] for e in rows_payload])
    ax.set_xlabel("Seconds since run start")
    ax.set_title("M5b: get outcomes around link_down/link_up (dark gray=down, light gray=up)")
    legend_handles = [
        Patch(facecolor=STATUS["good"], label="get success"),
        Patch(facecolor=STATUS["critical"], label="get failure"),
    ]
    ax.legend(handles=legend_handles, frameon=False, loc="upper right", labelcolor=TEXT_SECONDARY)
    _style_axes(ax, horizontal_grid=False)
    _save(fig, out_dir, name)


# =============================================================================
# M5c: success rate vs failure intensity (down_count 1..4)
# =============================================================================


def fig_m5c_intensity(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m5c_intensity"
    by_dc: dict[int, list[Job]] = {}
    for dc in (1, 2, 3, 4):
        matched = _match(jobs, rf"m5c_dc{dc}_s\d+")
        if matched:
            by_dc[dc] = matched
    if not by_dc:
        _skip(name, "no m5c-family jobs found")
        return

    per_dc_rates: dict[int, list[float]] = {}
    for dc, job_list in by_dc.items():
        rates = []
        for job in job_list:
            successes = [
                eval_success(r)
                for r in job.results
                if r.get("op_type") in ("get", "sub") and r.get("phase") != "warmup"
            ]
            if successes:
                rates.append(sum(successes) / len(successes))
        if rates:
            per_dc_rates[dc] = rates

    if not per_dc_rates:
        _skip(name, "no eval get/sub records in m5c runs")
        return

    dcs = sorted(per_dc_rates)
    means = [mean(per_dc_rates[dc]) for dc in dcs]
    errs = [pstdev(per_dc_rates[dc]) if len(per_dc_rates[dc]) > 1 else 0.0 for dc in dcs]
    _write_json(
        analysis_dir,
        name,
        {"down_count": dcs, "mean_success_rate": means, "stdev": errs, "n_seeds": [len(per_dc_rates[dc]) for dc in dcs]},
    )

    fig, ax = _new_figure((6.5, 4.5))
    ax.errorbar(dcs, means, yerr=errs, color=CATEGORICAL[1], marker="o", markersize=6, linewidth=2, capsize=4)
    ax.set_xticks(dcs)
    ax.set_xlabel("down_count (hosts flapped per cycle)")
    ax.set_ylabel("Eval success rate")
    ax.set_ylim(0, 1.05)
    ax.set_title("M5c: success rate vs failure intensity")
    _style_axes(ax)
    _save(fig, out_dir, name)


# =============================================================================
# M5d: success rate per cache strategy
# =============================================================================


def fig_m5d_strategies(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m5d_strategies"
    strategies = ["kcenters", "degree", "manual"]
    by_strategy: dict[str, list[Job]] = {}
    for strategy in strategies:
        matched = _match(jobs, rf"m5d_{strategy}_s\d+")
        if matched:
            by_strategy[strategy] = matched
    if not by_strategy:
        _skip(name, "no m5d-family jobs found")
        return

    rates_by_strategy: dict[str, list[float]] = {}
    for strategy, job_list in by_strategy.items():
        rates = []
        for job in job_list:
            successes = [
                eval_success(r)
                for r in job.results
                if r.get("op_type") in ("get", "sub") and r.get("phase") != "warmup"
            ]
            if successes:
                rates.append(sum(successes) / len(successes))
        if rates:
            rates_by_strategy[strategy] = rates

    if not rates_by_strategy:
        _skip(name, "no eval get/sub records in m5d runs")
        return

    names_present = [s for s in strategies if s in rates_by_strategy]
    means = [mean(rates_by_strategy[s]) for s in names_present]
    errs = [pstdev(rates_by_strategy[s]) if len(rates_by_strategy[s]) > 1 else 0.0 for s in names_present]
    _write_json(
        analysis_dir,
        name,
        {
            "strategies": names_present,
            "mean_success_rate": means,
            "stdev": errs,
            "n_seeds": [len(rates_by_strategy[s]) for s in names_present],
        },
    )

    fig, ax = _new_figure((6.5, 4.5))
    ax.bar(names_present, means, yerr=errs, capsize=4, color=CATEGORICAL[1], width=0.5)
    ax.set_ylabel("Eval success rate")
    ax.set_ylim(0, 1.05)
    ax.set_title("M5d: success rate by cache node-selection strategy")
    _style_axes(ax)
    _save(fig, out_dir, name)


# =============================================================================
# M5e: repeated publisher outages -- cached vs fresh URI availability timeline
# =============================================================================


# host number -> lane label. The M5e scenario is a fixed three-actor story:
# h7 re-fetches a URI it already cached before any outage (the control), h3
# fetches a fresh URI for the first time mid-story, and h5 is a brand-new
# consumer that only starts asking after the content is already cached
# upstream. Hosts outside this cast (if a config variant adds one) fall back
# to a plain "hN" lane rather than being dropped.
def _m5e_lane_labels(gets_raw: list[dict]) -> dict[tuple[int, str], str]:
    """Per-seed role classification (hosts differ per seed's cache placement).

    The generated configs (tools/workshop/gen_m5e_config.py) schedule roles
    by first-attempt order: control polls the pre-cached URI from t=5; the
    fresh URI is touched first by the protagonist (cache on its path), then
    the unlucky contrast host (no cache on any path), and last by the
    newcomer whose first touch lands inside a later outage window. Deriving
    labels from (uri, first-attempt order) keeps the figure correct for any
    seed without hardcoding host ids.
    """
    firsts: dict[tuple[int, str], float] = {}
    for r in gets_raw:
        key = (r.get("host"), r.get("uri", ""))
        ts = r["_t"]
        if key not in firsts or ts < firsts[key]:
            firsts[key] = ts
    labels: dict[tuple[int, str], str] = {}
    fresh = sorted(
        (k for k in firsts if "cached" not in k[1]), key=lambda k: firsts[k]
    )
    fresh_roles = ["cache on path", "no cache on path", "new consumer"]
    for key in firsts:
        host, uri = key
        if "cached" in uri:
            labels[key] = f"pre-cached URI @h{host} (control)"
    for idx, key in enumerate(fresh):
        role = fresh_roles[idx] if idx < len(fresh_roles) else f"extra {idx}"
        labels[key] = f"fresh URI @h{key[0]} ({role})"
    ordered = [labels[k] for k in sorted(firsts, key=lambda k: ("cached" not in k[1], firsts[k]))]
    return labels, ordered
# Outage band fill: lighter than any palette gray so markers stay readable
# on top of it; the band is context, not data.
_M5E_BAND = "#e8e8e8"


def fig_m5e_timeline(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    """Per-lane get outcomes over time against shaded publisher-down windows.

    Emphasis: failed gets are the only red (TUT #B6261D, large X); successes
    are near-black dots; outage windows are light-gray bands with thin red
    solid boundary lines (dashed linestyles are banned deck-wide).
    """
    name = "m5e_timeline"
    # Anchored fullmatch: real campaign ids (m5e_s101), a bare family id
    # (m5e), and the ad hoc smoke id (smoke_m5e) all resolve to this figure.
    m5e_jobs = _match(jobs, r"(?:smoke_)?m5e(?:_s\d+)?")
    if not m5e_jobs:
        _skip(name, "no m5e-family jobs found")
        return

    from datetime import datetime

    def _parse_ts(ts: str) -> float:
        return datetime.fromisoformat(ts).timestamp()

    per_job: dict[str, dict] = {}
    for job in m5e_jobs:
        gets_raw = [
            r
            for r in job.results
            if r.get("op_type") == "get" and r.get("phase") in ("eval", "event")
        ]
        if not gets_raw:
            continue
        # t=0 is the first get, not the first record: the put/warmup preamble
        # before it is setup noise the availability story doesn't cover.
        t0 = _parse_ts(gets_raw[0]["ts"])
        for r in gets_raw:
            r["_t"] = _parse_ts(r["ts"])
        # Story order: control on top, then the fresh lanes by first attempt.
        lane_of, lane_order = _m5e_lane_labels(gets_raw)
        gets = [
            {
                "lane": lane_of.get((r.get("host"), r.get("uri", "")), f"h{r.get('host')}"),
                "t": r["_t"] - t0,
                "success": eval_success(r),
                "publisher_down": bool(r.get("publisher_down")),
            }
            for r in gets_raw
        ]
        # host_down -> host_up pairs become outage windows. A failed event
        # outcome means the host never actually flapped, so it must not open
        # or close a window (same rule as m5b's failed link events).
        events = [
            (_parse_ts(r["ts"]) - t0, r.get("event_type"))
            for r in job.results
            if r.get("op_type") == "event"
            and r.get("event_type") in ("host_down", "host_up")
            and r.get("success") is not False
        ]
        windows: list[list[float]] = []
        open_t: float | None = None
        for t, event_type in events:
            if event_type == "host_down" and open_t is None:
                open_t = t
            elif event_type == "host_up" and open_t is not None:
                windows.append([open_t, t])
                open_t = None
        if open_t is not None:
            # Publisher still down when the run ended: close the band at the
            # last observed get so the shading doesn't run off to infinity.
            windows.append([open_t, max(g["t"] for g in gets)])
        per_job[job.job_id] = {"windows": windows, "gets": gets, "lane_order": lane_order}

    if not per_job:
        _skip(name, "no eval/event get records in m5e runs")
        return

    _write_json(analysis_dir, name, {"per_job": per_job})

    from matplotlib.lines import Line2D

    def _draw(ax, entry: dict, annotate: bool) -> None:
        # Lanes in story order (control on top), plus any off-script hosts.
        lanes = [
            lane
            for lane in entry.get("lane_order", [])
            + sorted({g["lane"] for g in entry["gets"]} - set(entry.get("lane_order", [])))
            if any(g["lane"] == lane for g in entry["gets"])
        ]
        y_of = {lane: i for i, lane in enumerate(lanes)}
        for w0, w1 in entry["windows"]:
            ax.axvspan(w0, w1, color=_M5E_BAND, zorder=0)
            for edge in (w0, w1):
                ax.axvline(edge, color=CATEGORICAL[0], linewidth=0.8, zorder=1)
        for g in entry["gets"]:
            if g["success"]:
                ax.scatter(g["t"], y_of[g["lane"]], marker="o", color=CATEGORICAL[1], s=36, zorder=3)
            else:
                ax.scatter(g["t"], y_of[g["lane"]], marker="X", color=CATEGORICAL[0], s=80, zorder=3)
        ax.set_yticks(range(len(lanes)))
        ax.set_yticklabels(lanes)
        # Reversed limits put lane 0 (the control) at the top, with headroom
        # above it (-0.8) so beat annotations don't collide with the title.
        ax.set_ylim(len(lanes) - 0.5, -0.8)
        _style_axes(ax, horizontal_grid=False)

        if not annotate:
            return
        # The three story beats, located from the data rather than hardcoded
        # times so re-runs with different event schedules keep correct labels.
        gets = entry["gets"]
        first_fail = next((g for g in gets if not g["success"]), None)
        # Beat 2 is the fresh URI's own recovery: the first success on the
        # SAME lane that just failed (the control lane succeeds throughout,
        # so an any-lane "first success" would mislabel the story).
        first_ok = None
        if first_fail is not None:
            first_ok = next(
                (
                    g
                    for g in gets
                    if g["success"] and g["lane"] == first_fail["lane"] and g["t"] > first_fail["t"]
                ),
                None,
            )
        # Beat 3 must land AFTER beat 2 in story time: the control lane also
        # serves from cache during the first outage, but the payoff being
        # annotated is cache service after the fresh URI got cached.
        first_ok_down = next(
            (
                g
                for g in gets
                if g["success"]
                and g["publisher_down"]
                and (first_ok is None or g["t"] > first_ok["t"])
            ),
            None,
        )
        beats = [
            (first_fail, "fails (no cache)"),
            (first_ok, "first success -> cached"),
            (first_ok_down, "served from cache while publisher down"),
        ]
        for beat, label in beats:
            if beat is None:
                continue
            ax.annotate(
                label,
                xy=(beat["t"], y_of[beat["lane"]]),
                xytext=(beat["t"], y_of[beat["lane"]] - 0.55),
                fontsize=8,
                color=TEXT_SECONDARY,
                ha="center",
                arrowprops={"arrowstyle": "-", "color": TEXT_MUTED, "linewidth": 0.8},
            )

    # The DECK figure is the annotated representative panel alone (first job
    # by id -- seed order); the cross-seed small multiples go to a separate
    # `<name>_all` stem for the appendix / verification, so the slide image
    # stays landscape instead of a 5-panel portrait stack.
    job_ids = list(per_job)
    if len(job_ids) > 1:
        fig_all, axes_all = plt.subplots(
            len(job_ids), 1, figsize=(9, 2.8 * len(job_ids)), dpi=200
        )
        for idx, (ax, job_id) in enumerate(zip(list(axes_all), job_ids)):
            _draw(ax, per_job[job_id], annotate=False)
            ax.set_title(job_id, fontsize=9, color=TEXT_SECONDARY)
        list(axes_all)[-1].set_xlabel("Seconds since first get")
        fig_all.suptitle(
            "M5e: content availability across repeated publisher outages (all seeds)",
            color=TEXT_PRIMARY,
        )
        _save(fig_all, out_dir, f"{name}_all")
    job_ids = job_ids[:1]
    fig, ax = _new_figure((9, 3.6))
    axes = [ax]
    for idx, (ax, job_id) in enumerate(zip(axes, job_ids)):
        # 2026-07-14: annotations off -- three beats land within ~20s of each
        # other and the labels collide; the slide text carries the reading.
        _draw(ax, per_job[job_id], annotate=False)
        if len(job_ids) > 1:
            ax.set_title(job_id, fontsize=9, color=TEXT_SECONDARY)
    axes[-1].set_xlabel("Seconds since first get")
    legend_handles = [
        Line2D([], [], marker="o", linestyle="", color=CATEGORICAL[1], label="get success"),
        Line2D([], [], marker="X", linestyle="", color=CATEGORICAL[0], label="get failure"),
        Patch(facecolor=_M5E_BAND, label="publisher down"),
    ]
    axes[0].legend(
        handles=legend_handles, frameon=False, loc="upper right", fontsize=8,
        labelcolor=TEXT_SECONDARY,
    )
    title = "M5e: content availability across repeated publisher outages"
    if len(job_ids) == 1:
        axes[0].set_title(title)
    else:
        fig.suptitle(title, color=TEXT_PRIMARY)
    _save(fig, out_dir, name)


# =============================================================================
# M3: host-count scale vs setup wall time / success rate / peak memory
# =============================================================================


def fig_m3_scale(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m3_scale"
    host_counts = [5, 15, 30, 45, 60]
    by_hosts: dict[int, list[Job]] = {}
    for hosts in host_counts:
        matched = _match(jobs, rf"m3_h{hosts}_s\d+")
        if matched:
            by_hosts[hosts] = matched
    if not by_hosts:
        _skip(name, "no m3-family jobs found")
        return

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        s = sorted(values)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    hosts_present = sorted(by_hosts)
    median_wall = []
    success_rates = []
    peak_mem_gb = []
    for hosts in hosts_present:
        job_list = by_hosts[hosts]
        walls = [j.wall_seconds for j in job_list if j.wall_seconds is not None]
        mems = [j.peak_mem_used_kb for j in job_list if j.peak_mem_used_kb is not None]
        # 2026-07-07 fix: sub を混ぜると pubsub の hop-distance 既知問題 (CONTEXT.md)
        # がスケール軸の凹みに見えてしまう。この図の主張は「put/get がどのスケール
        # でも成立するか」なので get のみに限定する (実測: h5-h60 全て 100%)。
        # pubsub のスケール挙動は caveats + M2 の行で別途報告する。
        successes = [
            eval_success(r)
            for j in job_list
            for r in j.results
            if r.get("op_type") == "get" and r.get("phase") != "warmup"
        ]
        median_wall.append(_median(walls))
        peak_mem_gb.append(_median([m / 1e6 for m in mems]))
        success_rates.append(sum(successes) / len(successes) if successes else None)

    _write_json(
        analysis_dir,
        name,
        {
            "hosts": hosts_present,
            "median_setup_wall_seconds": median_wall,
            "success_rate": success_rates,
            "median_peak_mem_gb": peak_mem_gb,
        },
    )

    # Three measures at different scales -> three small multiples, never a
    # dual-axis chart (dataviz skill anti-pattern #1: an invented alignment
    # between unrelated scales), sharing one x axis.
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), dpi=200, sharex=True)
    panels = [
        (axes[0], median_wall, "Median setup wall time (s)"),
        (axes[1], success_rates, "Eval get success rate"),
        (axes[2], peak_mem_gb, "Median peak memory (GB)"),
    ]
    for ax, values, ylabel in panels:
        plot_hosts = [h for h, v in zip(hosts_present, values) if v is not None]
        plot_values = [v for v in values if v is not None]
        ax.plot(plot_hosts, plot_values, color=CATEGORICAL[1], marker="o", markersize=6, linewidth=2)
        ax.set_xlabel("Hosts")
        ax.set_ylabel(ylabel)
        _style_axes(ax)
    fig.suptitle("M3: scale-out cost and success rate vs host count", color=TEXT_PRIMARY)
    _save(fig, out_dir, name)


# =============================================================================
# M4: configured bandwidth vs measured cefgetfile throughput
# =============================================================================


# Matches both the legacy bw_set-event family (m4_bw{BW}_s{SEED}) and the
# 2026-07-07 static-bw redesign family (m4st_bw{BW}_s{SEED}) -- job ids
# encode the configured Mbps directly (group 1), so the figure reads it from
# the id instead of keeping a fixed bw-values list per family.
_M4_JOB_RE = re.compile(r"m4(?:st)?_bw(\d+)_s\d+")


def fig_m4_bw_fidelity(jobs: dict[str, Job], analysis_dir: Path, out_dir: Path) -> None:
    name = "m4_bw_fidelity"

    matched = sorted(
        (j for j in jobs.values() if _M4_JOB_RE.fullmatch(j.job_id)),
        key=lambda j: j.job_id,
    )
    if not matched:
        _skip(name, "no m4-family jobs found")
        return

    # Two series, not one: the 2026-07-07 M4 redesign applies the bandwidth
    # cap statically from network-creation time (see config/workshop/
    # m4_static/*.yaml headers), so the WARMUP-phase cefgetfile logs
    # (cefgetfile_warmup_h{N}_*.log -- src/scenarios/disaster.py's
    # _run_warmup, which runs before the eval-phase event scheduler) are now
    # the network-bound "first fetch" measurement, while the EVAL-phase logs
    # (the t=20/35/50 get events, phase="eval") are a cache-hit REPEAT fetch
    # of content warmup already pulled onto that host's cache. Plotting both
    # against the same configured-bw x-axis visualizes the caching
    # acceleration the M4 story is about, instead of just fidelity.
    warmup_points: list[tuple[int, float]] = []
    eval_points: list[tuple[int, float]] = []
    for job in matched:
        bw = int(_M4_JOB_RE.fullmatch(job.job_id).group(1))
        if job.run_dir is None:
            continue
        grouped = collect_records([job.run_dir])
        for row in grouped.get("cefgetfile", []):
            throughput = row.get("throughput_bps")
            if not isinstance(throughput, (int, float)):
                continue
            mbps = throughput / 1e6  # bps -> Mbps
            if row.get("phase") == "warmup":
                warmup_points.append((bw, mbps))
            elif row.get("phase") == "eval":
                eval_points.append((bw, mbps))

    if not warmup_points and not eval_points:
        _skip(name, "no parsed cefgetfile throughput in m4 runs")
        return

    _write_json(
        analysis_dir,
        name,
        {
            "warmup_configured_mbps": [p[0] for p in warmup_points],
            "warmup_measured_mbps": [p[1] for p in warmup_points],
            "eval_configured_mbps": [p[0] for p in eval_points],
            "eval_measured_mbps": [p[1] for p in eval_points],
        },
    )

    fig, ax = _new_figure((6.5, 6.5))
    all_values = (
        [p[0] for p in warmup_points]
        + [p[1] for p in warmup_points]
        + [p[0] for p in eval_points]
        + [p[1] for p in eval_points]
    )
    axis_max = max(all_values) * 1.1 if all_values else 100

    # Emphasis: the eval (cache-hit) series IS the M4 story -- points rising
    # above y=x are the caching acceleration -- so it gets the TUT red; the
    # warmup first-fetch series is the near-black baseline it beats.
    if warmup_points:
        ax.scatter(
            [p[0] for p in warmup_points],
            [p[1] for p in warmup_points],
            color=CATEGORICAL[1],
            s=40,
            alpha=0.8,
            zorder=3,
            marker="o",
            label="warmup (network-bound first fetch)",
        )
    if eval_points:
        ax.scatter(
            [p[0] for p in eval_points],
            [p[1] for p in eval_points],
            color=CATEGORICAL[0],
            s=40,
            alpha=0.8,
            zorder=3,
            marker="^",
            label="eval (cache-hit repeat fetch)",
        )
    ax.plot([0, axis_max], [0, axis_max], color=BASELINE, linewidth=1.5, linestyle="-", zorder=1)
    ax.text(axis_max * 0.55, axis_max * 0.6, "y = x (perfect fidelity)", color=TEXT_MUTED, fontsize=8)
    ax.set_xlim(0, axis_max)
    ax.set_ylim(0, axis_max)
    ax.set_xlabel("Configured bandwidth (Mbps)")
    ax.set_ylabel("Measured cefgetfile throughput (Mbps)")
    ax.set_title("M4: bandwidth-cap fidelity vs cache acceleration")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    _style_axes(ax)
    _save(fig, out_dir, name)


FIGURES: list[Callable[[dict[str, Job], Path, Path], None]] = [
    fig_m1_structure,
    fig_m1_verdict_agreement,
    fig_m1_perf_cv,
    fig_m2_matrix,
    fig_m5a_pubdown,
    fig_m5b_timeline,
    fig_m5c_intensity,
    fig_m5d_strategies,
    fig_m5e_timeline,
    fig_m3_scale,
    fig_m4_bw_fidelity,
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="figures output directory")
    args = parser.parse_args(argv)

    campaign_dir: Path = args.campaign_dir.resolve()
    out_dir: Path = args.out.resolve()
    analysis_dir = out_dir.parent / "analysis"

    if not campaign_dir.is_dir():
        print(f"[plots] campaign dir not found: {campaign_dir}", file=sys.stderr)
        return 0  # nothing to do yet; the campaign may not have started

    jobs = discover_jobs(campaign_dir)

    for fn in FIGURES:
        try:
            fn(jobs, analysis_dir, out_dir)
        except Exception:  # noqa: BLE001 -- one figure's bug must not sink the batch
            print(f"[plots] {fn.__name__} raised:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
