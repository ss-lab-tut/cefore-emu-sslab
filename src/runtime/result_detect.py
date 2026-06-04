"""Success detection helpers for cefore content operations."""

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


def clear_sub_output_artifacts(output_dir: Path) -> int:
    """Remove stale cefsubfile output artifacts from an existing directory."""
    if not output_dir.is_dir():
        return 0
    removed = 0
    for artifact in output_dir.glob("RNP0x*.out"):
        if not artifact.is_file():
            continue
        artifact.unlink()
        removed += 1
    return removed


def detect_sub_success(result, output_dir: Path, log_path: Path) -> dict:
    """Evaluate cefsubfile success from a CommandResult and the output directory.

    cefsubfile writes ``RNP0x<hex>.out`` files under the output directory; the
    exact name is session-dependent and cannot be predicted in advance. Success
    requires a non-empty output file AND the process having either exited
    cleanly (returncode 0) or been killed by the outer deadline/cancellation
    after content was already delivered (``timed_out``/``cancelled``). The flags
    replace the former ``exit_code in (0, None)`` sentinel.
    """
    artifacts = sorted(output_dir.glob("RNP0x*.out")) if output_dir.is_dir() else []
    non_empty = [p for p in artifacts if p.stat().st_size > 0]
    has_out = bool(non_empty)
    delivered_ok = result.returncode == 0 or result.timed_out or result.cancelled
    return {
        "success": has_out and delivered_ok,
        "has_completed_log": False,
        "has_output_file": has_out,
        "artifact_path": str(non_empty[0]) if non_empty else None,
    }
