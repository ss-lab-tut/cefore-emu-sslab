"""Link state operations for mesh topologies."""

from mininet.log import info


def find_link(mesh_links, host_a, host_b):
    """Find link definition between two hosts."""
    for link in mesh_links:
        if "hosts" in link:
            if host_a in link["hosts"] and host_b in link["hosts"]:
                return link
            continue
        if {link["host_a"], link["host_b"]} == {host_a, host_b}:
            return link
    return None


def set_link_state(net, mesh_links, host_a, host_b, state):
    """Set link state between two hosts."""
    link = find_link(mesh_links, host_a, host_b)
    if link is None:
        raise RuntimeError(f"link not found between h{host_a} and h{host_b}")
    switch_name = link["switch"]
    host_a_name = f"h{host_a}"
    host_b_name = f"h{host_b}"
    info("link", host_a_name, host_b_name, state, "\n")
    net.configLinkStatus(host_a_name, switch_name, state)
    net.configLinkStatus(host_b_name, switch_name, state)


def link_down(net, mesh_links, host_a, host_b):
    """Bring down link between two hosts."""
    set_link_state(net, mesh_links, host_a, host_b, "down")


def link_up(net, mesh_links, host_a, host_b):
    """Bring up link between two hosts."""
    set_link_state(net, mesh_links, host_a, host_b, "up")


def pick_publish_link(mesh_links, publisher):
    """Find a link connected to the publisher host."""
    for link in mesh_links:
        if "hosts" in link:
            if publisher in link["hosts"]:
                for host in link["hosts"]:
                    if host != publisher:
                        return {
                            "host_a": publisher,
                            "host_b": host,
                            "switch": link["switch"],
                            "subnet": link["subnet"],
                        }
            continue
        if publisher in (link["host_a"], link["host_b"]):
            return link
    raise RuntimeError(f"publisher h{publisher} has no links")


def set_node_links_state(net, node_name, state):
    """Set state of all links connected to a node."""
    node = net.get(node_name)
    for link in net.links:
        if link.intf1.node == node:
            net.configLinkStatus(node.name, link.intf2.node.name, state)
        elif link.intf2.node == node:
            net.configLinkStatus(node.name, link.intf1.node.name, state)
