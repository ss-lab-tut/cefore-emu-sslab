"""Network configuration application (Mininet-dependent)."""

from mininet.log import info

from ..core.fib import compute_fib, compute_fib_for_uris


def apply_ip_addr(net, mesh_links):
    """Assign IP addresses to all host interfaces.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
    """
    for link in mesh_links:
        subnet = link["subnet"]
        if "hosts" in link:
            for host_idx in link["hosts"]:
                eth_idx = link["host_eth"][host_idx]
                node_name = f"h{host_idx}"
                ip = f"192.168.{subnet}.{host_idx + 1}"
                command = f"ifconfig {node_name}-eth{eth_idx} {ip}"
                print(node_name, "command:", command)
                net.hosts[host_idx].cmd(command)
            continue
        for host_idx, eth_idx in (
            (link["host_a"], link["host_a_eth"]),
            (link["host_b"], link["host_b_eth"]),
        ):
            node_name = f"h{host_idx}"
            ip = f"192.168.{subnet}.{host_idx + 1}"
            command = f"ifconfig {node_name}-eth{eth_idx} {ip}"
            print(node_name, "command:", command)
            net.hosts[host_idx].cmd(command)


def apply_fib(net, mesh_links, k_paths):
    """Apply FIB entries to all hosts.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of best next hops per destination.
    """
    routes = compute_fib(mesh_links, k_paths)
    for route in routes:
        node_name = f"h{route.source}"
        command = f"cefroute add {route.prefix} udp {route.next_hop_ip} -d ./{node_name}"
        print(node_name, "command:", command)
        info(net.hosts[route.source].cmd(command))


def apply_fib_for_uris(net, mesh_links, k_paths, uri_publishers):
    """Apply FIB entries for multiple URIs.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of shortest paths per destination.
        uri_publishers: Dict mapping URI prefix to publisher host ID.
    """
    routes = compute_fib_for_uris(mesh_links, k_paths, uri_publishers)
    for route in routes:
        node_name = f"h{route.source}"
        command = f"cefroute add {route.prefix} udp {route.next_hop_ip} -d ./{node_name}"
        print(node_name, "command:", command)
        info(net.hosts[route.source].cmd(command))
