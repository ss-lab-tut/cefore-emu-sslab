"""Network configuration (IP address and FIB setup)."""

from mininet.log import info

from .graph_algos import dijkstra_all


def set_ip_addr(net, mesh_links):
    """Assign IP addresses to all host interfaces.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
    """
    # Assign one /24 per link or per shared switch; host index selects the last octet.
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


def _build_graph_and_subnets(mesh_links):
    """Build adjacency graph and link subnet mapping.

    Args:
        mesh_links: List of link definitions.

    Returns:
        Tuple of (host_num, graph dict, link_subnets dict).
    """
    host_num = 0
    for link in mesh_links:
        if "hosts" in link:
            host_num = max(host_num, max(link["hosts"]) + 1)
        else:
            host_num = max(host_num, max(link["host_a"], link["host_b"]) + 1)
    graph = {idx: set() for idx in range(host_num)}
    link_subnets = {}
    for link in mesh_links:
        if "hosts" in link:
            hosts = link["hosts"]
            subnet = link["subnet"]
            for idx, host_a in enumerate(hosts):
                for host_b in hosts[idx + 1 :]:
                    graph[host_a].add(host_b)
                    graph[host_b].add(host_a)
                    key = tuple(sorted((host_a, host_b)))
                    link_subnets[key] = subnet
            continue
        host_a = link["host_a"]
        host_b = link["host_b"]
        graph[host_a].add(host_b)
        graph[host_b].add(host_a)
        key = tuple(sorted((host_a, host_b)))
        link_subnets[key] = link["subnet"]
    return host_num, graph, link_subnets


def set_fib(net, mesh_links, k_paths):
    """Add FIB entries for all destinations with multiple next hops.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of best next hops per destination.
    """
    host_num, graph, link_subnets = _build_graph_and_subnets(mesh_links)

    all_dist = []
    for src in range(host_num):
        distances, _parents = dijkstra_all(graph, src)
        all_dist.append(distances)

    for src in range(host_num):
        node_name = f"h{src}"
        for dest in range(host_num):
            if src == dest:
                continue
            prefix = f"ccnx:/test/example{dest + 1}"
            candidates = []
            for neighbor in graph[src]:
                dist_to_dest = all_dist[neighbor].get(dest)
                if dist_to_dest is None:
                    continue
                cost = 1 + dist_to_dest
                candidates.append((cost, neighbor))
            if not candidates:
                info(f"host h{src} has no path to h{dest}\n")
                continue
            candidates.sort()
            next_hops = [neighbor for _cost, neighbor in candidates[:k_paths]]
            for next_hop in next_hops:
                link_key = tuple(sorted((src, next_hop)))
                subnet = link_subnets[link_key]
                next_hop_ip = f"192.168.{subnet}.{next_hop + 1}"
                command = f"cefroute add {prefix} udp {next_hop_ip} -d ./{node_name}"
                print(node_name, "command:", command)
                info(net.hosts[src].cmd(command))


def set_fib_for_uris(net, mesh_links, k_paths, uri_publishers):
    """Set FIB entries for multiple URIs with their respective publishers.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of shortest paths per destination.
        uri_publishers: Dict mapping URI prefix to publisher host ID.
                        Example: {"ccnx:/test/content1": 9, "ccnx:/video": 5}
    """
    host_num, graph, link_subnets = _build_graph_and_subnets(mesh_links)

    all_dist = []
    for src in range(host_num):
        distances, _parents = dijkstra_all(graph, src)
        all_dist.append(distances)

    for uri_prefix, publisher in uri_publishers.items():
        dest = publisher
        for src in range(host_num):
            if src == dest:
                continue
            node_name = f"h{src}"
            candidates = []
            for neighbor in graph[src]:
                dist_to_dest = all_dist[neighbor].get(dest)
                if dist_to_dest is None:
                    continue
                cost = 1 + dist_to_dest
                candidates.append((cost, neighbor))
            if not candidates:
                info(f"host h{src} has no path to publisher h{dest} for {uri_prefix}\n")
                continue
            candidates.sort()
            next_hops = [neighbor for _cost, neighbor in candidates[:k_paths]]
            for next_hop in next_hops:
                link_key = tuple(sorted((src, next_hop)))
                subnet = link_subnets[link_key]
                next_hop_ip = f"192.168.{subnet}.{next_hop + 1}"
                command = f"cefroute add {uri_prefix} udp {next_hop_ip} -d ./{node_name}"
                print(node_name, "command:", command)
                info(net.hosts[src].cmd(command))
