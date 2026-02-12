"""Network configuration (IP address, FIB setup, and bandwidth control)."""

from mininet.log import info

from .graph_algos import dijkstra_all


def parse_int_list(value):
    """Parse integer list from string or list input.

    Args:
        value: Comma-separated string or list of integers/strings.

    Returns:
        List of integers.
    """
    if value is None or value == "":
        return []
    items = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if item is None or item == "":
                continue
            if isinstance(item, str):
                parts = [part for part in item.split(",") if part.strip() != ""]
                items.extend(parts)
            else:
                items.append(item)
    elif isinstance(value, str):
        items = [part for part in value.split(",") if part.strip() != ""]
    else:
        items = [value]
    try:
        return [int(item) for item in items]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"expected list of ints or comma-separated string, got {value!r}"
        ) from exc


def parse_bw_args(values):
    """Parse bandwidth arguments.

    Args:
        values: List of "nodeA,nodeB,mbps" strings.

    Returns:
        List of (node_a, node_b, bandwidth) tuples.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 3:
            raise ValueError("bw format is nodeA,nodeB,mbps")
        entries.append((parts[0], parts[1], float(parts[2])))
    return entries


def set_link_bandwidth(net, node_a, node_b, bandwidth):
    """Set bandwidth on link between two nodes.

    Args:
        net: Mininet network instance.
        node_a: First node name.
        node_b: Second node name.
        bandwidth: Bandwidth in Mbps.
    """
    for link in net.linksBetween(net.get(node_a), net.get(node_b)):
        link.intf1.config(bw=bandwidth)
        link.intf2.config(bw=bandwidth)
        info(f"set bw {bandwidth} Mbps between {node_a} and {node_b}\n")


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


def _add_fib_entries(net, graph, all_dist, link_subnets, host_num, k_paths,
                     uri_prefix, dest, direction_label="forward"):
    """Add FIB entries from all hosts toward a single destination.

    Args:
        net: Mininet network instance.
        graph: Adjacency graph dict.
        all_dist: Pre-computed distances per source.
        link_subnets: Link subnet mapping.
        host_num: Total number of hosts.
        k_paths: Number of best next hops.
        uri_prefix: Content URI prefix.
        dest: Destination host ID.
        direction_label: Label for log messages ("forward" or "reverse").
    """
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
            info(f"host h{src} has no path to h{dest} for {uri_prefix} ({direction_label})\n")
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


def set_fib_for_uris(net, mesh_links, k_paths, uri_publishers, uri_subscribers=None):
    """Set FIB entries for multiple URIs with their respective publishers.

    Generates forward FIB entries (all hosts → publisher) for every URI.
    When uri_subscribers is provided, also generates reverse FIB entries
    (all hosts → each subscriber) for pubsub URIs so that Trigger Interests
    from the publisher can reach subscribers.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of shortest paths per destination.
        uri_publishers: Dict mapping URI prefix to publisher host ID.
                        Example: {"ccnx:/test/content1": 9, "ccnx:/video": 5}
        uri_subscribers: Optional dict mapping URI prefix to set of subscriber host IDs.
                         Example: {"ccnx:/test/content1": {0, 1, 2}}
    """
    host_num, graph, link_subnets = _build_graph_and_subnets(mesh_links)

    all_dist = []
    for src in range(host_num):
        distances, _parents = dijkstra_all(graph, src)
        all_dist.append(distances)

    # Forward direction: all hosts → publisher
    for uri_prefix, publisher in uri_publishers.items():
        _add_fib_entries(
            net, graph, all_dist, link_subnets, host_num, k_paths,
            uri_prefix, publisher, direction_label="forward",
        )

    # Reverse direction: all hosts → each subscriber (pubsub only)
    if uri_subscribers:
        for uri_prefix, subscribers in uri_subscribers.items():
            for sub_host in subscribers:
                _add_fib_entries(
                    net, graph, all_dist, link_subnets, host_num, k_paths,
                    uri_prefix, sub_host, direction_label="reverse",
                )
