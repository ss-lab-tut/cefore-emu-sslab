"""Runtime layer (Mininet/Cefore integration)."""

from .base import FakeRuntime, MininetRuntime, Runtime
from .bridge import (
    attach_external_interface,
    attach_external_via_bridge,
    cleanup_external_bridges,
    parse_ext_args,
)
from .bandwidth import parse_bw_args, set_link_bandwidth
from .cleanup import cleanup_all, kill_cef_processes
from .debug import archive_node_dirs
from .cefore import (
    run_cefgetfile,
    run_cefputfile,
    run_cefstatus,
    run_cefstatus_all,
    run_csmgrstatus,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .links import (
    find_link,
    link_down,
    link_up,
    pick_publish_link,
    set_link_state,
    set_node_links_state,
)
from .failure_manager import FlexibleFailureManager, periodic_host_flap
from .net_config import apply_fib, apply_fib_for_uris, apply_ip_addr, cefroute_del, cefroute_enable
from .template import (
    cleanup_cefnetd_socket,
    cleanup_node_dirs,
    ensure_node_dirs,
    read_port_num,
    update_local_sock_id,
    update_node_name,
)
from .topo import LineTopo, MeshTopo, SimpleLinkTopo, max_possible_links, min_required_links
from .viz import (
    build_host_graph,
    build_tree,
    print_mesh_links,
    render_topology_png,
)

__all__ = [
    # base
    "Runtime",
    "MininetRuntime",
    "FakeRuntime",
    # cefore
    "wait_for_cefnetd",
    "start_csmgrd",
    "stop_csmgrd",
    "start_cefnetd",
    "stop_cefnetd",
    "run_cefputfile",
    "run_cefgetfile",
    "run_cefstatus",
    "run_cefstatus_all",
    "run_csmgrstatus",
    # cleanup
    "cleanup_all",
    "kill_cef_processes",
    # template
    "update_local_sock_id",
    "update_node_name",
    "read_port_num",
    "cleanup_cefnetd_socket",
    "ensure_node_dirs",
    "cleanup_node_dirs",
    # debug
    "archive_node_dirs",
    # bridge
    "attach_external_via_bridge",
    "attach_external_interface",
    "cleanup_external_bridges",
    "parse_ext_args",
    # bandwidth
    "set_link_bandwidth",
    "parse_bw_args",
    # links
    "find_link",
    "set_link_state",
    "link_down",
    "link_up",
    "pick_publish_link",
    "set_node_links_state",
    "periodic_host_flap",
    "FlexibleFailureManager",
    # net_config
    "apply_ip_addr",
    "apply_fib",
    "apply_fib_for_uris",
    "cefroute_del",
    "cefroute_enable",
    # topo
    "MeshTopo",
    "LineTopo",
    "SimpleLinkTopo",
    "max_possible_links",
    "min_required_links",
    # viz
    "build_host_graph",
    "build_tree",
    "print_mesh_links",
    "render_topology_png",
]
