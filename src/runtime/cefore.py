"""Cefore daemon control functions."""

import os
import time

from mininet.log import info

from .cef_argv import (
    build_cefgetfile_argv,
    build_cefpubfile_argv,
    build_cefputfile_argv,
    build_cefsubfile_argv,
)
from .command_runner import MininetCommandRunner


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


def wait_for_cefnetd(net, idx, timeout=10, interval=0.25, runner=None):
    """Wait for cefnetd to become ready.

    Args:
        net: Mininet network instance.
        idx: Host index.
        timeout: Maximum wait time in seconds.
        interval: Check interval in seconds.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).

    Returns:
        True if ready, False if timeout.
    """
    node_name = f"h{idx}"
    runner = runner or MininetCommandRunner(net)
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = runner.run(
            node_name, ["cefstatus", "-d", f"./{node_name}"], log_path=os.devnull
        )
        if result.returncode == 0:
            return True
        time.sleep(interval)
    info(f"{node_name} cefnetd not ready; check {node_name}-cefnetd-log\n")
    return False


def wait_for_csmgrd(net, idx, timeout=10, interval=0.5, runner=None):
    """Wait for csmgrd to become ready.

    Args:
        net: Mininet network instance.
        idx: Host index.
        timeout: Maximum wait time in seconds.
        interval: Check interval in seconds.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).

    Returns:
        True if ready, False if timeout.
    """
    node_name = f"h{idx}"
    runner = runner or MininetCommandRunner(net)
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = runner.run(node_name, ["csmgrstatus"], log_path=os.devnull)
        if result.returncode == 0:
            return True
        time.sleep(interval)
    info(f"{node_name} csmgrd not ready; check {node_name}-csmgrd-log\n")
    return False


def start_csmgrd(net, idx, log_dir=None, runner=None):
    """Start cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        log_dir: Directory to write daemon log files (hN-csmgrd-log).
                 If None, logs go to CWD.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """
    node_name = f"h{idx}"
    runner = runner or MininetCommandRunner(net)
    if log_dir is not None:
        abs_node_dir = os.path.abspath(f"./{node_name}")
        argv = ["csmgrdstart", "-d", abs_node_dir]
        cwd = str(log_dir)
    else:
        argv = ["csmgrdstart", "-d", f"./{node_name}"]
        cwd = None
    info(f"{node_name} command: {argv} cwd: {cwd}\n")
    runner.run(node_name, argv, cwd=cwd, log_path=os.devnull)
    wait_for_csmgrd(net, idx, runner=runner)


def stop_csmgrd(net, idx, runner=None):
    """Stop cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """
    node_name = f"h{idx}"
    argv = ["csmgrdstop", "-d", f"./{node_name}"]
    info("hosts[", idx, "]:", argv, "\n")
    runner = runner or MininetCommandRunner(net)
    runner.run(node_name, argv)


def start_cefnetd(net, idx, log_dir=None, runner=None):
    """Start cefnetd forwarding daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        log_dir: Directory to write daemon log files (hN-cefnetd-log).
                 If None, logs go to CWD.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """
    node_name = f"h{idx}"
    cleanup_cefnetd_socket(node_name, idx)
    runner = runner or MininetCommandRunner(net)
    if log_dir is not None:
        abs_node_dir = os.path.abspath(f"./{node_name}")
        argv = ["cefnetdstart", "-d", abs_node_dir]
        cwd = str(log_dir)
    else:
        argv = ["cefnetdstart", "-d", f"./{node_name}"]
        cwd = None
    info(f"{node_name} command: {argv} cwd: {cwd}\n")
    runner.run(node_name, argv, cwd=cwd, log_path=os.devnull)
    time.sleep(1)


def stop_cefnetd(net, idx, runner=None):
    """Stop cefnetd forwarding daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """
    node_name = f"h{idx}"
    argv = ["cefnetdstop", "-F", "-d", f"./{node_name}"]
    info("hosts[", idx, "]:", argv, "\n")
    runner = runner or MininetCommandRunner(net)
    runner.run(node_name, argv)


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
    *,
    log_name,
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
    info(f"{node_name} command: {argv}\n")
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
    sg: bool = False,
    *,
    log_name,
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
        sg (bool): If True, pass -z sg (Send Long Life Interest) flag.
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
    info(f"{node_name} command: {argv}\n")
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
    argv = ["cefstatus", "-d", f"./{node_name}"]
    info(f"{node_name} command: {argv}\n")
    info(MininetCommandRunner(net).run(node_name, argv).stdout)


def run_cefstatus_all(net, host_num):
    """Run cefstatus for all hosts.

    Args:
        net: Mininet network instance.
        host_num: Total number of hosts.
    """
    info("\nFIB status per host:\n")
    for host_idx in range(host_num):
        run_cefstatus(net, host_idx)


def start_cefsubfile(
    runner,
    host_idx,
    uri,
    output_path=None,
    pipeline=None,
    ri_valid_algo=None,
    td_valid_algo=None,
    port_num=None,
    *,
    log_name,
):
    """Start cefsubfile in the background (non-blocking).

    Builds the same cefsubfile argv but returns a CommandHandle immediately
    without waiting. The caller waits on it through the runner.

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
    info(f"{node_name} command: {argv}\n")
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
    *,
    log_name,
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
    info(f"{node_name} command: {argv}\n")
    return runner.start(node_name, argv, log_path=log_name)


def run_csmgrstatus(
    net,
    host_idx,
    uri=None,
    port_num=None,
    host=None,
    log_name=None,
    quiet=False,
    timeout=None,
):
    """Run csmgrstatus to query cache manager status.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
        uri: Content URI to query (optional).
        port_num: Port number.
        host: Hostname or IP to connect to.
        log_name: When given, stdout is redirected to this log file (stdout
            only, matching the old ``> log`` shell redirect) and the empty
            stdout is returned.
        quiet: When True, suppress the command echo and the output ``info``
            (the output is still returned).
        timeout: Command timeout (seconds).

    Returns:
        Command output string.
    """
    node_name = f"h{host_idx}"
    argv = ["csmgrstatus"]
    if uri is not None:
        argv.append(uri)
    if port_num is not None:
        argv.extend(["-p", str(port_num)])
    if host is not None:
        argv.extend(["-h", host])

    if not quiet:
        info(f"{node_name} command: {argv} log: {log_name}\n")

    runner = MininetCommandRunner(net)
    if log_name:
        # stdout -> log file (stdout only, like the old "> log"); stderr is
        # kept separate so the log stays stdout-only.
        result = runner.run(
            node_name, argv, log_path=log_name, capture_stderr=True, timeout=timeout
        )
        return "error: command timeout" if result.timed_out else result.stdout
    result = runner.run(node_name, argv, timeout=timeout)
    output = "error: command timeout" if result.timed_out else result.stdout
    if not quiet:
        info(output)
    return output
