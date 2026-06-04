"""Cefore daemon control functions."""

import os
import shlex
import subprocess
import time

from mininet.log import info

from .cef_argv import (
    build_cefgetfile_argv,
    build_cefpubfile_argv,
    build_cefputfile_argv,
    build_cefsubfile_argv,
)


def _terminate_process(proc):
    """Terminate a command and escalate if it does not promptly exit."""
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def popen_capture(node, command, timeout=None):
    """Run a command in a host netns via popen and return its stdout text.

    Unlike ``node.cmd()`` this does not use the host's shared pexpect shell,
    so it can run concurrently with the Mininet CLI without shell contention.
    On timeout the process is terminated and ``"error: command timeout"`` is
    returned.
    """
    proc = node.popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process(proc)
        return "error: command timeout"
    if isinstance(out, bytes):
        return out.decode(errors="replace")
    return out or ""


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
    runner,
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
    timeout=None,
    cancel_event=None,
):
    """Run cefputfile to publish content.

    Args:
        runner: CommandRunner used to execute the command.
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
        timeout: Optional maximum number of seconds to wait.
        cancel_event: Optional threading event used to cancel the command.

    Returns:
        exit_code: Exit code of the command.
    """
    node_name = f"h{host_idx}"
    argv = build_cefputfile_argv(
        uri,
        file_path,
        node_name=node_name,
        rate=rate,
        block_size=block_size,
        expiry=expiry,
        cache_time=cache_time,
        valid_algo=valid_algo,
        port_num=port_num,
    )
    if not log_name:
        log_name = f"cefputfile-h{host_idx}.log"
    print(node_name, "command:", argv)
    result = runner.run(
        node_name,
        argv,
        log_path=log_name,
        timeout=timeout,
        cancel_event=cancel_event,
    )
    return result.returncode


def run_cefgetfile(
    runner,
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
    timeout=None,
    cancel_event=None,
):
    """Run cefgetfile to retrieve content.

    Args:
        runner: CommandRunner used to execute the command.
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
        timeout: Optional maximum number of seconds to wait.
        cancel_event: Optional threading event used to cancel the command.

    Returns:
        exit_code: Exit code of the command.
    """
    node_name = f"h{host_idx}"
    argv = build_cefgetfile_argv(
        uri,
        output_path,
        node_name=node_name,
        owner_only=owner_only,
        chunk=chunk,
        pipeline=pipeline,
        valid_algo=valid_algo,
        port_num=port_num,
        sg=sg,
    )
    if not log_name:
        log_name = f"cefgetfile-h{host_idx}.log"
    print(node_name, "command:", argv)
    result = runner.run(
        node_name,
        argv,
        log_path=log_name,
        timeout=timeout,
        cancel_event=cancel_event,
    )
    return result.returncode


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
    runner,
    host_idx,
    uri,
    output_path=None,
    pipeline=None,
    ri_valid_algo=None,
    td_valid_algo=None,
    port_num=None,
    log_name=None,
):
    """Run cefsubfile to subscribe content (blocking).

    Args:
        runner: CommandRunner used to execute the command.
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
    argv = build_cefsubfile_argv(
        uri,
        node_name=node_name,
        output_path=output_path,
        pipeline=pipeline,
        ri_valid_algo=ri_valid_algo,
        td_valid_algo=td_valid_algo,
        port_num=port_num,
    )
    if not log_name:
        log_name = f"cefsubfile-h{host_idx}.log"
    print(node_name, "command:", argv)
    return runner.run(node_name, argv, log_path=log_name).returncode


def start_cefsubfile(
    runner,
    host_idx,
    uri,
    output_path=None,
    pipeline=None,
    ri_valid_algo=None,
    td_valid_algo=None,
    port_num=None,
    log_name=None,
):
    """Start cefsubfile in the background (non-blocking).

    Identical argv construction to run_cefsubfile but returns a CommandHandle
    immediately without waiting. The caller waits on it through the runner.

    Args:
        runner: CommandRunner used to start the command.
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
        CommandHandle for the running cefsubfile process.
    """
    node_name = f"h{host_idx}"
    argv = build_cefsubfile_argv(
        uri,
        node_name=node_name,
        output_path=output_path,
        pipeline=pipeline,
        ri_valid_algo=ri_valid_algo,
        td_valid_algo=td_valid_algo,
        port_num=port_num,
    )
    if not log_name:
        log_name = f"cefsubfile-h{host_idx}.log"
    print(node_name, "command:", argv)
    return runner.start(node_name, argv, log_path=log_name)


def run_cefpubfile(
    runner,
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
    """Start cefpubfile in the background (non-blocking).

    Returns a CommandHandle immediately; the caller waits on it through the
    runner (cefpubfile is long-running in the pub/sub model).

    Args:
        runner: CommandRunner used to start the command.
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

    Returns:
        CommandHandle for the running cefpubfile process.
    """
    node_name = f"h{host_idx}"
    argv = build_cefpubfile_argv(
        uri,
        file_path,
        node_name=node_name,
        rate=rate,
        block_size=block_size,
        expiry=expiry,
        cache_time=cache_time,
        lifetime=lifetime,
        retry_limit=retry_limit,
        target=target,
        ti_valid_algo=ti_valid_algo,
        rd_valid_algo=rd_valid_algo,
        port_num=port_num,
    )
    if not log_name:
        log_name = f"cefpubfile-h{host_idx}.log"
    print(node_name, "command:", argv)
    return runner.start(node_name, argv, log_path=log_name)


def run_csmgrstatus(
    net,
    host_idx,
    uri=None,
    port_num=None,
    host=None,
    log_name=None,
    quiet=False,
    use_popen=False,
    timeout=None,
):
    """Run csmgrstatus to query cache manager status.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
        uri: Content URI to query (optional).
        port_num: Port number.
        host: Hostname or IP to connect to.
        log_name: Name of the log file.
        quiet: When True, suppress the command echo and the output ``info``
            (the output is still returned).
        use_popen: When True, run via ``popen_capture`` (separate process, no
            shared pexpect shell) instead of ``node.cmd()``. Avoids contention
            with the Mininet CLI.
        timeout: Command timeout (seconds) used only when ``use_popen`` is True.

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
    if not quiet:
        print(node_name, "command:", command)
    if use_popen:
        output = popen_capture(net.hosts[host_idx], command, timeout=timeout)
    else:
        output = net.hosts[host_idx].cmd(command)
    if not log_name and not quiet:
        info(output)
    return output
