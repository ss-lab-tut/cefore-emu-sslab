#!/usr/bin/env python3
"""Render a self-contained HTML report for the workshop measurement campaign.

Usage:
    .venv/bin/python3 tools/workshop/report.py \\
        --campaign-dir logs/workshop_20260707/smoke \\
        --out logs/workshop_20260707/smoke/report.html

By the same convention plots.py writes to, this reads figures from
``<campaign-dir>/figures`` and cached aggregates from
``<campaign-dir>/analysis`` -- run plots.py against the same --campaign-dir
first. The campaign may still be running: any section whose analysis JSON
isn't there yet renders "計測未完了" instead of erroring, so this can be
re-run at any point in an overnight batch and always produce a valid report.

The HTML is a single file: CSS is inlined in a <style> block and every
figure is a base64 data: URI <img>, so the report has no external
dependencies and can be opened, emailed, or printed standalone.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# report.py and plots.py are sibling scripts in this same (non-package)
# directory; reuse plots.py's campaign discovery instead of re-parsing
# campaign_state.jsonl / config.used.json a second time here (see this
# repo's CLAUDE.md: "do not recreate existing functions").
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import plots  # noqa: E402


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _embed_image(figures_dir: Path, stem: str) -> str | None:
    path = figures_dir / f"{stem}.png"
    if not path.exists():
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img class="fig" src="data:image/png;base64,{b64}" alt="{stem}">'


def _fmt_rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _fmt_duration(seconds: float) -> str:
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _repro_command(job: "plots.Job") -> str | None:
    """The exact CLI invocation to reproduce one job, from its manifest entry.

    Mirrors the "Usage:" line every config/workshop/*.yaml carries in its own
    header comment (disaster jobs) or campaign.py's _linear_cmd (linear
    jobs) -- shown as a single representative command per job family, not a
    verbatim replay of campaign.py's own multi-seed driving loop.
    """
    manifest = job.manifest
    if not manifest:
        return None
    if manifest.get("kind") == "linear":
        return f"sudo .venv/bin/python3 -m src linear --hosts {manifest.get('hosts')}"
    config = manifest.get("config")
    seed = manifest.get("seed")
    if config and seed is not None:
        return f"sudo .venv/bin/python3 -m src disaster --config {config} --seed {seed} --no-cli"
    return None


def _pending_html(label: str) -> str:
    return f'<p class="pending">{label}: 計測未完了</p>'


def _code_block(lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(lines)
    return f'<pre class="repro">{body}</pre>'


# =============================================================================
# Campaign-level header stats
# =============================================================================


def _campaign_stats(state_rows: list[dict]) -> dict:
    """Per-job final status (last attempt line wins) + total wall time.

    Total wall time sums *every* attempt line (including retries), since
    that is the actual wall-clock the overnight batch spent; the ok/failed/
    skipped counts use only each job's last attempt, matching campaign.py's
    own resume semantics (only "ok" ever counts as done).
    """
    last_by_job = plots._final_attempt_by_job(state_rows)
    counts = {"ok": 0, "failed": 0, "skipped": 0}
    for row in last_by_job.values():
        status = row.get("status")
        if status == "ok":
            counts["ok"] += 1
        elif status == "skipped_memory":
            counts["skipped"] += 1
        else:  # "failed", "timeout", or anything unrecognized
            counts["failed"] += 1
    total_wall = sum(row.get("wall_seconds") or 0.0 for row in state_rows)
    return {
        "n_jobs": len(last_by_job),
        "counts": counts,
        "total_wall_seconds": total_wall,
        "failed_or_skipped": [
            row for row in last_by_job.values() if row.get("status") != "ok"
        ],
    }


def _render_header(campaign_dir: Path, stats: dict) -> str:
    counts = stats["counts"]
    return f"""
<header>
  <h1>Workshop Measurement Campaign Report</h1>
  <p class="meta">campaign-dir: <code>{campaign_dir}</code> &middot;
     generated {datetime.now(timezone.utc).isoformat(timespec="seconds")}</p>
  <table class="stats">
    <tr><th>Jobs total</th><th>OK</th><th>Failed/timeout</th><th>Skipped</th><th>Total wall time</th></tr>
    <tr>
      <td>{stats['n_jobs']}</td>
      <td class="good">{counts['ok']}</td>
      <td class="critical">{counts['failed']}</td>
      <td class="warning">{counts['skipped']}</td>
      <td>{_fmt_duration(stats['total_wall_seconds'])}</td>
    </tr>
  </table>
</header>
"""


# =============================================================================
# M1: reproducibility
# =============================================================================


def _section_m1(jobs: dict, figures_dir: Path, analysis_dir: Path) -> str:
    structure = _load_json(analysis_dir / "m1_structure.json")
    agreement = _load_json(analysis_dir / "m1_verdict_agreement.json")
    perf_cv = _load_json(analysis_dir / "m1_perf_cv.json")

    evidence: list[str] = []
    if structure:
        same = structure["same_seed"]
        distinct = structure["distinct_seed"]
        evidence.append(
            f"<li>同一シード: {same['n_identical']}/{same['n_jobs']} 件が同一フィンガープリント</li>"
        )
        evidence.append(
            f"<li>異なるシード: {distinct['n_unique']}/{distinct['n_jobs']} 件が相異なるフィンガープリント</li>"
        )
    if agreement:
        avg = sum(agreement["agreement"]) / len(agreement["agreement"]) if agreement["agreement"] else None
        evidence.append(
            f"<li>成否ベクトル一致率: 平均 {_fmt_rate(avg)}（{agreement['n_runs']} run, "
            f"{agreement['n_ops']} ops）</li>"
        )
    if perf_cv:
        cvs = [c for c in perf_cv["throughput_bps_cv_pct"] if c is not None]
        cv_text = f"平均CV {sum(cvs)/len(cvs):.1f}%" if cvs else "n=1（CV算出不可）"
        evidence.append(f"<li>スループットの変動係数（同一シード{perf_cv['n_runs']} run間）: {cv_text}</li>")

    figs = "".join(
        img for img in (
            _embed_image(figures_dir, "m1_structure"),
            _embed_image(figures_dir, "m1_verdict_agreement"),
            _embed_image(figures_dir, "m1_perf_cv"),
        ) if img
    )

    same_group, distinct_group = plots._m1_groups(jobs)
    repro_lines = []
    for label, group in (("same-seed", same_group), ("distinct-seed", distinct_group)):
        if group:
            cmd = _repro_command(group[0])
            if cmd:
                repro_lines.append(f"# {label} representative ({group[0].job_id})\n{cmd}")

    body = "".join(evidence) if evidence else ""
    return f"""
<section id="m1">
  <h2>M1: 同一シードは再現性、異なるシードは多様性を保証する</h2>
  {'<ul class="evidence">' + body + '</ul>' if body else _pending_html("M1")}
  {figs}
  {_code_block(repro_lines)}
</section>
"""


# =============================================================================
# M2: topology x command matrix
# =============================================================================


def _section_m2(jobs: dict, figures_dir: Path, analysis_dir: Path) -> str:
    matrix = _load_json(analysis_dir / "m2_matrix.json")
    fig = _embed_image(figures_dir, "m2_matrix")

    if not matrix:
        return f"""
<section id="m2">
  <h2>M2: トポロジ(linear/mesh/disaster) x コマンド(put/get, pubsub) の成功率</h2>
  {_pending_html("M2")}
</section>
"""

    rows_html = []
    for topo in matrix["rows"]:
        cells = []
        for col in matrix["cols"]:
            cell = matrix["cells"][topo][col]
            if "note" in cell:
                cells.append(f"<td>{cell['note']}</td>")
            elif cell["success_rate"] is None:
                cells.append("<td>N/A</td>")
            else:
                cells.append(f"<td>{_fmt_rate(cell['success_rate'])} (n={cell['n']})</td>")
        rows_html.append(f"<tr><th>{topo}</th>{''.join(cells)}</tr>")

    families = {
        "linear": plots._match(jobs, r"m2_linear_r\d+"),
        "mesh putget": plots._match(jobs, r"m2_putget_s\d+"),
        "mesh pubsub": plots._match(jobs, r"m2_pubsub_s\d+"),
        "disaster": plots._match(jobs, r"m2_disaster_s\d+"),
    }
    repro_lines = []
    for label, group in families.items():
        if group:
            cmd = _repro_command(group[0])
            if cmd:
                repro_lines.append(f"# {label} representative ({group[0].job_id})\n{cmd}")

    return f"""
<section id="m2">
  <h2>M2: トポロジ(linear/mesh/disaster) x コマンド(put/get, pubsub) の成功率</h2>
  <table class="matrix">
    <tr><th></th>{''.join(f'<th>{c}</th>' for c in matrix['cols'])}</tr>
    {''.join(rows_html)}
  </table>
  {fig or ''}
  {_code_block(repro_lines)}
</section>
"""


# =============================================================================
# M5a/b/c/d: failure-tolerance family
# =============================================================================


def _section_m5(jobs: dict, figures_dir: Path, analysis_dir: Path) -> str:
    parts = ['<section id="m5"><h2>M5: 障害耐性 (パブリッシャー断・リンク断・多重障害・キャッシュ戦略)</h2>']

    # --- M5a: the headline ---
    pubdown = _load_json(analysis_dir / "m5a_pubdown.json")
    parts.append('<h3>M5a (headline): パブリッシャー断中もキャッシュがあれば get は成功し続ける</h3>')
    if pubdown:
        rows = []
        for bucket, states in pubdown["buckets"].items():
            up = states["up"]
            down = states["down"]
            rows.append(
                f"<li>{bucket}: up {_fmt_rate(up['success_rate'])} (n={up['n']}) / "
                f"down {_fmt_rate(down['success_rate'])} (n={down['n']})</li>"
            )
        parts.append(f'<ul class="evidence">{"".join(rows)}</ul>')
    else:
        parts.append(_pending_html("M5a"))
    fig = _embed_image(figures_dir, "m5a_pubdown")
    if fig:
        parts.append(fig)
    m5a_jobs = plots._contains_token(jobs, "m5a")
    if m5a_jobs:
        cmd = _repro_command(m5a_jobs[0])
        if cmd:
            parts.append(_code_block([f"# representative ({m5a_jobs[0].job_id})", cmd]))

    # --- M5b: link cycle timeline ---
    timeline = _load_json(analysis_dir / "m5b_timeline.json")
    parts.append("<h3>M5b: リンク断/復旧サイクル前後の get 成否タイムライン</h3>")
    if timeline:
        parts.append(f"<p class=\"evidence\">{len(timeline['seeds'])} seed 分のタイムラインを記録。</p>")
    else:
        parts.append(_pending_html("M5b"))
    fig = _embed_image(figures_dir, "m5b_timeline")
    if fig:
        parts.append(fig)
    m5b_jobs = plots._match(jobs, r"m5b_s\d+")
    if m5b_jobs:
        cmd = _repro_command(m5b_jobs[0])
        if cmd:
            parts.append(_code_block([f"# representative ({m5b_jobs[0].job_id})", cmd]))

    # --- M5c: failure intensity sweep ---
    intensity = _load_json(analysis_dir / "m5c_intensity.json")
    parts.append("<h3>M5c: 同時障害数 (down_count 1..4) に対する成功率</h3>")
    if intensity:
        rows = [
            f"<li>down_count={dc}: {_fmt_rate(rate)} (n_seeds={n})</li>"
            for dc, rate, n in zip(
                intensity["down_count"], intensity["mean_success_rate"], intensity["n_seeds"]
            )
        ]
        parts.append(f'<ul class="evidence">{"".join(rows)}</ul>')
    else:
        parts.append(_pending_html("M5c"))
    fig = _embed_image(figures_dir, "m5c_intensity")
    if fig:
        parts.append(fig)
    for dc in (1, 2, 3, 4):
        group = plots._match(jobs, rf"m5c_dc{dc}_s\d+")
        if group:
            cmd = _repro_command(group[0])
            if cmd:
                parts.append(_code_block([f"# down_count={dc} representative ({group[0].job_id})", cmd]))

    # --- M5d: cache strategy comparison ---
    strategies = _load_json(analysis_dir / "m5d_strategies.json")
    parts.append("<h3>M5d: キャッシュノード選択戦略 (kcenters/degree/manual) 別の成功率</h3>")
    if strategies:
        rows = [
            f"<li>{strat}: {_fmt_rate(rate)} (n_seeds={n})</li>"
            for strat, rate, n in zip(
                strategies["strategies"], strategies["mean_success_rate"], strategies["n_seeds"]
            )
        ]
        parts.append(f'<ul class="evidence">{"".join(rows)}</ul>')
    else:
        parts.append(_pending_html("M5d"))
    fig = _embed_image(figures_dir, "m5d_strategies")
    if fig:
        parts.append(fig)
    for strat in ("kcenters", "degree", "manual"):
        group = plots._match(jobs, rf"m5d_{strat}_s\d+")
        if group:
            cmd = _repro_command(group[0])
            if cmd:
                parts.append(_code_block([f"# {strat} representative ({group[0].job_id})", cmd]))

    parts.append("</section>")
    return "\n".join(parts)


# =============================================================================
# M3: scale-out
# =============================================================================


def _section_m3(jobs: dict, figures_dir: Path, analysis_dir: Path) -> str:
    scale = _load_json(analysis_dir / "m3_scale.json")
    fig = _embed_image(figures_dir, "m3_scale")

    if not scale:
        return f"""
<section id="m3">
  <h2>M3: ホスト数を増やしてもセットアップコストと成功率は許容範囲に収まる</h2>
  {_pending_html("M3")}
</section>
"""

    rows = [
        f"<li>{h} hosts: setup {w:.1f}s / success {_fmt_rate(s)} / peak {m:.2f}GB</li>"
        for h, w, s, m in zip(
            scale["hosts"], scale["median_setup_wall_seconds"], scale["success_rate"], scale["median_peak_mem_gb"]
        )
        if w is not None and m is not None
    ]
    families = {h: plots._match(jobs, rf"m3_h{h}_s\d+") for h in (5, 15, 30, 45, 60)}
    repro_lines = []
    for h, group in families.items():
        if group:
            cmd = _repro_command(group[0])
            if cmd:
                repro_lines.append(f"# hosts={h} representative ({group[0].job_id})\n{cmd}")

    return f"""
<section id="m3">
  <h2>M3: ホスト数を増やしてもセットアップコストと成功率は許容範囲に収まる</h2>
  <ul class="evidence">{''.join(rows)}</ul>
  {fig or ''}
  {_code_block(repro_lines)}
</section>
"""


# =============================================================================
# M4: bandwidth fidelity
# =============================================================================


def _section_m4(jobs: dict, figures_dir: Path, analysis_dir: Path) -> str:
    fidelity = _load_json(analysis_dir / "m4_bw_fidelity.json")
    fig = _embed_image(figures_dir, "m4_bw_fidelity")

    if not fidelity:
        return f"""
<section id="m4">
  <h2>M4: 設定した帯域制限は実測スループットに忠実に反映される</h2>
  {_pending_html("M4")}
</section>
"""

    # 2026-07-07: m4 は静的 bw 再設計後、warmup(ネットワーク律速の初回取得) と
    # eval(キャッシュ加速の再取得) の 2 系列に分割された (plots.py 参照)
    n_warm = len(fidelity.get("warmup_configured_mbps", []))
    n_eval = len(fidelity.get("eval_configured_mbps", []))
    evidence = (
        f"<li>warmup(初回取得・ネットワーク律速): {n_warm} 件 / "
        f"eval(キャッシュ加速): {n_eval} 件 の cefgetfile 計測（帯域 5-100Mbps 静的設定）</li>"
    )
    families = {bw: plots._match(jobs, rf"m4(?:st)?_bw{bw}_s\d+") for bw in (5, 10, 20, 50, 100)}
    repro_lines = []
    for bw, group in families.items():
        if group:
            cmd = _repro_command(group[0])
            if cmd:
                repro_lines.append(f"# bw={bw}Mbps representative ({group[0].job_id})\n{cmd}")

    return f"""
<section id="m4">
  <h2>M4: 設定した帯域制限は実測スループットに忠実に反映される</h2>
  <ul class="evidence">{evidence}</ul>
  {fig or ''}
  {_code_block(repro_lines)}
</section>
"""


# =============================================================================
# Appendix: failed/skipped jobs + caveats
# =============================================================================


def _section_appendix(stats: dict, analysis_dir: Path) -> str:
    rows = [
        f"<tr><td>{r['job_id']}</td><td>{r.get('status')}</td>"
        f"<td>{r.get('exit_code')}</td><td>{r.get('wall_seconds')}</td>"
        f"<td><code>{r.get('run_dir')}</code></td></tr>"
        for r in sorted(stats["failed_or_skipped"], key=lambda r: r["job_id"])
    ]
    table = (
        '<table class="matrix"><tr><th>job_id</th><th>status</th><th>exit_code</th>'
        f'<th>wall_seconds</th><th>run_dir</th></tr>{"".join(rows)}</table>'
        if rows
        else "<p>失敗/スキップしたジョブはありません。</p>"
    )

    caveats = _load_json(analysis_dir / "caveats.json")
    caveats_html = ""
    if isinstance(caveats, list) and caveats:
        items = "".join(f"<li>{c}</li>" for c in caveats)
        caveats_html = f'<h3>Caveats</h3><ul class="evidence">{items}</ul>'

    return f"""
<section id="appendix">
  <h2>Appendix: 失敗/スキップしたジョブ</h2>
  {table}
  {caveats_html}
</section>
"""


CSS = """
:root { color-scheme: light; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #0b0b0b;
  background: #fcfcfb;
  max-width: 960px;
  margin: 0 auto;
  padding: 2rem 1.5rem 4rem;
  line-height: 1.6;
}
header h1 { margin-bottom: 0.25rem; }
.meta { color: #52514e; font-size: 0.9rem; }
table.stats, table.matrix { border-collapse: collapse; margin: 1rem 0; width: 100%; }
table.stats th, table.stats td, table.matrix th, table.matrix td {
  border: 1px solid #e1e0d9; padding: 0.5rem 0.75rem; text-align: center;
}
table.matrix th:first-child, table.matrix td:first-child { text-align: left; }
.good { color: #006300; font-weight: 600; }
.critical { color: #d03b3b; font-weight: 600; }
.warning { color: #a97300; font-weight: 600; }
section { margin: 2.5rem 0; border-top: 1px solid #e1e0d9; padding-top: 1.5rem; }
h2 { font-size: 1.3rem; }
h3 { font-size: 1.05rem; color: #52514e; margin-top: 1.5rem; }
ul.evidence { color: #0b0b0b; }
img.fig { max-width: 100%; height: auto; display: block; margin: 1rem 0; border: 1px solid #e1e0d9; }
pre.repro {
  background: #f2f1ec; border: 1px solid #e1e0d9; border-radius: 4px;
  padding: 0.75rem 1rem; overflow-x: auto; font-size: 0.85rem; white-space: pre-wrap;
}
.pending { color: #898781; font-style: italic; }
@media print {
  section { break-inside: avoid; }
  img.fig { break-inside: avoid; }
}
"""


def build_report(campaign_dir: Path) -> str:
    figures_dir = campaign_dir / "figures"
    analysis_dir = campaign_dir / "analysis"

    jobs = plots.discover_jobs(campaign_dir)
    state_rows = plots.load_campaign_state(campaign_dir)
    stats = _campaign_stats(state_rows)

    sections = [
        _render_header(campaign_dir, stats),
        _section_m1(jobs, figures_dir, analysis_dir),
        _section_m2(jobs, figures_dir, analysis_dir),
        _section_m5(jobs, figures_dir, analysis_dir),
        _section_m3(jobs, figures_dir, analysis_dir),
        _section_m4(jobs, figures_dir, analysis_dir),
        _section_appendix(stats, analysis_dir),
    ]

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>Workshop Measurement Campaign Report</title>
<style>{CSS}</style>
</head>
<body>
{''.join(sections)}
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    campaign_dir: Path = args.campaign_dir.resolve()
    if not campaign_dir.is_dir():
        print(f"[report] campaign dir not found: {campaign_dir}", file=sys.stderr)
        return 0

    html = build_report(campaign_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"[report] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
