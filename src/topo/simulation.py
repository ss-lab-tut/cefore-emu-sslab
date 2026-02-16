"""Common simulation execution logic for disaster topologies."""

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info
from mininet.net import Mininet

from .cef_daemons import (
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefsubfile,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .external_bridge import (
    attach_external_interface,
    cleanup_external_bridges,
    parse_ext_args,
)
from .graph_algos import select_k_centers
from .net_config import parse_bw_args, set_fib, set_fib_for_uris, set_ip_addr, set_link_bandwidth
from .paths import resolve_run_path
from .templates import (
    apply_cache_node_settings,
    apply_pubsub_node_settings,
    cleanup_node_dirs,
)
from .viz import build_host_graph, print_mesh_links, render_topology_png


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _effective_down_count(args):
    """Extract effective down_count from failure_scenarios.

    Args:
        args: Parsed arguments with optional failure_scenarios attribute.

    Returns:
        Integer count of hosts to down per cycle.
    """
    fs = getattr(args, "failure_scenarios", None)
    if not fs:
        return 0
    strategy = fs.get("strategy", "simple")
    if strategy == "simple":
        simple = fs.get("simple", {}) or {}
        return simple.get("count") if simple.get("count") is not None else 0
    cycles = fs.get("cycles", []) or []
    if cycles:
        return max((c.get("count") or 0 for c in cycles), default=0)
    return 0


def artifact_path(run_dir, raw_path, default_name):
    """Resolve output file path under run_dir."""
    return resolve_run_path(run_dir, raw_path, default_name)


def timestamp_utc():
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def detect_get_success(log_path, out_path, exit_code):
    """Evaluate cefgetfile/cefsubfile success using exit code, log, and output file."""
    log_text = ""
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    has_completed = "Completed to get all the chunks." in log_text
    if out_path.is_dir():
        has_out = any(out_path.iterdir())
    else:
        has_out = out_path.exists() and out_path.stat().st_size > 0
    success = exit_code == 0 and has_completed and has_out
    return {
        "success": success,
        "has_completed_log": has_completed,
        "has_output_file": has_out,
    }


def default_transfer_log_name(
    kind, seed_label, phase, cycle_idx, idx, host_idx, down_hosts=None,
):
    """Build default operation log file names.

    Args:
        kind: "get", "sub", "put", or "pub".
        seed_label: Seed label string.
        phase: Operation phase label.
        cycle_idx: Evaluation cycle index.
        idx: Operation index in the phase.
        host_idx: Host index executing the operation.
        down_hosts: Optional iterable of down hosts.
    """
    if kind in ("get", "sub"):
        down_label = "none" if not down_hosts else ",".join(
            str(h) for h in sorted(down_hosts)
        )
        tool = "cefgetfile" if kind == "get" else "cefsubfile"
        return (
            f"{tool}_seed{seed_label}_downhosts{down_label}_"
            f"phase{phase}_cycle{cycle_idx}_idx{idx}_h{host_idx}.log"
        )
    if kind == "pub":
        return (
            f"cefpubfile_seed{seed_label}_downhostsnone_"
            f"phase{phase}_cycle{cycle_idx}_idx{idx}_h{host_idx}.log"
        )
    return f"cefputfile_h{host_idx}_c{idx}.log"


def resolve_results_path(args, run_dir):
    """Resolve results JSON path from args."""
    raw = getattr(args, "results_json", None)
    if not raw:
        return None
    return artifact_path(run_dir, raw, "results.json")


def build_warmup_ops(args, run_dir, hot_uris, cache_nodes):
    """Build warmup operations when not explicitly configured."""
    explicit = getattr(args, "warmup_gets", None) or []
    if explicit:
        return explicit

    if not hot_uris:
        return []

    warmup_nodes = list(cache_nodes) if getattr(args, "warmup_only_cache_nodes", True) else []
    if not warmup_nodes:
        warmup_nodes = [idx for idx in range(args.hosts)]

    warmup_ops = []
    for host_idx in warmup_nodes:
        for uri_idx, uri in enumerate(hot_uris):
            warmup_ops.append(
                {
                    "host": host_idx,
                    "uri": uri,
                    "file": str(run_dir / f"warmup_recv_h{host_idx}_u{uri_idx}"),
                }
            )
    return warmup_ops


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def _resolve_publisher_host(op, args, uri_publishers, uri):
    """Resolve the publisher host for a given operation."""
    publisher_host = op.get("publisher_host")
    if publisher_host is None:
        publisher_host = getattr(args, "publisher_host", None)
    if publisher_host is None:
        publisher_host = uri_publishers.get(uri)
    return publisher_host


def _build_result_entry(phase, consumer, uri, outfile_path, log_path,
                        exit_code, down_hosts, publisher_host):
    """Build a single result entry dict."""
    verdict = detect_get_success(log_path, outfile_path, exit_code)
    publisher_down = (
        publisher_host in down_hosts if publisher_host is not None else False
    )
    return {
        "ts": timestamp_utc(),
        "phase": phase,
        "host": consumer,
        "uri": uri,
        "out_file": str(outfile_path),
        "log_file": str(log_path),
        "exit_code": exit_code,
        "down_hosts": down_hosts,
        "publisher_host": publisher_host,
        "publisher_down": publisher_down,
        "success": verdict["success"],
        "has_completed_log": verdict["has_completed_log"],
        "has_output_file": verdict["has_output_file"],
    }


def run_get_ops(
    net, run_dir, ops, phase, per_get_interval, seed_label,
    flap_state, uri_publishers, args, results,
    cycle_idx=0, return_procs=False,
):
    """Run get/subscribe operations.

    Args:
        net: Mininet network instance.
        run_dir: Output directory.
        ops: List of get operation dicts.
        phase: Phase name ("warmup", "eval").
        per_get_interval: Seconds between operations.
        seed_label: Seed label for log names.
        flap_state: FlapState instance.
        uri_publishers: Dict of uri→publisher host ID.
        args: Parsed CLI args (for publisher_host attr).
        results: Mutable list to append result dicts.
        cycle_idx: Cycle index for logging.
        return_procs: If True, return pubsub process tuples instead of waiting.

    Returns:
        List of process tuples if return_procs, else None.
    """
    pubsub_procs = [] if return_procs else None

    for idx, op in enumerate(ops):
        consumer = int(op["host"])
        uri = op["uri"]
        outfile_path = artifact_path(
            run_dir,
            op.get("file"),
            f"{phase}_recvfile_h{consumer}_idx{idx}",
        )
        down_hosts = flap_state.snapshot()
        if op.get("log"):
            log_path = artifact_path(
                run_dir,
                op["log"],
                f"{phase}_cefgetfile_h{consumer}_idx{idx}.log",
            )
        else:
            log_kind = "sub" if op.get("mode") == "pubsub" else "get"
            log_path = artifact_path(
                run_dir,
                None,
                default_transfer_log_name(
                    log_kind, seed_label, phase, cycle_idx,
                    idx, consumer, down_hosts=down_hosts,
                ),
            )

        mode = op.get("mode") or "putget"

        if mode == "pubsub":
            sub_opts = op.get("sub_opts", {}) or {}
            proc = run_cefsubfile(
                net, consumer, uri,
                output_path=str(outfile_path),
                pipeline=sub_opts.get("pipeline"),
                ri_valid_algo=sub_opts.get("ri_valid_algo"),
                td_valid_algo=sub_opts.get("td_valid_algo"),
                port_num=sub_opts.get("port_num"),
                log_name=str(log_path),
            )

            if return_procs:
                pubsub_procs.append(
                    (proc, op, log_path, outfile_path, idx, consumer, uri, down_hosts)
                )
                info(f"Started subscriber h{consumer} for {uri}\n")
            else:
                exit_code = proc.wait()
                publisher_host = _resolve_publisher_host(op, args, uri_publishers, uri)
                results.append(_build_result_entry(
                    phase, consumer, uri, outfile_path, log_path,
                    exit_code, down_hosts, publisher_host,
                ))
        else:
            exit_code = run_cefgetfile(
                net, consumer, uri, str(outfile_path),
                owner_only=op.get("owner_only", False),
                chunk=op.get("chunk"),
                pipeline=op.get("pipeline"),
                valid_algo=op.get("valid_algo"),
                port_num=op.get("port_num"),
                sg=op.get("sg"),
                log_name=str(log_path),
            )

            publisher_host = _resolve_publisher_host(op, args, uri_publishers, uri)
            results.append(_build_result_entry(
                phase, consumer, uri, outfile_path, log_path,
                exit_code, down_hosts, publisher_host,
            ))

        if idx < len(ops) - 1 and per_get_interval > 0:
            time.sleep(per_get_interval)

    if return_procs:
        return pubsub_procs


def wait_pubsub_procs(pubsub_procs, uri_publishers, args, results,
                      timeout_per_proc=60):
    """Wait for pubsub subscriber processes to complete.

    Args:
        pubsub_procs: List of (proc, op, log_path, outfile_path,
                      idx, consumer, uri, down_hosts) tuples.
        uri_publishers: Dict of uri→publisher host ID.
        args: Parsed CLI args.
        results: Mutable list to append results.
        timeout_per_proc: Timeout in seconds per process.
    """
    info(f"\n=== Waiting for {len(pubsub_procs)} pubsub subscribers ===\n")

    for proc, op, log_path, outfile_path, idx, consumer, uri, down_hosts in pubsub_procs:
        try:
            exit_code = proc.wait(timeout=timeout_per_proc)
        except Exception as e:
            info(f"WARNING: Subscriber h{consumer} timeout: {e}\n")
            proc.terminate()
            try:
                exit_code = proc.wait(timeout=5)
            except Exception:
                info(f"WARNING: Subscriber h{consumer} force killing\n")
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                exit_code = -1

        publisher_host = _resolve_publisher_host(op, args, uri_publishers, uri)
        results.append(_build_result_entry(
            "eval", consumer, uri, outfile_path, log_path,
            exit_code, down_hosts, publisher_host,
        ))
        info(f"Subscriber h{consumer} completed (exit={exit_code})\n")


def wait_pub_procs(pubsub_pub_procs, timeout=60):
    """Wait for pubsub publisher processes to complete."""
    if not pubsub_pub_procs:
        return
    info(f"\n=== Waiting for {len(pubsub_pub_procs)} pubsub publishers ===\n")
    for proc in pubsub_pub_procs:
        try:
            exit_code = proc.wait(timeout=timeout)
            if exit_code != 0:
                info(f"WARNING: Publisher exited with code {exit_code}\n")
        except subprocess.TimeoutExpired as e:
            info(f"WARNING: Publisher timeout: {e}\n")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def run_put_phase(net, run_dir, ops_put_putget, seed_label):
    """Run putget publisher operations (synchronous).

    Returns when all puts are complete.
    """
    if not ops_put_putget:
        return
    info(f"\n=== Phase 1: Running {len(ops_put_putget)} putget publishers ===\n")
    for put_idx, op in enumerate(ops_put_putget):
        host = int(op["host"])
        uri = op["uri"]
        infile = op.get("file", "./sample-putfile")
        log_path = artifact_path(
            run_dir,
            op.get("log"),
            default_transfer_log_name("put", seed_label, "publish", 0, put_idx, host),
        )
        run_cefputfile(
            net, host, uri,
            file_path=infile,
            rate=op.get("rate"),
            block_size=op.get("block_size"),
            expiry=op.get("expiry", 3000),
            cache_time=op.get("cache_time", 3000),
            valid_algo=op.get("valid_algo"),
            port_num=op.get("port_num"),
            log_name=str(log_path),
        )
        time.sleep(1)


def run_pub_phase(net, run_dir, ops_put_pubsub, seed_label):
    """Start pubsub publisher operations (asynchronous).

    Returns list of Popen processes.
    """
    if not ops_put_pubsub:
        return []
    info(f"\n=== Phase 3: Starting {len(ops_put_pubsub)} pubsub publishers ===\n")
    procs = []
    for put_idx, op in enumerate(ops_put_pubsub):
        host = int(op["host"])
        uri = op["uri"]
        infile = op.get("file", "./sample-putfile")
        pub_opts = op.get("pub_opts", {}) or {}
        log_path = artifact_path(
            run_dir,
            op.get("log"),
            default_transfer_log_name("pub", seed_label, "publish", 0, put_idx, host),
        )
        proc = run_cefpubfile(
            net, host, uri,
            file_path=infile,
            rate=pub_opts.get("rate"),
            block_size=pub_opts.get("block_size"),
            expiry=pub_opts.get("expiry"),
            cache_time=pub_opts.get("cache_time"),
            lifetime=pub_opts.get("lifetime"),
            retry_limit=pub_opts.get("retry_limit"),
            target=pub_opts.get("target"),
            ti_valid_algo=pub_opts.get("ti_valid_algo"),
            rd_valid_algo=pub_opts.get("rd_valid_algo"),
            port_num=pub_opts.get("port_num"),
            log_name=str(log_path),
            async_mode=True,
        )
        procs.append(proc)
        time.sleep(1)
    return procs


# ---------------------------------------------------------------------------
# Network setup / teardown
# ---------------------------------------------------------------------------


def setup_network(net, topo, args, bridge_manager, bridge_configs, seed_label, run_dir):
    """Set up IP addresses, bandwidth, external interfaces, and topology PNG."""
    set_ip_addr(net, topo.mesh_links)

    from .external_bridge import setup_bridges
    if bridge_configs:
        setup_bridges(net, bridge_manager, bridge_configs, args.hosts, topo.mesh_links)

    for idx in range(args.hosts):
        info(net.hosts[idx].cmd("ifconfig"))

    for node_a, node_b, bandwidth in parse_bw_args(args.bw):
        set_link_bandwidth(net, node_a, node_b, bandwidth)

    for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
        attach_external_interface(net, host_name, intf_name, ip, mtu)

    topo_png = artifact_path(
        run_dir, args.topo_png, f"ex{args.hosts}_seed{seed_label}.png",
    )
    render_topology_png(
        topo.mesh_links, str(topo_png), seed=args.seed, layout=args.topo_layout,
    )


def setup_cache_nodes(args, topo, publisher_ids, pubsub_publisher_ids):
    """Select cache nodes and apply cache/pubsub settings.

    Returns:
        (cache_node_set, cache_nodes list)
    """
    host_graph, _ = build_host_graph(topo.mesh_links)
    cache_count = args.cache_count if args.cache_count > 0 else _effective_down_count(args) + 1
    cache_nodes = select_k_centers(host_graph, cache_count)
    cache_nodes = [
        idx for idx in cache_nodes
        if idx not in publisher_ids and idx not in pubsub_publisher_ids
    ]
    if not cache_nodes and args.hosts > 0:
        candidates = [idx for idx in range(args.hosts) if idx not in publisher_ids]
        if candidates:
            cache_nodes = [candidates[-1]]
    cache_node_set = set(cache_nodes)
    if cache_nodes:
        info("cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n")

    apply_cache_node_settings(
        args.hosts, cache_node_set,
        getattr(args, "cache_default_rct_ms", None),
    )
    if pubsub_publisher_ids:
        apply_pubsub_node_settings(args.hosts, pubsub_publisher_ids)

    return cache_node_set, cache_nodes


def start_daemons(net, args, cache_node_set, started_csmgrd_hosts):
    """Start csmgrd and cefnetd daemons, wait for readiness."""
    for idx in sorted(cache_node_set):
        start_csmgrd(net, idx)
        started_csmgrd_hosts.add(idx)

    for idx in range(args.hosts):
        start_cefnetd(net, idx)

    failed_hosts = []
    for idx in range(args.hosts):
        if not wait_for_cefnetd(net, idx, timeout=10):
            failed_hosts.append(idx)

    if failed_hosts:
        raise RuntimeError(
            f"cefnetd failed to start on hosts: {failed_hosts}. "
            f"Check daemon logs (hX-cefnetd-log) for details."
        )


def program_fib(net, topo, args, uri_publishers, uri_subscribers=None):
    """Program FIB entries and run cefstatus."""
    if uri_publishers:
        set_fib_for_uris(net, topo.mesh_links, args.k, uri_publishers,
                         uri_subscribers=uri_subscribers)
    else:
        set_fib(net, topo.mesh_links, args.k)

    run_cefstatus_all(net, args.hosts)
    print_mesh_links(topo.mesh_links)


def health_check_publishers(net, publisher_ids):
    """Verify publisher cefnetd daemons are running."""
    failed = []
    for idx in sorted(publisher_ids):
        if not wait_for_cefnetd(net, idx, timeout=5):
            failed.append(idx)
    if failed:
        raise RuntimeError(
            f"Publisher cefnetd not running on hosts: {failed}. "
            f"Cannot proceed with put operations. Check hX-cefnetd-log."
        )


def run_cli_or_duration(net, args, log_context, ops_get_putget, ops_put,
                        ops_get_pubsub, run_dir, seed_label, flap_state,
                        uri_publishers, results, get_interval):
    """Run CLI or duration mode."""
    use_cli = not getattr(args, "no_cli", False)
    if use_cli:
        if log_context:
            import sys
            sys.stdout = log_context["original_stdout"]
            sys.stderr = log_context["original_stderr"]
        CLI(net)
        if log_context:
            import sys
            sys.stdout = log_context["tee_stdout"]
            sys.stderr = log_context["tee_stderr"]
    else:
        duration = max(0, int(getattr(args, "duration", 0)))
        if duration > 0:
            if ops_get_pubsub or any(op.get("mode") == "pubsub" for op in ops_put):
                info("WARNING: duration mode with pubsub is not yet supported\n")
            deadline = time.time() + duration
            cycle_idx = 0
            while time.time() < deadline:
                run_get_ops(
                    net, run_dir, ops_get_putget, "eval", get_interval,
                    seed_label, flap_state, uri_publishers, args, results,
                    cycle_idx=cycle_idx,
                )
                cycle_idx += 1
                if time.time() >= deadline:
                    break


def cleanup_all(net, args, started_csmgrd_hosts, bridge_manager, stop_event,
                results, results_path, stop_thread=None,
                pubsub_sub_procs=None, pubsub_pub_procs=None):
    """Clean up daemons, bridges, and network; write results."""
    import json
    import signal

    if stop_event is not None:
        stop_event.set()
    if stop_thread is not None:
        stop_thread.join(timeout=10)

    # Kill remaining pubsub processes with SIGINT
    for proc_list in (pubsub_sub_procs, pubsub_pub_procs):
        if not proc_list:
            continue
        for item in proc_list:
            try:
                proc = item[0] if isinstance(item, tuple) else item
                if hasattr(proc, "poll") and proc.poll() is None:
                    proc.send_signal(signal.SIGINT)
            except OSError:
                pass
    # Wait briefly for graceful exit
    for proc_list in (pubsub_sub_procs, pubsub_pub_procs):
        if not proc_list:
            continue
        for item in proc_list:
            try:
                proc = item[0] if isinstance(item, tuple) else item
                if not hasattr(proc, "wait"):
                    continue
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=3)
                except Exception:
                    pass

    if net is not None:
        for idx in range(args.hosts):
            stop_cefnetd(net, idx)
        for idx in sorted(started_csmgrd_hosts):
            stop_csmgrd(net, idx)
        bridge_manager.cleanup()
        cleanup_external_bridges()
        net.stop()
        mn_cleanup()

    cleanup_node_dirs()

    if results_path is not None:
        results_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
