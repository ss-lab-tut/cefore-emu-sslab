"""Bridge operations for external network connectivity.

Provides two bridging mechanisms:
- Linux bridge: attach_external_via_bridge() for direct NIC bridging
- Root namespace bridge: BridgeManager for cross-VM communication via Mininet switches
"""

from dataclasses import dataclass
from typing import Any, Callable

from mininet.log import info
from mininet.net import Mininet
from mininet.node import Node

from ..core.addressing import AddressingScheme
from ..core.topology import TopologyModel
from .bridge_args import validate_static_ip as _validate_static_ip
from .command_runner import ROOT_SENTINEL, MininetCommandRunner


# ---------------------------------------------------------------------------
# Cleanup action model
# ---------------------------------------------------------------------------


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
# Linux bridge functions (attach physical NIC to Mininet host)
# ---------------------------------------------------------------------------

# Track created Linux bridges for cleanup (ownership-aware)
_created_bridges: dict[str, dict] = {}


class ExternalBridgeError(RuntimeError):
    """External bridge setup or cleanup failure with structured details.

    Attributes:
        setup_failure: Original setup failure message (if any).
        rollback_failures: List of (action, error) from rollback attempts.
    """

    def __init__(
        self,
        setup_failure: str | None = None,
        rollback_failures: list[tuple[str, str]] | None = None,
    ):
        self.setup_failure = setup_failure
        self.rollback_failures = rollback_failures or []
        msgs = [setup_failure] if setup_failure else []
        msgs.extend(f"rollback {a}: {e}" for a, e in self.rollback_failures)
        super().__init__("; ".join(msgs))


# ---------------------------------------------------------------------------
# Status-aware root command execution
# ---------------------------------------------------------------------------


def _run_root_cmd_vec(args: list[str]) -> tuple[int, str, str]:
    """Execute a command in the root namespace through the CommandRunner seam.

    Args:
        args: Command and arguments as a list (no shell).

    Returns:
        Tuple of (returncode, stdout, stderr).
    """
    result = MininetCommandRunner(None).run(
        ROOT_SENTINEL, list(args), capture_stderr=True
    )
    rc = result.returncode if result.returncode is not None else 0
    return rc, result.stdout, result.stderr


def _run_host_cmd_vec(runner, host_name: str, argv: list[str]) -> tuple[str, str, int]:
    """Execute a command inside a Mininet host namespace via the runner.

    Args:
        runner: CommandRunner used to execute the command.
        host_name: Target host node name (e.g. "h3").
        argv: Command and arguments as a list (no shell).

    Returns:
        Tuple of (stdout, stderr, returncode).
    """
    result = runner.run(host_name, argv, capture_stderr=True)
    rc = result.returncode if result.returncode is not None else 0
    return result.stdout, result.stderr, rc


# ---------------------------------------------------------------------------
# Physical interface inspection helpers
# ---------------------------------------------------------------------------


def _inspect_link(phy_intf: str) -> tuple[bool, dict | None, str]:
    """Inspect a physical interface via ip -j link show."""
    rc, out, err = _run_root_cmd_vec(["ip", "-j", "link", "show", "dev", phy_intf])
    if rc != 0:
        return False, None, f"ip link show {phy_intf} failed (rc={rc}): {err.strip()}"
    try:
        import json as _json

        data = _json.loads(out)
        if not isinstance(data, list) or not data:
            return False, None, f"ip link show {phy_intf} returned empty result"
        return True, data[0], ""
    except (_json.JSONDecodeError, ValueError) as exc:
        return False, None, f"ip link show {phy_intf} parse error: {exc}"


def _inspect_addresses(phy_intf: str) -> tuple[bool, list[dict] | None, str]:
    """Inspect addresses on a physical interface via ip -j addr show."""
    rc, out, err = _run_root_cmd_vec(["ip", "-j", "addr", "show", "dev", phy_intf])
    if rc != 0:
        return False, None, f"ip addr show {phy_intf} failed (rc={rc}): {err.strip()}"
    try:
        import json as _json

        data = _json.loads(out)
        if not isinstance(data, list) or not data:
            return True, [], ""
        return True, data[0].get("addr_info", []), ""
    except (_json.JSONDecodeError, ValueError) as exc:
        return False, None, f"ip addr show {phy_intf} parse error: {exc}"


