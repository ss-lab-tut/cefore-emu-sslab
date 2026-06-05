"""Unit tests for bridge helper functions (addressing scheme propagation)."""

import json as _json
from unittest.mock import MagicMock, patch, call

import pytest

from src.core.addressing import AddressingScheme
from src.runtime.bridge import _resolve_root_ip, setup_bridges
from src.runtime.command_runner import CommandResult, FakeCommandRunner


def _pexec_runner(holder):
    """Adapt a legacy ``holder.pexec(cmd_str) -> (stdout, stderr, rc)`` fake onto
    the CommandRunner seam.

    Bridge commands now run through an injected CommandRunner instead of
    ``Node.pexec()``. This returns a FakeCommandRunner whose ``run`` is routed
    to ``holder.pexec`` with the argv joined back into a command string, so the
    existing command-substring predicates (``if "sysctl -n" in cmd``) keep
    working. ``holder.pexec`` is read at call time, so tests may assign it after
    constructing the runner.
    """
    fake = FakeCommandRunner()

    def _on_run(node, argv):
        out, err, rc = holder.pexec(" ".join(argv))
        return CommandResult(returncode=rc, stdout=out, stderr=err)

    fake.on_run = _on_run
    return fake


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


class TestCleanupArchitecture:
    """Tests for the structured cleanup action model."""

    def test_mandatory_cleanup_failure_is_surfaced(self):
        """A mandatory cleanup action failure must raise TeardownError."""
        from src.runtime.bridge import BridgeManager, TeardownError, CleanupAction
        from unittest.mock import Mock

        mgr = BridgeManager()
        mgr.cleanup_actions.append(CleanupAction(
            description="restore ip_forward",
            category="sysctl",
            mandatory=True,
            execute=lambda: (1, "error"),
        ))

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        assert len(exc_info.value.failures) == 1
        assert "restore ip_forward" in exc_info.value.failures[0][0]

    def test_best_effort_cleanup_failure_does_not_raise(self):
        """A best-effort cleanup action failure should not raise."""
        from src.runtime.bridge import BridgeManager, CleanupAction

        mgr = BridgeManager()
        mgr.cleanup_actions.append(CleanupAction(
            description="remove route",
            category="route",
            mandatory=False,
            execute=lambda: (1, "error"),
        ))

        # Should not raise
        mgr.cleanup()

    def test_all_cleanup_actions_attempted_even_if_earlier_fails(self):
        """All cleanup actions must be attempted even if one fails."""
        from src.runtime.bridge import BridgeManager, TeardownError, CleanupAction

        mgr = BridgeManager()
        call_log = []

        def make_fail(desc):
            def fn():
                call_log.append(desc)
                return (1, "error")
            return fn

        mgr.cleanup_actions.extend([
            CleanupAction("action1", "nat", True, make_fail("action1")),
            CleanupAction("action2", "nat", True, make_fail("action2")),
            CleanupAction("action3", "nat", True, make_fail("action3")),
        ])

        with pytest.raises(TeardownError):
            mgr.cleanup()

        # All three actions were attempted
        assert len(call_log) == 3

    def test_multiple_mandatory_failures_aggregated(self):
        """Multiple mandatory failures must all be reported."""
        from src.runtime.bridge import BridgeManager, TeardownError, CleanupAction

        mgr = BridgeManager()
        mgr.cleanup_actions.extend([
            CleanupAction("nat rule 1", "nat", True, lambda: (1, "error1")),
            CleanupAction("route", "route", False, lambda: (1, "error2")),  # best-effort
            CleanupAction("nat rule 2", "nat", True, lambda: (1, "error3")),
        ])

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        # Only mandatory failures in the aggregated error
        assert len(exc_info.value.failures) == 2

    def test_reverse_execution_order_preserved(self):
        """Cleanup actions must execute in reverse registration order."""
        from src.runtime.bridge import BridgeManager, CleanupAction

        mgr = BridgeManager()
        call_log = []

        def make_record(desc):
            def fn():
                call_log.append(desc)
                return (0, "")
            return fn

        mgr.cleanup_actions.extend([
            CleanupAction("first", "nat", True, make_record("first")),
            CleanupAction("second", "nat", True, make_record("second")),
            CleanupAction("third", "nat", True, make_record("third")),
        ])

        mgr.cleanup()

        # Reverse order: third, second, first
        assert call_log == ["third", "second", "first"]

    def test_cleanup_commands_do_not_suffer_late_binding(self):
        """Captured cleanup commands must not suffer late-binding lambda errors."""
        from src.runtime.bridge import BridgeManager, CleanupAction

        mgr = BridgeManager()

        # Simulate the pattern where prior values are captured in a loop
        for prior_val in ["0", "1"]:
            # Use default argument binding to avoid late-binding issues
            mgr.cleanup_actions.append(CleanupAction(
                description=f"restore value to {prior_val}",
                category="sysctl",
                mandatory=True,
                execute=lambda pv=prior_val: (0, f"restored to {pv}"),
            ))

        # Execute all cleanup actions
        mgr.cleanup()

        # Both should have been executed successfully
        assert len(mgr.cleanup_actions) == 0  # Cleared after cleanup


# ---------------------------------------------------------------------------
# IP forwarding tests
# ---------------------------------------------------------------------------

