"""Mesh topology scenario."""

import random
import sys
import time
from pathlib import Path

from mininet.log import info

from ..runtime.command_runner import MininetCommandRunner
from ..runtime.cefore import (
    run_cefgetfile,
    run_cefputfile,
    run_cefstatus_all,
)
from ..runtime.daemon_fleet import DaemonFleet
from ..core.addressing import AddressingScheme
from ..core.roles import assign_roles
from ..core.topology import TopologyModel
from ..runtime.net_config import apply_fib, apply_ip_addr
from ..runtime.template import provision_node_dirs
from ..runtime.topo import MeshTopo, max_possible_links, min_required_links
from ..runtime.viz import print_mesh_links, render_topology_png

from .base import BaseScenario


class MeshScenario(BaseScenario):
    """Mesh topology scenario with random host-to-host connections."""

    def __init__(
        self,
        host_num,
        swhich_num,
        seed,
        k_paths,
        topo_png=None,
        topo_layout="spring",
        node_per_switch=2,
        host_degree_min=1,
        host_degree_max=2,
        switch_use_all=False,
        run_dir=None,
        debug_config=None,
        scheme=None,
    ):
        self.host_num = host_num
        self.swhich_num = swhich_num
        self.seed = seed
        self.k_paths = k_paths
        self.topo_png = topo_png
        self.topo_layout = topo_layout
        self.node_per_switch = node_per_switch
        self.host_degree_min = host_degree_min
        self.host_degree_max = host_degree_max
        self.switch_use_all = switch_use_all
        self.run_dir = run_dir or Path(".")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.debug_config = debug_config
        self.generated_node_dirs = []
        self.roles = {}
        self.scheme = scheme if scheme is not None else AddressingScheme()

        if host_num < 3:
            sys.exit("host count must be at least 3")
        if k_paths < 1:
            sys.exit("k must be at least 1")
        if swhich_num < 2:
            sys.exit("link count must be at least 2")
        max_links = max_possible_links(host_num)
        if swhich_num > max_links:
            sys.exit(f"link count must be at most {max_links}")
        min_links = min_required_links(host_num)
        if swhich_num < min_links:
            sys.exit(f"link count must be at least {min_links} to cover all hosts")

        self.rng = random.Random(seed)
        self.topo = None
        self.daemon_fleet = None

    def build_topology(self):
        self.roles = assign_roles(self.host_num, self.rng)
        self.generated_node_dirs = provision_node_dirs(self.roles)
        self.topo = MeshTopo(
            hosts=self.host_num,
            swhich_num=self.swhich_num,
            rng=self.rng,
            node_per_switch=self.node_per_switch,
            host_degree_min=self.host_degree_min,
            host_degree_max=self.host_degree_max,
            switch_use_all=self.switch_use_all,
        )
        return self.topo

    def configure(self, net):
        apply_ip_addr(net, self.topo.mesh_links, scheme=self.scheme)

        runner = MininetCommandRunner(net)
        for idx in range(self.host_num):
            node_name = f"h{idx}"
            print(node_name, "command:", "ifconfig")
            info(runner.run(node_name, ["ifconfig"]).stdout)

        log_dir = str(self.run_dir) if self.run_dir != Path(".") else None
        self.daemon_fleet = DaemonFleet(
            net,
            node_names=[f"h{idx}" for idx in range(self.host_num)],
            csmgrd_nodes={
                f"h{idx}" for idx in range(self.host_num)
                if self.roles.get(idx) and self.roles[idx].runs_csmgrd
            },
            log_dir=log_dir,
        )
        self.daemon_fleet.start_all()
        self.daemon_fleet.wait_ready()

        apply_fib(net, self.topo.mesh_links, self.k_paths, scheme=self.scheme)
        run_cefstatus_all(net, self.host_num)
        print_mesh_links(self.topo.mesh_links)

        topo_png_path = self.topo_png
        if topo_png_path:
            topo_png_path = str(self.run_dir / Path(topo_png_path).name)
        render_topology_png(
            self.topo.mesh_links, topo_png_path,
            seed=self.seed, layout=self.topo_layout,
        )
        time.sleep(1)

    def run_experiment(self, net):
        publisher = self.host_num - 1
        publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
        consumer = TopologyModel(self.topo.mesh_links).peer_of(publisher)

        runner = MininetCommandRunner(net)
        put_log = str(self.run_dir / f"cefputfile_h{publisher}.log")
        exit_code = run_cefputfile(runner, publisher, publish_uri, log_name=put_log)
        if exit_code != 0:
            info(f"[ERROR] cefputfile failed on h{publisher} (exit_code={exit_code})\n")
            sys.exit(1)
        time.sleep(5)

        recvfile_path = str(self.run_dir / f"recvfile_at_h{consumer}")
        get_log = str(self.run_dir / f"cefgetfile_h{consumer}.log")
        exit_code = run_cefgetfile(runner, consumer, publish_uri, recvfile_path, log_name=get_log)
        if exit_code != 0:
            info(f"[ERROR] cefgetfile failed on h{consumer} (exit_code={exit_code})\n")
            sys.exit(1)

    def teardown(self, net):
        fleet = self.daemon_fleet or DaemonFleet(
            net, node_names=[f"h{idx}" for idx in range(self.host_num)]
        )
        fleet.stop_all()


def run_mesh_scenario(
    host_num,
    swhich_num,
    seed,
    k_paths,
    topo_png=None,
    topo_layout="spring",
    node_per_switch=2,
    host_degree_min=1,
    host_degree_max=2,
    switch_use_all=False,
    run_dir=None,
    debug_config=None,
):
    """Entry point for mesh topology scenario."""
    scenario = MeshScenario(
        host_num=host_num,
        swhich_num=swhich_num,
        seed=seed,
        k_paths=k_paths,
        topo_png=topo_png,
        topo_layout=topo_layout,
        node_per_switch=node_per_switch,
        host_degree_min=host_degree_min,
        host_degree_max=host_degree_max,
        switch_use_all=switch_use_all,
        run_dir=run_dir,
        debug_config=debug_config,
    )
    scenario.execute()