# ---------------------------------------------------------------------------
# External bridge attachment with transactional safety
# ---------------------------------------------------------------------------


def _get_admin_up(link_data: dict) -> bool | None:
    """Determine administrative UP/DOWN state from interface flags."""
    flags = link_data.get("flags")
    if flags is None:
        return None
    if not isinstance(flags, list):
        return None
    return "UP" in flags


def attach_external_via_bridge(
    net: Mininet,
    host_name: str,
    phy_intf: str,
    ip: str | None = None,
    mtu: int | None = None,
) -> None:
    """Attach host to external network via Linux bridge.

    Transactional: if any mutation fails, previously-completed mutations
    are rolled back in reverse order. DHCP is not supported; a static
    IP is required in CIDR form.
    """
    if not ip:
        raise RuntimeError(
            f"static IP required for external bridge attachment of {host_name}; "
            "DHCP mode is not supported"
        )

    _validate_static_ip(ip)

    bridge_name = f"br-{host_name}"
    veth_root = f"veth-{host_name}-root"
    veth_host = f"veth-{host_name}"

    if len(bridge_name) > 15 or len(veth_root) > 15 or len(veth_host) > 15:
        raise RuntimeError(
            f"generated interface names exceed 15-character limit: "
            f"bridge={bridge_name!r}({len(bridge_name)}), "
            f"veth_root={veth_root!r}({len(veth_root)}), "
            f"veth_host={veth_host!r}({len(veth_host)})"
        )

    if host_name in _created_bridges:
        raise RuntimeError(
            f"active attachment already exists for {host_name}; "
            f"run cleanup_external_bridges() first"
        )

    # Reject pre-mutation if any existing record (including rollback-failed
    # retained records) already owns the requested physical interface.
    for existing_host, existing_record in _created_bridges.items():
        if existing_record.get("phy_intf") == phy_intf and existing_host != host_name:
            raise RuntimeError(
                f"physical interface {phy_intf} is already attached via active "
                f"external bridge for host {existing_host}; "
                f"run cleanup_external_bridges() first"
            )

    host = net.get(host_name)
    if host is None:
        info(f"[bridge] host {host_name} not found\n")
        return
    host_runner = MininetCommandRunner(net)

    success, link_data, err = _inspect_link(phy_intf)
    if not success:
        raise RuntimeError(f"cannot inspect {phy_intf}: {err}")

    master = link_data.get("master") or link_data.get("bridge")
    if master:
        raise RuntimeError(
            f"{phy_intf} already enslaved to {master}; cannot reassign to new bridge"
        )

    addr_success, addrs, addr_err = _inspect_addresses(phy_intf)
    if not addr_success:
        raise RuntimeError(f"cannot inspect addresses on {phy_intf}: {addr_err}")
    for addr_info in addrs or []:
        addr = addr_info.get("local", "")
        if addr and not addr.startswith("169.254."):
            raise RuntimeError(
                f"{phy_intf} has configured address {addr}; "
                f"refusing to mutate non-clean interface"
            )

    prior_up = _get_admin_up(link_data)
    if prior_up is None:
        raise RuntimeError(
            f"cannot determine administrative state of {phy_intf}; "
            f"flags field missing or invalid"
        )

    record: dict = {
        "bridge": bridge_name,
        "veth_root": veth_root,
        "veth_host": veth_host,
        "phy_intf": phy_intf,
        "prior_up": prior_up,
        "bridge_created": False,
        "bridge_up": False,
        "phy_up_changed": False,
        "phy_enslaved": False,
        "veth_created": False,
        "veth_root_mastered": False,
        "veth_root_up": False,
        "veth_host_ns_moved": False,
        "veth_host_up": False,
        "mtu_set": False,
        "ip_assigned": False,
    }
    _created_bridges[host_name] = record

    rollback_actions: list[_RollbackAction] = []

    def _commit_record() -> None:
        record["rollback_actions"] = list(rollback_actions)

    def _abort(reason: str) -> "list[tuple[str, str]]":
        """Run rollback for `reason` and pop the record iff fully discharged."""
        rb_failures = _rollback(rollback_actions, record, reason)
        if not _record_has_outstanding_state(record):
            _created_bridges.pop(host_name, None)
        return rb_failures

    info(f"[bridge] creating bridge {bridge_name} for {host_name} via {phy_intf}\n")

    rc, _, err = _run_root_cmd_vec(["ip", "link", "add", bridge_name, "type", "bridge"])
    if rc != 0:
        _created_bridges.pop(host_name, None)
        raise RuntimeError(f"bridge creation failed (rc={rc}): {err.strip()}")
    record["bridge_created"] = True
    rollback_actions.append(
        _RollbackAction(
            "delete bridge",
            lambda: _rollback_del_link(bridge_name),
            ("bridge_created", "bridge_up"),
        )
    )

    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", bridge_name, "up"])
    if rc != 0:
        rb_failures = _abort("bridge-up failure")
        raise ExternalBridgeError("bridge-up failure", rb_failures)
    record["bridge_up"] = True

    if not prior_up:
        rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "up"])
        if rc != 0:
            rb_failures = _abort("phy-up failure")
            raise ExternalBridgeError("phy-up failure", rb_failures)
        record["phy_up_changed"] = True
        # Register restore-DOWN immediately after phy-up succeeds, BEFORE the
        # enslave attempt, so an enslave failure still triggers DOWN
        # restoration via rollback. (Defect 2.)
        rollback_actions.append(
            _RollbackAction(
                "restore phy DOWN",
                lambda: _rollback_set_link(phy_intf, "down"),
                ("phy_up_changed",),
            )
        )

    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "set", phy_intf, "master", bridge_name]
    )
    if rc != 0:
        rb_failures = _abort("phy-enslave failure")
        raise ExternalBridgeError("phy-enslave failure", rb_failures)
    record["phy_enslaved"] = True
    rollback_actions.append(
        _RollbackAction(
            "unmaster phy",
            lambda: _rollback_unmaster(phy_intf),
            ("phy_enslaved",),
        )
    )

    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "add", veth_root, "type", "veth", "peer", "name", veth_host]
    )
    if rc != 0:
        rb_failures = _abort("veth creation failure")
        raise ExternalBridgeError("veth creation failure", rb_failures)
    record["veth_created"] = True
    rollback_actions.append(
        _RollbackAction(
            "delete veth",
            lambda: _rollback_del_link(veth_root),
            (
                "veth_created",
                "veth_root_mastered",
                "veth_root_up",
                "veth_host_ns_moved",
                "veth_host_up",
                "mtu_set",
                "ip_assigned",
            ),
        )
    )

    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "set", veth_root, "master", bridge_name]
    )
    if rc != 0:
        rb_failures = _abort("veth-root-master failure")
        raise ExternalBridgeError("veth-root-master failure", rb_failures)
    record["veth_root_mastered"] = True

    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", veth_root, "up"])
    if rc != 0:
        rb_failures = _abort("veth-root-up failure")
        raise ExternalBridgeError("veth-root-up failure", rb_failures)
    record["veth_root_up"] = True

    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", veth_host, "up"])
    if rc != 0:
        rb_failures = _abort("veth-host-up failure")
        raise ExternalBridgeError("veth-host-up failure", rb_failures)

    host_pid = host.pid
    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "set", veth_host, "netns", str(host_pid)]
    )
    if rc != 0:
        rb_failures = _abort("veth-host-ns-move failure")
        raise ExternalBridgeError("veth-host-ns-move failure", rb_failures)
    record["veth_host_ns_moved"] = True

    out, err, rc = _run_host_cmd_vec(
        host_runner, host_name, ["ip", "link", "set", veth_host, "up"]
    )
    if rc != 0:
        record["veth_host_up_failed"] = True
        rb_failures = _abort("veth-host-up-in-ns failure")
        raise ExternalBridgeError("veth-host-up-in-ns failure", rb_failures)
    record["veth_host_up"] = True

    if mtu:
        rc, _, err = _run_root_cmd_vec(
            ["ip", "link", "set", bridge_name, "mtu", str(mtu)]
        )
        if rc != 0:
            rb_failures = _abort("bridge-mtu failure")
            raise ExternalBridgeError("bridge-mtu failure", rb_failures)
        rc, _, err = _run_root_cmd_vec(
            ["ip", "link", "set", veth_root, "mtu", str(mtu)]
        )
        if rc != 0:
            rb_failures = _abort("veth-root-mtu failure")
            raise ExternalBridgeError("veth-root-mtu failure", rb_failures)
        out, err, rc = _run_host_cmd_vec(
            host_runner, host_name, ["ip", "link", "set", veth_host, "mtu", str(mtu)]
        )
        if rc != 0:
            rb_failures = _abort("veth-host-mtu failure")
            raise ExternalBridgeError("veth-host-mtu failure", rb_failures)
        record["mtu_set"] = True

    out, err, rc = _run_host_cmd_vec(
        host_runner, host_name, ["ip", "addr", "add", ip, "dev", veth_host]
    )
    if rc != 0:
        rb_failures = _abort("static-ip failure")
        raise ExternalBridgeError("static-ip failure", rb_failures)
    record["ip_assigned"] = True
    info(f"[bridge] {host_name}: static IP {ip} on {veth_host}\n")

    _commit_record()
    info(f"[bridge] attached {host_name} to {phy_intf} via bridge {bridge_name}\n")


