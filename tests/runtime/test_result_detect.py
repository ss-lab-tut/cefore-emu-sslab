"""Unit tests for result detection helpers."""

import subprocess
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.result_detect import (
    clear_sub_output_artifacts,
    detect_get_success,
    timestamp_utc,
    wait_pubsub_process,
)


class TestDetectGetSuccess:
    def test_success_all_criteria_met(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("Completed to get all the chunks.\n")
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=0)
        assert result["success"] is True
        assert result["has_completed_log"] is True
        assert result["has_output_file"] is True

    def test_failure_exit_code_nonzero(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("Completed to get all the chunks.\n")
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=1)
        assert result["success"] is False
        assert result["has_completed_log"] is True
        assert result["has_output_file"] is True

    def test_failure_missing_log_marker(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("some other log output\n")
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=0)
        assert result["success"] is False
        assert result["has_completed_log"] is False

    def test_failure_empty_output_file(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("Completed to get all the chunks.\n")
        out = tmp_path / "recv"
        out.write_bytes(b"")
        result = detect_get_success(log, out, exit_code=0)
        assert result["success"] is False
        assert result["has_output_file"] is False

    def test_failure_missing_log_file(self, tmp_path):
        log = tmp_path / "get.log"  # not created
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=0)
        assert result["has_completed_log"] is False


class TestTimestampUtc:
    def test_returns_iso_format(self):
        ts = timestamp_utc()
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None


class TestWaitPubsubProcess:
    """Deterministic tests using patched time.monotonic.

    All tests patch src.runtime.result_detect.time.monotonic to control
    deadline expiry without wall-clock sleep.
    """

    def test_completes_before_deadline(self):
        proc = MagicMock()
        proc.wait.return_value = 0

        with patch("src.runtime.result_detect.time.monotonic", return_value=10.0):
            result = wait_pubsub_process(proc, deadline=50.0)

        assert result == 0

    def test_exceeds_deadline_terminated(self):
        """Deadline expires, terminate succeeds, wait after terminate succeeds.

        side_effect=[0.0, 1.0] makes the first loop iteration check
        time.monotonic()=0.0 < deadline=0.5, call proc.wait() which raises
        TimeoutExpired, then the next loop iteration sees time.monotonic()=1.0
        > deadline=0.5, breaks the loop, and enters terminate path.
        """
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 0.1),  # loop: timeout
            0,  # post-terminate wait succeeds
        ]
        proc.terminate = MagicMock()
        proc.kill = MagicMock()

        with patch("src.runtime.result_detect.time.monotonic",
                   side_effect=[0.0, 1.0]):
            result = wait_pubsub_process(proc, deadline=0.5)

        assert result is None
        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()

    def test_resists_terminate_killed(self):
        """Deadline expires, terminate fails (wait timeout), kill succeeds.

        side_effect=[0.0, 1.0]: first iteration at 0.0 < 0.5, wait raises.
        Second iteration at 1.0 > 0.5, breaks loop.
        Then terminate, wait(timeout=2) raises TimeoutExpired, kill, wait().
        """
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 0.1),  # loop: timeout
            subprocess.TimeoutExpired("cmd", 2),  # post-terminate: still alive
            0,  # post-kill: exited
        ]
        proc.terminate = MagicMock()
        proc.kill = MagicMock()

        with patch("src.runtime.result_detect.time.monotonic",
                   side_effect=[0.0, 1.0]):
            result = wait_pubsub_process(proc, deadline=0.5)

        assert result is None
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_cancel_event_returns_none(self):
        """Cancel event set before loop starts returns None."""
        proc = MagicMock()
        cancel_event = MagicMock()
        cancel_event.is_set.return_value = True

        with patch("src.runtime.result_detect.time.monotonic", return_value=10.0):
            result = wait_pubsub_process(proc, deadline=50.0,
                                         cancel_event=cancel_event)

        assert result is None
        proc.terminate.assert_called_once()

    def test_terminate_processlookuperror_returns_none(self):
        """terminate() raises ProcessLookupError after deadline: must return None.

        Fail-before: ProcessLookupError propagates, crashing caller.
        Pass-after: exception caught, returns None.
        """
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 0.1),  # loop: timeout
            0,  # post-terminate wait (not reached due to PLER)
        ]
        proc.terminate = MagicMock(side_effect=ProcessLookupError())
        proc.kill = MagicMock()

        with patch("src.runtime.result_detect.time.monotonic",
                   side_effect=[0.0, 1.0]):
            result = wait_pubsub_process(proc, deadline=0.5)

        assert result is None
        proc.terminate.assert_called_once()

    def test_kill_processlookuperror_returns_none(self):
        """kill() raises ProcessLookupError after kill escalation: must return None.

        Fail-before: ProcessLookupError from kill() propagates.
        Pass-after: exception caught, returns None.
        """
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 0.1),  # loop: timeout
            subprocess.TimeoutExpired("cmd", 2),  # post-terminate: still alive
            0,  # post-kill wait (not reached due to PLER)
        ]
        proc.terminate = MagicMock()
        proc.kill = MagicMock(side_effect=ProcessLookupError())

        with patch("src.runtime.result_detect.time.monotonic",
                   side_effect=[0.0, 1.0]):
            result = wait_pubsub_process(proc, deadline=0.5)

        assert result is None
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()


class TestClearSubOutputArtifacts:
    def test_nonexistent_dir_returns_zero(self, tmp_path):
        result = clear_sub_output_artifacts(tmp_path / "nonexistent")
        assert result == 0
