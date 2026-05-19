"""Content operation runner for timed put/get/pubsub events."""

import queue
import subprocess
import threading
import time
from pathlib import Path

from mininet.log import info

from .cefore import (
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    start_cefsubfile,
)
from .result_detect import (
    clear_sub_output_artifacts,
    detect_get_success,
    detect_sub_success,
    timestamp_utc,
    wait_pubsub_process,
)


def _safe_uri_label(uri):
    """Convert URI to a filesystem-safe label."""
    return uri.replace("ccnx:/", "").replace("/", "_")


class ContentOperationRunner:
    """Execute timed content operations (put/get/pubsub_pub/pubsub_sub) in a
    background worker thread so the EventScheduler timer thread is never blocked.

    Pub/sub ordering:
      - pubsub_sub events spawn cefsubfile immediately and store the pending proc.
      - pubsub_pub events apply the startup grace delay, then run cefpubfile,
        then wait for all pending subscriber processes for the same URI and record
        results via the result_callback.

    get events run cefgetfile and record results.
    put events run cefputfile (no result recording).
    """

    def __init__(
        self,
        net,
        run_dir,
        result_callback,
        flap_state,
        seed_label,
        uri_publishers=None,
        startup_grace=1.0,
    ):
        self._net = net
        self._run_dir = Path(run_dir)
        self._result_callback = result_callback
        self._flap_state = flap_state
        self._seed_label = seed_label
        self._uri_publishers = uri_publishers or {}
        self._startup_grace = float(startup_grace)

        self._queue = queue.Queue()
        self._pending_subs = {}  # uri -> list of pending sub dicts
        self._pending_subs_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ContentOpRunner"
        )

    def start(self):
        """Start the background worker thread."""
        self._thread.start()

    def submit(self, op_type, event):
        """Enqueue a content operation (non-blocking)."""
        self._queue.put((op_type, event))

    def wait_all(self, timeout=None):
        """Wait for all queued operations to complete."""
        try:
            self._queue.join()
        except Exception:
            pass
        # Also wait for any leftover pending subs (no matching pub arrived).
        with self._pending_subs_lock:
            leftovers = []
            for uri, entries in list(self._pending_subs.items()):
                leftovers.extend(entries)
            self._pending_subs.clear()
        for item in leftovers:
            exit_code = wait_pubsub_process(item["proc"], item["deadline"])
            self.record_sub_result(item, exit_code)

    def stop(self):
        """Stop the worker thread."""
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=15)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                break
            op_type, event = item
            try:
                self._dispatch(op_type, event)
            except Exception as exc:
                info(f"[content_runner] error handling {op_type}: {exc}\n")
            finally:
                self._queue.task_done()

    def _dispatch(self, op_type, event):
        if op_type == "put":
            self._do_put(event)
        elif op_type == "get":
            self._do_get(event)
        elif op_type == "pubsub_sub":
            self._do_pubsub_sub(event)
        elif op_type == "pubsub_pub":
            self._do_pubsub_pub(event)
        else:
            info(f"[content_runner] unknown op_type: {op_type}\n")

    def _log_path(self, cmd, host, uri, suffix=""):
        label = _safe_uri_label(uri)
        fname = f"{cmd}_event_h{host}_{label}{suffix}.log"
        return self._run_dir / fname

    # ------------------------------------------------------------------
    # put
    # ------------------------------------------------------------------

    def _do_put(self, event):
        host = int(event["host"])
        uri = event["uri"]
        infile = event.get("file", "./sample-putfile")
        log_path = self._log_path("cefputfile", host, uri)
        info(f"[content_runner] put h{host} uri={uri}\n")
        run_cefputfile(
            self._net,
            host,
            uri,
            file_path=infile,
            rate=event.get("rate"),
            block_size=event.get("block_size"),
            expiry=event.get("expiry"),
            cache_time=event.get("cache_time"),
            valid_algo=event.get("valid_algo"),
            port_num=event.get("port_num"),
            log_name=str(log_path),
        )

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    def _do_get(self, event):
        host = int(event["host"])
        uri = event["uri"]
        label = _safe_uri_label(uri)
        out_path = self._run_dir / f"event_recvfile_h{host}_{label}"
        log_path = self._log_path("cefgetfile", host, uri)
        down_hosts = self._flap_state.snapshot()
        info(f"[content_runner] get h{host} uri={uri}\n")
        exit_code = run_cefgetfile(
            self._net,
            host,
            uri,
            str(out_path),
            owner_only=event.get("owner_only", False),
            chunk=event.get("chunk"),
            pipeline=event.get("pipeline"),
            valid_algo=event.get("valid_algo"),
            port_num=event.get("port_num"),
            sg=event.get("sg"),
            log_name=str(log_path),
        )
        verdict = detect_get_success(log_path, out_path, exit_code)
        publisher_host = event.get("publisher_host") or self._uri_publishers.get(uri)
        publisher_down = (
            publisher_host in down_hosts if publisher_host is not None else False
        )
        self._result_callback(
            {
                "op_type": "get",
                "ts": timestamp_utc(),
                "phase": "event",
                "host": host,
                "uri": uri,
                "out_file": str(out_path),
                "log_file": str(log_path),
                "exit_code": exit_code,
                "down_hosts": down_hosts,
                "publisher_host": publisher_host,
                "publisher_down": publisher_down,
                "success": verdict["success"],
                "has_completed_log": verdict["has_completed_log"],
                "has_output_file": verdict["has_output_file"],
            }
        )

    # ------------------------------------------------------------------
    # pubsub_sub
    # ------------------------------------------------------------------

    def _do_pubsub_sub(self, event):
        host = int(event["host"])
        uri = event["uri"]
        sub_opts = event.get("sub_opts", {}) or {}
        wait_sec = float(sub_opts.get("wait", 30.0))
        label = _safe_uri_label(uri)
        output_dir = self._run_dir / f"event_recvdir_h{host}_{label}"
        output_dir.mkdir(parents=True, exist_ok=True)
        removed = clear_sub_output_artifacts(output_dir)
        if removed:
            info(
                f"[content_runner] cleared {removed} stale pubsub artifacts from {output_dir}\n"
            )
        log_path = self._log_path("cefsubfile", host, uri)
        down_hosts = self._flap_state.snapshot()
        started_at = time.monotonic()
        proc = start_cefsubfile(
            self._net,
            host,
            uri,
            output_path=str(output_dir),
            pipeline=sub_opts.get("pipeline"),
            ri_valid_algo=sub_opts.get("ri_valid_algo"),
            td_valid_algo=sub_opts.get("td_valid_algo"),
            port_num=sub_opts.get("port_num"),
            log_name=str(log_path),
        )
        deadline = started_at + wait_sec
        info(
            f"[content_runner] pubsub_sub h{host} uri={uri} pid={proc.pid} "
            f"wait={wait_sec:.1f}s deadline={deadline:.1f}\n"
        )
        entry = {
            "op": event,
            "proc": proc,
            "output_dir": output_dir,
            "log_path": log_path,
            "down_hosts": down_hosts,
            "deadline": deadline,
        }
        with self._pending_subs_lock:
            if uri not in self._pending_subs:
                self._pending_subs[uri] = []
            self._pending_subs[uri].append(entry)

    # ------------------------------------------------------------------
    # pubsub_pub
    # ------------------------------------------------------------------

    def _do_pubsub_pub(self, event):
        host = int(event["host"])
        uri = event["uri"]
        pub_opts = event.get("pub_opts", {}) or {}
        infile = event.get("file", "./sample-putfile")
        log_path = self._log_path("cefpubfile", host, uri)

        if self._startup_grace > 0:
            info(
                f"[content_runner] pubsub_pub grace {self._startup_grace:.1f}s h{host} uri={uri}\n"
            )
            time.sleep(self._startup_grace)

        # Compute publisher deadline based on pending subscriber waits.
        with self._pending_subs_lock:
            sub_entries = list(self._pending_subs.pop(uri, []))
        if sub_entries:
            max_deadline = max(e["deadline"] for e in sub_entries)
            remaining_sub_wait = max(0.0, max_deadline - time.monotonic())
        else:
            remaining_sub_wait = 30.0
        lifetime_sec = float(pub_opts.get("lifetime", 3))
        pub_deadline = max(remaining_sub_wait, lifetime_sec) + 5.0

        info(
            f"[content_runner] pubsub_pub h{host} uri={uri} deadline={pub_deadline:.1f}s\n"
        )
        proc = run_cefpubfile(
            self._net,
            host,
            uri,
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
        )
        pub_exit = None
        timed_out = False
        try:
            pub_exit = proc.wait(timeout=pub_deadline)
            info(
                f"[content_runner] cefpubfile h{host} uri={uri} exit_code={pub_exit}\n"
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            info(
                f"[WARN] content_runner: cefpubfile h{host} uri={uri} exceeded {pub_deadline:.1f}s; terminating\n"
            )
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            pub_exit = proc.returncode

        # Record pub completion before waiting on subscribers
        self._result_callback({
            "op_type":           "pub",
            "ts":                timestamp_utc(),
            "phase":             "event",
            "host":              host,
            "uri":               uri,
            "out_file":          str(log_path),
            "log_file":          str(log_path),
            "exit_code":         pub_exit,
            "down_hosts":        self._flap_state.snapshot(),
            "publisher_host":    host,
            "publisher_down":    False,
            "success":           pub_exit == 0 and not timed_out,
            "has_completed_log": False,
            "has_output_file":   False,
        })

        for item in sub_entries:
            exit_code = wait_pubsub_process(item["proc"], item["deadline"])
            artifacts = (
                sorted(item["output_dir"].glob("RNP0x*.out"))
                if item["output_dir"].is_dir()
                else []
            )
            non_empty = [p for p in artifacts if p.stat().st_size > 0]
            info(
                f"[content_runner] cefsubfile h{int(item['op']['host'])} uri={uri} "
                f"exit_code={exit_code} artifacts={len(non_empty)}\n"
            )
            self.record_sub_result(item, exit_code)

    def record_sub_result(self, item, exit_code):
        """Record a cefsubfile result via the result_callback."""
        op = item["op"]
        host = int(op["host"])
        uri = op["uri"]
        verdict = detect_sub_success(exit_code, item["output_dir"], item["log_path"])
        out_file = verdict.get("artifact_path") or str(item["output_dir"])
        publisher_host = op.get("publisher_host") or self._uri_publishers.get(uri)
        down_hosts = item["down_hosts"]
        publisher_down = (
            publisher_host in down_hosts if publisher_host is not None else False
        )
        self._result_callback(
            {
                "op_type": "sub",
                "ts": timestamp_utc(),
                "phase": "event",
                "host": host,
                "uri": uri,
                "out_file": out_file,
                "log_file": str(item["log_path"]),
                "exit_code": exit_code,
                "down_hosts": down_hosts,
                "publisher_host": publisher_host,
                "publisher_down": publisher_down,
                "success": verdict["success"],
                "has_completed_log": verdict["has_completed_log"],
                "has_output_file": verdict["has_output_file"],
            }
        )
