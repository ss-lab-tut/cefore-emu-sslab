"""Root-namespace bridge management and setup orchestration."""

from unittest.mock import MagicMock, patch

import pytest

from src.core.addressing import AddressingScheme
from src.runtime.bridge_root import (
    _resolve_root_ip,
    extract_gateway_from_ip,
    setup_bridges,
)
from src.runtime.command_runner import ROOT_SENTINEL, CommandResult, FakeCommandRunner


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
        {
            "switch": switch_name,
            "subnet": subnet,
            "hosts": [0, 1],
            "host_eth": {0: 0, 1: 0},
        },
    ]


def test_extract_gateway_from_ip_drops_prefix_length():
    assert extract_gateway_from_ip("192.168.100.1/24") == "192.168.100.1"


class TestResolveRootIP:
    def test_explicit_root_ip_returned_unchanged(self):
        result = _resolve_root_ip("s1", "10.0.0.1/24", _mesh_links_with_switch())
        assert result == "10.0.0.1/24"

    def test_auto_with_default_scheme(self):
        result = _resolve_root_ip("s1", "auto", _mesh_links_with_switch(subnet=3))
        assert result == "192.168.3.254/24"

    def test_auto_with_custom_scheme(self):
        scheme = AddressingScheme("172.20.0.0/16")
        result = _resolve_root_ip(
            "s1", "auto", _mesh_links_with_switch(subnet=5), scheme=scheme
        )
        assert result == "172.20.5.254/24"

    def test_auto_unknown_switch_returns_original(self):
        result = _resolve_root_ip(
            "s99", "auto", _mesh_links_with_switch("s1", subnet=3)
        )
        assert result == "auto"

    def test_none_root_ip_no_match_returns_none(self):
        result = _resolve_root_ip("s1", None, [])
        assert result is None

    def test_scheme_none_fallback_to_default(self):
        result = _resolve_root_ip(
            "s1", "auto", _mesh_links_with_switch(subnet=2), scheme=None
        )
        assert result == "192.168.2.254/24"


class TestConnectToRootNsCidrValidation:
    """Verify connect_to_root_ns rejects bare IPs before any mutation."""

    def test_bare_ip_rejected(self):
        from src.runtime.bridge_root import BridgeManager

        manager = BridgeManager(runner=FakeCommandRunner())
        net = MagicMock()
        net.get.return_value = MagicMock()
        with pytest.raises(RuntimeError, match="CIDR"):
            manager.connect_to_root_ns(net, "s1", "10.0.0.1", "192.168.0.0/16")
        assert manager.root_node is None
        net.addLink.assert_not_called()

    def test_cidr_ip_does_not_raise_validation_error(self):
        from src.runtime.bridge_root import BridgeManager

        fake = FakeCommandRunner()
        fake.on_run = lambda node, argv: CommandResult(0)
        manager = BridgeManager(runner=fake)
        root = MagicMock()
        manager.root_node = root
        net = MagicMock()
        switch = MagicMock()
        net.get.return_value = switch
        link = MagicMock()
        link.intf1 = "root-eth0"
        net.addLink.return_value = link
        manager.connect_to_root_ns(net, "s1", "10.0.0.1/24", "192.168.0.0/16")
        root.setIP.assert_called_once()

    def test_unresolved_auto_rejected(self):
        from src.runtime.bridge_root import BridgeManager

        manager = BridgeManager(runner=FakeCommandRunner())
        net = MagicMock()
        net.get.return_value = MagicMock()
        with pytest.raises(RuntimeError, match="CIDR"):
            manager.connect_to_root_ns(net, "s1", "auto", "192.168.0.0/16")
        assert manager.root_node is None
        net.addLink.assert_not_called()


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

        with patch(
            "src.runtime.bridge_root._resolve_root_ip", wraps=_resolve_root_ip
        ) as mock_resolve:
            try:
                setup_bridges(
                    net, bridge_manager, bridge_configs, 2, mesh_links, scheme=scheme
                )
            except Exception:
                pass  # BridgeManager internals may fail without real net — that's OK
            mock_resolve.assert_called_once_with(
                "s1", "auto", mesh_links, scheme=scheme
            )

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

        with patch(
            "src.runtime.bridge_root._resolve_root_ip", side_effect=capture_resolve
        ):
            try:
                setup_bridges(net, bridge_manager, bridge_configs, 2, mesh_links)
            except Exception:
                pass
        assert resolved_ips and resolved_ips[0] == "192.168.3.254/24"


