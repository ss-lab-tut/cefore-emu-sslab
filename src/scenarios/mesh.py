"""Mesh topology scenario."""

import random
import sys
import time
from pathlib import Path

from mininet.log import info

from ..runtime.cefore import (
    run_cefgetfile,
    run_cefputfile,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from ..runtime.links import pick_publish_link
from ..runtime.net_config import apply_fib, apply_ip_addr
from ..runtime.template import cleanup_node_dirs, ensure_node_dirs
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

    def build_topology(self):
        ensure_node_dirs(self.host_num, self.rng)
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
        apply_ip_addr(net, self.topo.mesh_links)

        for idx in range(self.host_num):
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

        apply_fib(net, self.topo.mesh_links, self.k_paths)
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
        publish_link = pick_publish_link(self.topo.mesh_links, publisher)
        publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
        consumer = (
            publish_link["host_b"]
            if publish_link["host_a"] == publisher
            else publish_link["host_a"]
        )

        run_cefputfile(net, publisher, publish_uri)
        time.sleep(5)

        recvfile_path = str(self.run_dir / f"recvfile_at_h{consumer}")
        run_cefgetfile(net, consumer, publish_uri, recvfile_path)

    def teardown(self, net):
        for idx in range(self.host_num):
            stop_cefnetd(net, idx)
        for idx in range(self.host_num):
            if idx % 2 == 1:
                stop_csmgrd(net, idx)
        cleanup_node_dirs()


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
    )
    scenario.execute()
