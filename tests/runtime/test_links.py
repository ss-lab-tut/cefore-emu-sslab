"""Unit tests for link state operations (src/runtime/links.py).

These operations mutate a live Mininet ``net`` object via
``net.configLinkStatus``/``net.get``/``net.links``. Since no Mininet
process is running in unit tests, ``net`` is a ``MagicMock()`` and the
assertions check the calls made against it rather than real network
effects. ``mininet.log.info`` writes directly to a stream that bypasses
``sys.stdout``, so ``capsys`` cannot observe it (verified in the 調査結果
1/3 conventions survey) — tests patch ``src.runtime.links.info`` instead.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.runtime.links import (
    find_link,
    link_down,
    link_up,
    set_link_state,
    set_node_links_state,
)


@pytest.fixture
def mesh_links():
    """Canonical mesh_links shape as emitted by MeshTopo (src/runtime/topo.py).

    Unlike conftest's ``sample_mesh_links`` (legacy host_a/host_b, no
    ``switch`` key), this carries the ``switch`` key that
    ``TopologyModel._normalize`` reads at src/core/topology.py:54. Without
    it, ``find_link`` would return a Link with ``switch=None`` and every
    assertion on the switch name in this file would be vacuous.
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


class TestFindLink:
    def test_finds_link_between_two_connected_hosts(self, mesh_links):
        """A link whose switch both hosts share is returned with that switch name."""
        link = find_link(mesh_links, 0, 1)
        assert link is not None
        assert link.switch == "s0"

    def test_returns_none_when_hosts_share_no_link(self, mesh_links):
        """Hosts on disjoint links (0 and 2 here) have no shared switch."""
        assert find_link(mesh_links, 0, 2) is None


class TestSetLinkState:
    def test_raises_runtime_error_when_link_not_found(self, mesh_links):
        """No shared switch between the hosts means there is nothing to toggle."""
        net = MagicMock()
        with pytest.raises(RuntimeError, match="link not found between h0 and h2"):
            set_link_state(net, mesh_links, 0, 2, "down")
        # The guard must fail before touching the network.
        net.configLinkStatus.assert_not_called()

    def test_configures_link_status_on_both_host_ends(self, mesh_links):
        """Both host names are told to change state via the shared switch."""
        net = MagicMock()
        set_link_state(net, mesh_links, 0, 1, "down")
        net.configLinkStatus.assert_any_call("h0", "s0", "down")
        net.configLinkStatus.assert_any_call("h1", "s0", "down")
        assert net.configLinkStatus.call_count == 2

    def test_logs_link_state_change(self, mesh_links):
        """The state change is logged via mininet.log.info (capsys-invisible)."""
        net = MagicMock()
        with patch("src.runtime.links.info") as mock_info:
            set_link_state(net, mesh_links, 0, 1, "down")
        mock_info.assert_called_with("link", "h0", "h1", "down", "\n")


class TestLinkDownUp:
    def test_link_down_sets_state_down(self, mesh_links):
        """link_down is set_link_state pinned to the 'down' state string."""
        net = MagicMock()
        link_down(net, mesh_links, 0, 1)
        net.configLinkStatus.assert_any_call("h0", "s0", "down")
        net.configLinkStatus.assert_any_call("h1", "s0", "down")

    def test_link_up_sets_state_up(self, mesh_links):
        """link_up is set_link_state pinned to the 'up' state string."""
        net = MagicMock()
        link_up(net, mesh_links, 0, 1)
        net.configLinkStatus.assert_any_call("h0", "s0", "up")
        net.configLinkStatus.assert_any_call("h1", "s0", "up")


class TestSetNodeLinksState:
    def _make_link(self, node_a, node_b):
        """Build a MagicMock resembling a Mininet Link with two named endpoints."""
        link = MagicMock()
        link.intf1.node = node_a
        link.intf1.node.name = node_a.name
        link.intf2.node = node_b
        link.intf2.node.name = node_b.name
        return link

    def test_matches_link_via_intf1(self):
        """When the target node sits on intf1, the peer (intf2) is toggled."""
        h0, s0 = MagicMock(name="h0"), MagicMock(name="s0")
        h0.name, s0.name = "h0", "s0"
        net = MagicMock()
        net.get.return_value = h0
        net.links = [self._make_link(h0, s0)]

        set_node_links_state(net, "h0", "down")

        net.configLinkStatus.assert_called_once_with("h0", "s0", "down")

    def test_matches_link_via_intf2(self):
        """When the target node sits on intf2, the peer (intf1) is toggled."""
        h0, s0 = MagicMock(name="h0"), MagicMock(name="s0")
        h0.name, s0.name = "h0", "s0"
        net = MagicMock()
        net.get.return_value = h0
        net.links = [self._make_link(s0, h0)]

        set_node_links_state(net, "h0", "up")

        net.configLinkStatus.assert_called_once_with("h0", "s0", "up")

    def test_no_configlinkstatus_call_when_no_link_matches(self):
        """Links not touching the target node are left untouched."""
        h0 = MagicMock(name="h0")
        h0.name = "h0"
        s0, s1 = MagicMock(name="s0"), MagicMock(name="s1")
        s0.name, s1.name = "s0", "s1"
        net = MagicMock()
        net.get.return_value = h0
        net.links = [self._make_link(s0, s1)]

        set_node_links_state(net, "h0", "down")

        net.configLinkStatus.assert_not_called()