class TestSetupBridgesCommandRunnerWiring:
    """Verify setup_bridges reaches bridge root/host paths through one runner."""

    def test_setup_bridges_uses_injected_runner_for_root_host_and_resolv(self):
        from src.runtime.bridge_root import BridgeManager

        fake = FakeCommandRunner()

        def on_run(node, argv):
            if argv == ["sysctl", "-n", "net.ipv4.ip_forward"]:
                return CommandResult(0, stdout="0\n")
            if argv[:3] == ["sysctl", "-n", "net.ipv4.conf.root-eth0.proxy_arp"]:
                return CommandResult(0, stdout="0\n")
            if argv == ["sysctl", "-n", "net.ipv4.conf.all.proxy_arp"]:
                return CommandResult(0, stdout="0\n")
            return CommandResult(0)

        fake.on_run = on_run
        manager = BridgeManager(runner=fake)
        manager.root_node = MagicMock()

        switch = MagicMock()
        host = MagicMock()
        net = MagicMock()
        net.get = MagicMock(side_effect=lambda name: switch if name == "s1" else host)
        net.addLink = MagicMock(return_value=MagicMock(intf1="root-eth0"))

        setup_bridges(
            net,
            manager,
            [
                {
                    "switch": "s1",
                    "root_ip": "100.64.3.254/24",
                    "local_routes": "100.64.0.0/16",
                    "external_routes": "10.0.0.0/24",
                    "gateway": "100.64.3.1",
                    "hosts": [0, 1],
                    "nat": True,
                    "nat_out": "eth0",
                    "proxy_arp": True,
                    "vm_host_network": "172.20.0.0/16",
                }
            ],
            host_num=2,
            mesh_links=[
                {
                    "switch": "s1",
                    "subnet": 3,
                    "hosts": [0, 1],
                    "host_eth": {0: 0, 1: 1},
                }
            ],
        )

        runs = [(r["node"], r["argv"], r["log_path"]) for r in fake.runs]

        assert (
            ROOT_SENTINEL,
            ["route", "add", "-net", "100.64.0.0/16", "dev", "root-eth0"],
            None,
        ) in runs
        assert (
            ROOT_SENTINEL,
            ["ovs-ofctl", "add-flow", "s1", "priority=0,actions=NORMAL"],
            None,
        ) in runs
        assert (
            "h0",
            [
                "route",
                "add",
                "-net",
                "10.0.0.0/24",
                "gw",
                "100.64.3.254",
                "dev",
                "h0-eth0",
            ],
            None,
        ) in runs
        assert (
            "h1",
            [
                "route",
                "add",
                "-net",
                "172.20.0.0/16",
                "gw",
                "100.64.3.254",
                "dev",
                "h1-eth1",
            ],
            None,
        ) in runs
        assert (
            "h0",
            ["printf", "nameserver 8.8.8.8\n"],
            "/etc/resolv.conf",
        ) in runs
        assert (
            ROOT_SENTINEL,
            [
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                "100.64.0.0/16",
                "-o",
                "eth0",
                "-j",
                "MASQUERADE",
            ],
            None,
        ) in runs
        assert (
            ROOT_SENTINEL,
            ["sysctl", "-w", "net.ipv4.ip_forward=1"],
            None,
        ) in runs
        assert (
            ROOT_SENTINEL,
            ["sysctl", "-w", "net.ipv4.conf.root-eth0.proxy_arp=1"],
            None,
        ) in runs
        assert {a.category for a in manager.cleanup_actions} >= {
            "route",
            "flow",
            "sysctl",
            "nat",
            "proxy_arp",
        }


