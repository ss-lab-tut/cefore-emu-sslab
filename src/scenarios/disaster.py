"""Disaster topology scenario with periodic host failure simulation."""

import json
import random
import sys
import threading
import time
from pathlib import Path

from mininet.link import TCLink
from mininet.log import info

from ..core.config.auto_gen import generate_operations
from ..core.flap_state import FlapState
from ..core.graph import select_k_centers
from ..runtime.bandwidth import parse_bw_args, set_link_bandwidth
from ..runtime.bridge import (
    attach_external_interface,
    cleanup_external_bridges,
    parse_ext_args,
)
from ..runtime.cefore import (
    run_cefgetfile,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from ..runtime.links import pick_publish_link, set_node_links_state
from ..runtime.net_config import apply_fib, apply_fib_for_uris, apply_ip_addr
from ..runtime.template import cleanup_node_dirs, ensure_node_dirs
from ..runtime.topo import MeshTopo
from ..runtime.viz import build_host_graph, print_mesh_links, render_topology_png

from .base import BaseScenario


class Tee:
    """Write to multiple streams simultaneously."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def parse_int_list(value):
    """Parse comma-separated integers."""
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def periodic_host_flap(
    net, host_num, interval, down_time, rng, exclude, state, down_count, stagger
):
    """Start background thread for periodic host flapping.

    Returns:
        threading.Event to stop the flapping.
    """
    stop_event = threading.Event()
    exclude_set = set(exclude or [])

    def worker():
        while not stop_event.is_set():
            stop_event.wait(interval)
            if stop_event.is_set():
                break

            candidates = [
                i for i in range(host_num) if i not in exclude_set
            ]
            if not candidates:
                continue

            count = min(down_count, len(candidates))
            down_hosts = (rng or random.Random()).sample(candidates, count)

            for host_idx in down_hosts:
                node_name = f"h{host_idx}"
                info(f"[flap] bringing down {node_name}\n")
                set_node_links_state(net, node_name, "down")
                state.update(down_hosts, last_down=host_idx)
                if stagger > 0:
                    stop_event.wait(stagger)
                    if stop_event.is_set():
                        break

            stop_event.wait(down_time)
            if stop_event.is_set():
                break

            for host_idx in down_hosts:
                node_name = f"h{host_idx}"
                info(f"[flap] bringing up {node_name}\n")
                set_node_links_state(net, node_name, "up")

            state.update([])

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return stop_event


def run_host_command(net, host_idx, command):
    """Run command on host and wait for completion."""
    proc = net.hosts[host_idx].popen(command, shell=True)
    return proc.wait()


class DisasterScenario(BaseScenario):
    """Mesh topology with periodic host failure simulation."""

    def __init__(self, args, run_dir=None):
        self.args = args
        self.run_dir = run_dir or Path(".")
        self.rng = random.Random(args.seed) if args.seed is not None else None
        self.topo = None
        self.ops_put = []
        self.ops_get = []
        self.auto_config = getattr(args, "auto", None)
        self.stop_event = None
        self.flap_state = FlapState()

    def build_topology(self):
        self.ops_put = self.args.puts or []
        if self.auto_config and not self.ops_put:
            self.ops_put, _ = generate_operations(
                self.auto_config, self.args.hosts, self.args.seed, self.run_dir
            )

        publisher_ids = set(op["host"] for op in self.ops_put) if self.ops_put else None
        ensure_node_dirs(self.args.hosts, self.rng or random.Random(), publisher_ids)

        self.topo = MeshTopo(
            hosts=self.args.hosts,
            swhich_num=self.args.switches,
            rng=self.rng,
            node_per_switch=self.args.node_per_switch,
            host_degree_min=self.args.host_degree_min,
            host_degree_max=self.args.host_degree_max,
            switch_use_all=self.args.switch_use_all,
        )
        return self.topo

    def create_mininet(self, topo, **kwargs):
        from mininet.net import Mininet
        return Mininet(topo=topo, link=TCLink, waitConnected=True, **kwargs)

    def configure(self, net):
        apply_ip_addr(net, self.topo.mesh_links)

        for idx in range(self.args.hosts):
            info(net.hosts[idx].cmd("ifconfig"))

        for idx in range(self.args.hosts):
            if idx % 2 == 1:
                start_csmgrd(net, idx)
        for idx in range(self.args.hosts):
            start_cefnetd(net, idx)
        for idx in range(self.args.hosts):
            wait_for_cefnetd(net, idx)

        self.ops_get = self.args.gets or []
        if self.auto_config and not self.ops_get:
            _, self.ops_get = generate_operations(
                self.auto_config, self.args.hosts, self.args.seed, self.run_dir
            )

        if not self.ops_put:
            publisher = self.args.hosts - 1
            publish_link = pick_publish_link(self.topo.mesh_links, publisher)
            publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
            seed_label = "none" if self.args.seed is None else str(self.args.seed)
            down_host_label = "none"
            log_name = (
                f"cefputfile_{self.args.hosts}_{self.args.switches}_{seed_label}_"
                f"{self.args.down_interval}_{self.args.down_duration}_{down_host_label}.log"
            )
            self.ops_put = [
                {
                    "host": publisher,
                    "uri": publish_uri,
                    "file": "./sample-putfile",
                    "log": str(self.run_dir / log_name),
                }
            ]

        uri_publishers = {}
        for op in self.ops_put:
            uri_publishers[op["uri"]] = op["host"]

        if uri_publishers:
            apply_fib_for_uris(net, self.topo.mesh_links, self.args.k, uri_publishers)
        else:
            apply_fib(net, self.topo.mesh_links, self.args.k)

        run_cefstatus_all(net, self.args.hosts)
        print_mesh_links(self.topo.mesh_links)

        topo_png_path = self.args.topo_png
        if topo_png_path:
            topo_png_path = str(self.run_dir / Path(topo_png_path).name)
        render_topology_png(
            self.topo.mesh_links, topo_png_path,
            seed=self.args.seed, layout=self.args.topo_layout,
        )
        host_graph, _ = build_host_graph(self.topo.mesh_links)
        cache_count = self.args.cache_count if self.args.cache_count > 0 else self.args.down_count + 1
        cache_nodes = select_k_centers(host_graph, cache_count)
        if cache_nodes:
            info("cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n")
        time.sleep(1)

        for node_a, node_b, bandwidth in parse_bw_args(self.args.bw):
            set_link_bandwidth(net, node_a, node_b, bandwidth)

        for host_name, intf_name, ip, mtu in parse_ext_args(self.args.ext):
            attach_external_interface(net, host_name, intf_name, ip, mtu)

    def run_experiment(self, net):
        for op in self.ops_put:
            host = op["host"]
            uri = op["uri"]
            infile = op.get("file", "./sample-putfile")
            log_name = op.get("log", f"cefputfile_h{host}.log")
            if not Path(log_name).is_absolute() and not str(log_name).startswith(
                str(self.run_dir)
            ):
                log_path = str(self.run_dir / log_name)
            else:
                log_path = log_name
            command = (
                f"cefputfile {uri} -f {infile} -t 3000 -e 3000 -d ./h{host} > {log_path}"
            )
            print(f"h{host}", "command:", command)
            run_host_command(net, host, command)
            time.sleep(1)

        if self.args.down_interval > 0 and self.args.down_duration > 0:
            self.stop_event = periodic_host_flap(
                net,
                self.args.hosts,
                self.args.down_interval,
                self.args.down_duration,
                self.rng,
                parse_int_list(self.args.down_exclude),
                self.flap_state,
                self.args.down_count,
                self.args.down_stagger,
            )

        rng = self.rng or random.Random()
        if not self.ops_get:
            base_uri = self.ops_put[0]["uri"]
            for idx in range(1, 6):
                candidates = [h for h in range(self.args.hosts) if h != self.ops_put[0]["host"]]
                consumer = rng.choice(candidates)
                self.ops_get.append(
                    {
                        "host": consumer,
                        "uri": base_uri,
                        "file": str(self.run_dir / f"recvfile_at_h{consumer}"),
                    }
                )

        wait_state = self.flap_state if self.stop_event is not None else None
        seed_label = "none" if self.args.seed is None else str(self.args.seed)

        for idx, op in enumerate(self.ops_get):
            consumer = op["host"]
            uri = op["uri"]
            outfile = op.get("file", f"recvfile_at_h{consumer}")

            if not Path(outfile).is_absolute() and not str(outfile).startswith(
                str(self.run_dir)
            ):
                outfile = str(self.run_dir / outfile)

            if "log" in op:
                log_name = op["log"]
                if not Path(log_name).is_absolute() and not str(log_name).startswith(
                    str(self.run_dir)
                ):
                    log_path = str(self.run_dir / log_name)
                else:
                    log_path = log_name
                run_cefgetfile(net, consumer, uri, outfile, log_path=log_path)
            else:
                def make_log_factory(i, c, seed, rd, flap_state_ref):
                    def factory(snap):
                        actual_snap = snap
                        if not actual_snap and flap_state_ref is not None:
                            actual_snap = flap_state_ref.snapshot()
                        down_label = (
                            "none"
                            if not actual_snap
                            else ",".join(str(h) for h in sorted(actual_snap))
                        )
                        return str(
                            rd
                            / f"cefgetfile_seed{seed}_downhosts{down_label}_idx{i}_h{c}.log"
                        )
                    return factory

                log_factory = make_log_factory(
                    idx, consumer, seed_label, self.run_dir, self.flap_state
                )
                run_cefgetfile(
                    net,
                    consumer,
                    uri,
                    outfile,
                    wait_for_down=wait_state if idx == 0 else None,
                    log_path_factory=log_factory,
                )

            if idx < len(self.ops_get) - 1 and self.args.get_interval > 0:
                time.sleep(self.args.get_interval)

    def teardown(self, net):
        if self.stop_event is not None:
            self.stop_event.set()
        for idx in range(self.args.hosts):
            stop_cefnetd(net, idx)
        for idx in range(self.args.hosts):
            if idx % 2 == 1:
                stop_csmgrd(net, idx)
        cleanup_external_bridges()
        cleanup_node_dirs()


def run_disaster_scenario(args, run_dir=None):
    """Entry point for disaster topology scenario."""
    scenario = DisasterScenario(args, run_dir)
    scenario.execute()
