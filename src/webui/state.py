"""Thread-safe dashboard state hub for the WebUI."""

import copy
import threading
import time
from typing import Callable


def _cefnetd_is_up(output: str) -> bool:
    """Infer cefnetd liveness from cefstatus text output."""
    if not output:
        return False
    low = output.lower()
    if any(k in low for k in ("error", "failed", "connection refused", "no such file")):
        return False
    return "faces" in low or "fib" in low


def _csmgrd_is_up(output: str) -> bool:
    """Infer csmgrd liveness from csmgrstatus text output.

    Requires positive markers to confirm up, not just absence of errors.
    Monitor returns "skipped: host down" for down hosts — treat as not-up.
    """
    if not output:
        return False
    low = output.lower()
    if any(k in low for k in (
        "error", "failed", "connection refused", "no such file",
        "skipped", "not found", "cannot", "timeout", "timed out",
    )):
        return False
    return "connect to" in low or "all connection num" in low


class DashboardState:
    MAX_OPERATIONS = 1000
    MAX_MONITOR    = 500
    MAX_HISTORY    = 300

    def __init__(
        self,
        host_count: int,
        cache_nodes: set,
        seed,
        started_at: float,
        flap_state_getter: Callable[[], list] | None = None,
    ):
        self._lock = threading.Lock()
        self.host_count = host_count
        self.cache_nodes = set(cache_nodes)
        self.seed = seed
        self.started_at = started_at
        self._flap_state_getter = flap_state_getter

        # hosts[i] = {"last_cefstatus": str, "last_csmgrstatus": str, "is_cache": bool}
        # (up/down は snapshot 時に flap_state_getter で動的に計算)
        self._hosts: dict[int, dict] = {
            i: {
                "last_cefstatus": "",
                "last_csmgrstatus": "",
                "is_cache": i in cache_nodes,
            }
            for i in range(host_count)
        }
        self._operations: list[dict] = []
        self._monitor_records: list[dict] = []
        self._topology: dict = {"nodes": [], "edges": []}
        self._success_history: list[dict] = []  # [{elapsed, total, success, rate}]

    # ------------------------------------------------------------------ #
    # Topology                                                             #
    # ------------------------------------------------------------------ #

    def set_topology(self, mesh_links: list) -> None:
        """Convert MeshTopo.mesh_links to vis-network nodes/edges.

        mesh_links format: [{"subnet":int, "switch":str, "hosts":[int,...], ...}, ...]
        All host pairs sharing a switch become edges (logical connectivity).
        """
        nodes = [{"id": i, "label": f"h{i}"} for i in range(self.host_count)]
        edges: list[dict] = []
        seen: set[tuple] = set()
        for link in mesh_links:
            hosts = link["hosts"]
            for a in range(len(hosts)):
                for b in range(a + 1, len(hosts)):
                    key = (min(hosts[a], hosts[b]), max(hosts[a], hosts[b]))
                    if key not in seen:
                        seen.add(key)
                        edges.append({"from": key[0], "to": key[1]})
        with self._lock:
            self._topology = {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------ #
    # Monitor callback (called from Monitor thread)                        #
    # ------------------------------------------------------------------ #

    def record_monitor(self, record: dict) -> None:
        """Receive one Monitor record. Called from Monitor background thread."""
        with self._lock:
            host = record.get("host")
            rtype = record.get("type")
            if host is not None and host in self._hosts:
                if rtype == "cefstatus":
                    self._hosts[host]["last_cefstatus"] = record.get("output", "")
                elif rtype == "csmgrstatus":
                    self._hosts[host]["last_csmgrstatus"] = record.get("output", "")
            if len(self._monitor_records) >= self.MAX_MONITOR:
                del self._monitor_records[0]
            self._monitor_records.append(record)

    # ------------------------------------------------------------------ #
    # Operation callbacks (called from experiment/scheduler threads)      #
    # ------------------------------------------------------------------ #

    def record_operation(self, result: dict) -> None:
        """Called from DisasterScenario._append_result after get/sub completes."""
        elapsed = round(time.time() - self.started_at, 1)
        with self._lock:
            if len(self._operations) >= self.MAX_OPERATIONS:
                del self._operations[0]
            self._operations.append({
                "ts":         result.get("ts"),
                "op_type":    result.get("op_type", "get"),
                "host":       result.get("host"),
                "uri":        result.get("uri"),
                "success":    result.get("success"),
                "exit_code":  result.get("exit_code"),
                "down_hosts": result.get("down_hosts", []),
                "phase":      result.get("phase"),
            })
            # Success rate history (get + sub only)
            ops = [o for o in self._operations if o["op_type"] in ("get", "sub")]
            total   = len(ops)
            success = sum(1 for o in ops if o["success"])
            rate    = round(success / total, 3) if total > 0 else 0.0
            if len(self._success_history) >= self.MAX_HISTORY:
                del self._success_history[0]
            self._success_history.append({
                "elapsed": elapsed,
                "total":   total,
                "success": success,
                "rate":    rate,
            })

    def record_launch(self, op_type: str, host: int, uri: str) -> None:
        """Record put/pub launch (fire-and-forget; result unknown at launch time)."""
        with self._lock:
            if len(self._operations) >= self.MAX_OPERATIONS:
                del self._operations[0]
            self._operations.append({
                "ts":         None,
                "op_type":    op_type,  # "put" or "pub"
                "host":       host,
                "uri":        uri,
                "success":    None,
                "exit_code":  None,
                "down_hosts": [],
                "phase":      None,
            })

    # ------------------------------------------------------------------ #
    # Snapshot (called from Flask thread)                                 #
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict:
        """Return an immutable snapshot for JSON serialization.

        flap_state_getter is called outside the lock to avoid lock-order conflicts.
        """
        down_list = self._flap_state_getter() if self._flap_state_getter else []
        down_set  = set(down_list)

        with self._lock:
            hosts_out: dict = {}
            for i, h in self._hosts.items():
                hosts_out[str(i)] = {
                    "up":               i not in down_set,
                    "is_cache":         h["is_cache"],
                    "cefnetd_ok":       _cefnetd_is_up(h["last_cefstatus"]),
                    "csmgrd_ok":        _csmgrd_is_up(h["last_csmgrstatus"]),
                    "last_cefstatus":   h["last_cefstatus"],
                    "last_csmgrstatus": h["last_csmgrstatus"],
                }
            return {
                "elapsed_sec":     round(time.time() - self.started_at, 1),
                "meta": {
                    "seed":        self.seed,
                    "host_count":  self.host_count,
                    "cache_nodes": sorted(self.cache_nodes),
                },
                "hosts":           hosts_out,
                "operations":      list(self._operations[-200:]),
                "topology":        copy.deepcopy(self._topology),
                "success_history": list(self._success_history[-300:]),
                "down_hosts":      sorted(down_set),
            }
