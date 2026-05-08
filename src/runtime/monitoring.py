"""Periodic monitoring of Cefore daemon status."""

import csv
import json
import threading
import time
from pathlib import Path
from typing import Callable

from mininet.log import info

from .cefore import run_cefstatus, run_csmgrstatus


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
    ):
        self.net = net
        self.targets = targets
        self.interval = max(1, interval)
        self.output_dir = Path(output_dir)
        self.host_count = host_count
        self.cache_nodes = cache_nodes or set()
        self.output_json = output_json
        self.output_csv = output_csv
        self._csmgr_host_resolver = csmgr_host_resolver
        self._down_hosts_getter = down_hosts_getter
        self._stop_event = threading.Event()
        self._thread = None
        self._records = []

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
                self._records.append(
                    {
                        "elapsed_sec": round(elapsed, 1),
                        "type": target_type,
                        "host": host_idx,
                        "output": output,
                    }
                )

    def _collect_target(self, target_type, host_idx, target):
        """Collect a single target output."""
        if (
            self._down_hosts_getter is not None
            and host_idx in self._down_hosts_getter()
        ):
            if target_type == "csmgrstatus":
                info(f"[monitor] h{host_idx} is down, skipping csmgrstatus\n")
            return "skipped: host down"
        if target_type == "cefstatus":
            node_name = f"h{host_idx}"
            return self.net.hosts[host_idx].cmd(f"cefstatus -d ./{node_name}")
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
            )
        else:
            return f"unknown monitor type: {target_type}"

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

        if self.output_json and self._records:
            path = self.output_dir / self.output_json
            path.write_text(
                json.dumps(self._records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            info(f"[monitor] wrote {path}\n")

        if self.output_csv and self._records:
            path = self.output_dir / self.output_csv
            fieldnames = ["elapsed_sec", "type", "host", "output"]
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self._records)
            info(f"[monitor] wrote {path}\n")
