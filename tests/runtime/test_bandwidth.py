"""Unit tests for bandwidth control operations (src/runtime/bandwidth.py).

Like links.py, these functions drive a live Mininet ``net`` object, so the
tests substitute ``MagicMock()`` and assert on the calls made to it.
``mininet.log.info`` bypasses ``sys.stdout`` (capsys-invisible, per the
調査結果 1/3 conventions survey) so the "no shared switch" message is
verified via ``patch("src.runtime.bandwidth.info")`` instead.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.runtime.bandwidth import (
    parse_bw_args,
    set_link_bandwidth,
    set_switch_bandwidth,
)


@pytest.fixture
def mesh_links():
    """Canonical mesh_links shape as emitted by MeshTopo (src/runtime/topo.py).

    Carries the ``switch`` key that conftest's legacy ``sample_mesh_links``
    fixture omits — without it TopologyModel.find_link would hand back a
    Link with ``switch=None`` and set_switch_bandwidth's per-host loop
    would operate on a meaningless switch name.
    """
    return [
        {
            "switch": "s0",
            "subnet": "192.168.0.0/24",
            "hosts": [0, 1],
            "host_eth": {0: 0, 1: 0},
        },
    ]


class TestParseBwArgs:
    def test_parses_valid_node_pair_bandwidth_strings(self):
        """Each 'nodeA,nodeB,mbps' entry becomes a (str, str, float) tuple."""
        result = parse_bw_args(["h0,h1,10", "h1,h2,5.5"])
        assert result == [("h0", "h1", 10.0), ("h1", "h2", 5.5)]

    def test_returns_empty_list_for_none_or_empty_input(self):
        """No values means no bandwidth entries, not an error."""
        assert parse_bw_args(None) == []
        assert parse_bw_args([]) == []

    def test_raises_value_error_on_malformed_entry(self):
        """An entry without exactly 3 comma-separated parts is rejected."""
        with pytest.raises(ValueError, match="bw format is nodeA,nodeB,mbps"):
            parse_bw_args(["h0,h1"])


class TestSetLinkBandwidth:
    def test_configures_bandwidth_on_both_interfaces_of_every_link(self):
        """Every link between the two nodes gets both its interfaces reconfigured."""
        net = MagicMock()
        mock_link = MagicMock()
        net.linksBetween.return_value = [mock_link]

        set_link_bandwidth(net, "h0", "s0", 10.0)

        net.linksBetween.assert_called_once_with(net.get("h0"), net.get("s0"))
        mock_link.intf1.config.assert_called_once_with(bw=10.0)
        mock_link.intf2.config.assert_called_once_with(bw=10.0)

    def test_logs_bandwidth_change(self):
        """The bandwidth change is logged via mininet.log.info (capsys-invisible)."""
        net = MagicMock()
        net.linksBetween.return_value = [MagicMock()]
        with patch("src.runtime.bandwidth.info") as mock_info:
            set_link_bandwidth(net, "h0", "s0", 10.0)
        mock_info.assert_called_with("set bw 10.0 Mbps between h0 and s0\n")


class TestSetSwitchBandwidth:
    def test_sets_bandwidth_on_every_host_link_of_shared_switch_and_returns_true(
        self, mesh_links
    ):
        """Every host attached to the hosts' shared switch gets its link reconfigured."""
        net = MagicMock()
        mock_link = MagicMock()
        net.linksBetween.return_value = [mock_link]

        result = set_switch_bandwidth(net, mesh_links, 0, 1, 10.0)

        assert result is True
        # link.hosts == [0, 1], so set_link_bandwidth runs once per host against s0.
        net.linksBetween.assert_any_call(net.get("h0"), net.get("s0"))
        net.linksBetween.assert_any_call(net.get("h1"), net.get("s0"))
        assert mock_link.intf1.config.call_count == 2
        mock_link.intf1.config.assert_called_with(bw=10.0)

    def test_returns_false_and_logs_when_hosts_share_no_switch(self, mesh_links):
        """Hosts on disjoint links have nothing to configure and the caller is told."""
        net = MagicMock()
        with patch("src.runtime.bandwidth.info") as mock_info:
            result = set_switch_bandwidth(net, mesh_links, 0, 2, 10.0)

        assert result is False
        mock_info.assert_called_with("[bw] no shared switch between h0 and h2\n")
        net.linksBetween.assert_not_called()
