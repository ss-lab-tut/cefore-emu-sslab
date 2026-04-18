"""Unit tests for bridge helper functions (addressing scheme propagation)."""

from unittest.mock import MagicMock, patch, call

import pytest

from src.core.addressing import AddressingScheme
from src.runtime.bridge import _resolve_root_ip, setup_bridges


def _mesh_links_with_switch(switch_name="s1", subnet=3):
    return [
        {"switch": switch_name, "subnet": subnet, "hosts": [0, 1], "host_eth": {0: 0, 1: 0}},
    ]


# ---------------------------------------------------------------------------
# _resolve_root_ip
# ---------------------------------------------------------------------------

class TestResolveRootIP:
    def test_explicit_root_ip_returned_unchanged(self):
        result = _resolve_root_ip("s1", "10.0.0.1/24", _mesh_links_with_switch())
        assert result == "10.0.0.1/24"

    def test_auto_with_default_scheme(self):
        result = _resolve_root_ip("s1", "auto", _mesh_links_with_switch(subnet=3))
        assert result == "192.168.3.254/24"

    def test_auto_with_custom_scheme(self):
        scheme = AddressingScheme("172.20.0.0/16")
        result = _resolve_root_ip("s1", "auto", _mesh_links_with_switch(subnet=5), scheme=scheme)
        assert result == "172.20.5.254/24"

    def test_auto_unknown_switch_returns_original(self):
        result = _resolve_root_ip("s99", "auto", _mesh_links_with_switch("s1", subnet=3))
        assert result == "auto"

    def test_none_root_ip_no_match_returns_none(self):
        result = _resolve_root_ip("s1", None, [])
        assert result is None

    def test_scheme_none_fallback_to_default(self):
        result = _resolve_root_ip("s1", "auto", _mesh_links_with_switch(subnet=2), scheme=None)
        assert result == "192.168.2.254/24"


# ---------------------------------------------------------------------------
# setup_bridges — wiring test
# ---------------------------------------------------------------------------

class TestSetupBridgesSchemeWiring:
    """Verify that setup_bridges threads scheme down to _resolve_root_ip."""

    def test_custom_scheme_reaches_resolve_root_ip(self):
        """Mock _resolve_root_ip and check it receives the custom scheme."""
        scheme = AddressingScheme("172.20.0.0/16")
        bridge_configs = [
            {"switch": "s1", "root_ip": "auto", "local_routes": "172.20.0.0/16"},
        ]
        mesh_links = _mesh_links_with_switch("s1", subnet=3)
        net = MagicMock()
        bridge_manager = MagicMock()
        bridge_manager.connect_to_root_ns.return_value = None
        bridge_manager.enable_normal_flow.return_value = None

        with patch("src.runtime.bridge._resolve_root_ip", wraps=_resolve_root_ip) as mock_resolve:
            try:
                setup_bridges(net, bridge_manager, bridge_configs, 2, mesh_links, scheme=scheme)
            except Exception:
                pass  # BridgeManager internals may fail without real net — that's OK
            mock_resolve.assert_called_once_with("s1", "auto", mesh_links, scheme=scheme)

    def test_default_scheme_produces_192_168_address(self):
        """Without custom scheme, auto-resolved address stays 192.168.*."""
        bridge_configs = [
            {"switch": "s1", "root_ip": "auto", "local_routes": "192.168.3.0/24"},
        ]
        mesh_links = _mesh_links_with_switch("s1", subnet=3)
        net = MagicMock()
        bridge_manager = MagicMock()
        bridge_manager.connect_to_root_ns.return_value = None
        bridge_manager.enable_normal_flow.return_value = None

        resolved_ips = []

        def capture_resolve(switch_name, root_ip, ml, scheme=None):
            result = _resolve_root_ip(switch_name, root_ip, ml, scheme=scheme)
            resolved_ips.append(result)
            return result

        with patch("src.runtime.bridge._resolve_root_ip", side_effect=capture_resolve):
            try:
                setup_bridges(net, bridge_manager, bridge_configs, 2, mesh_links)
            except Exception:
                pass
        assert resolved_ips and resolved_ips[0] == "192.168.3.254/24"
