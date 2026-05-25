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
    def test_completes_before_deadline(self):
        proc = MagicMock()
        proc.wait.return_value = 0
        deadline = time.monotonic() + 10
        result = wait_pubsub_process(proc, deadline)
        assert result == 0

    def test_exceeds_deadline_terminated(self):
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 0),
            0,
        ]
        proc.returncode = None
        deadline = time.monotonic() + 0.01
        result = wait_pubsub_process(proc, deadline)
        assert result is None
        proc.terminate.assert_called_once()

    def test_resists_terminate_killed(self):
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 0),
            subprocess.TimeoutExpired("cmd", 2),
            None,
        ]
        deadline = time.monotonic() + 0.01
        result = wait_pubsub_process(proc, deadline)
        assert result is None
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()


class TestClearSubOutputArtifacts:
    def test_nonexistent_dir_returns_zero(self, tmp_path):
        result = clear_sub_output_artifacts(tmp_path / "nonexistent")
        assert result == 0
