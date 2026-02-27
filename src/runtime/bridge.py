"""External interface bridge operations (extracted from disaster.py)."""

import subprocess

from mininet.log import info

# Track created bridges for cleanup
_created_bridges = {}


def _run_root_cmd(cmd):
    """Run command in root namespace."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr:
        info(f"[bridge] cmd failed: {cmd}\n  stderr: {result.stderr}\n")
    return result.returncode == 0


def attach_external_via_bridge(net, host_name, phy_intf, ip=None, mtu=None):
    """Attach host to external network via Linux bridge (does not hijack NIC).

    Creates a Linux bridge, enslaves the physical interface, and connects
    the Mininet host via a veth pair.

    Args:
        net: Mininet network instance.
        host_name: Host name to attach (e.g., "h0").
        phy_intf: Physical interface name on host machine (e.g., "eth0").
        ip: Optional static IP (CIDR format). If None, runs dhclient.
        mtu: Optional MTU to set on bridge and veth.
    """
    bridge_name = f"br-{host_name}"
    veth_root = f"veth-{host_name}-root"
    veth_host = f"veth-{host_name}"

    host = net.get(host_name)
    if host is None:
        info(f"[bridge] host {host_name} not found\n")
        return

    info(f"[bridge] creating bridge {bridge_name} for {host_name} via {phy_intf}\n")

    _run_root_cmd(f"ip link add {bridge_name} type bridge")
    _run_root_cmd(f"ip link set {bridge_name} up")
    _run_root_cmd(f"ip link set {phy_intf} up")
    _run_root_cmd(f"ip link set {phy_intf} master {bridge_name}")
    _run_root_cmd(f"ip link add {veth_root} type veth peer name {veth_host}")
    _run_root_cmd(f"ip link set {veth_root} master {bridge_name}")
    _run_root_cmd(f"ip link set {veth_root} up")
    _run_root_cmd(f"ip link set {veth_host} up")

    host_pid = host.pid
    _run_root_cmd(f"ip link set {veth_host} netns {host_pid}")
    host.cmd(f"ip link set {veth_host} up")

    if mtu:
        _run_root_cmd(f"ip link set {bridge_name} mtu {mtu}")
        _run_root_cmd(f"ip link set {veth_root} mtu {mtu}")
        host.cmd(f"ip link set {veth_host} mtu {mtu}")

    if ip:
        host.cmd(f"ip addr add {ip} dev {veth_host}")
        info(f"[bridge] {host_name}: static IP {ip} on {veth_host}\n")
    else:
        info(f"[bridge] {host_name}: starting dhclient on {veth_host}\n")
        host.cmd(f"dhclient -v {veth_host} &")

    _created_bridges[host_name] = {
        "bridge": bridge_name,
        "veth_root": veth_root,
        "veth_host": veth_host,
        "phy_intf": phy_intf,
    }

    info(f"[bridge] attached {host_name} to {phy_intf} via bridge {bridge_name}\n")


def cleanup_external_bridges():
    """Clean up all created bridges and veth pairs."""
    for host_name, info_dict in list(_created_bridges.items()):
        bridge_name = info_dict["bridge"]
        veth_root = info_dict["veth_root"]
        phy_intf = info_dict["phy_intf"]

        info(f"[bridge] cleaning up {bridge_name}\n")
        _run_root_cmd(f"ip link set {phy_intf} nomaster")
        _run_root_cmd(f"ip link del {veth_root} 2>/dev/null")
        _run_root_cmd(f"ip link set {bridge_name} down")
        _run_root_cmd(f"ip link del {bridge_name}")

    _created_bridges.clear()


def attach_external_interface(net, host_name, intf_name, ip=None, mtu=None):
    """Attach external interface to a host via bridge (backward compatible)."""
    attach_external_via_bridge(net, host_name, intf_name, ip, mtu)


def parse_ext_args(values):
    """Parse external interface arguments.

    Args:
        values: List of "host,ifname[,ip][,mtu]" strings.

    Returns:
        List of (host_name, intf_name, ip, mtu) tuples.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) not in (2, 3, 4):
            raise ValueError("ext format is host,ifname[,ip][,mtu]")
        host_name = parts[0]
        intf_name = parts[1]
        ip = parts[2] if len(parts) >= 3 and parts[2] else None
        mtu = int(parts[3]) if len(parts) == 4 and parts[3] else None
        entries.append((host_name, intf_name, ip, mtu))
    return entries