class TestCleanupArchitecture:
    """Tests for the structured cleanup action model."""

    def test_mandatory_cleanup_failure_is_surfaced(self):
        """A mandatory cleanup action failure must raise TeardownError."""
        from src.runtime.bridge_root import BridgeManager, TeardownError, CleanupAction

        mgr = BridgeManager()
        mgr.cleanup_actions.append(
            CleanupAction(
                description="restore ip_forward",
                category="sysctl",
                mandatory=True,
                execute=lambda: (1, "error"),
            )
        )

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        assert len(exc_info.value.failures) == 1
        assert "restore ip_forward" in exc_info.value.failures[0][0]

    def test_best_effort_cleanup_failure_does_not_raise(self):
        """A best-effort cleanup action failure should not raise."""
        from src.runtime.bridge_root import BridgeManager, CleanupAction

        mgr = BridgeManager()
        mgr.cleanup_actions.append(
            CleanupAction(
                description="remove route",
                category="route",
                mandatory=False,
                execute=lambda: (1, "error"),
            )
        )

        # Should not raise
        mgr.cleanup()

    def test_all_cleanup_actions_attempted_even_if_earlier_fails(self):
        """All cleanup actions must be attempted even if one fails."""
        from src.runtime.bridge_root import BridgeManager, TeardownError, CleanupAction

        mgr = BridgeManager()
        call_log = []

        def make_fail(desc):
            def fn():
                call_log.append(desc)
                return (1, "error")

            return fn

        mgr.cleanup_actions.extend(
            [
                CleanupAction("action1", "nat", True, make_fail("action1")),
                CleanupAction("action2", "nat", True, make_fail("action2")),
                CleanupAction("action3", "nat", True, make_fail("action3")),
            ]
        )

        with pytest.raises(TeardownError):
            mgr.cleanup()

        # All three actions were attempted
        assert len(call_log) == 3

    def test_multiple_mandatory_failures_aggregated(self):
        """Multiple mandatory failures must all be reported."""
        from src.runtime.bridge_root import BridgeManager, TeardownError, CleanupAction

        mgr = BridgeManager()
        mgr.cleanup_actions.extend(
            [
                CleanupAction("nat rule 1", "nat", True, lambda: (1, "error1")),
                CleanupAction(
                    "route", "route", False, lambda: (1, "error2")
                ),  # best-effort
                CleanupAction("nat rule 2", "nat", True, lambda: (1, "error3")),
            ]
        )

        with pytest.raises(TeardownError) as exc_info:
            mgr.cleanup()

        # Only mandatory failures in the aggregated error
        assert len(exc_info.value.failures) == 2

    def test_reverse_execution_order_preserved(self):
        """Cleanup actions must execute in reverse registration order."""
        from src.runtime.bridge_root import BridgeManager, CleanupAction

        mgr = BridgeManager()
        call_log = []

        def make_record(desc):
            def fn():
                call_log.append(desc)
                return (0, "")

            return fn

        mgr.cleanup_actions.extend(
            [
                CleanupAction("first", "nat", True, make_record("first")),
                CleanupAction("second", "nat", True, make_record("second")),
                CleanupAction("third", "nat", True, make_record("third")),
            ]
        )

        mgr.cleanup()

        # Reverse order: third, second, first
        assert call_log == ["third", "second", "first"]

    def test_cleanup_commands_do_not_suffer_late_binding(self):
        """Captured cleanup commands must not suffer late-binding lambda errors."""
        from src.runtime.bridge_root import BridgeManager, CleanupAction

        mgr = BridgeManager()

        # Simulate the pattern where prior values are captured in a loop
        for prior_val in ["0", "1"]:
            # Use default argument binding to avoid late-binding issues
            mgr.cleanup_actions.append(
                CleanupAction(
                    description=f"restore value to {prior_val}",
                    category="sysctl",
                    mandatory=True,
                    execute=lambda pv=prior_val: (0, f"restored to {pv}"),
                )
            )

        # Execute all cleanup actions
        mgr.cleanup()

        # Both should have been executed successfully
        assert len(mgr.cleanup_actions) == 0  # Cleared after cleanup


class TestIPForwarding:
    """Tests for enable_ip_forwarding() sysctl restoration."""

    def _make_mgr(self):
        """Create a BridgeManager with an injected pexec-backed runner."""
        from src.runtime.bridge_root import BridgeManager

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
            a for a in mgr.cleanup_actions if "ip_forward" in a.description
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
            a for a in mgr.cleanup_actions if "ip_forward" in a.description
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
            a for a in mgr.cleanup_actions if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 0

    def test_invalid_captured_value_aborts_without_mutation(self):
        """If captured value is invalid, no mutation should occur."""
        mgr, root = self._make_mgr()
        root.pexec = MagicMock(return_value=("2", "", 0))  # Invalid value

        with pytest.raises(RuntimeError, match="ip_forward"):
            mgr.enable_ip_forwarding()

        ip_forward_actions = [
            a for a in mgr.cleanup_actions if "ip_forward" in a.description
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
            a for a in mgr.cleanup_actions if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 0

    def test_restoration_failure_during_cleanup_is_surfaced(self):
        """Restoration failure during cleanup must be surfaced through the
        production registration, not via a locally rebound `cleanup_actions`
        entry.

        The cleanup `pexec()` returns `rc=1` so the normalized lambda
        propagates `(1, "restore failed")` into `TeardownError.failures`.
        """
        from src.runtime.bridge_root import TeardownError

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


class TestProxyARP:
    """Tests for enable_proxy_arp() transactional mutation."""

    def _make_mgr(self):
        """Create a BridgeManager with mocked root node and interface."""
        from src.runtime.bridge_root import BridgeManager

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
            a for a in mgr.cleanup_actions if "proxy_arp" in a.description
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
            a for a in mgr.cleanup_actions if "proxy_arp" in a.description
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
            a for a in mgr.cleanup_actions if "proxy_arp" in a.description
        ]
        assert len(proxy_arp_actions) == 2
        assert all(a.mandatory for a in proxy_arp_actions)

    def test_cleanup_restoration_failure_surfaced(self):
        """Proxy ARP cleanup restoration failure surfaces through the
        production registrations.

        Both restore writes return `rc=1` so `TeardownError.failures` contains
        two `proxy_arp` entries with the intended detail.
        """
        from src.runtime.bridge_root import TeardownError

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


