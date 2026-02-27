"""Cefore daemon control functions."""

import time

from mininet.log import info

from .template import cleanup_cefnetd_socket


def wait_for_cefnetd(net, idx, timeout=5, interval=0.25):
    """Wait for cefnetd to become ready.

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
    """Start cache manager daemon for a host."""
    node_name = f"h{idx}"
    command = f"csmgrdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_csmgrd(net, idx):
    """Stop cache manager daemon for a host."""
    command = f"csmgrdstop -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def start_cefnetd(net, idx):
    """Start cefnetd forwarding daemon for a host."""
    node_name = f"h{idx}"
    cleanup_cefnetd_socket(node_name, idx)
    command = f"cefnetdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_cefnetd(net, idx):
    """Stop cefnetd forwarding daemon for a host."""
    command = f"cefnetdstop -F -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def run_cefputfile(net, host_idx, uri):
    """Run cefputfile to publish content."""
    node_name = f"h{host_idx}"
    command = (
        f"cefputfile {uri} -f ./sample-putfile -t 3000 -e 3000 -d ./{node_name} "
        "> cefputfile-log"
    )
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefgetfile(
    net,
    host_idx,
    uri,
    output_path,
    log_path=None,
    wait_for_down=None,
    wait_timeout=5.0,
    log_path_factory=None,
):
    """Run cefgetfile to retrieve content.

    Args:
        net: Mininet network instance.
        host_idx: Consumer host index.
        uri: Content URI.
        output_path: Path to save retrieved file.
        log_path: Path for log output.
        wait_for_down: Optional FlapState object or dict with "down_hosts" key.
        wait_timeout: Max seconds to wait for down state.
        log_path_factory: Optional callback fn(down_hosts_snapshot) -> log_path.

    Returns:
        Tuple of (exit_code, down_hosts_snapshot, chosen_log_path).
    """
    node_name = f"h{host_idx}"

    snapshot = []
    if wait_for_down is not None:
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            if hasattr(wait_for_down, "snapshot"):
                snapshot = wait_for_down.snapshot()
            elif isinstance(wait_for_down, dict):
                snapshot = list(wait_for_down.get("down_hosts") or [])
            elif hasattr(wait_for_down, "get"):
                snapshot = list(wait_for_down.get("down_hosts") or [])
            else:
                snapshot = []

            if snapshot:
                break
            time.sleep(0.1)

        if not snapshot:
            if hasattr(wait_for_down, "snapshot"):
                snapshot = wait_for_down.snapshot()
            elif isinstance(wait_for_down, dict):
                snapshot = list(wait_for_down.get("down_hosts") or [])
            elif hasattr(wait_for_down, "get"):
                snapshot = list(wait_for_down.get("down_hosts") or [])

    if log_path_factory:
        chosen_log = log_path_factory(snapshot)
    else:
        chosen_log = log_path if log_path else "cefgetfile.log"

    command = f"cefgetfile {uri} -f {output_path} -d ./{node_name} > {chosen_log}"
    print(node_name, "command:", command)
    proc = net.hosts[host_idx].popen(command, shell=True)
    exit_code = proc.wait()

    return exit_code, list(snapshot), chosen_log


def run_cefstatus(net, host_idx):
    """Run cefstatus to display FIB state."""
    node_name = f"h{host_idx}"
    command = f"cefstatus -d ./{node_name}"
    print(node_name, "command:", command)
    info(net.hosts[host_idx].cmd(command))


def run_cefstatus_all(net, host_num):
    """Run cefstatus for all hosts."""
    info("\nFIB status per host:\n")
    for host_idx in range(host_num):
        run_cefstatus(net, host_idx)
