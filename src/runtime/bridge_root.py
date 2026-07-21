"""Root-namespace bridge management and setup orchestration.

This module owns BridgeManager, root namespace route/NAT/proxy-ARP cleanup,
and bridge setup orchestration. External-NIC attach and its rollback ledger
live in bridge_external.py; argument parsing/validation in bridge_args.py.
"""

from dataclasses import dataclass
from typing import Any, Callable

from mininet.log import info
from mininet.net import Mininet
from mininet.node import Node

from ..core.addressing import AddressingScheme
from ..core.topology import TopologyModel
from .bridge_args import validate_static_ip
from .command_runner import ROOT_SENTINEL, MininetCommandRunner


@dataclass(frozen=True)
class CleanupAction:
    """A single cleanup action to be executed during teardown.

    Attributes:
        description: Human-readable description for error reporting.
        category: Category tag (sysctl, nat, route, flow, proxy_arp).
        mandatory: True = failure must be surfaced; False = best-effort.
        execute: Callable returning ``(rc, detail)``. Producers based on the
            CommandRunner seam must normalize the ``CommandResult`` to this
            2-tuple form (via ``_result_to_rc_detail``) so ``cleanup()`` can
            unpack uniformly.
    """

    description: str
    category: str
    mandatory: bool
    execute: Callable[[], tuple[int, str]]


class TeardownError(RuntimeError):
    """Aggregated teardown failure containing all failed mandatory cleanup actions.

    Attributes:
        failures: List of (description, exit_code, error_detail) tuples.
    """

    def __init__(self, failures: list[tuple[str, int, str]]):
        self.failures = failures
        msgs = [f"{desc} (rc={rc}): {detail}" for desc, rc, detail in failures]
        super().__init__("mandatory cleanup failures: " + "; ".join(msgs))


def _result_to_rc_detail(result) -> tuple[int, str]:
    """Normalize a ``CommandResult`` to the ``(rc, detail)`` 2-tuple shape
    ``cleanup()`` expects (detail is the stripped stderr)."""
    return result.returncode, (result.stderr or "").strip()


# ---------------------------------------------------------------------------
# Root namespace bridging (BridgeManager for cross-VM communication)
# ---------------------------------------------------------------------------


