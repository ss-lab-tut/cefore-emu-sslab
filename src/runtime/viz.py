"""Visualization utilities for mesh topologies."""

from mininet.log import info

from ..core.topology import TopologyModel

# Lazy import for optional dependencies
HAVE_TOPO_DEPS = True
TOPO_DEPS_ERROR = None
_nx = None
_plt = None


def _ensure_topo_deps():
    """Lazy-load networkx and matplotlib."""
    global HAVE_TOPO_DEPS, TOPO_DEPS_ERROR, _nx, _plt
    if _nx is not None:
        return HAVE_TOPO_DEPS
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx

        _nx = nx
        _plt = plt
        HAVE_TOPO_DEPS = True
    except Exception as exc:
        HAVE_TOPO_DEPS = False
        TOPO_DEPS_ERROR = exc
    return HAVE_TOPO_DEPS


def build_host_graph(mesh_links):
    """Build adjacency graph from mesh links.

    Returns:
        Tuple of (graph dict, link_switch dict).
    """
    graph = {}
    link_switch = {}
    for host_a, host_b, link in TopologyModel(mesh_links).edges():
        graph.setdefault(host_a, set()).add(host_b)
        graph.setdefault(host_b, set()).add(host_a)
        link_switch[(host_a, host_b)] = link.switch
    return graph, link_switch


def build_tree(graph, root):
    """Build BFS tree from graph rooted at given node."""
    parent = {root: None}
    queue = [root]
    for node in queue:
        for neighbor in sorted(graph.get(node, [])):
            if neighbor not in parent:
                parent[neighbor] = node
                queue.append(neighbor)
    children = {node: [] for node in parent}
    for node, ancestor in parent.items():
        if ancestor is not None:
            children[ancestor].append(node)
    for node in children:
        children[node].sort()
    return children


def print_mesh_links(mesh_links):
    """Print ASCII visualization of mesh topology."""
    graph, link_switch = build_host_graph(mesh_links)
    info("\nMesh topology (per-host tree view):\n")
    for root in sorted(graph.keys()):
        info(f"h{root}\n")
        children = build_tree(graph, root)

        def walk(node, prefix):
            kids = children.get(node, [])
            for idx, child in enumerate(kids):
                last = idx == len(kids) - 1
                branch = "`-- " if last else "|-- "
                link_key = tuple(sorted((node, child)))
                switch_name = link_switch.get(link_key, "?")
                label = f"h{child} (via {switch_name})"
                info(f"{prefix}{branch}{label}\n")
                walk(child, prefix + ("    " if last else "|   "))

        walk(root, "")
        info("\n")

    info("> - Topology view as a single figure (adjacency matrix)\n")
    nodes = sorted(graph.keys())
    host_labels = [f"h{node}" for node in nodes]
    switch_labels = list(link_switch.values())
    cell_width = max(
        2,
        max((len(label) for label in host_labels), default=2),
        max((len(label) for label in switch_labels), default=2),
    )

    info("Mesh topology (adjacency matrix; cell = switch):\n")
    header = " " * (cell_width + 1) + " ".join(
        label.ljust(cell_width) for label in host_labels
    )
    info(f"{header}\n")

    for row_idx, node in enumerate(nodes):
        row = [host_labels[row_idx].ljust(cell_width)]
        for col_idx, other in enumerate(nodes):
            if row_idx == col_idx:
                row.append(".".ljust(cell_width))
                continue
            link_key = tuple(sorted((node, other)))
            switch_name = link_switch.get(link_key, ".")
            row.append(str(switch_name).ljust(cell_width))
        info(" ".join(row) + "\n")
    info("\n")


def render_topology_png(mesh_links, output_path, seed=None, layout="spring"):
    """Render topology to PNG image."""
    if not output_path:
        return
    if not _ensure_topo_deps():
        info(f"topology PNG skipped (missing deps): {TOPO_DEPS_ERROR}\n")
        return
    if not mesh_links:
        info("topology PNG skipped (no links)\n")
        return

    nx = _nx
    plt = _plt

    model = TopologyModel(mesh_links)
    host_num = model.host_count
    graph = nx.Graph()
    host_nodes = {f"h{idx}" for idx in range(host_num)}
    switch_nodes = set()

    for link in model.links:
        switch = str(link.switch)
        switch_nodes.add(switch)
        for host in link.hosts:
            graph.add_edge(f"h{host}", switch)

    graph.add_nodes_from(host_nodes)
    graph.add_nodes_from(switch_nodes)

    if layout == "kamada_kawai":
        try:
            pos = nx.kamada_kawai_layout(graph)
        except (ImportError, ModuleNotFoundError) as exc:
            info(
                "kamada_kawai layout requires scipy; "
                f"falling back to spring ({exc})\n"
            )
            pos = nx.spring_layout(graph, seed=seed)
    elif layout == "circular":
        pos = nx.circular_layout(graph)
    else:
        pos = nx.spring_layout(graph, seed=seed)

    fig, ax = plt.subplots(figsize=(10, 8))
    nx.draw_networkx_edges(graph, pos, ax=ax, width=1.2, alpha=0.6)
    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=sorted(host_nodes),
        node_color="#8ecae6",
        node_size=800,
        ax=ax,
    )
    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=sorted(switch_nodes),
        node_color="#b0bec5",
        node_shape="s",
        node_size=700,
        ax=ax,
    )
    nx.draw_networkx_labels(graph, pos, font_size=9, ax=ax)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    info(f"topology PNG saved to {output_path}\n")
