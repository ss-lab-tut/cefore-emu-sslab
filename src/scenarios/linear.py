"""Linear topology scenario."""

import random
import sys
import time
from pathlib import Path

from mininet.log import info
from mininet.util import irange

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
        self.debug_config = debug_config
        self.rng = random.Random()
        self.generated_node_dirs = []

    def build_topology(self):
        self.generated_node_dirs = ensure_node_dirs(self.host_num, self.rng)
        return LineTopo(hosts=self.host_num)

    def configure(self, net):
        self._set_ip_addr(net)
        for idx in irange(0, self.host_num - 1):
            node_name = f"h{idx}"
            print(node_name, "command:", "ifconfig")
            info(net.hosts[idx].cmd("ifconfig"))

        for idx in range(self.host_num):
            if idx % 2 == 1:
                start_csmgrd(net, idx)
        for idx in range(self.host_num):
            start_cefnetd(net, idx)
        for idx in range(self.host_num):
            if not wait_for_cefnetd(net, idx):
                info(f"WARNING: h{idx} cefnetd not ready\n")

        self._set_fib(net)
        time.sleep(1)

    def run_experiment(self, net):
        publisher = self.host_num - 1
        node_name = f"h{publisher}"
        command = (
            f"cefputfile ccnx:/test -f ./sample-putfile -t 3000 -e 3000 -d ./{node_name} "
            "> cefputfile-log"
        )
        print(node_name, "command:", command)
        net.hosts[publisher].cmd(command)
        time.sleep(5)

        node_name = "h0"
        command = (
            "cefgetfile ccnx:/test -f ./recvfile_at_h0 -d ./h0 > cefgetfile-log"
        )
        print(node_name, "command:", command)
        net.hosts[0].cmd(command)

    def teardown(self, net):
        for idx in range(self.host_num):
            stop_cefnetd(net, idx)
        for idx in range(self.host_num):
            if idx % 2 == 1:
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