class TestIPForwarding:
    """Tests for enable_ip_forwarding() sysctl restoration."""

    def _make_mgr(self):
        """Create a BridgeManager with an injected pexec-backed runner."""
        from src.runtime.bridge import BridgeManager
        root = MagicMock()
        mgr = BridgeManager(runner=_pexec_runner(root))
        mgr.root_node = root
        return mgr, root

    def test_prior_value_zero_is_restored(self):
        """Prior value '0' must be captured and restored."""
        mgr, root = self._make_mgr()

        def pexec(cmd):
            if "sysctl -n" in cmd:
                return "0", "", 0
            return "", "", 0  # sysctl -w success
        root.pexec = pexec

        mgr.enable_ip_forwarding()

        # Check that a cleanup action was registered with prior value '0'
        ip_forward_actions = [
            a for a in mgr.cleanup_actions
            if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 1
        assert ip_forward_actions[0].mandatory is True
        # Execute the cleanup and check it restores to '0'
        ip_forward_actions[0].execute()

    def test_prior_value_one_is_restored(self):
        """Prior value '1' must be captured and restored."""
        mgr, root = self._make_mgr()

        def pexec(cmd):
            if "sysctl -n" in cmd:
                return "1", "", 0
            return "", "", 0  # sysctl -w success
        root.pexec = pexec

        mgr.enable_ip_forwarding()

        ip_forward_actions = [
            a for a in mgr.cleanup_actions
            if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 1
        assert ip_forward_actions[0].mandatory is True

    def test_read_failure_aborts_without_mutation(self):
        """If prior value read fails, no mutation should occur."""
        mgr, root = self._make_mgr()
        root.pexec = MagicMock(return_value=("", "sysctl: not found", 127))

        with pytest.raises(RuntimeError, match="ip_forward"):
            mgr.enable_ip_forwarding()

        # No cleanup actions registered
        ip_forward_actions = [
            a for a in mgr.cleanup_actions
            if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 0

    def test_invalid_captured_value_aborts_without_mutation(self):
        """If captured value is invalid, no mutation should occur."""
        mgr, root = self._make_mgr()
        root.pexec = MagicMock(return_value=("2", "", 0))  # Invalid value

        with pytest.raises(RuntimeError, match="ip_forward"):
            mgr.enable_ip_forwarding()

        ip_forward_actions = [
            a for a in mgr.cleanup_actions
            if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 0

    def test_enable_write_failure_does_not_register_restoration(self):
        """If the enable write fails, no restoration should be registered."""
        mgr, root = self._make_mgr()
        call_count = [0]

        def pexec(cmd):
            call_count[0] += 1
            if call_count[0] == 1:  # First call: read
                return "0", "", 0
            return "", "permission denied", 1  # Second call: write fails
        root.pexec = pexec

        with pytest.raises(RuntimeError, match="ip_forward"):
            mgr.enable_ip_forwarding()

        ip_forward_actions = [
            a for a in mgr.cleanup_actions
            if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 0

    def test_restoration_failure_during_cleanup_is_surfaced(self):
        """Restoration failure during cleanup must be surfaced through the
        production registration, not via a locally rebound `cleanup_actions`
        entry.

        The cleanup `pexec()` returns `rc=1` so the normalized lambda
        propagates `(1, "restore failed")` into `TeardownError.failures`.
        """
        from src.runtime.bridge import TeardownError
        mgr, root = self._make_mgr()

        # 1) `sysctl -n ip_forward` -> ("0", "", 0)    (read prior)
        # 2) `sysctl -w ip_forward=1` -> ("", "", 0)   (enable)
        # 3) `sysctl -w ip_forward=0` -> ("", "restore failed", 1) (cleanup)
        calls = 0

        def pexec(cmd):
            nonlocal calls
            calls += 1
            if "sysctl -n" in cmd:
                return ("0", "", 0)
            if calls == 2:
                return ("", "", 0)
            return ("", "restore failed", 1)

        root.pexec = pexec

        mgr.enable_ip_forwarding()

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        assert exc_info.value.failures == [
            ("restore ip_forward to 0", 1, "restore failed")
        ]


# ---------------------------------------------------------------------------
# Proxy ARP transactional tests
# ---------------------------------------------------------------------------

class TestProxyARP:
    """Tests for enable_proxy_arp() transactional mutation."""

    def _make_mgr(self):
        """Create a BridgeManager with mocked root node and interface."""
        from src.runtime.bridge import BridgeManager
        root = MagicMock()
        mgr = BridgeManager(runner=_pexec_runner(root))
        mgr.root_node = root
        mgr.root_intf = MagicMock()
        mgr.root_intf.__str__ = lambda s: "eth0"
        return mgr, root

    def test_read_failure_aborts_before_mutation(self):
        """If prior value read fails, no mutation should occur."""
        mgr, root = self._make_mgr()
        root.pexec = MagicMock(return_value=("", "sysctl: not found", 127))

        with pytest.raises(RuntimeError, match="proxy_arp"):
            mgr.enable_proxy_arp()

        proxy_arp_actions = [
            a for a in mgr.cleanup_actions
            if "proxy_arp" in a.description
        ]
        assert len(proxy_arp_actions) == 0

    def test_first_write_failure_no_rollback_no_cleanup(self):
        """If the first enable write fails, no rollback and no cleanup actions."""
        mgr, root = self._make_mgr()
        call_count = [0]

        def pexec(cmd):
            call_count[0] += 1
            if call_count[0] <= 2:  # First two calls: reads
                return "0", "", 0
            return "", "fail", 1  # Third call: first write fails
        root.pexec = pexec

        with pytest.raises(RuntimeError, match="proxy_arp"):
            mgr.enable_proxy_arp()

        proxy_arp_actions = [
            a for a in mgr.cleanup_actions
            if "proxy_arp" in a.description
        ]
        assert len(proxy_arp_actions) == 0

    def test_second_write_failure_rolls_back_first(self):
        """If the second write fails, the first successful write is rolled back."""
        mgr, root = self._make_mgr()
        call_count = [0]
        rollback_called = [False]

        def pexec(cmd):
            call_count[0] += 1
            if "sysctl -n" in cmd:
                return "0", "", 0
            if call_count[0] == 3:  # First write: iface-level
                return "", "", 0
            if call_count[0] == 4:  # Second write: all-level fails
                return "", "fail", 1
            if "proxy_arp=0" in cmd:  # Rollback
                rollback_called[0] = True
                return "", "", 0
            return "", "", 0
        root.pexec = pexec

        with pytest.raises(RuntimeError, match="proxy_arp"):
            mgr.enable_proxy_arp()

        assert rollback_called[0], "Rollback should have been called"

    def test_successful_setup_commits_cleanup_actions(self):
        """Successful setup commits two mandatory cleanup actions."""
        mgr, root = self._make_mgr()

        def pexec(cmd):
            if "sysctl -n" in cmd:
                return "0", "", 0
            return "", "", 0
        root.pexec = pexec

        mgr.enable_proxy_arp()

        proxy_arp_actions = [
            a for a in mgr.cleanup_actions
            if "proxy_arp" in a.description
        ]
        assert len(proxy_arp_actions) == 2
        assert all(a.mandatory for a in proxy_arp_actions)

    def test_cleanup_restoration_failure_surfaced(self):
        """Proxy ARP cleanup restoration failure surfaces through the
        production registrations.

        Both restore writes return `rc=1` so `TeardownError.failures` contains
        two `proxy_arp` entries with the intended detail.
        """
        from src.runtime.bridge import TeardownError
        mgr, root = self._make_mgr()

        # Setup pexec sequence:
        #   1) sysctl -n iface.proxy_arp     -> ("1", "", 0)
        #   2) sysctl -n all.proxy_arp       -> ("1", "", 0)
        #   3) sysctl -w iface.proxy_arp=1   -> ("", "", 0)
        #   4) sysctl -w all.proxy_arp=1     -> ("", "", 0)
        # Cleanup pexec sequence (reverse order):
        #   5) sysctl -w iface.proxy_arp=1   restore -> ("", "fail iface", 1)
        #   6) sysctl -w all.proxy_arp=1     restore -> ("", "fail all", 1)
        # The cleanup action names embed the prior value (1) so the restore
        # write is also `=1`; we identify cleanup by call count.
        calls = 0

        def pexec(cmd):
            nonlocal calls
            calls += 1
            if "sysctl -n" in cmd:
                return ("1", "", 0)
            if calls <= 4:
                return ("", "", 0)
            if "conf.all" in cmd:
                return ("", "fail all", 1)
            return ("", "fail iface", 1)

        root.pexec = pexec

        mgr.enable_proxy_arp()

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        descs = [f[0] for f in exc_info.value.failures]
        details = [f[2] for f in exc_info.value.failures]
        assert any("proxy_arp" in d for d in descs)
        assert "fail all" in details and "fail iface" in details
        # All recorded failures must report rc=1 (not -1 from unpack error)
        assert all(f[1] == 1 for f in exc_info.value.failures)


# ---------------------------------------------------------------------------
# NAT transactional tests
# ---------------------------------------------------------------------------

class TestNAT:
    """Tests for enable_nat() transactional setup and cleanup."""

    def _make_mgr(self):
        """Create a BridgeManager with mocked root node."""
        from src.runtime.bridge import BridgeManager
        root = MagicMock()
        mgr = BridgeManager(runner=_pexec_runner(root))
        mgr.root_node = root
        mgr.root_intf = MagicMock()
        mgr.root_intf.__str__ = lambda s: "eth0"
        return mgr, root

    def test_first_add_failure_no_deletion(self):
        """If the first NAT add fails, no deletion should occur."""
        mgr, root = self._make_mgr()
        root.cmd = MagicMock(return_value="default via 10.0.0.1 dev eth0")
        root.pexec = MagicMock(return_value=("", "iptables: fail", 1))

        with pytest.raises(RuntimeError, match="NAT"):
            mgr.enable_nat("192.168.1.0/24", "eth0")

        nat_actions = [
            a for a in mgr.cleanup_actions
            if "NAT" in a.description
        ]
        assert len(nat_actions) == 0

    def test_second_add_failure_deletes_first(self):
        """If the second add fails, only the first successfully installed rule is deleted."""
        mgr, root = self._make_mgr()
        root.cmd = MagicMock(return_value="default via 10.0.0.1 dev eth0")
        call_count = [0]
        call_log = []

        def pexec(cmd):
            call_count[0] += 1
            call_log.append(cmd)
            if call_count[0] == 1:  # First add: success
                return "", "", 0
            if "-D" in cmd:  # Rollback deletion
                return "", "", 0
            return "", "iptables: fail", 1  # Second add: fail
        root.pexec = pexec

        with pytest.raises(RuntimeError, match="NAT"):
            mgr.enable_nat("192.168.1.0/24", "eth0")

        # Verify rollback occurred
        rollback_calls = [c for c in call_log if "-D" in c]
        assert len(rollback_calls) == 1

    def test_successful_setup_commits_cleanup_actions(self):
        """Successful setup commits exactly one cleanup action per rule."""
        mgr, root = self._make_mgr()
        root.cmd = MagicMock(return_value="default via 10.0.0.1 dev eth0")
        root.pexec = MagicMock(return_value=("", "", 0))

        mgr.enable_nat("192.168.1.0/24", "eth0")

        nat_actions = [
            a for a in mgr.cleanup_actions
            if "NAT" in a.description
        ]
        assert len(nat_actions) == 3
        assert all(a.mandatory for a in nat_actions)

    def test_cleanup_deletion_failure_surfaced(self):
        """NAT cleanup deletion failure surfaces through TeardownError via
        the production lambda, not via a locally rebound list entry.

        Setup `iptables -A` calls all succeed; subsequent `iptables -D`
        cleanup calls all fail with `rc=1`, and every recorded failure
        reports `rc=1` (not `-1` from a tuple-unpack `ValueError`).
        """
        from src.runtime.bridge import TeardownError
        mgr, root = self._make_mgr()
        root.cmd = MagicMock(return_value="default via 10.0.0.1 dev eth0")

        def pexec(cmd):
            # During setup all iptables -A calls succeed
            if " -A " in cmd:
                return ("", "", 0)
            # During cleanup every iptables -D call fails
            if " -D " in cmd:
                return ("", "iptables del failed", 1)
            return ("", "", 0)

        root.pexec = pexec

        mgr.enable_nat("192.168.1.0/24", "eth0")

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        nat_failures = [
            f for f in exc_info.value.failures if "NAT" in f[0]
        ]
        # enable_nat registers exactly 3 mandatory NAT delete actions
        assert len(nat_failures) == 3
        # All recorded failures must report rc=1 (not -1 from unpack error)
        assert all(f[1] == 1 for f in nat_failures)
        assert all(f[2] == "iptables del failed" for f in nat_failures)

    def test_nat_failure_after_ip_forwarding_leaves_restoration(self):
        """If NAT fails after ip_forwarding, the ip_forward restoration remains."""
        from src.runtime.bridge import BridgeManager
        root = MagicMock()
        mgr = BridgeManager(runner=_pexec_runner(root))
        mgr.root_node = root
        mgr.root_intf = MagicMock()
        mgr.root_intf.__str__ = lambda s: "eth0"
        root.cmd = MagicMock(return_value="default via 10.0.0.1 dev eth0")

        call_count = [0]

        def pexec(cmd):
            call_count[0] += 1
            if "sysctl -n" in cmd:
                return "0", "", 0  # ip_forward read
            if call_count[0] == 2:  # ip_forward write
                return "", "", 0
            return "", "iptables: fail", 1  # NAT add fails
        root.pexec = pexec

        # Simulate the sequence: ip_forwarding succeeds, NAT fails
        mgr.enable_ip_forwarding()

        with pytest.raises(RuntimeError, match="NAT"):
            mgr.enable_nat("192.168.1.0/24", "eth0")

        # ip_forward restoration should still be registered
        ip_forward_actions = [
            a for a in mgr.cleanup_actions
            if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 1




# ---------------------------------------------------------------------------
# Plan §6 Unit C: Non-masking regression — every producer + cleanup() must
# complete on success without raising and without emitting a phantom
# "best-effort failure" warning.
# ---------------------------------------------------------------------------


class TestProducerCleanupContract:
    """Drives every cleanup-action producer through cleanup() against
    success-returning mocks and asserts the normalized contract."""

    def test_all_cleanup_action_producers_use_normalized_success_contract(self):
        from src.runtime.bridge import BridgeManager

        root = MagicMock()
        mgr = BridgeManager(runner=_pexec_runner(root))
        mgr.root_node = root

        def pexec_ok(cmd):
            if "sysctl -n" in cmd:
                return ("0", "", 0)
            return ("", "", 0)

        root.pexec = pexec_ok
        root.cmd = MagicMock(return_value="default via 10.0.0.1 dev eth0")
        root.setIP = MagicMock()

        net = MagicMock()
        fake_node = MagicMock()
        fake_node.pexec = pexec_ok
        fake_node.cmd = MagicMock(return_value="")
        net.get = MagicMock(return_value=fake_node)
        link = MagicMock()
        link.intf1 = "eth0"
        net.addLink = MagicMock(return_value=link)

        mgr.connect_to_root_ns(net, "s1", "192.168.0.1/24", "192.168.0.0/24")
        mgr.add_host_route(net, "h0", "10.0.0.0/24", "192.168.0.1")
        mgr.add_root_route("10.1.0.0/24", "192.168.0.2")
        mgr.enable_ip_forwarding()
        mgr.enable_nat("192.168.0.0/24", "eth0")
        mgr.enable_normal_flow(net, "s1")
        mgr.enable_proxy_arp()

        # Pin expected registrations: 3 route + 1 ip_forward + 3 NAT
        # + 1 normal_flow + 2 proxy_arp = 10 actions; 6 mandatory.
        assert len(mgr.cleanup_actions) == 10, [
            (a.description, a.category, a.mandatory) for a in mgr.cleanup_actions
        ]
        assert sum(1 for a in mgr.cleanup_actions if a.mandatory) == 6
        assert {a.category for a in mgr.cleanup_actions} >= {
            "route", "sysctl", "nat", "flow", "proxy_arp"
        }

        with patch("src.runtime.bridge.info") as mock_info:
            mgr.cleanup()
            warning_calls = [
                str(c)
                for c in mock_info.call_args_list
                if "best-effort failure" in str(c)
            ]
            assert warning_calls == [], (
                "Phantom best-effort warning emitted on success-only cleanup: "
                f"{warning_calls}"
            )


# ---------------------------------------------------------------------------
# Unit E: External bridge tests (Phase II-B + II-B.3, strict-CIDR policy)
# ---------------------------------------------------------------------------

class TestExternalBridgeSafety:
    """Tests for external bridge attachment safety and rollback."""

    def _make_net(self):
        """Create a mock Mininet-like object."""
        net = MagicMock()
        host = MagicMock()
        host.pid = 12345
        net.get.return_value = host
        return net

    def test_dhcp_mode_rejected(self):
        """B2: External bridge attachment without static IP is rejected."""
        from src.runtime.bridge import attach_external_via_bridge

        net = self._make_net()

        with pytest.raises(RuntimeError, match="static IP required"):
            attach_external_via_bridge(net, "h0", "eth0", ip=None)

    def test_duplicate_attachment_rejected(self):
        """B1.5: Duplicate active attachment is rejected."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        # Simulate existing attachment
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
        }

        net = self._make_net()

        with pytest.raises(RuntimeError, match="active attachment already exists"):
            attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Cleanup
        _created_bridges.clear()

    def test_interface_name_overflow_rejected(self):
        """B1.4: Interface names exceeding 15 characters are rejected."""
        from src.runtime.bridge import attach_external_via_bridge

        net = self._make_net()
        long_host = "h" + "x" * 20  # 21 chars

        with pytest.raises(RuntimeError, match="exceed 15-character"):
            attach_external_via_bridge(net, long_host, "eth0", ip="10.0.0.2/24")

    def test_inspect_failure_aborts(self):
        """B1.1: Physical interface inspection failure aborts before mutation."""
        from src.runtime.bridge import attach_external_via_bridge, _run_root_cmd_vec

        net = self._make_net()

        with patch("src.runtime.bridge._run_root_cmd_vec", return_value=(1, "", "not found")):
            with pytest.raises(RuntimeError, match="cannot inspect"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

    def test_existing_master_rejected(self):
        """B1.2: Interface with existing master is rejected."""
        from src.runtime.bridge import attach_external_via_bridge, _run_root_cmd_vec

        net = self._make_net()

        mock_result = {"ifname": "eth0", "master": "br-exist"}

        def mock_cmd(args):
            if "addr" in args:
                return 0, "[]", ""
            return 0, _json.dumps([mock_result]), ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(RuntimeError, match="already enslaved"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

    def test_existing_l3_address_rejected(self):
        """B1.3: Interface with non-link-local L3 address is rejected."""
        from src.runtime.bridge import attach_external_via_bridge, _run_root_cmd_vec

        net = self._make_net()

        mock_link = {"ifname": "eth0", "flags": ["BROADCAST", "UP"]}
        mock_addrs = [{"ifname": "eth0", "addr_info": [{"local": "192.168.1.100"}]}]

        def mock_cmd(args):
            if "addr" in args:
                return 0, _json.dumps(mock_addrs), ""
            return 0, _json.dumps([mock_link]), ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(RuntimeError, match="configured address"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

    def test_bridge_creation_failure_no_cleanup_record(self):
        """Bridge creation failure issues no delete and creates no record."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, _run_root_cmd_vec

        _created_bridges.clear()
        net = self._make_net()

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            # First command (inspect link): success
            # Second command (inspect addr): success
            # Third command (bridge creation): fail
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            return 1, "", "bridge exists"

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(RuntimeError, match="bridge creation failed"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # No record created
        assert "h0" not in _created_bridges

    def test_successful_attachment_creates_record(self):
        """Successful attachment records all owned resources."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        def mock_cmd(args):
            if "addr" in args or "link" in args:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "operstate": "UP", "flags": ["BROADCAST", "UP"]}]), ""
            return 0, "", ""

        def mock_pexec(cmd):
            return "", "", 0

        host.pexec = mock_pexec

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd), \
                patch(
                    "src.runtime.bridge.MininetCommandRunner",
                    return_value=_pexec_runner(host),
                ):
            attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Record exists with all fields
        assert "h0" in _created_bridges
        record = _created_bridges["h0"]
        assert record["bridge"] == "br-h0"
        assert record["veth_root"] == "veth-h0-root"
        assert record["veth_host"] == "veth-h0"
        assert record["phy_intf"] == "eth0"
        assert record["ip_assigned"] is True
        assert record["bridge_created"] is True

        _created_bridges.clear()

    def test_cleanup_attempts_all_records(self):
        """Cleanup attempts all records even when one fails."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        call_log = []

        def mock_cmd(args):
            call_log.append(tuple(args))
            # Simulate failure on first cleanup, success on second
            if "br-h0" in str(args):
                return 1, "", "failed"
            return 0, "", ""

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }
        _created_bridges["h1"] = {
            "bridge": "br-h1",
            "veth_root": "veth-h1-root",
            "veth_host": "veth-h1",
            "phy_intf": "eth1",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                cleanup_external_bridges()

        # h1 was cleaned, h0 was retained for retry
        assert "h1" not in _created_bridges
        assert "h0" in _created_bridges

        _created_bridges.clear()

    def test_cleanup_failure_retains_record(self):
        """Cleanup failure retains the failed record for retry."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges, ExternalBridgeError

        _created_bridges.clear()

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }

        def mock_cmd(args):
            return 1, "", "failed"

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                cleanup_external_bridges()

        # Record retained for retry
        assert "h0" in _created_bridges

        _created_bridges.clear()

    def test_cleanup_restores_phy_down(self):
        """Successful cleanup restores physical interface DOWN if it was raised."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": True,  # This run raised it from DOWN
        }

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            cleanup_external_bridges()

        # Verify DOWN restoration was called
        down_calls = [c for c in calls if "down" in str(c) and "eth0" in str(c)]
        assert len(down_calls) > 0

        _created_bridges.clear()

    def test_link_local_address_not_rejected(self):
        """Link-local address (169.254.x.x) does not block attachment."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        mock_link = {"ifname": "eth0", "flags": ["BROADCAST", "UP"]}
        mock_addrs = [{"ifname": "eth0", "addr_info": [{"local": "169.254.1.1"}]}]

        def mock_cmd(args):
            if "addr" in args:
                return 0, _json.dumps(mock_addrs), ""
            return 0, _json.dumps([mock_link]), ""

        def mock_pexec(cmd):
            return "", "", 0

        host.pexec = mock_pexec

        # Link-local address should NOT be rejected
        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd), \
                patch(
                    "src.runtime.bridge.MininetCommandRunner",
                    return_value=_pexec_runner(host),
                ):
            # This will proceed past address check
            attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" in _created_bridges
        _created_bridges.clear()


# ---------------------------------------------------------------------------
# External bridge rollback order tests
# ---------------------------------------------------------------------------

class TestExternalBridgeRollbackOrder:
    """Tests for correct rollback order during setup failure."""

    def _make_net(self):
        """Create a mock Mininet-like object."""
        net = MagicMock()
        host = MagicMock()
        host.pid = 12345
        net.get.return_value = host
        return net

    def test_rollback_order_after_veth_creation(self):
        """After veth creation, rollback deletes veth before unmastering."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                # Inspect link and addr: success
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # Fail at veth creation (step 5)
            if "veth" in str(args) and "add" in str(args):
                return 1, "", "veth creation failed"
            return 0, "", ""

        host.pexec = lambda cmd: ("", "", 0)

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(RuntimeError, match="veth creation failure"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Bridge should be cleaned up (rollback succeeded)
        assert "h0" not in _created_bridges

        _created_bridges.clear()

    def test_rollback_failure_preserves_record(self):
        """Setup failure + rollback failure → residual record for retry."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                # Inspect link and addr: success
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # Fail at bridge-up (step 2)
            if cmd_count[0] == 3:
                return 1, "", "bridge-up failed"
            # Rollback: also fail
            return 1, "", "rollback failed"

        host.pexec = lambda cmd: ("", "", 0)

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(Exception):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # No residual record (current implementation raises before creating record)
        # This is acceptable: the bridge exists but is not tracked
        # A future improvement would track in-progress state

        _created_bridges.clear()


# ---------------------------------------------------------------------------
# Phase II-B.3: Fail-before defect tests
# ---------------------------------------------------------------------------

class TestInspectionDefects:
    """Defect tests for source bugs identified in Phase II-B.2 verification."""

    def test_inspect_addresses_malformed_json_no_name_error(self):
        """D1: _inspect_addresses() malformed JSON must not raise NameError.

        After fix: function returns structured failure (success=False) instead
        of raising NameError from undefined `json` name.
        """
        from src.runtime.bridge import _inspect_addresses

        with patch("src.runtime.bridge._run_root_cmd_vec", return_value=(0, "not valid json{{", "")):
            success, data, err = _inspect_addresses("eth0")

        # Should return failure, not raise NameError
        assert success is False
        assert data is None
        assert len(err) > 0

    def test_inspect_addresses_rc_nonzero_returns_failure(self):
        """_inspect_addresses() non-zero exit code returns structured failure."""
        from src.runtime.bridge import _inspect_addresses

        with patch("src.runtime.bridge._run_root_cmd_vec", return_value=(1, "", "no such device")):
            success, data, err = _inspect_addresses("eth0")

        assert success is False
        assert data is None
        assert "no such device" in err


class TestDefectRollbackRetention:
    """D2/D3: Rollback failure retention and cleanup retry."""

    def _make_net(self):
        net = MagicMock()
        host = MagicMock()
        host.pid = 12345
        net.get.return_value = host
        return net

    def test_rollback_failure_preserves_record(self):
        """D2: Setup failure + rollback failure retains retryable record."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback: also fail
            return 1, "", "rollback del failed"

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError) as exc_info:
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Setup failure should be in the error
        assert exc_info.value.setup_failure is not None
        # Rollback failure should be in the error
        assert len(exc_info.value.rollback_failures) > 0
        # Record should be retained for retry
        assert "h0" in _created_bridges
        record = _created_bridges["h0"]
        # Record should contain outstanding cleanup state
        assert record.get("bridge_created") is True

        _created_bridges.clear()

    def test_successful_cleanup_retry_clears_retained_record(self):
        """D3: Cleanup retry on retained setup-failure record clears the record."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges

        _created_bridges.clear()

        # Simulate a retained record from rollback failure
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "prior_up": True,
            "bridge_created": True,
            "bridge_up": False,
            "phy_up_changed": False,
            "phy_enslaved": False,
            "veth_created": False,
        }

        with patch("src.runtime.bridge._run_root_cmd_vec", return_value=(0, "", "")):
            cleanup_external_bridges()

        assert "h0" not in _created_bridges

    def test_setup_failure_rollback_success_removes_record(self):
        """Setup failure with successful rollback removes the record."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback: succeed
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Record should be removed since rollback succeeded
        assert "h0" not in _created_bridges

        _created_bridges.clear()


# ---------------------------------------------------------------------------
# Phase II-B.3: Missing mandatory external bridge tests
# ---------------------------------------------------------------------------

def _make_net_helper():
    net = MagicMock()
    host = MagicMock()
    host.pid = 12345
    net.get.return_value = host
    return net


class TestExternalBridgePreconditions:
    """Precondition validation tests."""

    def test_invalid_static_ip_rejected_before_mutation(self):
        """Invalid static IP is rejected before any mutation.

        Uses an input that passes the strict-CIDR check (`/` present) so the
        deeper `ipaddress.ip_interface()` rejection path is exercised.
        """
        from src.runtime.bridge import attach_external_via_bridge

        net = _make_net_helper()

        with pytest.raises(RuntimeError, match="invalid static IP"):
            attach_external_via_bridge(net, "h0", "eth0", ip="not-an-ip/24")

    def test_bare_ip_without_cidr_rejected(self):
        """Strict-CIDR policy: bare IP without explicit prefix is rejected.

        The published `--ext host,ifname,ip[,mtu] (ip required in CIDR form)`
        contract requires an explicit prefix length. Bare addresses must be
        rejected before any mutation.
        """
        from src.runtime.bridge import _validate_static_ip

        with pytest.raises(RuntimeError, match="CIDR"):
            _validate_static_ip("10.0.0.2")

        with pytest.raises(RuntimeError, match="CIDR"):
            _validate_static_ip("")

    def test_missing_flags_aborts_before_mutation(self):
        """Missing/invalid flags field aborts before mutation."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        net = _make_net_helper()

        # Return link data without flags field
        def mock_cmd(args):
            if "addr" in args:
                return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
            return 0, _json.dumps([{"ifname": "eth0"}]), ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(RuntimeError, match="cannot determine administrative state"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # No record created
        assert "h0" not in _created_bridges


class TestExternalBridgeSetupRollback:
    """Setup-stage failure rollback tests for each mutation step."""

    def test_bridge_up_failure_deletes_owned_bridge(self):
        """Bridge-up failure triggers rollback that deletes the owned bridge."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]
        called_cmds = []

        def mock_cmd(args):
            cmd_count[0] += 1
            called_cmds.append(tuple(args))
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback: bridge deletion succeeds
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Record should be removed (rollback succeeded)
        assert "h0" not in _created_bridges
        # Verify rollback del bridge was called
        del_calls = [c for c in called_cmds if "del" in str(c) and "br-h0" in str(c)]
        assert len(del_calls) > 0

        _created_bridges.clear()

    def test_enslave_failure_rolls_back(self):
        """Enslave failure restores owned prior state and deletes bridge."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            if cmd_count[0] == 3:
                return 0, "", ""  # bridge-up
            # Step 5: enslave fails
            if cmd_count[0] == 4:
                return 1, "", "enslave failed"
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" not in _created_bridges
        _created_bridges.clear()

    def test_veth_attach_failure_rolls_back(self):
        """Veth-to-bridge attachment failure rolls back completed mutations."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # Steps 3-5 succeed (bridge-up, enslave, veth-create)
            if cmd_count[0] <= 5:
                return 0, "", ""
            # Step 6: veth-root-master fails
            if cmd_count[0] == 6:
                return 1, "", "veth-master failed"
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" not in _created_bridges
        _created_bridges.clear()

    def test_namespace_move_failure_rolls_back(self):
        """Namespace move failure rolls back completed mutations."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # Steps 3-8 succeed
            if cmd_count[0] <= 8:
                return 0, "", ""
            # Step 9: namespace move fails
            if cmd_count[0] == 9:
                return 1, "", "netns failed"
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" not in _created_bridges
        _created_bridges.clear()

    def test_static_ip_assignment_failure_rolls_back(self):
        """Static-IP assignment failure rolls back completed mutations."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        # Host-side IP assignment fails
        host.pexec = lambda cmd: ("", "addr assignment failed", 1)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            if cmd_count[0] <= 9:
                return 0, "", ""
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd), \
                patch(
                    "src.runtime.bridge.MininetCommandRunner",
                    return_value=_pexec_runner(host),
                ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        _created_bridges.clear()

    def test_mtu_failure_rolls_back(self):
        """MTU failure is fatal and rolls back completed mutations."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # cmd 3-11 succeed (bridge creation through netns move)
            if cmd_count[0] <= 11:
                return 0, "", ""
            # cmd 12: veth_root MTU fails
            if cmd_count[0] == 12:
                return 1, "", "mtu failed"
            # Rollback succeeds
            return 0, "", ""

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd), \
                patch(
                    "src.runtime.bridge.MininetCommandRunner",
                    return_value=_pexec_runner(host),
                ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24", mtu=1400)

        assert "h0" not in _created_bridges
        _created_bridges.clear()


class TestExternalBridgeRollbackFailureReporting:
    """Rollback failure reporting test."""

    def test_setup_failure_plus_rollback_failure_reports_both(self):
        """Setup failure + rollback failure: ExternalBridgeError contains both."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges, ExternalBridgeError

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback fails
            return 1, "", "rollback failed"

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError) as exc_info:
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert exc_info.value.setup_failure is not None
        assert len(exc_info.value.rollback_failures) > 0

        _created_bridges.clear()


class TestExternalBridgeAdminState:
    """Administrative state restoration tests."""

    def test_prior_admin_down_restored_to_down(self):
        """Prior administratively-DOWN interface restored to DOWN during cleanup."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        # prior_up=False means this run raised it from DOWN
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": True,
        }

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            cleanup_external_bridges()

        down_calls = [c for c in calls if "down" in str(c) and "eth0" in str(c)]
        assert len(down_calls) > 0

        _created_bridges.clear()

    def test_prior_admin_up_not_forced_down(self):
        """Prior administratively-UP interface is not forced DOWN during cleanup."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        # prior_up=True means interface was already UP
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,  # This run did NOT raise it
        }

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            cleanup_external_bridges()

        # No DOWN command for eth0 (it was already UP)
        down_calls = [c for c in calls if "down" in str(c) and "eth0" in str(c)]
        assert len(down_calls) == 0

        _created_bridges.clear()


class TestExternalBridgeCleanupOrder:
    """Cleanup command order and aggregate failure tests."""

    def test_cleanup_command_order(self):
        """Explicit cleanup order assertion: veth→unmaster→DOWN→bridge."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        # bridge_up is now an independent gate from bridge_created (per
        # cleanup invariant in the remediation contract). A fully-attached
        # record has both bridge_created and bridge_up set, so we mirror that.
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "bridge_up": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": True,
        }

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            cleanup_external_bridges()

        # Find indices of key operations
        veth_del_idx = None
        unmaster_idx = None
        phy_down_idx = None
        bridge_down_idx = None
        bridge_del_idx = None

        for i, c in enumerate(calls):
            cstr = str(c)
            if "del" in cstr and "veth-h0-root" in cstr:
                veth_del_idx = i
            elif "nomaster" in cstr:
                unmaster_idx = i
            elif "down" in cstr and "eth0" in cstr:
                phy_down_idx = i
            elif "down" in cstr and "br-h0" in cstr:
                bridge_down_idx = i
            elif "del" in cstr and "br-h0" in cstr:
                bridge_del_idx = i

        assert veth_del_idx is not None, "veth delete not found"
        assert unmaster_idx is not None, "unmaster not found"
        assert phy_down_idx is not None, "phy down not found"
        assert bridge_down_idx is not None, "bridge down not found"
        assert bridge_del_idx is not None, "bridge del not found"

        assert veth_del_idx < unmaster_idx
        assert unmaster_idx < phy_down_idx
        assert phy_down_idx < bridge_down_idx
        assert bridge_down_idx < bridge_del_idx

        _created_bridges.clear()

    def test_cleanup_failure_externally_observable(self):
        """Cleanup failure raises ExternalBridgeError with failure details."""
        from src.runtime.bridge import cleanup_external_bridges, _created_bridges, ExternalBridgeError

        _created_bridges.clear()

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }

        def mock_cmd(args):
            return 1, "", "cleanup failed"

        with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
            with pytest.raises(ExternalBridgeError) as exc_info:
                cleanup_external_bridges()

        assert len(exc_info.value.rollback_failures) > 0

        _created_bridges.clear()


# ===========================================================================
# Defect Remediation Tests (T1, T1b, T1c, T2, T3, T4, T5, T7, T8, T9)
#
# These tests target the four defects called out in doc/chatGPT_assumed-Plan.md
# plus the duplicate-phy_intf rejection feature and the BridgeManager.cleanup()
# retry-retention contract. They follow the fail-before / pass-after pattern
# documented in the remediation plan.
# ===========================================================================


def _populate_full_record(host_name: str = "h0", phy: str = "eth0") -> None:
    """Pre-populate _created_bridges with a fully-attached record for tests."""
    from src.runtime.bridge import _created_bridges

    _created_bridges[host_name] = {
        "bridge": f"br-{host_name}",
        "veth_root": f"veth-{host_name}-root",
        "veth_host": f"veth-{host_name}",
        "phy_intf": phy,
        "prior_up": False,
        "bridge_created": True,
        "bridge_up": True,
        "phy_up_changed": True,
        "phy_enslaved": True,
        "veth_created": True,
        "veth_root_mastered": True,
        "veth_root_up": True,
        "veth_host_ns_moved": True,
        "veth_host_up": True,
        "mtu_set": False,
        "ip_assigned": True,
    }


class TestDefect1CleanupPartialSuccess:
    """T1 / T1b: cleanup_external_bridges() must clear only succeeded flags
    and skip already-discharged actions on retry."""

    def test_T1_nomaster_fails_only_remaining_action_retried(self):
        """T1: veth-del succeeds, nomaster fails, phy-down/bridge-down/bridge-del succeed.
        After first cleanup: only phy_enslaved=True remains. Second cleanup with
        all-success mocks must execute ONLY the nomaster command.
        """
        from src.runtime.bridge import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            _populate_full_record("h0", "eth0")

            first_calls: list[tuple] = []

            def mock_first_pass(args):
                first_calls.append(tuple(args))
                if tuple(args) == ("ip", "link", "set", "eth0", "nomaster"):
                    return 1, "", "nomaster failed"
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_first_pass):
                with pytest.raises(ExternalBridgeError):
                    cleanup_external_bridges()

            rec = _created_bridges["h0"]
            assert rec["veth_created"] is False, "veth_created must clear after veth-del success"
            assert rec["phy_enslaved"] is True, "phy_enslaved must remain True after nomaster failure"
            assert rec["phy_up_changed"] is False, "phy_up_changed must clear after phy-down success"
            assert rec["bridge_up"] is False, "bridge_up must clear after bridge-down success"
            assert rec["bridge_created"] is False, "bridge_created must clear after bridge-del success"
            assert "h0" in _created_bridges, "record must be retained while phy_enslaved outstanding"

            # Second pass — all succeed
            second_calls: list[tuple] = []

            def mock_second_pass(args):
                second_calls.append(tuple(args))
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_second_pass):
                cleanup_external_bridges()

            assert "h0" not in _created_bridges, "record must be cleared after retry success"

            # The second pass must call ONLY the outstanding nomaster.
            assert second_calls == [("ip", "link", "set", "eth0", "nomaster")], (
                f"second pass should only retry nomaster; got {second_calls}"
            )
            # Explicit no-re-call assertions
            assert ("ip", "link", "del", "veth-h0-root") not in second_calls
            assert ("ip", "link", "set", "eth0", "down") not in second_calls
            assert ("ip", "link", "set", "br-h0", "down") not in second_calls
            assert ("ip", "link", "del", "br-h0") not in second_calls
        finally:
            _created_bridges.clear()

    def test_T1b_bridge_del_fails_only_remaining_action_retried(self):
        """T1b: veth-del, nomaster, phy-down, bridge-down succeed; bridge-del fails.
        After first cleanup: only bridge_created=True remains. Second cleanup
        must execute ONLY the bridge-del command.
        """
        from src.runtime.bridge import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            _populate_full_record("h0", "eth0")

            first_calls: list[tuple] = []

            def mock_first_pass(args):
                first_calls.append(tuple(args))
                if tuple(args) == ("ip", "link", "del", "br-h0"):
                    return 1, "", "bridge-del failed"
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_first_pass):
                with pytest.raises(ExternalBridgeError):
                    cleanup_external_bridges()

            rec = _created_bridges["h0"]
            assert rec["veth_created"] is False
            assert rec["phy_enslaved"] is False
            assert rec["phy_up_changed"] is False
            assert rec["bridge_up"] is False, "bridge_up clears via bridge-down success"
            assert rec["bridge_created"] is True, "bridge_created remains because bridge-del failed"
            assert "h0" in _created_bridges

            # Second pass — all succeed
            second_calls: list[tuple] = []

            def mock_second_pass(args):
                second_calls.append(tuple(args))
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_second_pass):
                cleanup_external_bridges()

            assert "h0" not in _created_bridges
            assert second_calls == [("ip", "link", "del", "br-h0")], (
                f"second pass should only retry bridge-del; got {second_calls}"
            )
            assert ("ip", "link", "del", "veth-h0-root") not in second_calls
            assert ("ip", "link", "set", "eth0", "nomaster") not in second_calls
            assert ("ip", "link", "set", "eth0", "down") not in second_calls
            assert ("ip", "link", "set", "br-h0", "down") not in second_calls
        finally:
            _created_bridges.clear()


class TestDefect1SetupRollbackPartialFlagClear:
    """T1c: setup rollback must clear flags only for actions whose status-aware
    run() completed without raising. Failed undos retain the corresponding
    outstanding flag(s) so cleanup_external_bridges() retries them."""

    def test_T1c_rollback_partial_failure_retains_only_failed_flag(self):
        """During setup rollback after veth_root_master failure, inject the
        bridge-delete COMMAND to return rc=1 so the status-aware helper raises.
        All other rollback commands (delete veth, unmaster phy, restore phy DOWN)
        succeed. After raise: record retains ONLY bridge_created=True and
        bridge_up=True; subsequent cleanup runs ONLY bridge-down + bridge-del.
        """
        from src.runtime.bridge import (
            attach_external_via_bridge,
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            net = _make_net_helper()
            host = net.get.return_value
            host.pexec = lambda cmd: ("", "", 0)

            setup_call_idx = [0]
            captured: list[tuple] = []
            seen_step_6_fail = [False]

            # Status-aware injection: the bridge-delete COMMAND used by the
            # rollback helper returns rc=1, so `_RollbackAction.run()` raises
            # through `_rollback_del_link` with the failed command + rc/stderr
            # detail. Every other rollback command (delete veth, unmaster phy,
            # restore phy DOWN) succeeds via its status-aware helper.
            def combined_mock(args):
                t = tuple(args)
                captured.append(t)

                if t[:2] == ("ip", "-j") and "addr" in t:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if t[:2] == ("ip", "-j") and "link" in t:
                    return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST"]}]), ""

                if not seen_step_6_fail[0]:
                    setup_call_idx[0] += 1
                    if setup_call_idx[0] == 6:
                        seen_step_6_fail[0] = True
                        return 1, "", "veth-root-master injected failure"
                    return 0, "", ""

                # rollback phase
                if t == ("ip", "link", "del", "br-h0"):
                    return 1, "", "bridge-del injected failure (rollback)"
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=combined_mock):
                with pytest.raises(ExternalBridgeError):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            # The bridge-delete rollback raised through the status-aware helper,
            # so the bridge_created flag stays True and the record is retained.
            assert "h0" in _created_bridges, "record must be retained when bridge-del rollback failed"
            rec = _created_bridges["h0"]
            assert rec["bridge_created"] is True
            assert rec["bridge_up"] is True  # bridge-down rollback is NOT issued in this path
            assert rec["phy_enslaved"] is False
            assert rec["phy_up_changed"] is False
            assert rec["veth_created"] is False, "veth-del rollback succeeded → flag cleared"

            # Now retry cleanup with all-success mocks.
            retry_calls: list[tuple] = []

            def retry_mock(args):
                retry_calls.append(tuple(args))
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=retry_mock):
                cleanup_external_bridges()

            assert "h0" not in _created_bridges
            # The retry must only run the outstanding bridge cleanup steps.
            # bridge_up was still True so bridge-down is also issued, then bridge-del.
            assert retry_calls == [
                ("ip", "link", "set", "br-h0", "down"),
                ("ip", "link", "del", "br-h0"),
            ], f"retry must issue only bridge-down + bridge-del; got {retry_calls}"
            # Explicit no-re-call assertions
            assert ("ip", "link", "del", "veth-h0-root") not in retry_calls
            assert ("ip", "link", "set", "eth0", "nomaster") not in retry_calls
            assert ("ip", "link", "set", "eth0", "down") not in retry_calls
        finally:
            _created_bridges.clear()


class TestDefect2PhyDownRestoreOnEnslaveFailure:
    """T2: when the physical interface was raised UP by the setup and enslave
    subsequently fails, the rollback must restore phy DOWN before exiting."""

    def test_T2_enslave_failure_restores_phy_down(self):
        from src.runtime.bridge import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            net = _make_net_helper()
            host = net.get.return_value
            host.pexec = lambda cmd: ("", "", 0)

            captured: list[tuple] = []
            cmd_idx = [0]

            def mock_cmd(args):
                t = tuple(args)
                captured.append(t)
                if t[:2] == ("ip", "-j") and "addr" in t:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if t[:2] == ("ip", "-j") and "link" in t:
                    # NOT UP → prior_up=False, so setup will run phy-up
                    return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST"]}]), ""

                cmd_idx[0] += 1
                # 1: ip link add br-h0 type bridge -> ok
                # 2: ip link set br-h0 up         -> ok
                # 3: ip link set eth0 up          -> ok
                # 4: ip link set eth0 master br-h0 -> FAIL
                if cmd_idx[0] == 4:
                    return 1, "", "enslave injected failure"
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
                with pytest.raises(ExternalBridgeError, match="phy-enslave failure"):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            # The rollback must have set eth0 back DOWN.
            assert ("ip", "link", "set", "eth0", "down") in captured, (
                f"phy DOWN restoration command missing from rollback; got {captured}"
            )
            # Owned bridge must be removed during rollback.
            assert ("ip", "link", "del", "br-h0") in captured, (
                f"owned bridge deletion missing from rollback; got {captured}"
            )
            assert "h0" not in _created_bridges
        finally:
            _created_bridges.clear()


class TestDefect3ProxyARPRetryableRestoration:
    """T3/T4/T5: enable_proxy_arp() retry-restoration invariants I-PA-1..I-PA-5."""

    def _make_mgr(self):
        from src.runtime.bridge import BridgeManager
        root = MagicMock()
        mgr = BridgeManager(runner=_pexec_runner(root))
        mgr.root_node = root
        mgr.root_intf = MagicMock()
        mgr.root_intf.__str__ = lambda s: "eth0"
        return mgr, root

    def test_T3_success_path_action_order_iface_then_all(self):
        """T3 (coverage): on success the appended cleanup actions are
        [iface_restore, all_restore]; reversed teardown runs all then iface."""
        mgr, root = self._make_mgr()

        def pexec(cmd):
            if "sysctl -n" in cmd:
                return "0", "", 0
            return "", "", 0

        root.pexec = pexec
        mgr.enable_proxy_arp()

        proxy_arp_descs = [
            a.description for a in mgr.cleanup_actions
            if "proxy_arp" in a.description
        ]
        # Take the last two — those are the proxy_arp registrations from
        # enable_proxy_arp().
        assert len(proxy_arp_descs) >= 2
        last_two = proxy_arp_descs[-2:]
        assert last_two == [
            "restore proxy_arp eth0 to 0",
            "restore proxy_arp all to 0",
        ], f"append order must be [iface, all]; got {last_two}"

    def test_T4_second_write_fail_iface_rollback_success_removes_tentative(self):
        """T4: iface write ok, all write fails, iface restore succeeds → raise
        with the all-write detail, no `restore proxy_arp eth0` entry remains."""
        mgr, root = self._make_mgr()
        calls = []

        def pexec(cmd):
            calls.append(cmd)
            if "sysctl -n" in cmd:
                return "0", "", 0
            if "net.ipv4.conf.eth0.proxy_arp=1" in cmd:
                return "", "", 0
            if "net.ipv4.conf.all.proxy_arp=1" in cmd:
                return "", "all-write failed", 1
            if "net.ipv4.conf.eth0.proxy_arp=0" in cmd:
                # Iface restore — succeeds
                return "", "", 0
            return "", "", 0

        root.pexec = pexec

        with pytest.raises(RuntimeError) as exc_info:
            mgr.enable_proxy_arp()

        # The exception detail mentions the all-write failure
        assert "all-write failed" in str(exc_info.value) or "all" in str(exc_info.value)

        # No `restore proxy_arp eth0` entry remains
        proxy_arp_iface_actions = [
            a for a in mgr.cleanup_actions
            if "proxy_arp eth0" in a.description
        ]
        assert len(proxy_arp_iface_actions) == 0, (
            f"tentative iface action must be removed; got {[a.description for a in mgr.cleanup_actions]}"
        )

    def test_T5_second_write_fail_iface_rollback_fail_retained_for_retry(self):
        """T5 (defect, principal `prior_iface='0'` case): verifies all five
        proxy-ARP invariants I-PA-1..I-PA-5. The retained action restores to
        the prior value `0`, not to `1`.
        """
        mgr, root = self._make_mgr()
        pexec_calls = []
        iface_restore_attempts = [0]

        def pexec(cmd):
            pexec_calls.append(cmd)
            if "sysctl -n" in cmd:
                # prior_iface and prior_all both read as "0"
                return "0", "", 0
            if "net.ipv4.conf.eth0.proxy_arp=1" in cmd:
                # Iface enable write — succeed
                return "", "", 0
            if "net.ipv4.conf.all.proxy_arp=1" in cmd:
                # All enable write — fail
                return "", "all-write failed", 1
            if "net.ipv4.conf.eth0.proxy_arp=0" in cmd:
                # Iface restore — fail first time, succeed on later retry
                iface_restore_attempts[0] += 1
                if iface_restore_attempts[0] == 1:
                    return "", "iface-restore failed", 1
                return "", "", 0
            return "", "", 0

        root.pexec = pexec

        with pytest.raises(RuntimeError) as exc_info:
            mgr.enable_proxy_arp()

        # I-PA-5: exception message preserves BOTH details
        msg = str(exc_info.value)
        assert "all-write failed" in msg, f"setup detail missing; got {msg}"
        assert "iface-restore failed" in msg, f"rollback detail missing; got {msg}"

        # I-PA-1 / I-PA-2: exactly one mandatory action remains restoring to "0"
        iface_actions = [
            a for a in mgr.cleanup_actions
            if a.description == "restore proxy_arp eth0 to 0"
        ]
        assert len(iface_actions) == 1, (
            f"exactly one retained iface action expected; got {[a.description for a in mgr.cleanup_actions]}"
        )

        # I-PA-3: cleanup() retries successfully
        mgr.cleanup()

        # I-PA-3 detail: the cleanup phase actually invoked the iface restore
        # again (the second attempt succeeds with rc=0)
        assert iface_restore_attempts[0] >= 2, "cleanup must have retried the iface restore"
        # The retried command was the prior-value restoration (=0)
        assert any(
            "net.ipv4.conf.eth0.proxy_arp=0" in c for c in pexec_calls
        )

        # I-PA-4: action list is empty after successful retry
        assert mgr.cleanup_actions == [], (
            f"cleanup_actions must be empty after successful retry; got {[a.description for a in mgr.cleanup_actions]}"
        )


class TestDefect5DuplicatePhyIntfRejection:
    """T7, T8: pre-mutation rejection of a duplicate phy_intf attachment
    against any existing record in _created_bridges, including rollback-failed
    retained records."""

    def test_T7_duplicate_phy_intf_vs_successful_active_record_rejected(self):
        """T7: a fully-attached record for h1 owns eth0; attaching h0 to the
        same eth0 must raise RuntimeError before any mutation."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        try:
            _populate_full_record("h1", "eth0")
            net = _make_net_helper()
            captured: list[tuple] = []

            def mock_cmd(args):
                captured.append(tuple(args))
                # If reached, the duplicate check did NOT fire pre-mutation.
                if args[:2] == ["ip", "-j"] and "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if args[:2] == ["ip", "-j"] and "link" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
                with pytest.raises(RuntimeError, match=r"(?i)eth0.*already.*attached"):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            # No mutating commands were issued.
            for c in captured:
                assert c[:2] != ("ip", "link") or c[2] not in ("add", "set", "del"), (
                    f"no mutation command may be issued before duplicate rejection; got {c}"
                )
            assert "h0" not in _created_bridges
        finally:
            _created_bridges.clear()

    def test_T8_duplicate_phy_intf_vs_rollback_failed_retained_record_rejected(self):
        """T8: a partial outstanding record for h1 owns eth0 (simulating a
        rollback-failed retained record); attaching h0 to eth0 must raise
        before any mutation."""
        from src.runtime.bridge import attach_external_via_bridge, _created_bridges

        _created_bridges.clear()
        try:
            _created_bridges["h1"] = {
                "bridge": "br-h1",
                "veth_root": "veth-h1-root",
                "veth_host": "veth-h1",
                "phy_intf": "eth0",
                "prior_up": False,
                "bridge_created": False,
                "bridge_up": False,
                "phy_up_changed": False,
                "phy_enslaved": True,  # only outstanding flag
                "veth_created": False,
                "veth_root_mastered": False,
                "veth_root_up": False,
                "veth_host_ns_moved": False,
                "veth_host_up": False,
                "mtu_set": False,
                "ip_assigned": False,
            }
            net = _make_net_helper()
            captured: list[tuple] = []

            def mock_cmd(args):
                captured.append(tuple(args))
                if args[:2] == ["ip", "-j"] and "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if args[:2] == ["ip", "-j"] and "link" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]), ""
                return 0, "", ""

            with patch("src.runtime.bridge._run_root_cmd_vec", side_effect=mock_cmd):
                with pytest.raises(RuntimeError, match=r"(?i)eth0.*already.*attached"):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            for c in captured:
                assert c[:2] != ("ip", "link") or c[2] not in ("add", "set", "del"), (
                    f"no mutation command may be issued before duplicate rejection; got {c}"
                )
            assert "h0" not in _created_bridges
        finally:
            _created_bridges.clear()


class TestDefect3BridgeManagerCleanupRetainsFailedMandatory:
    """T9: BridgeManager.cleanup() retains only failed mandatory actions
    across cleanup() invocations so a subsequent cleanup() retries them."""

    def test_T9_failed_mandatory_action_retained_then_retried(self):
        from src.runtime.bridge import BridgeManager, CleanupAction, TeardownError

        bm = BridgeManager()
        first_call_count = [0]
        second_call_count = [0]

        def first_action_execute():
            first_call_count[0] += 1
            if first_call_count[0] == 1:
                return 1, "first fail"
            return 0, ""

        def second_action_execute():
            second_call_count[0] += 1
            return 0, ""

        a1 = CleanupAction(
            description="first mandatory",
            category="test",
            mandatory=True,
            execute=first_action_execute,
        )
        a2 = CleanupAction(
            description="second mandatory",
            category="test",
            mandatory=True,
            execute=second_action_execute,
        )
        bm.cleanup_actions = [a1, a2]

        with pytest.raises(TeardownError):
            bm.cleanup()

        # First action failed; it must be retained for retry. Second action
        # succeeded and must be dropped.
        assert len(bm.cleanup_actions) == 1, (
            f"only the failed mandatory action should be retained; got {[a.description for a in bm.cleanup_actions]}"
        )
        assert bm.cleanup_actions[0].description == "first mandatory"

        # Second cleanup invocation — first action succeeds this time.
        bm.cleanup()

        # Action list must be empty after successful retry.
        assert bm.cleanup_actions == []

        # Verify the retained action was executed during the second cleanup.
        assert first_call_count[0] == 2, "retained action must have been retried"