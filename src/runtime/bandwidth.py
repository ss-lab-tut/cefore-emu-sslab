"""Bandwidth control operations (extracted from disaster.py)."""

from mininet.log import info

from .links import find_link


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


def set_switch_bandwidth(net, mesh_links, host_a, host_b, bandwidth):
    """Set bandwidth on all links of the shared switch between two hosts.

    Finds the switch that connects host_a and host_b via mesh_links,
    then sets bandwidth on ALL host-switch links connected to that switch.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        host_a: First host index.
        host_b: Second host index.
        bandwidth: Bandwidth in Mbps.
    """
    link = find_link(mesh_links, host_a, host_b)
    if link is None:
        info(f"[bw] no shared switch between h{host_a} and h{host_b}\n")
        return False
    switch_name = link["switch"]
    if "hosts" in link:
        hosts_on_switch = link["hosts"]
    else:
        hosts_on_switch = [link["host_a"], link["host_b"]]

    for host_idx in hosts_on_switch:
        host_name = f"h{host_idx}"
        set_link_bandwidth(net, host_name, switch_name, bandwidth)
    return True
