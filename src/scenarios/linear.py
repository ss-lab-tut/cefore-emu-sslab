"""Linear topology scenario."""

import random
import sys
import time
from pathlib import Path

from mininet.log import info
from mininet.util import irange

from ..core.roles import assign_roles
from ..runtime.cefore import (
    run_cefgetfile,
    run_cefputfile,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from ..runtime.template import ensure_node_dirs
from ..runtime.topo import LineTopo

from .base import BaseScenario


class LinearScenario(BaseScenario):
    """Linear topology scenario: h0-s0-h1-s1-...-sN-hN."""

    def __init__(self, host_num, run_dir=None, debug_config=None):
        if host_num < 2:
            sys.exit("host count must be at least 2")
        self.host_num = host_num
        self.run_dir = run_dir or Path(".")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.debug_config = debug_config
        self.rng = random.Random()
        self.generated_node_dirs = []
        self.roles = {}

    def build_topology(self):
        # Compute roles first, then restore rng state so ensure_node_dirs
        # uses the same rng sequence (ensure_node_dirs also calls assign_roles).
        rng_state = self.rng.getstate()
        self.roles = assign_roles(self.host_num, self.rng)
        self.rng.setstate(rng_state)
        self.generated_node_dirs = ensure_node_dirs(self.host_num, self.rng)
        return LineTopo(hosts=self.host_num)

    def configure(self, net):
        self._set_ip_addr(net)
        for idx in irange(0, self.host_num - 1):
            node_name = f"h{idx}"
            print(node_name, "command:", "ifconfig")
            info(net.hosts[idx].cmd("ifconfig"))

        log_dir = str(self.run_dir) if self.run_dir != Path(".") else None
        for idx in range(self.host_num):
            if self.roles.get(idx) and self.roles[idx].runs_csmgrd:
                start_csmgrd(net, idx, log_dir=log_dir)
        for idx in range(self.host_num):
            start_cefnetd(net, idx, log_dir=log_dir)
        for idx in range(self.host_num):
            if not wait_for_cefnetd(net, idx):
                info(f"WARNING: h{idx} cefnetd not ready\n")

        self._set_fib(net)
        time.sleep(1)

    def run_experiment(self, net):
        publisher = self.host_num - 1
        put_log = str(self.run_dir / "cefputfile.log")
        exit_code = run_cefputfile(
            net, publisher, "ccnx:/test",
            cache_time=3000, expiry=3000,
            log_name=put_log,
        )
        if exit_code != 0:
            info(f"[ERROR] cefputfile failed on h{publisher} (exit_code={exit_code})\n")
            sys.exit(1)
        time.sleep(5)

        get_log = str(self.run_dir / "cefgetfile.log")
        recvfile = str(self.run_dir / "recvfile_at_h0")
        exit_code = run_cefgetfile(net, 0, "ccnx:/test", recvfile, log_name=get_log)
        if exit_code != 0:
            info(f"[ERROR] cefgetfile failed on h0 (exit_code={exit_code})\n")
            sys.exit(1)

    def teardown(self, net):
        for idx in range(self.host_num):
            stop_cefnetd(net, idx)
        for idx in range(self.host_num):
            if self.roles.get(idx) and self.roles[idx].runs_csmgrd:
                stop_csmgrd(net, idx)

    def _set_ip_addr(self, net):
        """Assign IPs for linear topology."""
        for idx in irange(0, self.host_num - 1):
            node_name = f"h{idx}"
            if idx > 0:
                left_ip = f"192.168.{idx - 1}.{idx + 1}"
                command = f"ifconfig {node_name}-eth0 {left_ip}"
                print(node_name, "command:", command)
                net.hosts[idx].cmd(command)
            if idx < self.host_num - 1:
                right_ip = f"192.168.{idx}.{idx + 1}"
                eth_name = "eth1" if idx > 0 else "eth0"
                command = f"ifconfig {node_name}-{eth_name} {right_ip}"
                print(node_name, "command:", command)
                net.hosts[idx].cmd(command)

    def _set_fib(self, net):
        """Set FIB for linear topology (forward toward publisher)."""
        for idx in irange(0, self.host_num - 2):
            node_name = f"h{idx}"
            next_hop_ip = f"192.168.{idx}.{idx + 2}"
            command = f"cefroute add ccnx:/test udp {next_hop_ip} -d ./{node_name}"
            print(node_name, "command:", command)
            info(net.hosts[idx].cmd(command))


def run_linear_scenario(host_num, run_dir=None, debug_config=None):
    """Entry point for linear topology scenario."""
    scenario = LinearScenario(host_num, run_dir=run_dir, debug_config=debug_config)
    scenario.execute()
