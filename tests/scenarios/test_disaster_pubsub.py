"""Unit tests for pub/sub helpers in disaster scenario."""

import time
from unittest.mock import MagicMock, patch

from src.runtime.content_ops import ContentOperationRunner
from src.runtime.result_detect import (
    clear_sub_output_artifacts as _clear_sub_output_artifacts,
    detect_sub_success as _detect_sub_success,
    wait_pubsub_process as _wait_pubsub_process,
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
# pub/sub timeout resolution (ContentOperationRunner)
# ---------------------------------------------------------------------------


def _make_runner(tmp_path, pub_lifetime_by_uri=None):
    """Create a ContentOperationRunner with mocked dependencies."""
    net = MagicMock()
    flap_state = MagicMock()
    flap_state.snapshot.return_value = []
    return ContentOperationRunner(
        net,
        run_dir=tmp_path,
        result_callback=MagicMock(),
        flap_state=flap_state,
        seed_label="test",
        pub_lifetime_by_uri=pub_lifetime_by_uri,
    )


class TestPubsubTimingResolution:
    @patch("src.runtime.content_ops.start_cefsubfile")
    def test_explicit_sub_wait_takes_priority(self, mock_sub, tmp_path):
        runner = _make_runner(
            tmp_path, pub_lifetime_by_uri={"ccnx:/test/stream": 8}
        )
        mock_sub.return_value = MagicMock(pid=1)
        before = time.monotonic()
        runner._do_pubsub_sub({
            "host": 0, "uri": "ccnx:/test/stream",
            "sub_opts": {"wait": 15},
        })
        entries = runner._pending_subs["ccnx:/test/stream"]
        assert len(entries) == 1
        deadline = entries[0]["deadline"]
        assert abs(deadline - (before + 15)) < 2.0

    @patch("src.runtime.content_ops.start_cefsubfile")
    def test_pub_lifetime_fallback_uses_seconds(self, mock_sub, tmp_path):
        runner = _make_runner(
            tmp_path, pub_lifetime_by_uri={"ccnx:/test/stream": 8}
        )
        mock_sub.return_value = MagicMock(pid=1)
        before = time.monotonic()
        runner._do_pubsub_sub({
            "host": 0, "uri": "ccnx:/test/stream",
        })
        entries = runner._pending_subs["ccnx:/test/stream"]
        deadline = entries[0]["deadline"]
        assert abs(deadline - (before + 13)) < 2.0

    @patch("src.runtime.content_ops.start_cefsubfile")
    def test_default_wait_is_thirty_seconds(self, mock_sub, tmp_path):
        runner = _make_runner(tmp_path)
        mock_sub.return_value = MagicMock(pid=1)
        before = time.monotonic()
        runner._do_pubsub_sub({
            "host": 0, "uri": "ccnx:/test/stream",
        })
        entries = runner._pending_subs["ccnx:/test/stream"]
        deadline = entries[0]["deadline"]
        assert abs(deadline - (before + 30)) < 2.0

    def test_expired_deadline_terminates_subscriber_immediately(self):
        proc = MagicMock()
        proc.wait.return_value = 0
        exit_code = _wait_pubsub_process(proc, time.monotonic() - 1)
        assert exit_code is None
        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()


# ---------------------------------------------------------------------------
# ContentOperationRunner phase parameter
# ---------------------------------------------------------------------------


class TestContentOperationRunnerPhase:
    def test_phase_parameter_default_is_event(self):
        runner = ContentOperationRunner(
            net=MagicMock(),
            run_dir="/tmp",
            result_callback=MagicMock(),
            flap_state=MagicMock(),
            seed_label="test",
        )
        assert runner._phase == "event"

    def test_phase_parameter_custom(self):
        runner = ContentOperationRunner(
            net=MagicMock(),
            run_dir="/tmp",
            result_callback=MagicMock(),
            flap_state=MagicMock(),
            seed_label="test",
            phase="warmup",
        )
        assert runner._phase == "warmup"


class TestContentOperationRunnerDeadline:
    @patch("src.runtime.content_ops.run_cefgetfile")
    def test_timeout_cancels_running_operation_and_returns_false(
        self, mock_get, tmp_path
    ):
        def wait_until_cancelled(*args, **kwargs):
            cancel_event = kwargs["cancel_event"]
            assert cancel_event.wait(timeout=1)
            return -15

        mock_get.side_effect = wait_until_cancelled
        runner = _make_runner(tmp_path)
        runner.start()
        runner.submit("get", {"host": 0, "uri": "ccnx:/test/slow"})
        assert runner.wait_all(timeout=0.01) is False
        runner.stop()

    @patch("src.runtime.content_ops.run_cefputfile")
    def test_put_restores_disaster_default_expiry_and_cache_time(
        self, mock_put, tmp_path
    ):
        runner = _make_runner(tmp_path)
        runner._do_put({"host": 2, "uri": "ccnx:/test/defaults"})
        assert mock_put.call_args.kwargs["expiry"] == 3000
        assert mock_put.call_args.kwargs["cache_time"] == 3000

    @patch("src.runtime.content_ops.run_cefpubfile")
    def test_pubsub_pub_keeps_expiry_and_cache_time_explicit_only(
        self, mock_pub, tmp_path
    ):
        proc = MagicMock()
        proc.wait.return_value = 0
        mock_pub.return_value = proc
        runner = ContentOperationRunner(
            MagicMock(),
            run_dir=tmp_path,
            result_callback=MagicMock(),
            flap_state=MagicMock(),
            seed_label="test",
            startup_grace=0,
        )
        runner._do_pubsub_pub(
            {"host": 2, "uri": "ccnx:/test/live", "file": "./sample-putfile"}
        )
        assert mock_pub.call_args.kwargs["expiry"] is None
        assert mock_pub.call_args.kwargs["cache_time"] is None
