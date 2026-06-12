"""DaemonFleet: lifecycle of the Cefore daemons for one experiment.

Owns the csmgrd -> cefnetd startup order, the readiness policy
(warn vs raise), stop-failure aggregation, and started-daemon tracking,
so scenarios do not replicate the daemon loops.
"""

from mininet.log import info

from .cefore import (
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .command_runner import MininetCommandRunner


def _host_idx(node_name):
    """Host index of a Node name ("h3" -> 3)."""
    return int(node_name[1:])


class DaemonFleet:
    """Start, readiness-check, and stop csmgrd/cefnetd across all hosts.

    Args:
        net: Mininet network instance.
        node_names: Node names of every host in the experiment.
        csmgrd_nodes: Node names that run a cache manager (csmgrd).
        log_dir: Directory for daemon log files (None = CWD).
        cefnetd_timeout: Per-host cefnetd readiness timeout in seconds.
        readiness_policy: "warn" logs not-ready hosts and continues;
            "raise" raises RuntimeError before FIB programming.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """

    def __init__(
        self,
        net,
        *,
        node_names,
        csmgrd_nodes=(),
        log_dir=None,
        cefnetd_timeout=10,
        readiness_policy="warn",
        runner=None,
    ):
        if readiness_policy not in ("warn", "raise"):
            raise ValueError("readiness_policy must be 'warn' or 'raise'")
        self._net = net
        self.node_names = list(node_names)
        self.csmgrd_nodes = set(csmgrd_nodes)
        self._log_dir = log_dir
        self._cefnetd_timeout = cefnetd_timeout
        self._readiness_policy = readiness_policy
        self._runner = runner or MininetCommandRunner(net)
        self.started_csmgrd = set()

    def start_all(self):
        """Start csmgrd on cache nodes, then cefnetd on every host."""
        for name in sorted(self.csmgrd_nodes, key=_host_idx):
            start_csmgrd(
                self._net, _host_idx(name), log_dir=self._log_dir,
                runner=self._runner,
            )
            self.started_csmgrd.add(name)
        for name in self.node_names:
            start_cefnetd(
                self._net, _host_idx(name), log_dir=self._log_dir,
                runner=self._runner,
            )

    def wait_ready(self):
        """Wait for cefnetd on every host; apply the readiness policy.

        Returns:
            Node names that did not become ready. With the "raise" policy a
            RuntimeError is raised instead when any host is not ready.
        """
        not_ready = []
        for name in self.node_names:
            ready = wait_for_cefnetd(
                self._net, _host_idx(name), timeout=self._cefnetd_timeout,
                runner=self._runner,
            )
            if ready:
                continue
            not_ready.append(name)
            if self._readiness_policy == "warn":
                info(f"WARNING: {name} cefnetd not ready\n")
        if not_ready and self._readiness_policy == "raise":
            hosts = ", ".join(not_ready)
            raise RuntimeError(
                f"cefnetd not ready on {hosts}; aborting before FIB programming"
            )
        return not_ready

    def stop_all(self):
        """Stop cefnetd on every host, then csmgrd on started cache nodes.

        Each stop is attempted independently; failures are logged and
        returned as (stage, exception) pairs so teardown can aggregate them.
        BaseException is caught so SystemExit/KeyboardInterrupt during one
        stop cannot abort the remaining stops.
        """
        failures = []
        for name in self.node_names:
            try:
                stop_cefnetd(self._net, _host_idx(name), runner=self._runner)
            except BaseException as exc:
                failures.append((f"stop_cefnetd {name}", exc))
        for name in sorted(self.started_csmgrd, key=_host_idx):
            try:
                stop_csmgrd(self._net, _host_idx(name), runner=self._runner)
            except BaseException as exc:
                failures.append((f"stop_csmgrd {name}", exc))
        for stage, exc in failures:
            info(f"[daemon-fleet] warning: {stage} failed: {exc}\n")
        return failures