def cleanup_external_bridges() -> None:
    """Clean up all created Linux bridges and veth pairs.

    Cleanup invariant: attempts every cleanup step whose outstanding flag is
    still True. Each successful step clears only the flag(s) for the state
    it actually removes. A failed step records a failure but does NOT
    prevent later independent cleanup steps from being attempted. The host
    record is retained iff `_record_has_outstanding_state(record)` is True.

    Raises ``ExternalBridgeError`` if any cleanup step failed.
    """
    failures: list[tuple[str, str]] = []

    for host_name, record in list(_created_bridges.items()):
        host_name = str(host_name)
        bridge_name = record.get("bridge", f"br-{host_name}")
        veth_root = record.get("veth_root", f"veth-{host_name}-root")
        phy_intf = record.get("phy_intf", "")

        info(f"[bridge] cleaning up {bridge_name}\n")

        # veth deletion cascades — clears all veth-pair-dependent flags
        if record.get("veth_created"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "del", veth_root])
            if rc != 0:
                failures.append((f"del {veth_root}", err.strip()))
            else:
                for flag in (
                    "veth_created",
                    "veth_root_mastered",
                    "veth_root_up",
                    "veth_host_ns_moved",
                    "veth_host_up",
                    "mtu_set",
                    "ip_assigned",
                ):
                    record[flag] = False

        # unmaster — clears only phy_enslaved
        if record.get("phy_enslaved"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "nomaster"])
            if rc != 0:
                failures.append((f"unmaster {phy_intf}", err.strip()))
            else:
                record["phy_enslaved"] = False

        # phy down — clears only phy_up_changed
        if record.get("phy_up_changed"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "down"])
            if rc != 0:
                failures.append((f"down {phy_intf}", err.strip()))
            else:
                record["phy_up_changed"] = False

        # bridge down — independent gate, clears only bridge_up
        if record.get("bridge_up"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "set", bridge_name, "down"])
            if rc != 0:
                failures.append((f"down {bridge_name}", err.strip()))
            else:
                record["bridge_up"] = False

        # bridge del — clears bridge_created (and bridge_up defensively)
        if record.get("bridge_created"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "del", bridge_name])
            if rc != 0:
                failures.append((f"del {bridge_name}", err.strip()))
            else:
                record["bridge_created"] = False
                record["bridge_up"] = False  # del implies down

        if not _record_has_outstanding_state(record):
            _created_bridges.pop(host_name, None)

    if failures:
        raise ExternalBridgeError(rollback_failures=failures)


