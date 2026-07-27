"""Runtime layer (Mininet/Cefore integration).

The package exports the historical convenience names lazily so importing a
pure helper such as ``src.runtime.daemon_logs`` does not also import Mininet.
"""

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    # cefore
    "wait_for_cefnetd": ".cefore",
    "start_csmgrd": ".cefore",
    "stop_csmgrd": ".cefore",
    "start_cefnetd": ".cefore",
    "stop_cefnetd": ".cefore",
    "run_cefputfile": ".cefore",
    "run_cefgetfile": ".cefore",
    "run_cefstatus": ".cefore",
    "run_cefstatus_all": ".cefore",
    "run_ccninfo": ".cefore",
    "run_csmgrstatus": ".cefore",
    # cleanup
    "cleanup_all": ".cleanup",
    "kill_cef_processes": ".cleanup",
    # template
    "update_local_sock_id": ".template",
    "update_node_name": ".template",
    "read_port_num": ".cefore_conf",
    "cleanup_cefnetd_socket": ".cefore",
    "provision_node_dirs": ".template",
    "cleanup_node_dirs": ".template",
    "NodeDirError": ".template",
    # debug
    "archive_node_dirs": ".debug",
    # bridge
    "attach_external_via_bridge": ".bridge_external",
    "attach_external_interface": ".bridge_external",
    "cleanup_external_bridges": ".bridge_external",
    "parse_ext_args": ".bridge_args",
    # bandwidth
    "set_link_bandwidth": ".bandwidth",
    "parse_bw_args": ".bandwidth",
    # links
    "find_link": ".links",
    "set_link_state": ".links",
    "link_down": ".links",
    "link_up": ".links",
    "set_node_links_state": ".links",
    "periodic_host_flap": ".failure_manager",
    "FlexibleFailureManager": ".failure_manager",
    # forwarding
    "ForwardingConfigManager": ".forwarding",
    "resolve_forwarding_config": ".forwarding",
    # daemon_fleet
    "DaemonFleet": ".daemon_fleet",
    # net_config
    "apply_ip_addr": ".net_config",
    "apply_fib": ".net_config",
    "apply_fib_routes": ".net_config",
    "cefroute_add": ".net_config",
    "cefroute_del": ".net_config",
    "cefroute_enable": ".net_config",
    # topo
    "MeshTopo": ".topo",
    "LineTopo": ".topo",
    "SimpleLinkTopo": ".topo",
    "max_possible_links": ".topo",
    "min_required_links": ".topo",
    # viz
    "build_host_graph": ".viz",
    "build_tree": ".viz",
    "print_mesh_links": ".viz",
    "render_topology_png": ".viz",
}


def __getattr__(name: str) -> Any:
    """Load legacy runtime exports only when callers request them."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORT_MODULES[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    # cefore
    "wait_for_cefnetd",
    "start_csmgrd",
    "stop_csmgrd",
    "start_cefnetd",
    "stop_cefnetd",
    "run_cefputfile",
    "run_cefgetfile",
    "run_ccninfo",
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
    "provision_node_dirs",
    "cleanup_node_dirs",
    "NodeDirError",
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
    "set_node_links_state",
    "periodic_host_flap",
    "FlexibleFailureManager",
    # forwarding
    "ForwardingConfigManager",
    "resolve_forwarding_config",
    # daemon_fleet
    "DaemonFleet",
    # net_config
    "apply_ip_addr",
    "apply_fib",
    "apply_fib_routes",
    "cefroute_add",
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
