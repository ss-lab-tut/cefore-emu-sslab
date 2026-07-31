"""Runtime adapter producing Verdicts for cefore content operations.

The success criteria live in src/core/verdict.py (the Verdict module); this
adapter unpacks runtime evidence (exit codes, CommandResult flags, log files,
output artifacts) into plain values for it.
"""

from datetime import datetime, timezone
from pathlib import Path

from ..core.ccninfo_parse import CcninfoReply, parse_ccninfo
from ..core.verdict import (
    CcninfoVerdict,
    Verdict,
    from_runtime_ccninfo,
    from_runtime_get,
    from_runtime_pub,
    from_runtime_put,
    from_runtime_sub,
)


def timestamp_utc() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def detect_get_success(log_path: Path, out_path: Path, exit_code: int) -> Verdict:
    """Evaluate cefgetfile success using exit code, log, and output file."""
    log_text = ""
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    has_out = out_path.exists() and out_path.stat().st_size > 0
    return from_runtime_get(exit_code, log_text, has_out)


def detect_put_success(exit_code: int) -> Verdict:
    """Evaluate cefputfile success; the exit code is the only runtime evidence."""
    return from_runtime_put(exit_code)


def detect_pub_success(exit_code: int, timed_out: bool) -> Verdict:
    """Evaluate cefpubfile success from exit code and the publish deadline."""
    return from_runtime_pub(exit_code, timed_out)


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


def detect_sub_success(result, output_dir: Path, log_path: Path) -> Verdict:
    """Evaluate cefsubfile success from a CommandResult and the output directory.

    cefsubfile writes ``RNP0x<hex>.out`` files under the output directory; the
    exact name is session-dependent and cannot be predicted in advance. Success
    requires a non-empty output file AND the process having either exited
    cleanly (returncode 0) or been killed by the outer deadline/cancellation
    after content was already delivered (``timed_out``/``cancelled``).
    """
    artifacts = sorted(output_dir.glob("RNP0x*.out")) if output_dir.is_dir() else []
    non_empty = [p for p in artifacts if p.stat().st_size > 0]
    return from_runtime_sub(
        result.returncode,
        result.timed_out,
        result.cancelled,
        bool(non_empty),
        artifact_path=str(non_empty[0]) if non_empty else None,
    )


def detect_ccninfo_success(
    log_path: Path | str | None,
    result,
    expected_responder: str | None,
    expected_route: tuple[str, ...] | None,
) -> tuple[CcninfoVerdict, CcninfoReply]:
    """Evaluate a ccninfo run from its log file and CommandResult.

    Reads the log text (missing/unreadable file degrades to an empty string,
    producing reply_received=False from parse_ccninfo), then delegates to the
    pure verdict function for judgment.

    Args:
        log_path: Path to the ccninfo log file, or None if no log was written.
        result: CommandResult from run_ccninfo.
        expected_responder: Expected responder node name, or None if no
            expectation is set by the event.
        expected_route: Expected ordered subsequence of route node names,
            or None if no expectation is set by the event.

    Returns:
        (CcninfoVerdict, CcninfoReply) tuple so the caller can pass both to
        the ResultsSink for full record construction.
    """
    log_text = ""
    if log_path is not None:
        try:
            log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Missing/unreadable file → empty text → reply_received False.
            pass

    reply = parse_ccninfo(log_text)
    route_nodes = tuple(hop.node for hop in reply.route)

    verdict = from_runtime_ccninfo(
        exit_code=result.returncode,
        timed_out=result.timed_out,
        cancelled=result.cancelled,
        reply_received=reply.reply_received,
        responder=reply.responder,
        route_nodes=route_nodes,
        expected_responder=expected_responder,
        expected_route=expected_route,
    )
    return verdict, reply
