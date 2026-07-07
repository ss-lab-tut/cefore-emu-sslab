"""Link state operations for mesh topologies."""

from mininet.log import info

from ..core.topology import TopologyModel


def find_link(mesh_links, host_a, host_b):
    """Find the link between two hosts (a ``core.topology.Link``), or ``None``."""
    return TopologyModel(mesh_links).find_link(host_a, host_b)


def set_link_state(net, mesh_links, host_a, host_b, state):
    """Set link state between two hosts."""
    link = find_link(mesh_links, host_a, host_b)
    if link is None:
        raise RuntimeError(f"link not found between h{host_a} and h{host_b}")
    host_a_name = f"h{host_a}"
    host_b_name = f"h{host_b}"
    info("link", host_a_name, host_b_name, state, "\n")
    net.configLinkStatus(host_a_name, link.switch, state)
    net.configLinkStatus(host_b_name, link.switch, state)


def link_down(net, mesh_links, host_a, host_b):
    """Bring down link between two hosts."""
    set_link_state(net, mesh_links, host_a, host_b, "down")


def link_up(net, mesh_links, host_a, host_b):
    """Bring up link between two hosts."""
    set_link_state(net, mesh_links, host_a, host_b, "up")


def set_node_links_state(net, node_name, state):
    """Set state of all links connected to a node."""
    node = net.get(node_name)
    for link in net.links:
        if link.intf1.node == node:
            net.configLinkStatus(node.name, link.intf2.node.name, state)
        elif link.intf2.node == node:
            net.configLinkStatus(node.name, link.intf1.node.name, state)
