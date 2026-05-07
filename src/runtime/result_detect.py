"""Success detection helpers for cefore content operations."""

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def timestamp_utc() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def detect_get_success(log_path: Path, out_path: Path, exit_code: int) -> dict:
    """Evaluate cefgetfile success using exit code, log, and output file."""
    log_text = ""
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    has_completed = "Completed to get all the chunks." in log_text
    has_out = out_path.exists() and out_path.stat().st_size > 0
    return {
        "success": exit_code == 0 and has_completed and has_out,
        "has_completed_log": has_completed,
        "has_output_file": has_out,
    }


def detect_sub_success(exit_code, output_dir: Path, log_path: Path) -> dict:
    """Evaluate cefsubfile success using exit code and output directory.

    cefsubfile writes ``RNP0x<hex>.out`` files under the output directory;
    the exact name is session-dependent and cannot be predicted in advance.
    Success requires a non-empty output file and exit_code in (0, None) —
    None means the process was killed by the outer deadline after content was
    already delivered.
    """
    artifacts = sorted(output_dir.glob("RNP0x*.out")) if output_dir.is_dir() else []
    non_empty = [p for p in artifacts if p.stat().st_size > 0]
    has_out = bool(non_empty)
    return {
        "success": has_out and exit_code in (0, None),
        "has_completed_log": False,
        "has_output_file": has_out,
        "artifact_path": str(non_empty[0]) if non_empty else None,
    }


def wait_pubsub_process(proc, deadline: float):
    """Wait for a pub/sub process until its absolute deadline (monotonic seconds)."""
    remaining = max(0.0, deadline - time.monotonic())
    try:
        return proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return None
