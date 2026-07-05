"""Unit tests for topology visualization utilities (src/runtime/viz.py).

Covers build_host_graph/build_tree (pure graph construction over
TopologyModel), print_mesh_links (ASCII + adjacency-matrix rendering),
render_topology_png (matplotlib/networkx figure generation), and
_ensure_topo_deps (lazy dependency import + memoization).

Like links.py/bandwidth.py, mininet.log.info bypasses sys.stdout and is
capsys-invisible (verified in the 調査結果 1/3 conventions survey), so
print_mesh_links/render_topology_png output is asserted via
``patch("src.runtime.viz.info")`` rather than capsys.

matplotlib is switched to the Agg backend lazily inside
_ensure_topo_deps, which is process-safe to call repeatedly (per plotter.py
precedent) — no test isolates or resets that global state.
"""

from unittest.mock import patch

import pytest

from src.runtime.viz import (
    _ensure_topo_deps,
    build_host_graph,
    build_tree,
    print_mesh_links,
    render_topology_png,
)


@pytest.fixture
def mesh_links():
    """Canonical mesh_links shape as emitted by MeshTopo (src/runtime/topo.py).

    Two links sharing host 1 as a hub, so build_host_graph/build_tree
    exercise a non-trivial adjacency (h0-h1 via s0, h1-h2 via s1) and
    render_topology_png draws more than a single edge.
    """
    return [
        {
            "switch": "s0",
            "subnet": "192.168.0.0/24",
            "hosts": [0, 1],
            "host_eth": {0: 0, 1: 0},
        },
        {
            "switch": "s1",
            "subnet": "192.168.1.0/24",
            "hosts": [1, 2],
            "host_eth": {1: 1, 2: 0},
        },
    ]


class TestBuildHostGraph:
    def test_builds_bidirectional_adjacency_and_switch_lookup(self, mesh_links):
        """Every link contributes both directions of adjacency plus a switch label."""
        graph, link_switch = build_host_graph(mesh_links)
        assert graph == {0: {1}, 1: {0, 2}, 2: {1}}
        assert link_switch[(0, 1)] == "s0"
        assert link_switch[(1, 2)] == "s1"

    def test_absorbs_legacy_host_a_host_b_shape(self, sample_mesh_links):
        """TopologyModel normalizes legacy host_a/host_b links the same way."""
        graph, _ = build_host_graph(sample_mesh_links)
        # sample_mesh_links (conftest) is a 0-1-2 triangle.
        assert graph == {0: {1, 2}, 1: {0, 2}, 2: {0, 1}}

    def test_empty_mesh_links_yields_empty_graph(self):
        """No links means no hosts to graph."""
        graph, link_switch = build_host_graph([])
        assert graph == {}
        assert link_switch == {}


class TestBuildTree:
    def test_builds_bfs_spanning_tree_from_root(self, mesh_links):
        """Root h1 reaches both neighbors directly; each becomes a childless leaf."""
        graph, _ = build_host_graph(mesh_links)
        children = build_tree(graph, 1)
        assert children == {1: [0, 2], 0: [], 2: []}

    def test_root_choice_changes_tree_shape_on_a_chain(self, mesh_links):
        """Rooting at an endpoint (h0) produces a linear chain instead of a star."""
        graph, _ = build_host_graph(mesh_links)
        children = build_tree(graph, 0)
        assert children == {0: [1], 1: [2], 2: []}

    def test_single_node_graph_has_no_children(self):
        """A root with no neighbors is its own whole tree."""
        children = build_tree({0: set()}, 0)
        assert children == {0: []}

    def test_diamond_graph_visits_each_node_exactly_once(self, diamond_graph):
        """BFS parent-assignment prevents a node from appearing under two parents."""
        children = build_tree(diamond_graph, 0)
        assert children[0] == [1, 2]
        # Node 3 is reachable via both 1 and 2, but BFS assigns it a single parent.
        all_children = [child for kids in children.values() for child in kids]
        assert all_children.count(3) == 1


