"""Topology module for Cefore emulation."""

from .cef_daemons import (
    run_cefgetfile,
    run_cefputfile,
    run_cefstatus,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .config_io import (
    cleanup_cefnetd_socket,
    read_port_num,
    update_local_sock_id,
    update_node_name,
)
from .disaster import (
    Tee,
    attach_external_via_bridge,
    cleanup_external_bridges,
    run_disaster_topology,
)
from .disaster import Tee, run_disaster_topology
from .external_bridge import BridgeManager, parse_bridge_args, setup_bridges
from .flap_state import FlapState
from .graph_algos import (
    compute_distances,
    dijkstra_all,
    k_shortest_paths,
    path_cost,
    select_k_centers,
    shortest_path,
)
from .links import (
    find_link,
    link_down,
    link_up,
    pick_publish_link,
    set_link_state,
    set_node_links_state,
)
from .mesh_topo import MeshTopo, min_required_switches, run_mesh_topology
from .net_config import set_fib, set_fib_for_uris, set_ip_addr
from .paths import ROOT_DIR, TEMPLATE_ROOT, resolve_run_dir
from .templates import cleanup_node_dirs, ensure_node_dirs, select_template
from .viz import build_host_graph, build_tree, print_mesh_links, render_topology_png

__all__ = [
    # paths
    "ROOT_DIR",
    "TEMPLATE_ROOT",
    "resolve_run_dir",
    # templates
    "select_template",
    "ensure_node_dirs",
    "cleanup_node_dirs",
    # config_io
    "update_local_sock_id",
    "update_node_name",
    "read_port_num",
    "cleanup_cefnetd_socket",
    # graph_algos
    "shortest_path",
    "dijkstra_all",
    "path_cost",
    "k_shortest_paths",
    "compute_distances",
    "select_k_centers",
    # net_config
    "set_ip_addr",
    "set_fib",
    "set_fib_for_uris",
    # links
    "find_link",
    "set_link_state",
    "link_down",
    "link_up",
    "pick_publish_link",
    "set_node_links_state",
    # cef_daemons
    "wait_for_cefnetd",
    "start_csmgrd",
    "stop_csmgrd",
    "start_cefnetd",
    "stop_cefnetd",
    "run_cefputfile",
    "run_cefgetfile",
    "run_cefstatus",
    "run_cefstatus_all",
    # viz
    "build_host_graph",
    "build_tree",
    "print_mesh_links",
    "render_topology_png",
    # mesh_topo
    "MeshTopo",
    "min_required_switches",
    "run_mesh_topology",
    # disaster
    "Tee",
    "run_disaster_topology",
    "attach_external_via_bridge",
    "cleanup_external_bridges",
    # external_bridge
    "BridgeManager",
    "parse_bridge_args",
    "setup_bridges",
    # flap_state
    "FlapState",
]
