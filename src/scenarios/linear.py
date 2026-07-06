"""Linear topology scenario."""

import random
import sys
import time
from pathlib import Path

from mininet.log import info
from mininet.util import irange

from ..core.artifacts import content_log_name
from ..core.addressing import AddressingScheme, LINK_NETMASK
from ..core.roles import assign_roles
from ..runtime.command_runner import MininetCommandRunner
from ..runtime.cefore import run_cefgetfile, run_cefputfile
from ..runtime.daemon_fleet import build_fleet
from ..runtime.daemon_logs import HostLogScope
from ..runtime.net_config import cefroute_add
from ..runtime.scenario_setup import TeardownSpec, teardown_scenario
from ..runtime.template import provision_node_dirs
from ..runtime.topo import LineTopo

from .base import BaseScenario, _propagate_failures


class LinearScenario(BaseScenario):
    """Linear topology scenario: h0-s0-h1-s1-...-sN-hN."""

    def __init__(self, host_num, run_dir=None, debug_config=None, scheme=None):
        if host_num < 2:
            sys.exit("host count must be at least 2")
        self.host_num = host_num
        self.daemon_log_collection_enabled = run_dir is not None and Path(
            run_dir
        ) != Path(".")
        self.run_dir = run_dir or Path(".")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.debug_config = debug_config
        self.rng = random.Random()
        self.generated_node_dirs = []
        self.roles = {}
        self.scheme = scheme if scheme is not None else AddressingScheme()
        self.daemon_fleet = None

    def build_topology(self):
        self.roles = assign_roles(self.host_num, self.rng)
        self.generated_node_dirs = provision_node_dirs(self.roles)
        return LineTopo(hosts=self.host_num)

    def configure(self, net):
        self._set_ip_addr(net)
        runner = MininetCommandRunner(net)
        for idx in irange(0, self.host_num - 1):
            node_name = f"h{idx}"
            print(node_name, "command:", "ifconfig")
            info(runner.run(node_name, ["ifconfig"]).stdout)

        self.daemon_fleet = build_fleet(
            net, self.host_num, self._csmgrd_host_ids(), self.run_dir
        )
        self.daemon_fleet.start_all()
        self.daemon_fleet.wait_ready()

        self._set_fib(net)
        time.sleep(1)

    def run_experiment(self, net):
        runner = MininetCommandRunner(net)
        publisher = self.host_num - 1
        uri = "ccnx:/test"
        put_log = str(
            self.run_dir / content_log_name("cefputfile", "eval", publisher, uri)
        )
        exit_code = run_cefputfile(
            runner,
            publisher,
            uri,
            cache_time=3000,
            expiry=3000,
            log_name=put_log,
        )
        if exit_code != 0:
            info(f"[ERROR] cefputfile failed on h{publisher} (exit_code={exit_code})\n")
            sys.exit(1)
        time.sleep(5)

        get_log = str(self.run_dir / content_log_name("cefgetfile", "eval", 0, uri))
        recvfile = str(self.run_dir / "recvfile_at_h0")
        exit_code = run_cefgetfile(runner, 0, uri, recvfile, log_name=get_log)
        if exit_code != 0:
            info(f"[ERROR] cefgetfile failed on h0 (exit_code={exit_code})\n")
            sys.exit(1)

    def teardown(self, net):
        spec = TeardownSpec(
            host_count=self.host_num,
            csmgrd_host_ids=self._csmgrd_host_ids(),
            fleet_run_dir=self.run_dir,
            daemon_fleet=self.daemon_fleet,
        )
        result = teardown_scenario(net, spec)
        if result.failures:
            _propagate_failures(None, result.failures)

    def daemon_log_collection_scope(self):
        """Describe daemon logs from generated hN directories for this run."""
        csmgrd_ids = set(self._csmgrd_host_ids())
        return [
            HostLogScope(
                idx=i,
                node_dir=self.generated_node_dirs[i],
                has_csmgrd=i in csmgrd_ids,
            )
            for i in range(self.host_num)
            if i < len(self.generated_node_dirs)
        ]

    def _csmgrd_host_ids(self):
        return {
            idx
            for idx in range(self.host_num)
            if self.roles.get(idx) and self.roles[idx].runs_csmgrd
        }

    def _set_ip_addr(self, net, runner=None):
        """Assign IPs for linear topology.

        The explicit ``netmask`` is mandatory; see net_config.apply_ip_addr.
        """
        runner = runner or MininetCommandRunner(net)
        for idx in irange(0, self.host_num - 1):
            node_name = f"h{idx}"
            if idx > 0:
                left_ip = self.scheme.host_ip(idx - 1, idx)
                argv = [
                    "ifconfig",
                    f"{node_name}-eth0",
                    str(left_ip),
                    "netmask",
                    LINK_NETMASK,
                ]
                print(node_name, "command:", argv)
                runner.run(node_name, argv)
            if idx < self.host_num - 1:
                right_ip = self.scheme.host_ip(idx, idx)
                eth_name = "eth1" if idx > 0 else "eth0"
                argv = [
                    "ifconfig",
                    f"{node_name}-{eth_name}",
                    str(right_ip),
                    "netmask",
                    LINK_NETMASK,
                ]
                print(node_name, "command:", argv)
                runner.run(node_name, argv)

    def _set_fib(self, net, runner=None):
        """Set FIB for linear topology (forward toward publisher)."""
        runner = runner or MininetCommandRunner(net)
        for idx in irange(0, self.host_num - 2):
            next_hop_ip = self.scheme.host_ip(idx, idx + 1)
            cefroute_add(net, idx, "ccnx:/test", "udp", str(next_hop_ip), runner=runner)


def run_linear_scenario(host_num, run_dir=None, debug_config=None):
    """Entry point for linear topology scenario."""
    scenario = LinearScenario(host_num, run_dir=run_dir, debug_config=debug_config)
    scenario.execute()
