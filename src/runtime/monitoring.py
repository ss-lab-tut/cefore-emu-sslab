"""Periodic monitoring of Cefore daemon status.

Interval semantics: the loop waits ``interval`` seconds AFTER all targets
in a cycle complete (a fixed post-cycle delay, not a fixed-period timer).
The effective period is therefore collection_time + interval. With N hosts
probing ccninfo, expect ~5 s per probe (CCNINFO_REPLY_TIMEOUT=4 s + 1 s
grace) on top of the configured interval.
"""

import csv
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

from mininet.log import info, warn

from ..core.ccninfo_parse import parse_ccninfo
from ..core.paths import ensure_within_run_dir
from .cef_argv import build_ccninfo_argv
from .cefore import cefore_env_prefix, run_csmgrstatus
from .command_runner import MininetCommandRunner

# Default per-command timeout (seconds) for background popen collection.
# ccninfo self-terminates after CCNINFO_REPLY_TIMEOUT+1 (~5 s default); this
# guard exists to cap a *hung* binary so a single monitor cycle cannot block
# forever. The value 10 matches the existing test assertions
# (test_background_csmgrstatus_quiet_and_timeout expects timeout==10).
DEFAULT_COMMAND_TIMEOUT = 10

# Field order for every monitor record, shared by monitor.json, monitor.csv,
# and the webui live-status feed. Defined once here so a field rename cannot
# silently drift between the CSV header, the JSON records, and the dashboard.
MONITOR_FIELDS = ("elapsed_sec", "type", "host", "output")