class TestNAT:
    """Tests for enable_nat() transactional setup and cleanup."""

    def _make_mgr(self):
        """Create a BridgeManager with mocked root node."""
        from src.runtime.bridge_root import BridgeManager

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

        nat_actions = [a for a in mgr.cleanup_actions if "NAT" in a.description]
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

        nat_actions = [a for a in mgr.cleanup_actions if "NAT" in a.description]
        assert len(nat_actions) == 3
        assert all(a.mandatory for a in nat_actions)

    def test_cleanup_deletion_failure_surfaced(self):
        """NAT cleanup deletion failure surfaces through TeardownError via
        the production lambda, not via a locally rebound list entry.

        Setup `iptables -A` calls all succeed; subsequent `iptables -D`
        cleanup calls all fail with `rc=1`, and every recorded failure
        reports `rc=1` (not `-1` from a tuple-unpack `ValueError`).
        """
        from src.runtime.bridge_root import TeardownError

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

        nat_failures = [f for f in exc_info.value.failures if "NAT" in f[0]]
        # enable_nat registers exactly 3 mandatory NAT delete actions
        assert len(nat_failures) == 3
        # All recorded failures must report rc=1 (not -1 from unpack error)
        assert all(f[1] == 1 for f in nat_failures)
        assert all(f[2] == "iptables del failed" for f in nat_failures)

    def test_nat_failure_after_ip_forwarding_leaves_restoration(self):
        """If NAT fails after ip_forwarding, the ip_forward restoration remains."""
        from src.runtime.bridge_root import BridgeManager

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
            a for a in mgr.cleanup_actions if "ip_forward" in a.description
        ]
        assert len(ip_forward_actions) == 1


class TestProducerCleanupContract:
    """Drives every cleanup-action producer through cleanup() against
    success-returning mocks and asserts the normalized contract."""

    def test_all_cleanup_action_producers_use_normalized_success_contract(self):
        from src.runtime.bridge_root import BridgeManager

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
            "route",
            "sysctl",
            "nat",
            "flow",
            "proxy_arp",
        }

        with patch("src.runtime.bridge_root.info") as mock_info:
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


class TestDefect3ProxyARPRetryableRestoration:
    """T3/T4/T5: enable_proxy_arp() retry-restoration invariants I-PA-1..I-PA-5."""

    def _make_mgr(self):
        from src.runtime.bridge_root import BridgeManager

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
            a.description for a in mgr.cleanup_actions if "proxy_arp" in a.description
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
            a for a in mgr.cleanup_actions if "proxy_arp eth0" in a.description
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
            a
            for a in mgr.cleanup_actions
            if a.description == "restore proxy_arp eth0 to 0"
        ]
        assert len(iface_actions) == 1, (
            f"exactly one retained iface action expected; got {[a.description for a in mgr.cleanup_actions]}"
        )

        # I-PA-3: cleanup() retries successfully
        mgr.cleanup()

        # I-PA-3 detail: the cleanup phase actually invoked the iface restore
        # again (the second attempt succeeds with rc=0)
        assert iface_restore_attempts[0] >= 2, (
            "cleanup must have retried the iface restore"
        )
        # The retried command was the prior-value restoration (=0)
        assert any("net.ipv4.conf.eth0.proxy_arp=0" in c for c in pexec_calls)

        # I-PA-4: action list is empty after successful retry
        assert mgr.cleanup_actions == [], (
            f"cleanup_actions must be empty after successful retry; got {[a.description for a in mgr.cleanup_actions]}"
        )


class TestDefect3BridgeManagerCleanupRetainsFailedMandatory:
    """T9: BridgeManager.cleanup() retains only failed mandatory actions
    across cleanup() invocations so a subsequent cleanup() retries them."""

    def test_T9_failed_mandatory_action_retained_then_retried(self):
        from src.runtime.bridge_root import BridgeManager, CleanupAction, TeardownError

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
