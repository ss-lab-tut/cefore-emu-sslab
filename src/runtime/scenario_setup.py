"""Scenario Setup seam: the common mesh runtime setup recipe.

A single ``setup_scenario(net, spec)`` walks the canonical order that
disaster, connect, and mesh otherwise duplicated with drift:

  apply_ip_addr -> (bridges) -> ifconfig log -> bw -> ext -> render_png
  -> cache_strategy.place -> build_fleet + start + wait_ready -> apply_fib
  -> cefstatus + print_mesh_links

Each scenario builds a ``ScenarioSetupSpec`` and reads back a
``SetupResult`` (daemon_fleet, cache_node_set, fib_routes). The seam owns
the order; the spec carries policy.

This is the post-slice-2 canonical form. The pre-refactor variants --
connect's bw/ext-after-everything position, the mesh/connect
``time.sleep(1)`` after status, mesh's ``"command: ifconfig"`` debug print,
and PNG-after-status timing -- were preserved through a slice-1
behavior-preserving extraction, then verified harmless by /cefore-run-tests
smoke 12/12, then removed.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mininet.log import info

from .bandwidth import parse_bw_args, set_link_bandwidth
from .bridge import (
    attach_external_interface,
    BridgeManager,
    parse_ext_args,
    setup_bridges,
)
from .cache_strategy import CacheContext, CacheStrategy
from .cefore import run_cefstatus_all
from .command_runner import MininetCommandRunner
from .daemon_fleet import build_fleet, DaemonFleet
from .net_config import apply_fib, apply_ip_addr
from .viz import build_host_graph, print_mesh_links, render_topology_png


@dataclass(frozen=True)
class ScenarioSetupSpec:
    """Policy + ordering knobs the seam reads.

    Required fields appear first; defaults mirror the underlying functions'
    defaults so spec-built calls are byte-identical to the pre-refactor
    direct calls (apply_fib strategy="dijkstra", build_fleet
    cefnetd_timeout=10/readiness_policy="warn"). Drift would silently change
    routing or readiness behavior on the spec-using scenarios.
    """

    mesh_links: list
    scheme: Any
    host_count: int
    publisher_ids: set[int]
    cache_strategy: CacheStrategy
    fleet_run_dir: Path
    fib_k: int

    bridge_manager: BridgeManager | None = None
    bridge_configs: list | None = None
    bw_args: Any = ""
    ext_args: Any = ""
    topo_png_path: str | None = None
    topo_seed: int = 0
    topo_layout: str = "spring"
    fleet_cefnetd_timeout: int = 10
    fleet_readiness_policy: str = "warn"
    fib_strategy: str = "dijkstra"
    fib_uri_publishers: dict | None = None


@dataclass(frozen=True)
class SetupResult:
    """What the seam hands back to the scenario for downstream use.

    Scenarios MUST assign these back to self attrs (``self.daemon_fleet``,
    ``self.cache_node_set``, ``self._fib_routes``) because monitoring,
    webui, and FIB-restore code paths read them outside configure().
    """

    daemon_fleet: DaemonFleet
    cache_node_set: set[int]
    fib_routes: Any


def _log_ifconfig(net, host_count: int) -> None:
    """Print ``ifconfig`` per host."""
    runner = MininetCommandRunner(net)
    for idx in range(host_count):
        info(runner.run(f"h{idx}", ["ifconfig"]).stdout)


def _apply_bw_ext(net, spec: ScenarioSetupSpec) -> None:
    for node_a, node_b, bandwidth in parse_bw_args(spec.bw_args):
        set_link_bandwidth(net, node_a, node_b, bandwidth)
    for host_name, intf_name, ip, mtu in parse_ext_args(spec.ext_args):
        attach_external_interface(net, host_name, intf_name, ip, mtu)


def _render_png(spec: ScenarioSetupSpec) -> None:
    if not spec.topo_png_path:
        return
    render_topology_png(
        spec.mesh_links,
        spec.topo_png_path,
        seed=spec.topo_seed,
        layout=spec.topo_layout,
    )


def setup_scenario(net, spec: ScenarioSetupSpec) -> SetupResult:
    """Run the common scenario setup recipe in order, return SetupResult."""
    apply_ip_addr(net, spec.mesh_links, scheme=spec.scheme)

    if spec.bridge_configs:
        setup_bridges(
            net,
            spec.bridge_manager,
            spec.bridge_configs,
            spec.host_count,
            spec.mesh_links,
            scheme=spec.scheme,
        )

    _log_ifconfig(net, spec.host_count)
    _apply_bw_ext(net, spec)
    _render_png(spec)

    host_graph, _ = build_host_graph(spec.mesh_links)
    cache_ctx = CacheContext(
        host_count=spec.host_count,
        host_graph=host_graph,
        publisher_ids=set(spec.publisher_ids),
    )
    cache_node_set = spec.cache_strategy.place(cache_ctx)

    daemon_fleet = build_fleet(
        net,
        spec.host_count,
        cache_node_set,
        spec.fleet_run_dir,
        cefnetd_timeout=spec.fleet_cefnetd_timeout,
        readiness_policy=spec.fleet_readiness_policy,
    )
    daemon_fleet.start_all()
    daemon_fleet.wait_ready()

    fib_routes = apply_fib(
        net,
        spec.mesh_links,
        spec.fib_k,
        strategy=spec.fib_strategy,
        uri_publishers=spec.fib_uri_publishers,
        scheme=spec.scheme,
    )

    run_cefstatus_all(net, spec.host_count)
    print_mesh_links(spec.mesh_links)

    return SetupResult(
        daemon_fleet=daemon_fleet,
        cache_node_set=cache_node_set,
        fib_routes=fib_routes,
    )
