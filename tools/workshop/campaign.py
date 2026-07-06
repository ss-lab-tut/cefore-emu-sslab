#!/usr/bin/env python3
"""Unattended sequential campaign runner for overnight measurement batches.

Launched ONCE as root (Mininet needs network-namespace privileges), it walks
a manifest of jobs strictly in order:

    sudo .venv/bin/python3 tools/workshop/campaign.py \\
        --manifest manifest.json --out logs/workshop_20260707

Each job is its own subprocess so a single job's crash or hang can never take
down the whole overnight batch. This matters specifically because
tools/autotest/run.py ABORTS its entire --runs loop on the first failed run
or missing results.json -- campaign.py calls it once per job (--runs 1) so
that abort-on-failure blast radius is exactly one job, never the rest of the
manifest.

Per-job safety rails:
  - pre-attempt low-memory skip (MemAvailable < 20% of MemTotal)
  - a hard wall-clock timeout with whole-process-group kill (Mininet/cefnetd/
    csmgrd fork many processes per host; killing just the direct child would
    leave the rest running)
  - one retry after a `mn -c` cleanup pass on failure/timeout
  - a background peak-memory sampler

Progress is appended to <out>/campaign_state.jsonl, one JSON object per
attempt, flushed immediately so a crashed campaign is resumable: re-running
with the same --out skips any job id that already has a recorded "ok" line.
"""

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.artifacts import experiment_dir_name  # noqa: E402

# Below this fraction of MemAvailable/MemTotal, a job is skipped rather than
# started -- Mininet + cefnetd/csmgrd fleets under memory pressure tend to
# fail in confusing, hard-to-diagnose ways (OOM-killed daemons look like
# ordinary readiness-timeout failures), so refusing to start is safer than
# attempting and retrying into the same pressure.
_MEM_AVAILABLE_MIN_FRACTION = 0.20
_MEM_SAMPLE_INTERVAL_SEC = 5
# Grace period added on top of a job's own --timeout when we also wrap it in
# a shell-level `timeout` (linear jobs only): lets the inner `timeout` send
# its signal and the scenario unwind before our outer watchdog kills the
# whole process group.
_OUTER_TIMEOUT_GRACE_SEC = 30


def _read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a {field_name: kB} dict."""
    info: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as fp:
        for line in fp:
            key, _, rest = line.partition(":")
            fields = rest.strip().split()
            if fields:
                info[key] = int(fields[0])
    return info


def _mem_available_fraction() -> float:
    info = _read_meminfo()
    return info["MemAvailable"] / info["MemTotal"]


def _mem_used_kb() -> int:
    info = _read_meminfo()
    return info["MemTotal"] - info["MemAvailable"]


class _PeakMemorySampler:
    """Background thread tracking the host's peak used memory (kB) during a job.

    Sampling host-wide memory rather than a single child process's RSS is
    deliberate: a disaster/mesh run's real footprint is spread across many
    per-host cefnetd/csmgrd processes plus Mininet's own namespaces, so a
    single-PID RSS check would systematically undercount the pressure that
    actually risks an overnight OOM.
    """

    def __init__(self, interval: float = _MEM_SAMPLE_INTERVAL_SEC):
        self._interval = interval
        self._stop = threading.Event()
        self._peak_kb = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._peak_kb = max(self._peak_kb, _mem_used_kb())
            except OSError:
                pass  # /proc/meminfo transiently unreadable; skip this sample
            self._stop.wait(self._interval)

    def __enter__(self) -> "_PeakMemorySampler":
        self._thread.start()
        return self

    def __exit__(self, *_exc_info) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 1)

    @property
    def peak_kb(self) -> int:
        return self._peak_kb


def _run_cleanup() -> None:
    """Run Mininet's `mn -c` after a job failure/timeout, before retrying.

    Only invoked on the failure path: a successful run cleans up its own
    Mininet state, and unconditionally cleaning between every job would be
    safe but needlessly slow (see --clean-between for the opt-in variant
    that also cleans after successes).
    """
    subprocess.run(
        ["mn", "-c"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill every process in ``proc``'s group, not just the direct child.

    Jobs are started with start_new_session=True so each owns its own
    process group; a plain proc.kill() would only reach the immediate child
    (run.py, or the shell wrapping linear's printf/timeout pipeline) and
    leave any Mininet/cefnetd/csmgrd descendants running.
    """
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # process group already gone


