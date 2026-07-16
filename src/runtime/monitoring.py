"""Periodic monitoring of Cefore daemon status."""

import csv
import json
import threading
import time
from pathlib import Path
from typing import Callable

from mininet.log import info

from ..core.paths import ensure_within_run_dir
from .cefore import run_cefstatus, run_csmgrstatus, status_output

# Field order for every monitor record, shared by monitor.json, monitor.csv,
# and the webui live-status feed. Defined once here so a field rename cannot
# silently drift between the CSV header, the JSON records, and the dashboard.
MONITOR_FIELDS = ("elapsed_sec", "type", "host", "output", "outcome")

# Per-type negative markers. cefstatus uses 4 (matching the original
# _cefnetd_is_up); csmgrstatus uses 8 (matching _csmgrd_is_up) because
# csmgrstatus can return rc=0 with "ERROR: Connection failed".
# 2026-07-16: scoped per command type to avoid false negatives from
# FIB URI content (ccnx:/timeout would match a shared "timeout" marker).
_NEGATIVE_MARKERS = {
    "cefstatus": ("error", "failed", "connection refused", "no such file"),
    "csmgrstatus": (
        "error", "failed", "connection refused", "no such file",
        "skipped", "not found", "cannot", "timeout", "timed out",
    ),
}

# Per-type positive markers confirming the daemon is alive.
_POSITIVE_MARKERS = {
    "cefstatus": ("faces", "fib"),
    "csmgrstatus": ("connect to", "all connection num"),
}


def derive_monitor_outcome(target_type: str, result) -> str:
    """Derive tri-state outcome from a CommandResult.

    Fail-closed priority:
    1. timed_out or cancelled → "not-ok"
    2. returncode is None or nonzero → "not-ok"
    3. known negative marker in output → "not-ok"
       (catches csmgrstatus rc=0 + "ERROR: Connection failed")
    4. returncode 0 AND command-specific positive marker → "ok"
    5. otherwise → "not-ok" (unknown output, fail-closed)
    """
    if result.timed_out or result.cancelled:
        return "not-ok"
    if result.returncode is None or result.returncode != 0:
        return "not-ok"
    low = result.stdout.lower()
    negatives = _NEGATIVE_MARKERS.get(target_type, ())
    if any(m in low for m in negatives):
        return "not-ok"
    positives = _POSITIVE_MARKERS.get(target_type, ())
    if any(m in low for m in positives):
        return "ok"
    return "not-ok"


def make_monitor_record(elapsed_sec, type_, host, output, outcome="not-ok") -> dict:
    """Build a monitor record dict with the single, shared field shape.

    All producers must build records through this factory so that a field
    rename or reorder is caught at the one definition site.
    """
    return dict(zip(MONITOR_FIELDS, (elapsed_sec, type_, host, output, outcome)))


def _resolve_hosts(spec, host_count, cache_nodes=None):
    """Resolve host specification to a list of host indices.

    Args:
        spec: "all", "cache", or list of int host indices.
        host_count: Total number of hosts.
        cache_nodes: Set of cache node indices (for "cache" spec).

    Returns:
        List of host indices.
    """
    if spec == "all":
        return list(range(host_count))
    if spec == "cache":
        return sorted(cache_nodes or [])
    if isinstance(spec, list):
        return [int(h) for h in spec]
    return []


