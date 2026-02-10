"""Cefore daemon control functions."""

import shlex
import time
from pathlib import Path

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


def start_conpubd(net, idx):
    """Start conpubd daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    node_name = f"h{idx}"
    command = f"conpubdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_conpubd(net, idx):
    """Stop conpubd daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    command = f"conpubdstop -d ./h{idx}"
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


def run_cefputfile(
    net,
    host_idx,
    uri,
    file_path="./sample-putfile",
    rate=None,
    block_size=None,
    expiry=None,
    cache_time=None,
    valid_algo=None,
    port_num=None,
    log_name=None,
):
    """Run cefputfile to publish content.

    Args:
        net: Mininet network instance.
        host_idx: Publisher host index.
        uri: Content URI.
        file_path: Path to the file to publish (default: ./sample-putfile).
        rate: Transfer rate to cefnetd (Mbps).
        block_size: Max payload length (bytes) of the Content Object.
        expiry: Lifetime (seconds) of the Content Object.
        cache_time: Period (seconds) after which cached Content Objects are deleted.
        valid_algo: Validation algorithm (crc32c or rsa-sha256).
        port_num: Port number.
        log_name: Name of the log file.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefputfile {uri} -f {shlex.quote(file_path)}"]

    if rate is not None:
        cmd_parts.append(f"-r {rate}")
    if block_size is not None:
        cmd_parts.append(f"-b {block_size}")
    if expiry is not None:
        cmd_parts.append(f"-e {expiry}")
    if cache_time is not None:
        cmd_parts.append(f"-t {cache_time}")
    if valid_algo is not None:
        cmd_parts.append(f"-v {valid_algo}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefputfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(str(log_name))} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefgetfile(
    net,
    host_idx,
    uri,
    output_path,
    owner_only=False,
    chunk=None,
    pipeline=None,
    valid_algo=None,
    port_num=None,
    sg=None,
    log_name=None,
):
    """Run cefgetfile to retrieve content.

    Args:
        net: Mininet network instance.
        host_idx: Consumer host index.
        uri: Content URI.
        output_path: Path to save retrieved file.
        owner_only: If True, add -o flag for owner-only mode.
        chunk: Maximum number of chunks to retrieve.
        pipeline: Number of pipeline.
        valid_algo: Validation algorithm (crc32c or rsa-sha256).
        port_num: Port number.
        sg: Send Long Life Interest.
        log_name: Name of the log file.

    Returns:
        exit_code: Exit code of the command.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefgetfile {uri} -f {shlex.quote(output_path)}"]

    if owner_only:
        cmd_parts.append("-o")
    if chunk is not None:
        cmd_parts.append(f"-m {chunk}")
    if pipeline is not None:
        cmd_parts.append(f"-s {pipeline}")
    if valid_algo is not None:
        cmd_parts.append(f"-v {valid_algo}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")
    if sg is not None:
        cmd_parts.append(f"-z {sg}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefgetfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(str(log_name))} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    proc = net.hosts[host_idx].popen(command, shell=True)
    exit_code = proc.wait()

    return exit_code


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


def run_cefsubfile(
    net,
    host_idx,
    uri,
    output_path=None,
    pipeline=None,
    ri_valid_algo=None,
    td_valid_algo=None,
    port_num=None,
    log_name=None,
):
    """Run cefsubfile to subscribe content.

    Args:
        net: Mininet network instance.
        host_idx: Subscriber host index.
        uri: Content URI.
        output_path: Directory path to output content (use "-" for stdout).
        pipeline: Number of pipeline.
        ri_valid_algo: Validation algorithm for Reflexive Interest (crc32c or rsa-sha256).
        td_valid_algo: Validation algorithm for Trigger Data (crc32c or rsa-sha256).
        port_num: Port number.
        log_name: Name of the log file.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefsubfile {uri}"]

    if output_path is not None:
        output_str = str(output_path)
        if output_str == "-":
            cmd_parts.append("-f -")
        else:
            out_dir = Path(output_str)
            out_dir.mkdir(parents=True, exist_ok=True)
            cmd_parts.append(f"-f {shlex.quote(str(out_dir))}")
    if pipeline is not None:
        cmd_parts.append(f"-s {pipeline}")
    if ri_valid_algo is not None:
        cmd_parts.append(f"-v_RI {ri_valid_algo}")
    if td_valid_algo is not None:
        cmd_parts.append(f"-v_TD {td_valid_algo}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefsubfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(str(log_name))} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefpubfile(
    net,
    host_idx,
    uri,
    file_path,
    rate=None,
    block_size=None,
    expiry=None,
    cache_time=None,
    lifetime=None,
    retry_limit=None,
    target=None,
    ti_valid_algo=None,
    rd_valid_algo=None,
    port_num=None,
    log_name=None,
):
    """Run cefpubfile to publish content.

    Args:
        net: Mininet network instance.
        host_idx: Publisher host index.
        uri: Content URI.
        file_path: Path to the file to publish.
        rate: Transfer rate to cefnetd (Mbps).
        block_size: Max payload length (bytes) of the Content Object.
        expiry: Lifetime (seconds) of the Content Object.
        cache_time: Period (seconds) after which cached Content Objects are deleted.
        lifetime: Lifetime of Trigger Interest.
        retry_limit: Retry limit of Trigger Interest.
        target: Use Long Life Interest for Trigger Interest or/and Reflexive Interest (trg | ref | both).
        ti_valid_algo: Validation algorithm for Trigger Interest (crc32c or rsa-sha256).
        rd_valid_algo: Validation algorithm for Reflexive Data (crc32c or rsa-sha256).
        port_num: Port number.
        log_name: Name of the log file.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefpubfile {uri} -f {shlex.quote(file_path)}"]

    if rate is not None:
        cmd_parts.append(f"-r {rate}")
    if block_size is not None:
        cmd_parts.append(f"-b {block_size}")
    if expiry is not None:
        cmd_parts.append(f"-e {expiry}")
    if cache_time is not None:
        cmd_parts.append(f"-t {cache_time}")
    if lifetime is not None:
        cmd_parts.append(f"-l {lifetime}")
    if retry_limit is not None:
        cmd_parts.append(f"-m {retry_limit}")
    if target is not None:
        _valid_targets = ("trg", "ref", "both")
        if target not in _valid_targets:
            raise ValueError(
                f"cefpubfile -z accepts {_valid_targets}, got {target!r}"
            )
        cmd_parts.append(f"-z {target}")
    if ti_valid_algo is not None:
        cmd_parts.append(f"-v_TI {ti_valid_algo}")
    if rd_valid_algo is not None:
        cmd_parts.append(f"-v_RD {rd_valid_algo}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefpubfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(str(log_name))} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)
