"""Unit tests for result detection helpers.

The former cefsubfile deadline waiter (``wait_pubsub_process``) moved into the
CommandRunner seam; its wait/terminate/cancel behaviour is now covered by
tests/runtime/test_command_runner.py.
"""

from datetime import datetime

from src.runtime.result_detect import (
    clear_sub_output_artifacts,
    detect_get_success,
    timestamp_utc,
)


class TestDetectGetSuccess:
    def test_success_all_criteria_met(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("Completed to get all the chunks.\n")
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=0)
        assert result.success is True
        assert result.has_completed_log is True
        assert result.has_output_file is True

    def test_failure_exit_code_nonzero(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("Completed to get all the chunks.\n")
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=1)
        assert result.success is False
        assert result.has_completed_log is True
        assert result.has_output_file is True

    def test_failure_missing_log_marker(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("some other log output\n")
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=0)
        assert result.success is False
        assert result.has_completed_log is False

    def test_failure_empty_output_file(self, tmp_path):
        log = tmp_path / "get.log"
        log.write_text("Completed to get all the chunks.\n")
        out = tmp_path / "recv"
        out.write_bytes(b"")
        result = detect_get_success(log, out, exit_code=0)
        assert result.success is False
        assert result.has_output_file is False

    def test_failure_missing_log_file(self, tmp_path):
        log = tmp_path / "get.log"  # not created
        out = tmp_path / "recv"
        out.write_bytes(b"data")
        result = detect_get_success(log, out, exit_code=0)
        assert result.has_completed_log is False


class TestTimestampUtc:
    def test_returns_iso_format(self):
        ts = timestamp_utc()
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None


class TestClearSubOutputArtifacts:
    def test_nonexistent_dir_returns_zero(self, tmp_path):
        result = clear_sub_output_artifacts(tmp_path / "nonexistent")
        assert result == 0