def attach_external_interface(net, host_name, intf_name, ip=None, mtu=None):
    """Attach external interface to a host via bridge (backward compatible)."""
    attach_external_via_bridge(net, host_name, intf_name, ip, mtu)


# ---------------------------------------------------------------------------
# Rollback helpers
# ---------------------------------------------------------------------------


def _rollback_del_link(name: str) -> None:
    """Delete a network link."""
    rc, _, err = _run_root_cmd_vec(["ip", "link", "del", name])
    if rc != 0:
        raise RuntimeError(f"rollback del {name} failed (rc={rc}): {err.strip()}")


def _rollback_unmaster(phy_intf: str) -> None:
    """Remove physical interface from bridge master."""
    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "nomaster"])
    if rc != 0:
        raise RuntimeError(
            f"rollback unmaster {phy_intf} failed (rc={rc}): {err.strip()}"
        )


def _rollback_set_link(name: str, state: str) -> None:
    """Set link administrative state."""
    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", name, state])
    if rc != 0:
        raise RuntimeError(
            f"rollback set {name} {state} failed (rc={rc}): {err.strip()}"
        )


# Outstanding-state flags for _created_bridges records. The record is retained
# while any of these is True; cleared as their corresponding cleanup or
# rollback action succeeds (cleanup invariant / setup rollback invariant —
# see docs in the remediation plan).
_OUTSTANDING_FLAGS = (
    "bridge_created",
    "bridge_up",
    "phy_up_changed",
    "phy_enslaved",
    "veth_created",
    "veth_root_mastered",
    "veth_root_up",
    "veth_host_ns_moved",
    "veth_host_up",
    "mtu_set",
    "ip_assigned",
)


