"""Cefore daemon control functions."""

import os
import time
from pathlib import Path

from mininet.log import info

from .cef_argv import (
    build_ccninfo_argv,
    build_cefgetfile_argv,
    build_cefpubfile_argv,
    build_cefputfile_argv,
    build_cefsubfile_argv,
)
from .command_runner import MininetCommandRunner
from .cefore_conf import read_port_num
from .daemon_logs import (
    HostLogScope,
    cleanup_stale_cefnetd_log,
    cleanup_stale_csmgrd_log,
    tmp_daemon_log_paths,
)

# ccninfo self-terminates on its own once it gets a reply or hits
# CCNINFO_REPLY_TIMEOUT+1 (cefnetd.conf default 4s + 1s grace = ~5s), so this
# guard is not the primary bound — it exists to cap a *hung* binary (e.g. a
# wedged cefnetd never replying and never letting ccninfo's own timer fire)
# so a caller's run() call cannot block forever.
CCNINFO_GUARD_TIMEOUT = 10


def cefore_env_prefix(env_dir: str) -> list[str]:
    """Build the ``env CEFORE_DIR=<dir>`` argv prefix.

    Shared between ``run_ccninfo`` (event-driven, log-file mode) and
    monitoring (periodic, stdout mode).

    Why this prefix is necessary: ccninfo parses ``-d`` AFTER
    ``cef_client_init()``, so without ``CEFORE_DIR`` it reads
    ``/usr/local/cefore/cefnetd.conf``'s ``LOCAL_SOCK_ID`` and connects
    to the wrong cefnetd in multi-node Mininet runs.
    """
    return ["env", f"CEFORE_DIR={env_dir}"]


def _expected_daemon_log_path(idx: int, *, has_csmgrd: bool) -> Path:
    """Return the /tmp daemon log path that the Cefore daemon will open."""
    paths = tmp_daemon_log_paths(HostLogScope(idx, Path(f"h{idx}"), has_csmgrd))
    return paths[-1]


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
    log_path = _expected_daemon_log_path(idx, has_csmgrd=False)
    info(f"{node_name} cefnetd not ready; check {log_path}\n")
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
    log_path = _expected_daemon_log_path(idx, has_csmgrd=True)
    info(f"{node_name} csmgrd not ready; check {log_path}\n")
    return False


def start_csmgrd(net, idx, log_dir=None, runner=None):
    """Start cache manager daemon for a host.

    Args:
        net: Mininet network instance.
        idx: Host index.
        log_dir: Command working directory. Cefore writes daemon logs under /tmp.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """
    node_name = f"h{idx}"
    cleanup_stale_csmgrd_log(node_name, idx)
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
        log_dir: Command working directory. Cefore writes daemon logs under /tmp.
        runner: Optional CommandRunner (defaults to a Mininet-backed one).
    """
    node_name = f"h{idx}"
    cleanup_cefnetd_socket(node_name, idx)
    cleanup_stale_cefnetd_log(node_name, idx)
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


def run_ccninfo(
    runner,
    host_idx,
    uri,
    *,
    log_name,
    cache_info=False,
    owner_only=False,
    hop_count=None,
    skip_hop=None,
    valid_algo=None,
    timeout=CCNINFO_GUARD_TIMEOUT,
    cancel_event=None,
    cefore_env_dir=None,
):
    """Run ccninfo to query cache/path information for a content prefix.

    Args:
        runner: CommandRunner used to execute the command.
        host_idx: Querying host index.
        uri: Content name prefix to query.
        cache_info: If True, add -c flag to request cache info/RTT.
        owner_only: If True, add -o flag for owner-only query.
        hop_count: Max number of routers to trace.
        skip_hop: Number of upstream routers to skip.
        valid_algo: Validation algorithm (crc32c or rsa-sha256).
        log_name: Name of the log file.
        timeout: Maximum number of seconds to wait (default:
            CCNINFO_GUARD_TIMEOUT — bounds a hung binary; ccninfo itself
            self-terminates well before this under normal operation).
        cancel_event: Optional threading event used to cancel the command.
        cefore_env_dir: When set, prepend ``env CEFORE_DIR=<path>`` to the
            command so ccninfo reads the correct node's cefnetd.conf.

    Returns:
        CommandResult: the full result, not just the exit code. Unlike
        run_cefputfile/run_cefgetfile (which return a bare returncode — a
        legacy contract this function does not copy), interpreting a ccninfo
        run requires timed_out/cancelled: a real reply, a timeout, and a
        cancellation can all surface as similar-looking exit codes, and the
        verdict layer needs to tell them apart.
    """
    node_name = f"h{host_idx}"
    argv = build_ccninfo_argv(
        uri,
        node_name=node_name,
        cache_info=cache_info,
        owner_only=owner_only,
        hop_count=hop_count,
        skip_hop=skip_hop,
        valid_algo=valid_algo,
    )
    # 2026-07-27 upstream bug workaround — see cefore_env_prefix docstring.
    if cefore_env_dir is not None:
        argv = [*cefore_env_prefix(cefore_env_dir), *argv]
    info(f"{node_name} command: {argv}\n")
    return runner.run(
        node_name,
        argv,
        log_path=log_name,
        timeout=timeout,
        cancel_event=cancel_event,
    )


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
