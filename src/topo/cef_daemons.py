"""Cefore daemon control functions."""

import time

from mininet.log import info

from .config_io import cleanup_cefnetd_socket


def wait_for_cefnetd(net, idx, timeout=5, interval=0.25):
    """Wait for cefnetd to become ready.

    Args:
        net: Mininet network instance.
        idx: Host index.
        timeout: Maximum wait time in seconds.
        interval: Check interval in seconds.

    Returns:
        True if ready, False if timeout.
    """
    node_name = f"h{idx}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = net.hosts[idx].cmd(
            f"sh -c 'cefstatus -d ./{node_name} >/dev/null 2>&1; echo $?'"
        )
        if result.strip().endswith("0"):
            return True
        time.sleep(interval)
    info(f"{node_name} cefnetd not ready; check {node_name}-cefnetd-log\n")
    return False


def start_csmgrd(net, idx):
    """Start cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    node_name = f"h{idx}"
    command = f"csmgrdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_csmgrd(net, idx):
    """Stop cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    command = f"csmgrdstop -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def start_cefnetd(net, idx):
    """Start cefnetd forwarding daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    node_name = f"h{idx}"
    cleanup_cefnetd_socket(node_name, idx)
    command = f"cefnetdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_cefnetd(net, idx):
    """Stop cefnetd forwarding daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    command = f"cefnetdstop -F -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def run_cefputfile(net, host_idx, uri):
    """Run cefputfile to publish content.

    Args:
        net: Mininet network instance.
        host_idx: Publisher host index.
        uri: Content URI.
    """
    node_name = f"h{host_idx}"
    command = (
        f"cefputfile {uri} -f ./sample-putfile -t 3000 -e 3000 -d ./{node_name} "
        "> cefputfile-log"
    )
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefgetfile(net, host_idx, uri, output_path):
    """Run cefgetfile to retrieve content.

    Args:
        net: Mininet network instance.
        host_idx: Consumer host index.
        uri: Content URI.
        output_path: Path to save retrieved file.
    """
    node_name = f"h{host_idx}"
    command = f"cefgetfile {uri} -f {output_path} -d ./{node_name} > cefgetfile-log"
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefstatus(net, host_idx):
    """Run cefstatus to display FIB state.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
    """
    node_name = f"h{host_idx}"
    command = f"cefstatus -d ./{node_name}"
    print(node_name, "command:", command)
    info(net.hosts[host_idx].cmd(command))


def run_cefstatus_all(net, host_num):
    """Run cefstatus for all hosts.

    Args:
        net: Mininet network instance.
        host_num: Total number of hosts.
    """
    info("\nFIB status per host:\n")
    for host_idx in range(host_num):
        run_cefstatus(net, host_idx)