class TestPrintMeshLinks:
    def test_prints_ascii_tree_branches_for_each_root(self, mesh_links):
        """Every host is printed as a tree root with `-- / |-- branch markers."""
        with patch("src.runtime.viz.info") as mock_info:
            print_mesh_links(mesh_links)
        calls = "".join(call.args[0] for call in mock_info.call_args_list)
        assert "h0" in calls
        assert "h1" in calls
        assert "h2" in calls
        # Single-child branches use the terminal marker `-- (no sibling follows).
        assert "`-- " in calls
        assert "via s0" in calls
        assert "via s1" in calls

    def test_prints_branch_marker_for_non_last_sibling(self):
        """A node with two children uses |-- for the first and `-- for the last."""
        # Star topology: h0 hub connected to h1 and h2 on the same switch.
        links = [
            {
                "switch": "s0",
                "subnet": "192.168.0.0/24",
                "hosts": [0, 1, 2],
                "host_eth": {0: 0, 1: 0, 2: 1},
            },
        ]
        with patch("src.runtime.viz.info") as mock_info:
            print_mesh_links(links)
        calls = "".join(call.args[0] for call in mock_info.call_args_list)
        assert "|-- " in calls
        assert "`-- " in calls

    def test_prints_adjacency_matrix_header_with_host_labels(self, mesh_links):
        """The matrix section is announced and headed by every host label."""
        with patch("src.runtime.viz.info") as mock_info:
            print_mesh_links(mesh_links)
        calls = "".join(call.args[0] for call in mock_info.call_args_list)
        assert "adjacency matrix" in calls
        assert "h0" in calls and "h1" in calls and "h2" in calls

    def test_adjacency_matrix_diagonal_uses_dot_placeholder(self, mesh_links):
        """A host's own row/column entry (no self-link) is rendered as '.'."""
        with patch("src.runtime.viz.info") as mock_info:
            print_mesh_links(mesh_links)
        calls = "".join(call.args[0] for call in mock_info.call_args_list)
        # The diagonal cell for a host against itself is a lone '.', distinct
        # from switch-name cells like 's0'/'s1'.
        assert "." in calls


class TestEnsureTopoDeps:
    def test_returns_true_and_populates_module_globals_on_success(self):
        """A successful import sets HAVE_TOPO_DEPS and caches nx/plt modules."""
        import src.runtime.viz as viz_module

        result = _ensure_topo_deps()
        assert result is True
        assert viz_module.HAVE_TOPO_DEPS is True
        assert viz_module._nx is not None
        assert viz_module._plt is not None

    def test_memoizes_after_first_successful_call(self):
        """A second call short-circuits on the cached module instead of re-importing."""
        import src.runtime.viz as viz_module

        _ensure_topo_deps()
        cached_nx = viz_module._nx
        result = _ensure_topo_deps()
        assert result is True
        # Same object identity confirms the early `if _nx is not None: return` path.
        assert viz_module._nx is cached_nx


class TestRenderTopologyPng:
    def test_renders_png_file_with_default_spring_layout(self, mesh_links, tmp_path):
        """Happy path: a canonical mesh renders a non-empty PNG at the given path."""
        output_path = tmp_path / "topo.png"
        render_topology_png(mesh_links, str(output_path))
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_renders_with_circular_layout(self, mesh_links, tmp_path):
        """The 'circular' layout branch also produces a valid PNG."""
        output_path = tmp_path / "topo_circular.png"
        render_topology_png(mesh_links, str(output_path), layout="circular")
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_renders_with_kamada_kawai_layout(self, mesh_links, tmp_path):
        """The 'kamada_kawai' layout branch succeeds when scipy is installed.

        scipy presence was verified in the venv before writing this test
        (`.venv/bin/python3 -c "import scipy"` succeeds) — per the plan's
        exclusion list, the ImportError fallback branch is not exercised.
        """
        output_path = tmp_path / "topo_kamada.png"
        render_topology_png(mesh_links, str(output_path), layout="kamada_kawai")
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_no_output_path_is_a_silent_no_op(self, mesh_links, tmp_path):
        """A falsy output_path returns before touching matplotlib at all."""
        with patch("src.runtime.viz.info") as mock_info:
            render_topology_png(mesh_links, None)
        mock_info.assert_not_called()

    def test_empty_mesh_links_skips_rendering_and_logs_reason(self, tmp_path):
        """No links means nothing to draw; the skip reason is logged, no file written."""
        output_path = tmp_path / "topo_empty.png"
        with patch("src.runtime.viz.info") as mock_info:
            render_topology_png([], str(output_path))
        assert not output_path.exists()
        mock_info.assert_called_with("topology PNG skipped (no links)\n")