def _run_job_subprocess(
    cmd, *, cwd: Path, timeout: int, shell: bool
) -> tuple[int | None, bool]:
    """Run one job attempt under a hard wall-clock timeout.

    Returns (returncode, timed_out). On timeout the whole process group is
    killed; returncode reflects whatever the OS reports after the kill (may
    be a negative signal number or None if the process could not be reaped).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        shell=shell,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        proc.communicate(timeout=timeout)
        return proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass  # best-effort reap; proceed with whatever returncode we have
        return proc.returncode, True


def _validate_job(job: dict, index: int) -> None:
    """Fail fast on a malformed manifest entry rather than mid-campaign.

    An overnight batch should never discover a typo in job #14 at 3am after
    already burning hours on jobs #1-13; validating the whole manifest
    upfront turns that into an immediate, fixable error.
    """
    if "id" not in job:
        raise SystemExit(f"manifest job[{index}] missing required key 'id'")
    kind = job.get("kind")
    if kind == "disaster":
        required = ("config", "seed", "num", "duration", "timeout")
    elif kind == "linear":
        required = ("hosts", "timeout")
    else:
        raise SystemExit(
            f"manifest job[{index}] ({job.get('id')!r}): "
            f"unknown kind {kind!r} (expected 'disaster' or 'linear')"
        )
    missing = [key for key in required if key not in job]
    if missing:
        raise SystemExit(
            f"manifest job[{index}] ({job['id']!r}, kind={kind}): "
            f"missing required key(s) {missing}"
        )


def _disaster_cmd(job: dict, job_out: Path, py: str) -> list[str]:
    """Build the tools/autotest/run.py invocation for a kind=disaster job.

    One run.py call per job (--runs 1) is the load-bearing choice here: see
    the module docstring for why folding multiple jobs into one run.py call
    would be unsafe given its abort-on-first-failure behavior.
    """
    return [
        py,
        str(ROOT / "tools" / "autotest" / "run.py"),
        "--base-config", str(job["config"]),
        "--runs", "1",
        "--seed-base", str(job["seed"]),
        "--start-num", str(job["num"]),
        "--duration", str(job["duration"]),
        "--out", str(job_out),
    ]


def _disaster_run_dir(job: dict, job_out: Path) -> Path:
    """Compute run.py's actual experiment directory for a disaster job.

    Mirrors run.py's own _run_one(): run_root=<job_out>/run_0001, results
    land in <run_root>/logs/<experiment_dir_name>. run.py always sets
    cfg["timestamp"]=False, so the name is deterministic (no need to glob).
    """
    exp_name = experiment_dir_name(job["num"], job["seed"])
    return job_out / "run_0001" / "logs" / exp_name


def _linear_cmd(job: dict, job_out: Path, py: str) -> str:
    """Build the linear-scenario shell command for a kind=linear job.

    linear has no --no-cli: its OptionSpec's no_cli entry only lists
    block=("disaster", "connect") (src/core/config/validator.py), so linear
    always drops into the interactive Mininet CLI and stdin must supply
    "exit" for it to ever return. --output-dir (in linear's own argparse
    block; see src/cli/args.py add_linear_args) routes its artifacts into
    the job's own directory directly -- simpler and less surprising than
    launching the subprocess from a job-specific cwd.
    """
    return (
        f"printf 'exit\\n' | timeout {int(job['timeout'])} "
        f"{shlex.quote(py)} -m src linear --hosts {int(job['hosts'])} "
        f"--output-dir {shlex.quote(str(job_out))}"
    )


def _linear_run_dir(job_out: Path) -> Path:
    """Compute linear's actual run directory for a kind=linear job.

    linear's argparse block has no --seed, so resolve_run_dir's
    experiment_dir_name(num=None, seed=None) always yields "seednone"
    (verified: src/core/paths.resolve_run_dir + src/core/artifacts).
    """
    return job_out / experiment_dir_name(None, None)


def _build_job_command(job: dict, job_out: Path, py: str):
    """Return (cmd, shell, outer_timeout, run_dir) for one job."""
    kind = job["kind"]
    if kind == "disaster":
        cmd = _disaster_cmd(job, job_out, py)
        return cmd, False, int(job["timeout"]), _disaster_run_dir(job, job_out)
    if kind == "linear":
        cmd = _linear_cmd(job, job_out, py)
        outer_timeout = int(job["timeout"]) + _OUTER_TIMEOUT_GRACE_SEC
        return cmd, True, outer_timeout, _linear_run_dir(job_out)
    raise AssertionError(f"unreachable: unknown kind {kind!r}")  # _validate_job guards this


def _format_cmd_for_display(cmd, shell: bool) -> str:
    """Render a resolved command the same way for --dry-run and journaling."""
    if shell:
        return cmd
    return " ".join(shlex.quote(str(part)) for part in cmd)


def _load_completed_job_ids(state_path: Path) -> set[str]:
    """Read a prior campaign_state.jsonl and return ids with an "ok" attempt.

    Only "ok" counts as done; "failed"/"timeout"/"skipped_memory" jobs are
    re-attempted on the next invocation so a resumed campaign doesn't
    silently give up on transient failures.
    """
    completed: set[str] = set()
    if not state_path.exists():
        return completed
    with open(state_path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("status") == "ok":
                completed.add(record["job_id"])
    return completed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_manifest(
    jobs: list[dict], out_root: Path, *, clean_between: bool, dry_run: bool
) -> None:
    py = sys.executable
    state_path = out_root / "campaign_state.jsonl"
    out_root.mkdir(parents=True, exist_ok=True)
    completed = _load_completed_job_ids(state_path)

    # Kept open for the whole campaign; each write is immediately flushed
    # (and fsync'd) so a crash mid-batch loses at most the in-flight job,
    # never previously recorded attempts.
    state_fp = None if dry_run else open(state_path, "a", encoding="utf-8")

    try:
        for job in jobs:
            job_id = job["id"]
            job_out = out_root / job_id

            if job_id in completed:
                print(f"[{job_id}] skip (already ok in {state_path.name})", flush=True)
                continue

            cmd, shell, timeout, run_dir = _build_job_command(job, job_out, py)

            if dry_run:
                print(f"[{job_id}] kind={job['kind']} timeout={timeout}s")
                print(f"    cmd: {_format_cmd_for_display(cmd, shell)}")
                print(f"    run_dir: {run_dir}")
                continue

            job_out.mkdir(parents=True, exist_ok=True)
            _run_job_attempts(
                job=job,
                job_id=job_id,
                cmd=cmd,
                shell=shell,
                timeout=timeout,
                run_dir=run_dir,
                state_fp=state_fp,
                clean_between=clean_between,
            )
    finally:
        if state_fp is not None:
            state_fp.close()


def _append_state(state_fp, record: dict) -> None:
    """Write one journal line and flush+fsync it before returning.

    Crash-safety requirement from the campaign design: every attempt must be
    durable on disk before we move on, since a killed-mid-campaign process
    must never lose a record of what already happened.
    """
    state_fp.write(json.dumps(record) + "\n")
    state_fp.flush()
    os.fsync(state_fp.fileno())


def _run_job_attempts(
    *,
    job: dict,
    job_id: str,
    cmd,
    shell: bool,
    timeout: int,
    run_dir: Path,
    state_fp,
    clean_between: bool,
) -> None:
    """Run up to two attempts of one job, journaling and printing each."""
    for attempt in (1, 2):
        available_fraction = _mem_available_fraction()
        if available_fraction < _MEM_AVAILABLE_MIN_FRACTION:
            record = {
                "job_id": job_id,
                "attempt": attempt,
                "status": "skipped_memory",
                "exit_code": None,
                "wall_seconds": 0.0,
                "peak_mem_used_kb": _mem_used_kb(),
                "run_dir": str(run_dir),
                "started_at": _now_iso(),
                "ended_at": _now_iso(),
            }
            _append_state(state_fp, record)
            print(
                f"[{job_id}] skipped_memory attempt={attempt} "
                f"available={available_fraction:.1%}",
                flush=True,
            )
            return  # nothing ran; retrying immediately would hit the same wall

        started_at = _now_iso()
        wall_start = time.monotonic()
        with _PeakMemorySampler() as sampler:
            returncode, timed_out = _run_job_subprocess(
                cmd, cwd=ROOT, timeout=timeout, shell=shell
            )
        wall_seconds = time.monotonic() - wall_start
        ended_at = _now_iso()

        if timed_out:
            status = "timeout"
        elif returncode == 0:
            status = "ok"
        else:
            status = "failed"

        record = {
            "job_id": job_id,
            "attempt": attempt,
            "status": status,
            "exit_code": returncode,
            "wall_seconds": round(wall_seconds, 1),
            "peak_mem_used_kb": sampler.peak_kb,
            "run_dir": str(run_dir),
            "started_at": started_at,
            "ended_at": ended_at,
        }
        _append_state(state_fp, record)
        print(
            f"[{job_id}] {status} attempt={attempt} "
            f"wall={wall_seconds:.1f}s peak_mem={sampler.peak_kb / 1024:.0f}MB",
            flush=True,
        )

        if status == "ok":
            if clean_between:
                _run_cleanup()
            return

        if attempt == 1:
            _run_cleanup()  # clear stale Mininet state before the one retry
            continue
        # attempt == 2 also failed: give up on this job, move to the next one


def _load_manifest(manifest_path: str) -> list[dict]:
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise SystemExit(f"manifest {manifest_path}: 'jobs' must be a non-empty list")
    for index, job in enumerate(jobs):
        _validate_job(job, index)
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an overnight measurement campaign's jobs strictly in order."
    )
    parser.add_argument("--manifest", required=True, help="path to manifest JSON")
    parser.add_argument("--out", required=True, help="output directory root")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print resolved commands without executing anything",
    )
    parser.add_argument(
        "--clean-between",
        action="store_true",
        help="also run `mn -c` after every successful job, not just failures "
        "(unconditionally safe but slower; off by default)",
    )
    args = parser.parse_args()

    jobs = _load_manifest(args.manifest)
    out_root = Path(args.out).resolve()

    if not args.dry_run and os.geteuid() != 0:
        raise SystemExit("campaign.py must be executed with sudo/root (Mininet requirement)")

    _run_manifest(jobs, out_root, clean_between=args.clean_between, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