def _record_has_outstanding_state(record: dict) -> bool:
    """True iff at least one outstanding cleanup obligation remains."""
    return any(record.get(flag) for flag in _OUTSTANDING_FLAGS)


@dataclass(frozen=True)
class _RollbackAction:
    """A single setup-rollback action paired with the outstanding flags it
    clears when its undo command runs successfully.

    `run` MUST go through a status-aware command helper (e.g.,
    `_rollback_del_link`, `_rollback_unmaster`, `_rollback_set_link`) so that
    a non-zero undo rc raises `RuntimeError` carrying the failed command and
    rc/stderr detail. `_rollback()` clears `clear_flags` on the record only
    when `run` completes without raising; a non-zero undo rc therefore leaves
    the corresponding outstanding-state flag(s) set, and the record is
    retained for retry via `_record_has_outstanding_state(record)`.
    """

    description: str
    run: Callable[[], None]
    clear_flags: tuple[str, ...]


def _rollback(
    actions: list[_RollbackAction],
    record: dict,
    reason: str,
) -> list[tuple[str, str]]:
    """Execute rollback actions in reverse order, clearing outstanding-state
    flags only for actions whose `run()` completed without raising.

    Returns list of (description, error) for any rollback failures so the
    caller can include them in `ExternalBridgeError(rollback_failures=...)`.
    """
    rollback_failures: list[tuple[str, str]] = []
    for action in reversed(actions):
        try:
            action.run()
        except Exception as exc:
            rollback_failures.append((action.description, str(exc)))
            continue
        for flag in action.clear_flags:
            record[flag] = False
    if rollback_failures:
        info(f"[bridge] rollback for {reason} had failures: {rollback_failures}\n")
    return rollback_failures


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
    ) -> None:
        """Connect Mininet hosts to root namespace via switch.

        Args:
            net: Mininet network instance.
            switch_name: Switch name to connect to root namespace.
            root_ip: IP address for root namespace node (e.g., "192.168.100.1/24").
            local_routes: Local Mininet host networks to route to.
        """
        switch = net.get(switch_name)
        if switch is None:
            info(f"*** Warning: switch {switch_name} not found\n")
            return

        _validate_static_ip(root_ip)

        root = self.get_or_create_root()
        link = net.addLink(root, switch)
        self.root_intf = link.intf1

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
        switch = config["switch"]
        root_ip = _resolve_root_ip(
            config["switch"], config.get("root_ip"), mesh_links, scheme=scheme
        )
        if not root_ip:
            info(f"*** Warning: root_ip not set for switch {switch}\n")
            continue
        local_routes = config["local_routes"]

        bridge_manager.connect_to_root_ns(net, switch, root_ip, local_routes)
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