class Monitor:
    """Periodically collect status from Cefore daemons.

    Targets are dicts with ``type`` and ``hosts`` keys.
    Supported types: cefstatus, csmgrstatus.

    For csmgrstatus targets, csmgrd is queried via loopback (127.0.0.1) by
    default because csmgrstatus runs in the same netns as csmgrd.  Provide
    ``csmgr_host_resolver`` only when a non-loopback address is needed.
    Priority for csmgrd address: explicit target_host > resolver > 127.0.0.1.

    Args:
        net: Mininet network instance.
        targets: List of monitoring target specifications.
        interval: Collection interval in seconds.
        output_dir: Directory for output files.
        host_count: Total number of hosts.
        cache_nodes: Set of cache node indices.
        output_json: JSON output filename (relative to output_dir).
        output_csv: CSV output filename (relative to output_dir).
        csmgr_host_resolver: Optional callable [[int], str] that maps host_idx
            to the csmgrd listen IP.  Defaults to 127.0.0.1 when omitted.
        down_hosts_getter: Optional callable [[], list[int]] returning the
            current set of downed host indices. When provided, collection is
            skipped for hosts that are currently down to avoid concurrent
            Mininet shell access conflicts.
        background: Start in background mode. In background mode collection
            uses ``popen`` (no shared pexpect shell) and emits no terminal
            output, so it is safe to keep running during the Mininet CLI.
            Can also be entered later via ``enter_background()``.
        command_timeout: Per-command timeout (seconds) for background popen
            collection.
    """

    def __init__(
        self,
        net,
        targets,
        interval,
        output_dir,
        host_count=0,
        cache_nodes=None,
        output_json=None,
        output_csv=None,
        csmgr_host_resolver: Callable[[int], str] | None = None,
        down_hosts_getter: Callable[[], list] | None = None,
        on_record: Callable[[dict], None] | None = None,
        background: bool = False,
        command_timeout: int = 10,
    ):
        self.net = net
        self.targets = targets
        self.interval = max(1, interval)
        self.output_dir = Path(output_dir)
        self.host_count = host_count
        self.cache_nodes = cache_nodes or set()
        self.output_json = output_json
        self.output_csv = output_csv
        self._output_json_path = None
        self._output_csv_path = None
        if self.output_json:
            self._output_json_path = ensure_within_run_dir(
                self.output_dir, self.output_dir / self.output_json
            )
        if self.output_csv:
            self._output_csv_path = ensure_within_run_dir(
                self.output_dir, self.output_dir / self.output_csv
            )
        self._csmgr_host_resolver = csmgr_host_resolver
        self._down_hosts_getter = down_hosts_getter
        self._on_record = on_record
        self.command_timeout = command_timeout
        self._background = threading.Event()
        if background:
            self._background.set()
        self._stop_event = threading.Event()
        self._thread = None
        self._records = []

    def enter_background(self):
        """Switch collection to background mode (quiet + popen, no shell contention).

        Idempotent; safe to call from another thread while collecting.
        """
        self._background.set()

    def _collect_once(self, elapsed):
        """Run one collection cycle."""
        for target in self.targets:
            target_type = target.get("type")
            default_hosts = "cache" if target_type == "csmgrstatus" else "all"
            hosts = _resolve_hosts(
                target.get("hosts", default_hosts), self.host_count, self.cache_nodes
            )
            for host_idx in hosts:
                if self._stop_event.is_set():
                    return
                try:
                    output, outcome = self._collect_target(
                        target_type, host_idx, target
                    )
                except Exception as exc:
                    output = f"error: {exc}"
                    outcome = "not-ok"
                record = make_monitor_record(
                    round(elapsed, 1), target_type, host_idx, output, outcome
                )
                self._records.append(record)
                if self._on_record is not None:
                    try:
                        self._on_record(record)
                    except Exception as exc:
                        if not self._background.is_set():
                            info(f"[monitor] on_record callback failed: {exc}\n")

    def _collect_target(self, target_type, host_idx, target):
        """Collect a single target and return (output_str, outcome)."""
        bg = self._background.is_set()
        if (
            self._down_hosts_getter is not None
            and host_idx in self._down_hosts_getter()
        ):
            if target_type == "csmgrstatus" and not bg:
                info(f"[monitor] h{host_idx} is down, skipping csmgrstatus\n")
            return "skipped: host down", "skipped"
        if target_type == "cefstatus":
            result = run_cefstatus(
                self.net,
                host_idx,
                quiet=bg,
                timeout=self.command_timeout if bg else None,
            )
            return status_output(result), derive_monitor_outcome(target_type, result)
        elif target_type == "csmgrstatus":
            explicit = target.get("target_host")
            if isinstance(explicit, str) and explicit:
                csmgr_host = explicit
            elif self._csmgr_host_resolver is not None:
                csmgr_host = self._csmgr_host_resolver(host_idx)
            else:
                csmgr_host = "127.0.0.1"
            result = run_csmgrstatus(
                self.net,
                host_idx,
                uri=target.get("uri"),
                port_num=target.get("port_num"),
                host=csmgr_host,
                quiet=bg,
                timeout=self.command_timeout if bg else None,
            )
            return status_output(result), derive_monitor_outcome(target_type, result)
        else:
            return f"unknown monitor type: {target_type}", "not-ok"

    def _run(self):
        start = time.time()
        while not self._stop_event.is_set():
            elapsed = time.time() - start
            self._collect_once(elapsed)
            if self._stop_event.wait(timeout=self.interval):
                break

    def start(self):
        """Start background monitoring thread."""
        if not self.targets:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop monitoring and write output files."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._write_outputs()

    def _write_outputs(self):
        """Write collected records to JSON and/or CSV."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if self._output_json_path and self._records:
            self._output_json_path.write_text(
                json.dumps(self._records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            info(f"[monitor] wrote {self._output_json_path}\n")

        if self._output_csv_path and self._records:
            fieldnames = list(MONITOR_FIELDS)
            with open(self._output_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self._records)
            info(f"[monitor] wrote {self._output_csv_path}\n")
