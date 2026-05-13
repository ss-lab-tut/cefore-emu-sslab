"""Cefore daemon control functions."""

import os
import shlex
import time

from mininet.log import info


def read_port_num(node_dir, default=9695):
    """Read PORT_NUM from cefnetd.conf."""
    conf_path = os.path.join(node_dir, "cefnetd.conf")
    if not os.path.isfile(conf_path):
        return default
    with open(conf_path, "r", encoding="utf-8") as conf_file:
        for line in conf_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("PORT_NUM="):
                value = stripped.split("=", 1)[1].strip().split()[0]
                try:
                    return int(value)
                except ValueError:
                    break
    return default


def cleanup_cefnetd_socket(node_dir, idx):
    """Remove stale cefnetd socket file."""
    port = read_port_num(node_dir)
    sock_path = f"/tmp/cef_{port}.{idx}"
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
            info(f"removed stale socket {sock_path}\n")
        except OSError:
            info(f"failed to remove stale socket {sock_path}\n")


def wait_for_cefnetd(net, idx, timeout=10, interval=0.25):
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


def wait_for_csmgrd(net, idx, timeout=10, interval=0.5):
    """Wait for csmgrd to become ready.

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
        result = net.hosts[idx].cmd("sh -c 'csmgrstatus >/dev/null 2>&1; echo $?'")
        if result.strip().endswith("0"):
            return True
        time.sleep(interval)
    info(f"{node_name} csmgrd not ready; check {node_name}-csmgrd-log\n")
    return False


def start_csmgrd(net, idx, log_dir=None):
    """Start cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        log_dir: Directory to write daemon log files (hN-csmgrd-log).
                 If None, logs go to CWD.
    """
    node_name = f"h{idx}"
    if log_dir is not None:
        abs_node_dir = os.path.abspath(f"./{node_name}")
        command = (
            f"cd {shlex.quote(str(log_dir))} && "
            f"csmgrdstart -d {shlex.quote(abs_node_dir)} > /dev/null 2>&1"
        )
    else:
        command = f"csmgrdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    wait_for_csmgrd(net, idx)


def stop_csmgrd(net, idx):
    """Stop cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
    """
    command = f"csmgrdstop -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def start_cefnetd(net, idx, log_dir=None):
    """Start cefnetd forwarding daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        log_dir: Directory to write daemon log files (hN-cefnetd-log).
                 If None, logs go to CWD.
    """
    node_name = f"h{idx}"
    cleanup_cefnetd_socket(node_name, idx)
    if log_dir is not None:
        abs_node_dir = os.path.abspath(f"./{node_name}")
        command = (
            f"cd {shlex.quote(str(log_dir))} && "
            f"cefnetdstart -d {shlex.quote(abs_node_dir)} > /dev/null 2>&1"
        )
    else:
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

    Returns:
        exit_code: Exit code of the command.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefputfile {shlex.quote(uri)} -f {shlex.quote(file_path)}"]

    if rate is not None:
        cmd_parts.append(f"-r {rate}")
    if block_size is not None:
        cmd_parts.append(f"-b {block_size}")
    if expiry is not None:
        cmd_parts.append(f"-e {expiry}")
    if cache_time is not None:
        cmd_parts.append(f"-t {cache_time}")
    if valid_algo is not None:
        cmd_parts.append(f"-v {shlex.quote(valid_algo)}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefputfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(log_name)} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    proc = net.hosts[host_idx].popen(command, shell=True)
    return proc.wait()


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
    cmd_parts = [f"cefgetfile {shlex.quote(uri)} -f {shlex.quote(output_path)}"]

    if owner_only:
        cmd_parts.append("-o")
    if chunk is not None:
        cmd_parts.append(f"-m {chunk}")
    if pipeline is not None:
        cmd_parts.append(f"-s {pipeline}")
    if valid_algo is not None:
        cmd_parts.append(f"-v {shlex.quote(valid_algo)}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")
    if sg is not None:
        cmd_parts.append(f"-z {sg}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefgetfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(log_name)} 2>&1")

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
        output_path: Directory path to output content. cefsubfile creates files
            named ``RNP0x<hex>.out`` under this directory (use "-" for stdout).
        pipeline: Number of pipeline.
        ri_valid_algo: Validation algorithm for Reflexive Interest (crc32c or rsa-sha256).
        td_valid_algo: Validation algorithm for Trigger Data (crc32c or rsa-sha256).
        port_num: Port number.
        log_name: Name of the log file.

    Returns:
        exit_code: Exit code of the command.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefsubfile {shlex.quote(uri)}"]

    if output_path is not None:
        cmd_parts.append(f"-f {shlex.quote(output_path)}")
    if pipeline is not None:
        cmd_parts.append(f"-s {pipeline}")
    if ri_valid_algo is not None:
        cmd_parts.append(f"-v_RI {shlex.quote(ri_valid_algo)}")
    if td_valid_algo is not None:
        cmd_parts.append(f"-v_TD {shlex.quote(td_valid_algo)}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefsubfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(log_name)} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    proc = net.hosts[host_idx].popen(command, shell=True)
    exit_code = proc.wait()

    return exit_code


def start_cefsubfile(
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
    """Start cefsubfile in background (non-blocking).

    Identical command construction to run_cefsubfile but returns the Popen
    process immediately without waiting.  Caller is responsible for calling
    proc.wait() to collect the exit code.

    Args:
        net: Mininet network instance.
        host_idx: Subscriber host index.
        uri: Content URI.
        output_path: Directory path to output content. cefsubfile creates files
            named ``RNP0x<hex>.out`` under this directory (use "-" for stdout).
        pipeline: Number of pipeline.
        ri_valid_algo: Validation algorithm for Reflexive Interest.
        td_valid_algo: Validation algorithm for Trigger Data.
        port_num: Port number.
        log_name: Name of the log file.

    Returns:
        Popen process object.
    """
    node_name = f"h{host_idx}"
    cmd_parts = [f"cefsubfile {shlex.quote(uri)}"]

    if output_path is not None:
        cmd_parts.append(f"-f {shlex.quote(output_path)}")
    if pipeline is not None:
        cmd_parts.append(f"-s {pipeline}")
    if ri_valid_algo is not None:
        cmd_parts.append(f"-v_RI {shlex.quote(ri_valid_algo)}")
    if td_valid_algo is not None:
        cmd_parts.append(f"-v_TD {shlex.quote(td_valid_algo)}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefsubfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(log_name)} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    return net.hosts[host_idx].popen(command, shell=True)


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
    cmd_parts = [f"cefpubfile {shlex.quote(uri)} -f {shlex.quote(file_path)}"]

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
        cmd_parts.append(f"-z {shlex.quote(target)}")
    if ti_valid_algo is not None:
        cmd_parts.append(f"-v_TI {shlex.quote(ti_valid_algo)}")
    if rd_valid_algo is not None:
        cmd_parts.append(f"-v_RD {shlex.quote(rd_valid_algo)}")
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")

    cmd_parts.append(f"-d ./{node_name}")

    if not log_name:
        log_name = f"cefpubfile-h{host_idx}.log"
    cmd_parts.append(f"> {shlex.quote(log_name)} 2>&1")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    proc = net.get(node_name).popen(command, shell=True)
    return proc


def run_csmgrstatus(
    net,
    host_idx,
    uri=None,
    port_num=None,
    host=None,
    log_name=None,
):
    """Run csmgrstatus to query cache manager status.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
        uri: Content URI to query (optional).
        port_num: Port number.
        host: Hostname or IP to connect to.
        log_name: Name of the log file.

    Returns:
        Command output string.
    """
    node_name = f"h{host_idx}"
    cmd_parts = ["csmgrstatus"]

    if uri is not None:
        cmd_parts.append(shlex.quote(uri))
    if port_num is not None:
        cmd_parts.append(f"-p {port_num}")
    if host is not None:
        cmd_parts.append(f"-h {shlex.quote(host)}")

    if log_name:
        cmd_parts.append(f"> {shlex.quote(log_name)}")

    command = " ".join(cmd_parts)
    print(node_name, "command:", command)
    output = net.hosts[host_idx].cmd(command)
    if not log_name:
        info(output)
    return output