class BridgeManager:
    """Manage root namespace bridges and route cleanup.

    Cleanup is driven by ``cleanup_actions``: a list of ``CleanupAction``
    entries appended by each producer at setup time and drained in reverse
    order at teardown. CommandRunner-based registrations are normalized to
    the ``(rc, detail)`` contract via ``_result_to_rc_detail``.
    """

    def __init__(self, runner=None):
        self.root_node = None
        self.root_intf = None
        self.cleanup_actions: list[CleanupAction] = []
        # Injectable CommandRunner. When None, a real MininetCommandRunner is
        # built per use: net-less for root-namespace commands (ROOT_SENTINEL
        # routes to a plain subprocess) and net-bound for host-netns commands.
        self._runner = runner

    def _root_runner(self):
        """Runner for root-namespace commands (ROOT_SENTINEL, no net needed)."""
        return self._runner or MininetCommandRunner(None)

    def _host_runner(self, net):
        """Runner for host-netns commands (needs net to resolve the host)."""
        return self._runner or MininetCommandRunner(net)

    def get_or_create_root(self) -> Node:
        """Get or create the root namespace node."""
        if self.root_node is None:
            self.root_node = Node("root", inNamespace=False)
        return self.root_node

    def connect_to_root_ns(
        self,
        net: Mininet,
        switch_name: str,
        root_ip: str,
        local_routes: str,
    ) -> bool:
        """Connect Mininet hosts to root namespace via switch.

        Args:
            net: Mininet network instance.
            switch_name: Switch name to connect to root namespace.
            root_ip: IP address for root namespace node (e.g., "192.168.100.1/24").
            local_routes: Local Mininet host networks to route to.

        Returns:
            True when the root link is attached; False when the switch does
            not exist. The caller must skip every follow-on operation for
            the bridge entry on False — flows/routes/NAT against a missing
            switch would mutate unrelated state and register bogus cleanup.
        """
        # 2026-07-16 review fix: the switches config value is an upper bound
        # on the emergent topology, so a validator-accepted index can name a
        # switch that was never built — and net.get raises KeyError for
        # unknown names (the old `is None` guard was dead code).
        try:
            switch = net.get(switch_name)
        except KeyError:
            switch = None
        if switch is None:
            info(f"*** Warning: switch {switch_name} not found\n")
            return False

        validate_static_ip(root_ip)

        root = self.get_or_create_root()
        link = net.addLink(root, switch)
        self.root_intf = link.intf1

        # 2026-07-16 runtime fix: setup runs after net.start(), and addLink
        # alone does not enroll the new veth into a running OVS switch — the
        # port stayed off the bridge (ovs-vsctl list-ports lacked it), so
        # every host↔root packet was silently dropped and connections could
        # never be established. Explicitly attach the switch-side end.
        switch.attach(link.intf2)

        root.setIP(root_ip, intf=self.root_intf)

        runner = self._root_runner()
        add_argv = ["route", "add", "-net", local_routes, "dev", str(self.root_intf)]
        info(f"*** Adding route in root ns: {add_argv}\n")
        runner.run(ROOT_SENTINEL, add_argv, capture_stderr=True)
        del_argv = ["route", "del", "-net", local_routes]
        self.cleanup_actions.append(
            CleanupAction(
                description=f"remove route: {' '.join(del_argv)}",
                category="route",
                mandatory=False,
                execute=lambda r=runner, a=del_argv: _result_to_rc_detail(
                    r.run(ROOT_SENTINEL, a, capture_stderr=True)
                ),
            )
        )
        return True

    def add_host_route(
        self,
        net: Mininet,
        host_name: str,
        dest_network: str,
        gateway: str,
        dev: str | None = None,
    ) -> None:
        """Add route from Mininet host to external network."""
        host = net.get(host_name)
        if host is None:
            info(f"*** Warning: host {host_name} not found\n")
            return

        runner = self._host_runner(net)
        dev_clause = ["dev", dev] if dev else []
        if dest_network in ("default", "0.0.0.0/0"):
            add_argv = [
                "ip",
                "route",
                "replace",
                "default",
                "via",
                gateway,
            ] + dev_clause
            del_argv = ["ip", "route", "del", "default"]
        else:
            add_argv = [
                "route",
                "add",
                "-net",
                dest_network,
                "gw",
                gateway,
            ] + dev_clause
            del_argv = ["route", "del", "-net", dest_network]
        info(f"*** Adding route in {host_name}: {add_argv}\n")
        runner.run(host_name, add_argv, capture_stderr=True)
        self.cleanup_actions.append(
            CleanupAction(
                description=f"remove host route: {' '.join(del_argv)}",
                category="route",
                mandatory=False,
                execute=lambda r=runner, name=host_name, a=del_argv: (
                    _result_to_rc_detail(r.run(name, a, capture_stderr=True))
                ),
            )
        )

    def add_root_route(self, dest_network: str, gateway: str) -> None:
        """Add route from root namespace to external network."""
        self.get_or_create_root()
        runner = self._root_runner()
        add_argv = ["route", "add", "-net", dest_network, "gw", gateway]
        info(f"*** Adding route in root ns: {add_argv}\n")
        runner.run(ROOT_SENTINEL, add_argv, capture_stderr=True)
        del_argv = ["route", "del", "-net", dest_network]
        self.cleanup_actions.append(
            CleanupAction(
                description=f"remove root route: {' '.join(del_argv)}",
                category="route",
                mandatory=False,
                execute=lambda r=runner, a=del_argv: _result_to_rc_detail(
                    r.run(ROOT_SENTINEL, a, capture_stderr=True)
                ),
            )
        )

    def enable_ip_forwarding(self) -> None:
        """Enable IP forwarding on root namespace node.

        Captures the exact prior value and registers a mandatory cleanup
        action to restore it.
        """
        self.get_or_create_root()
        runner = self._root_runner()

        read = runner.run(
            ROOT_SENTINEL, ["sysctl", "-n", "net.ipv4.ip_forward"], capture_stderr=True
        )
        if read.returncode != 0:
            raise RuntimeError(
                f"failed to read ip_forward (rc={read.returncode}): "
                f"{(read.stderr or '').strip()}"
            )
        prior = read.stdout.strip()
        if prior not in ("0", "1"):
            raise RuntimeError(f"invalid ip_forward value '{prior}'")

        write = runner.run(
            ROOT_SENTINEL,
            ["sysctl", "-w", "net.ipv4.ip_forward=1"],
            capture_stderr=True,
        )
        if write.returncode != 0:
            raise RuntimeError(
                f"failed to enable ip_forward (rc={write.returncode}): "
                f"{(write.stderr or '').strip()}"
            )

        self.cleanup_actions.append(
            CleanupAction(
                description=f"restore ip_forward to {prior}",
                category="sysctl",
                mandatory=True,
                execute=lambda r=runner, pv=prior: _result_to_rc_detail(
                    r.run(
                        ROOT_SENTINEL,
                        ["sysctl", "-w", f"net.ipv4.ip_forward={pv}"],
                        capture_stderr=True,
                    )
                ),
            )
        )

    def enable_nat(self, local_routes: str, out_intf: str = None) -> None:
        """Enable NAT (masquerade) for local routes via outbound interface.

        Transactional: if any rule fails to install, previously-installed
        rules are rolled back in reverse before raising.
        """
        self.get_or_create_root()
        runner = self._root_runner()
        if out_intf is None:
            result = runner.run(
                ROOT_SENTINEL, ["ip", "route", "show", "default"], capture_stderr=True
            )
            parts = result.stdout.split()
            if "dev" in parts:
                idx = parts.index("dev")
                if idx + 1 < len(parts):
                    out_intf = parts[idx + 1]
        if not out_intf:
            info("*** Warning: could not detect outbound interface for NAT\n")
            return

        root_intf_name = str(self.root_intf)
        add_argvs = [
            [
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                local_routes,
                "-o",
                out_intf,
                "-j",
                "MASQUERADE",
            ],
            [
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                root_intf_name,
                "-o",
                out_intf,
                "-s",
                local_routes,
                "-j",
                "ACCEPT",
            ],
            [
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                out_intf,
                "-o",
                root_intf_name,
                "-d",
                local_routes,
                "-m",
                "state",
                "--state",
                "RELATED,ESTABLISHED",
                "-j",
                "ACCEPT",
            ],
        ]

        def _to_del(argv):
            return ["-D" if tok == "-A" else tok for tok in argv]

        owned_rules: list[list[str]] = []
        for i, add_argv in enumerate(add_argvs):
            info(f"*** NAT: {add_argv}\n")
            res = runner.run(ROOT_SENTINEL, add_argv, capture_stderr=True)
            if res.returncode != 0:
                rollback_failures = []
                for owned in reversed(owned_rules):
                    del_argv = _to_del(owned)
                    drc = runner.run(
                        ROOT_SENTINEL, del_argv, capture_stderr=True
                    ).returncode
                    if drc != 0:
                        rollback_failures.append((" ".join(del_argv), drc))
                msg = (
                    f"NAT rule {i} failed (rc={res.returncode}): "
                    f"{(res.stderr or '').strip()}"
                )
                if rollback_failures:
                    msg += f"; rollback failures: {rollback_failures}"
                raise RuntimeError(msg)
            owned_rules.append(add_argv)

        for add_argv in owned_rules:
            del_argv = _to_del(add_argv)
            self.cleanup_actions.append(
                CleanupAction(
                    description=f"delete NAT rule: {' '.join(del_argv)}",
                    category="nat",
                    mandatory=True,
                    execute=lambda r=runner, a=del_argv: _result_to_rc_detail(
                        r.run(ROOT_SENTINEL, a, capture_stderr=True)
                    ),
                )
            )

    def enable_normal_flow(self, net: Mininet, switch_name: str) -> None:
        """Add NORMAL action flow to OVS switch for L2 learning bridge behavior."""
        self.get_or_create_root()
        runner = self._root_runner()
        add_argv = ["ovs-ofctl", "add-flow", switch_name, "priority=0,actions=NORMAL"]
        runner.run(ROOT_SENTINEL, add_argv, capture_stderr=True)
        del_argv = ["ovs-ofctl", "del-flows", switch_name, "--strict", "priority=0"]
        self.cleanup_actions.append(
            CleanupAction(
                description=f"remove OVS flow: {' '.join(del_argv)}",
                category="flow",
                mandatory=False,
                execute=lambda r=runner, a=del_argv: _result_to_rc_detail(
                    r.run(ROOT_SENTINEL, a, capture_stderr=True)
                ),
            )
        )

    def enable_proxy_arp(self) -> None:
        """Enable Proxy ARP on root namespace interface (retryable restoration).

        Invariants (I-PA-1 .. I-PA-5):
        I-PA-1. If the interface-level write succeeds, an exact-prior-value
                restoration is appended to ``cleanup_actions`` immediately.
        I-PA-2. If the all-level write then fails AND the immediate rollback
                of the interface-level write also fails, the iface
                restoration entry remains in ``cleanup_actions`` (NOT removed)
                so a later ``cleanup()`` can retry it.
        I-PA-3. ``BridgeManager.cleanup()`` retries every retained mandatory
                action across calls (see ``cleanup()`` retention semantics).
        I-PA-4. Successful retry removes the retained action.
        I-PA-5. The raised exception preserves BOTH the all-write failure
                detail AND the rollback-failure detail.
        """
        self.get_or_create_root()
        runner = self._root_runner()
        if self.root_intf is None:
            info("*** Warning: root interface not set, cannot enable proxy ARP\n")
            return

        root_intf_name = str(self.root_intf)

        read_iface = runner.run(
            ROOT_SENTINEL,
            ["sysctl", "-n", f"net.ipv4.conf.{root_intf_name}.proxy_arp"],
            capture_stderr=True,
        )
        if read_iface.returncode != 0:
            raise RuntimeError(
                f"failed to read proxy_arp for {root_intf_name} "
                f"(rc={read_iface.returncode}): {(read_iface.stderr or '').strip()}"
            )
        prior_iface = read_iface.stdout.strip()
        if prior_iface not in ("0", "1"):
            raise RuntimeError(
                f"invalid proxy_arp value '{prior_iface}' for {root_intf_name}"
            )

        read_all = runner.run(
            ROOT_SENTINEL,
            ["sysctl", "-n", "net.ipv4.conf.all.proxy_arp"],
            capture_stderr=True,
        )
        if read_all.returncode != 0:
            raise RuntimeError(
                f"failed to read proxy_arp all (rc={read_all.returncode}): "
                f"{(read_all.stderr or '').strip()}"
            )
        prior_all = read_all.stdout.strip()
        if prior_all not in ("0", "1"):
            raise RuntimeError(f"invalid proxy_arp value '{prior_all}' for all")

        info(f"*** Proxy ARP: sysctl -w net.ipv4.conf.{root_intf_name}.proxy_arp=1\n")
        write_iface = runner.run(
            ROOT_SENTINEL,
            ["sysctl", "-w", f"net.ipv4.conf.{root_intf_name}.proxy_arp=1"],
            capture_stderr=True,
        )
        if write_iface.returncode != 0:
            raise RuntimeError(
                f"failed to enable proxy_arp for {root_intf_name} "
                f"(rc={write_iface.returncode}): {(write_iface.stderr or '').strip()}"
            )

        # I-PA-1: register the exact-prior-value restoration immediately after
        # the iface write succeeded.
        iface_restore = CleanupAction(
            description=f"restore proxy_arp {root_intf_name} to {prior_iface}",
            category="proxy_arp",
            mandatory=True,
            execute=lambda r=runner, pv=prior_iface: _result_to_rc_detail(
                r.run(
                    ROOT_SENTINEL,
                    ["sysctl", "-w", f"net.ipv4.conf.{root_intf_name}.proxy_arp={pv}"],
                    capture_stderr=True,
                )
            ),
        )
        self.cleanup_actions.append(iface_restore)

        info("*** Proxy ARP: sysctl -w net.ipv4.conf.all.proxy_arp=1\n")
        write_all = runner.run(
            ROOT_SENTINEL,
            ["sysctl", "-w", "net.ipv4.conf.all.proxy_arp=1"],
            capture_stderr=True,
        )
        if write_all.returncode != 0:
            setup_err = (
                f"failed to enable proxy_arp all (rc={write_all.returncode}): "
                f"{(write_all.stderr or '').strip()}"
            )
            # Immediate rollback attempt via the same status-aware helper.
            try:
                rb_rc, rb_detail = iface_restore.execute()
            except Exception as exc:
                # Rollback raised. Keep the action so cleanup() retries it
                # (I-PA-2). Surface BOTH setup and rollback details (I-PA-5).
                raise RuntimeError(
                    f"{setup_err}; iface rollback raised: {exc}"
                ) from exc
            if rb_rc == 0:
                # Rollback succeeded — remove the now-no-op action.
                try:
                    self.cleanup_actions.remove(iface_restore)
                except ValueError:
                    pass
                raise RuntimeError(setup_err)
            # Rollback failed via non-zero rc. Retain the action (I-PA-2)
            # and surface both details (I-PA-5).
            raise RuntimeError(
                f"{setup_err}; iface rollback failed (rc={rb_rc}): {rb_detail}"
            )

        # On success, append the all-level restoration. Final append order is
        # `iface_restore` then `all_restore`; cleanup() iterates
        # `reversed(cleanup_actions)`, so teardown runs all first, then iface
        # (LIFO matching setup).
        self.cleanup_actions.append(
            CleanupAction(
                description=f"restore proxy_arp all to {prior_all}",
                category="proxy_arp",
                mandatory=True,
                execute=lambda r=runner, pv=prior_all: _result_to_rc_detail(
                    r.run(
                        ROOT_SENTINEL,
                        ["sysctl", "-w", f"net.ipv4.conf.all.proxy_arp={pv}"],
                        capture_stderr=True,
                    )
                ),
            )
        )

    def cleanup(self) -> None:
        """Execute all registered cleanup actions in reverse order.

        Mandatory failures are aggregated into ``TeardownError``; best-effort
        failures are logged but not fatal.

        Retention semantic (contract #3 in the remediation plan):
        - Successful actions (rc == 0, no exception) are dropped.
        - Best-effort actions that fail are dropped (logged once).
        - Mandatory actions that fail (raise or return rc != 0) are RETAINED
          in ``cleanup_actions`` so a later ``cleanup()`` call retries them.
        """
        failures: list[tuple[str, int, str]] = []
        retained_reversed: list[CleanupAction] = []

        for action in reversed(self.cleanup_actions):
            try:
                rc, detail = action.execute()
            except Exception as exc:
                if action.mandatory:
                    failures.append((action.description, -1, str(exc)))
                    retained_reversed.append(action)
                else:
                    info(
                        f"[warning] cleanup best-effort failure: "
                        f"{action.description}: {exc}\n"
                    )
                continue

            if rc != 0:
                if action.mandatory:
                    failures.append((action.description, rc, detail))
                    retained_reversed.append(action)
                else:
                    info(
                        f"[warning] cleanup best-effort failure: "
                        f"{action.description} (rc={rc})\n"
                    )
            # rc == 0 → successful; action dropped (not retained)

        # `retained_reversed` is in reverse iteration order; flip back so the
        # next `cleanup()` reverses-iterates in the same logical order.
        self.cleanup_actions = list(reversed(retained_reversed))

        if failures:
            raise TeardownError(failures)