def make_monitor_record(elapsed_sec, type_, host, output) -> dict:
    """Build a monitor record dict with the single, shared field shape.

    This is the sole owner of the monitor-record shape consumed by
    monitor.json/monitor.csv (Monitor._collect_once, _write_outputs) and by
    the webui's live host-status feed (disaster-scenario pre-populate calls
    into DashboardState.record_monitor). All producers must build records
    through this factory rather than hand-rolling the dict literal, so that
    a field rename or reorder is caught at the one definition site instead
    of silently drifting between callers.
    """
    return dict(zip(MONITOR_FIELDS, (elapsed_sec, type_, host, output)))


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
    Supported types and their output shapes:

    * **cefstatus** / **csmgrstatus**: output is a plain string (stdout text).
    * **ccninfo**: output is a dict with keys ``uri``, ``raw`` (stdout),
      ``parsed`` (structured CcninfoReply fields with route as list of plain
      dicts and cache_lines as list of strings), ``elapsed_ms`` (int wall
      time), and ``timed_out`` (bool from CommandResult). Host-down skips
      and exception wrapping stay STRING outputs (the existing _collect_once
      contract), so the output type for any target is ``dict | str``.

    For csmgrstatus targets, csmgrd is queried via loopback (127.0.0.1) by
    default because csmgrstatus runs in the same netns as csmgrd.  Provide
    ``csmgr_host_resolver`` only when a non-loopback address is needed.
    Priority for csmgrd address: explicit target_host > resolver > 127.0.0.1.

    Args:
        net: Mininet network instance.
        targets: List of monitoring target specifications.
        interval: Post-cycle delay in seconds. The loop waits this long AFTER
            all targets complete, so the effective period is
            collection_time + interval.
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
            collection. Default: DEFAULT_COMMAND_TIMEOUT (10).
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
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
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
        self._records: list[dict] = []
        # Guards _records.append (in _collect_once) and snapshot (in
        # _write_outputs) so a late-returning thread cannot race the
        # final output write after stop().
        self._records_lock = threading.Lock()

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
                    output = self._collect_target(target_type, host_idx, target)
                except Exception as exc:
                    output = f"error: {exc}"
                record = make_monitor_record(
                    round(elapsed, 1), target_type, host_idx, output
                )
                with self._records_lock:
                    self._records.append(record)
                if self._on_record is not None:
                    try:
                        self._on_record(record)
                    except Exception as exc:
                        if not self._background.is_set():
                            info(f"[monitor] on_record callback failed: {exc}\n")

    def _collect_target(self, target_type, host_idx, target):
        """Collect a single target output."""
        bg = self._background.is_set()
        if (
            self._down_hosts_getter is not None
            and host_idx in self._down_hosts_getter()
        ):
            if target_type == "csmgrstatus" and not bg:
                info(f"[monitor] h{host_idx} is down, skipping csmgrstatus\n")
            return "skipped: host down"
        if target_type == "cefstatus":
            node_name = f"h{host_idx}"
            argv = ["cefstatus", "-d", f"./{node_name}"]
            timeout = self.command_timeout if bg else None
            return MininetCommandRunner(self.net).run(
                node_name, argv, timeout=timeout
            ).stdout
        elif target_type == "csmgrstatus":
            # Use explicit target_host if provided; otherwise use resolver.
            explicit = target.get("target_host")
            if isinstance(explicit, str) and explicit:
                csmgr_host = explicit
            elif self._csmgr_host_resolver is not None:
                csmgr_host = self._csmgr_host_resolver(host_idx)
            else:
                csmgr_host = "127.0.0.1"
            return run_csmgrstatus(
                self.net,
                host_idx,
                uri=target.get("uri"),
                port_num=target.get("port_num"),
                host=csmgr_host,
                quiet=bg,
                timeout=self.command_timeout if bg else None,
            )
        elif target_type == "ccninfo":
            node_name = f"h{host_idx}"
            return self._collect_ccninfo(node_name, host_idx, target)
        else:
            return f"unknown monitor type: {target_type}"

    def _collect_ccninfo(self, node_name, host_idx, target):
        """Collect a ccninfo probe and return a structured dict.

        Builds argv via build_ccninfo_argv with passthrough options from the
        target dict, prepends the CEFORE_DIR env prefix, and parses stdout
        into a CcninfoReply.

        Returns a dict (not a string) with keys: uri, raw, parsed,
        elapsed_ms, timed_out.  The ``parsed`` sub-dict carries plain
        JSON-primitive types (lists of dicts, not dataclass objects).
        """
        argv = build_ccninfo_argv(
            target["uri"],
            node_name=node_name,
            cache_info=target.get("cache_info", False),
            owner_only=target.get("owner_only", False),
            hop_count=target.get("hop_count"),
            skip_hop=target.get("skip_hop"),
            valid_algo=target.get("valid_algo"),
        )
        # 2026-07-27 upstream bug workaround — see cefore_env_prefix docstring.
        # Monitoring wants stdout (no log file), but still needs CEFORE_DIR so
        # cef_client_init reads the correct node's cefnetd.conf socket ID.
        env_dir = os.path.abspath(f"./{node_name}/.cefore_env")
        argv = [*cefore_env_prefix(env_dir), *argv]

        # Always apply command_timeout regardless of fg/bg mode: a reply-less
        # ccninfo blocks ~5s per host per cycle; the fg cefstatus convention
        # of timeout=None would stall the monitor thread.
        t0 = time.time()
        result = MininetCommandRunner(self.net).run(
            node_name, argv, timeout=self.command_timeout
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        reply = parse_ccninfo(result.stdout)
        return {
            "uri": target["uri"],
            "raw": result.stdout,
            "parsed": {
                "reply_received": reply.reply_received,
                "responder": reply.responder,
                "result": reply.result,
                "rtt_ms": reply.rtt_ms,
                "route": [
                    {"index": h.index, "node": h.node, "delay_ms": h.delay_ms}
                    for h in reply.route
                ],
                "cache_lines": list(reply.cache_lines),
            },
            "elapsed_ms": elapsed_ms,
            "timed_out": bool(result.timed_out),
        }

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

    def _join_budget(self) -> float:
        """Compute the thread join timeout in seconds.

        The budget accounts for two distinct failure modes:

        (a) **Bounded path** — every ccninfo (and bg csmgrstatus/cefstatus)
            collection is timeout-bounded by ``command_timeout``. After
            ``stop_event`` is set the worker exits within one command's
            bounded residual. The blocking-fake test pins exactly this.

        (b) **Defensive guard** — join can still exceed the budget via
            pre-existing unbounded residuals: ``on_record`` callbacks have
            no timeout; post-kill ``proc.wait()``; fg cefstatus AND fg
            csmgrstatus run with ``timeout=None``. Those are pre-existing
            behaviors this slice does not change.

        The ``+ 2`` is process-terminate grace; ``+ 3`` is margin.
        """
        return (self.command_timeout or DEFAULT_COMMAND_TIMEOUT) + 2 + 3

    def stop(self):
        """Stop monitoring and write output files.

        If the thread is still alive after the join budget, logs a warning
        and proceeds to write outputs from a locked snapshot so a
        late-returning thread cannot race ``_write_outputs``.
        """
        self._stop_event.set()
        if self._thread is not None:
            budget = self._join_budget()
            self._thread.join(timeout=budget)
            if self._thread.is_alive():
                warn(
                    f"[monitor] thread still alive after {budget}s join budget; "
                    "writing outputs from snapshot\n"
                )
        self._write_outputs()

    def _write_outputs(self):
        """Write collected records to JSON and/or CSV.

        Takes a snapshot of ``_records`` under the lock first so a
        late-returning thread (still alive after the join budget) cannot
        race this write.
        """
        with self._records_lock:
            snapshot = list(self._records)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        if self._output_json_path and snapshot:
            # JSON keeps nested dicts as-is (no double-encoding).
            self._output_json_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            info(f"[monitor] wrote {self._output_json_path}\n")

        if self._output_csv_path and snapshot:
            fieldnames = list(MONITOR_FIELDS)
            # For the CSV, dict-valued output cells are json.dumps'd so they
            # round-trip via json.loads; plain-string outputs stay untouched.
            csv_rows = []
            for record in snapshot:
                output = record["output"]
                if isinstance(output, dict):
                    csv_rows.append(
                        {**record, "output": json.dumps(output, ensure_ascii=False)}
                    )
                else:
                    csv_rows.append(record)
            with open(self._output_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_rows)
            info(f"[monitor] wrote {self._output_csv_path}\n")
