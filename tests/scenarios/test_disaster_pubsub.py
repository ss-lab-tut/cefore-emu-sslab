"""Unit tests for pub/sub helpers in disaster scenario."""

import subprocess
import time
from unittest.mock import MagicMock


from src.runtime.result_detect import (
    clear_sub_output_artifacts as _clear_sub_output_artifacts,
    detect_sub_success as _detect_sub_success,
    wait_pubsub_process as _wait_pubsub_process,
)
from src.scenarios.disaster import (
    _resolve_pubsub_publish_deadline_seconds,
    _resolve_pubsub_wait_seconds,
)


# ---------------------------------------------------------------------------
# _detect_sub_success
# ---------------------------------------------------------------------------


class TestDetectSubSuccess:
    def test_empty_directory_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is False
        assert result["artifact_path"] is None

    def test_nonempty_out_file_is_success(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        artifact = output_dir / "RNP0x0a1b2c.out"
        artifact.write_bytes(b"content data")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is True
        assert result["has_output_file"] is True
        assert result["artifact_path"] == str(artifact)

    def test_nonzero_exit_code_is_failure_even_with_file(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        artifact = output_dir / "RNP0xdeadbeef.out"
        artifact.write_bytes(b"content data")
        result = _detect_sub_success(1, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is True

    def test_zero_byte_file_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xempty.out").write_bytes(b"")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is False

    def test_nonexistent_directory_is_failure(self, tmp_path):
        output_dir = tmp_path / "does_not_exist"
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is False

    def test_returns_first_artifact_path(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        a1 = output_dir / "RNP0x0001.out"
        a2 = output_dir / "RNP0x0002.out"
        a1.write_bytes(b"a")
        a2.write_bytes(b"b")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["artifact_path"] in (str(a1), str(a2))

    def test_has_completed_log_always_false(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xabc.out").write_bytes(b"data")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["has_completed_log"] is False


# ---------------------------------------------------------------------------
# _clear_sub_output_artifacts
# ---------------------------------------------------------------------------


class TestClearSubOutputArtifacts:
    def test_removes_only_rnp_out_files(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        stale = output_dir / "RNP0xabc.out"
        stale.write_bytes(b"old")
        keep_log = output_dir / "cefsubfile.log"
        keep_log.write_text("log", encoding="utf-8")
        keep_other = output_dir / "RNP0xabc.tmp"
        keep_other.write_bytes(b"tmp")

        removed = _clear_sub_output_artifacts(output_dir)

        assert removed == 1
        assert not stale.exists()
        assert keep_log.exists()
        assert keep_other.exists()
        assert output_dir.exists()


# ---------------------------------------------------------------------------
# pub/sub timeout resolution
# ---------------------------------------------------------------------------


class TestPubsubTimingResolution:
    def test_explicit_sub_wait_takes_priority(self):
        wait = _resolve_pubsub_wait_seconds(
            {"wait": 15},
            "ccnx:/test/stream",
            {"ccnx:/test/stream": 8},
        )
        assert wait == 15

    def test_pub_lifetime_fallback_uses_seconds(self):
        wait = _resolve_pubsub_wait_seconds(
            {},
            "ccnx:/test/stream",
            {"ccnx:/test/stream": 8},
        )
        assert wait == 13

    def test_default_wait_is_thirty_seconds(self):
        wait = _resolve_pubsub_wait_seconds({}, "ccnx:/test/stream", {})
        assert wait == 30

    def test_publish_deadline_is_never_shorter_than_sub_wait(self):
        deadline = _resolve_pubsub_publish_deadline_seconds(
            "ccnx:/test/stream",
            {"lifetime": 8},
            {"ccnx:/test/stream": 15},
        )
        assert deadline == 20

    def test_publish_deadline_uses_default_lifetime_seconds(self):
        deadline = _resolve_pubsub_publish_deadline_seconds(
            "ccnx:/test/stream",
            {},
            {},
        )
        assert deadline == 35

    def test_expired_deadline_terminates_subscriber_immediately(self):
        proc = MagicMock()
        proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="cefsubfile", timeout=0),
            0,
        ]
        exit_code = _wait_pubsub_process(proc, time.monotonic() - 1)
        assert exit_code is None
        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()