def extract_gateway_from_ip(ip_with_prefix: str) -> str:
    """Extract gateway IP from IP/prefix notation.

    For "192.168.100.1/24", returns "192.168.100.1".
    """
    return ip_with_prefix.split("/")[0]


def _resolve_root_ip(
    switch_name: str,
    root_ip: str | None,
    mesh_links: list[dict[str, Any]] | None,
    scheme: AddressingScheme | None = None,
) -> str | None:
    """Auto-resolve root IP from mesh link subnet if set to 'auto'."""
    if root_ip and root_ip != "auto":
        return root_ip
    if not mesh_links:
        return root_ip
    if scheme is None:
        scheme = AddressingScheme()
    subnet = TopologyModel(mesh_links).subnet_of_switch(switch_name)
    if subnet is not None:
        return scheme.root_gateway(subnet)
    return root_ip


def _find_host_intf(
    mesh_links: list[dict[str, Any]] | None,
    host_idx: int,
    switch_name: str,
) -> str | None:
    """Find the host interface connected to a specific switch."""
    if not mesh_links:
        return None
    for link in TopologyModel(mesh_links).links:
        if link.switch == switch_name and host_idx in link.host_eth:
            return f"h{host_idx}-eth{link.eth_of(host_idx)}"
    return None


def setup_bridges(
    net: Mininet,
    bridge_manager: BridgeManager,
    bridge_configs: list[dict[str, Any]],
    host_num: int,
    mesh_links: list[dict[str, Any]] | None = None,
    scheme: AddressingScheme | None = None,
) -> None:
    """Set up all bridge configurations.

    Args:
        net: Mininet network instance.
        bridge_manager: BridgeManager instance to use.
        bridge_configs: List of bridge configuration dicts.
        host_num: Total number of hosts in the network.
        mesh_links: Optional mesh link info for auto-resolving IPs and interfaces.
        scheme: AddressingScheme for IP generation (defaults to 192.168.0.0/16).
    """
    for config in bridge_configs:
        # 2026-07-16 audit fix: YAML bridges give switch as an integer index
        # (the config validator requires int), but Mininet switches are named
        # sN — without translation net.get(0) raises KeyError. CLI-parsed
        # configs already carry the sN string and pass through unchanged.
        switch = config["switch"]
        if isinstance(switch, int):
            switch = f"s{switch}"
        root_ip = _resolve_root_ip(
            switch, config.get("root_ip"), mesh_links, scheme=scheme
        )
        if not root_ip:
            info(f"*** Warning: root_ip not set for switch {switch}\n")
            continue
        local_routes = config["local_routes"]

        # 2026-07-21 review fix: when attachment fails (emergent topology
        # lacks the switch), skip the WHOLE entry — continuing would issue
        # ovs-ofctl against the missing switch, register bogus cleanup
        # actions, and mutate unrelated routing/NAT state.
        if bridge_manager.connect_to_root_ns(
            net, switch, root_ip, local_routes
        ) is False:
            info(f"*** Skipping bridge entry for missing switch {switch}\n")
            continue
        bridge_manager.enable_normal_flow(net, switch)

        gateway = extract_gateway_from_ip(root_ip)

        hosts = config.get("hosts")
        if hosts is None:
            hosts = list(range(host_num))

        external_routes = config.get("external_routes")
        ext_gateway = config.get("gateway")

        if external_routes:
            if ext_gateway:
                bridge_manager.add_root_route(external_routes, ext_gateway)

            for host_idx in hosts:
                host_name = f"h{host_idx}"
                dev = _find_host_intf(mesh_links, host_idx, switch)
                bridge_manager.add_host_route(
                    net,
                    host_name,
                    external_routes,
                    gateway,
                    dev=dev,
                )

            # Route through the bridge manager's host runner so an injected
            # (fake) runner intercepts the write instead of truncating the real
            # /etc/resolv.conf.
            resolv_runner = bridge_manager._host_runner(net)
            for host_idx in hosts:
                # The seam owns the redirect: printf's stdout is written to the
                # (host-shared) /etc/resolv.conf via log_path, replacing the old
                # shell "echo ... > /etc/resolv.conf".
                resolv_runner.run(
                    f"h{host_idx}",
                    ["printf", "nameserver 8.8.8.8\n"],
                    log_path="/etc/resolv.conf",
                    capture_stderr=True,
                )

        use_nat = config.get("nat", False)
        if use_nat:
            bridge_manager.enable_ip_forwarding()
            nat_out = config.get("nat_out")
            bridge_manager.enable_nat(local_routes, nat_out)

        use_proxy_arp = config.get("proxy_arp", False)
        if use_proxy_arp:
            bridge_manager.enable_proxy_arp()

        vm_host_network = config.get("vm_host_network")
        if vm_host_network:
            for host_idx in hosts:
                host_name = f"h{host_idx}"
                dev = _find_host_intf(mesh_links, host_idx, switch)
                bridge_manager.add_host_route(
                    net,
                    host_name,
                    vm_host_network,
                    gateway,
                    dev=dev,
                )
