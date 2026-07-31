"""Unit tests for pub/sub helpers in disaster scenario.

These now drive the CommandRunner seam: cefsubfile/cefpubfile success is
expressed through ``CommandResult`` flags (returncode / timed_out / cancelled)
rather than a ``None`` exit-code sentinel. The killed-after-delivery case (a
subscriber terminated by the deadline once content already arrived) must still
count as success — that is the load-bearing invariant carried over from the old
``exit_code in (0, None)`` rule.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.content_ops import ContentOperationRunner
from src.runtime.results_sink import RecordingSink
from src.runtime.result_detect import (
    clear_sub_output_artifacts as _clear_sub_output_artifacts,
    detect_sub_success as _detect_sub_success,
)


def _result(returncode=0, timed_out=False, cancelled=False):
    return CommandResult(returncode=returncode, timed_out=timed_out, cancelled=cancelled)


# ---------------------------------------------------------------------------
# detect_sub_success (CommandResult-based)
# ---------------------------------------------------------------------------


class TestDetectSubSuccess:
    def test_empty_directory_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        result = _detect_sub_success(_result(0), output_dir, tmp_path / "sub.log")
        assert result.success is False
        assert result.has_output_file is False
        assert result.artifact_path is None

    def test_nonempty_out_file_is_success(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        artifact = output_dir / "RNP0x0a1b2c.out"
        artifact.write_bytes(b"content data")
        result = _detect_sub_success(_result(0), output_dir, tmp_path / "sub.log")
        assert result.success is True
        assert result.has_output_file is True
        assert result.artifact_path == str(artifact)

    def test_nonzero_exit_code_is_failure_even_with_file(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        artifact = output_dir / "RNP0xdeadbeef.out"
        artifact.write_bytes(b"content data")
        result = _detect_sub_success(_result(1), output_dir, tmp_path / "sub.log")
        assert result.success is False
        assert result.has_output_file is True

    def test_timed_out_with_file_is_success(self, tmp_path):
        # Killed by the deadline AFTER content was delivered -> still success.
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xaa.out").write_bytes(b"content data")
        result = _detect_sub_success(
            _result(-15, timed_out=True), output_dir, tmp_path / "sub.log"
        )
        assert result.success is True

    def test_cancelled_with_file_is_success(self, tmp_path):
        # Cancelled AFTER content was delivered -> still success.
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xbb.out").write_bytes(b"content data")
        result = _detect_sub_success(
            _result(-15, cancelled=True), output_dir, tmp_path / "sub.log"
        )
        assert result.success is True

    def test_timed_out_without_file_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        result = _detect_sub_success(
            _result(-15, timed_out=True), output_dir, tmp_path / "sub.log"
        )
        assert result.success is False

    def test_zero_byte_file_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xempty.out").write_bytes(b"")
        result = _detect_sub_success(_result(0), output_dir, tmp_path / "sub.log")
        assert result.success is False
        assert result.has_output_file is False

    def test_nonexistent_directory_is_failure(self, tmp_path):
        output_dir = tmp_path / "does_not_exist"
        result = _detect_sub_success(_result(0), output_dir, tmp_path / "sub.log")
        assert result.success is False
        assert result.has_output_file is False

    def test_returns_first_artifact_path(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        a1 = output_dir / "RNP0x0001.out"
        a2 = output_dir / "RNP0x0002.out"
        a1.write_bytes(b"a")
        a2.write_bytes(b"b")
        result = _detect_sub_success(_result(0), output_dir, tmp_path / "sub.log")
        assert result.artifact_path in (str(a1), str(a2))

    def test_has_completed_log_not_applicable(self, tmp_path):
        # The completed-marker Factor does not apply to sub: tri-state None.
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xabc.out").write_bytes(b"data")
        result = _detect_sub_success(_result(0), output_dir, tmp_path / "sub.log")
        assert result.has_completed_log is None


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


def _make_runner(tmp_path, pub_lifetime_by_uri=None, runner=None):
    """Create a ContentOperationRunner with mocked dependencies."""
    net = MagicMock()
    flap_state = MagicMock()
    flap_state.snapshot.return_value = []
    return ContentOperationRunner(
        net,
        run_dir=tmp_path,
        sink=RecordingSink(),
        flap_state=flap_state,
        pub_lifetime_by_uri=pub_lifetime_by_uri,
        runner=runner,
    )


class TestPubsubTimingResolution:
    @patch("src.runtime.content_ops.start_cefsubfile")
    def test_explicit_sub_wait_takes_priority(self, mock_sub, tmp_path):
        runner = _make_runner(
            tmp_path, pub_lifetime_by_uri={"ccnx:/test/stream": 8}
        )
        mock_sub.return_value = MagicMock()
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
        mock_sub.return_value = MagicMock()
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
        mock_sub.return_value = MagicMock()
        before = time.monotonic()
        runner._do_pubsub_sub({
            "host": 0, "uri": "ccnx:/test/stream",
        })
        entries = runner._pending_subs["ccnx:/test/stream"]
        deadline = entries[0]["deadline"]
        assert abs(deadline - (before + 30)) < 2.0


# ---------------------------------------------------------------------------
# Full pub/sub path through a FakeCommandRunner
# ---------------------------------------------------------------------------


class TestPubsubFullPathFake:
    def test_sub_killed_after_delivery_is_success(self, tmp_path):
        """A subscriber terminated by the deadline AFTER delivering content is
        still a success — the killed-after-delivery invariant, now expressed
        through the timed_out flag instead of a None exit code."""
        fake = FakeCommandRunner()

        def deliver_then_die(handle):
            if handle.argv[0] != "cefsubfile":
                return
            out_dir = Path(handle.argv[handle.argv.index("-f") + 1])
            (out_dir / "RNP0xabc.out").write_bytes(b"content")
            # The deadline kills this sub after content already arrived.
            handle.result = CommandResult(returncode=-15, timed_out=True)

        fake.on_start = deliver_then_die

        sink = RecordingSink()
        flap_state = MagicMock()
        flap_state.snapshot.return_value = []
        runner = ContentOperationRunner(
            MagicMock(),
            run_dir=tmp_path,
            sink=sink,
            flap_state=flap_state,
            startup_grace=0,
            runner=fake,
        )
        runner._do_pubsub_sub(
            {"host": 1, "uri": "ccnx:/test/live", "sub_opts": {"wait": 1}}
        )
        runner._do_pubsub_pub(
            {"host": 2, "uri": "ccnx:/test/live", "file": "./sample-putfile"}
        )

        sub_results = sink.of_type("sub")
        assert len(sub_results) == 1
        assert sub_results[0]["success"] is True
        assert sub_results[0]["has_output_file"] is True


# ---------------------------------------------------------------------------
# ContentOperationRunner phase parameter
# ---------------------------------------------------------------------------


class TestContentOperationRunnerPhase:
    def test_phase_parameter_default_is_event(self):
        runner = ContentOperationRunner(
            net=MagicMock(),
            run_dir="/tmp",
            sink=RecordingSink(),
            flap_state=MagicMock(),
        )
        assert runner._phase == "event"

    def test_phase_parameter_custom(self):
        runner = ContentOperationRunner(
            net=MagicMock(),
            run_dir="/tmp",
            sink=RecordingSink(),
            flap_state=MagicMock(),
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

    def test_pubsub_pub_keeps_expiry_and_cache_time_explicit_only(self, tmp_path):
        fake = FakeCommandRunner()
        flap_state = MagicMock()
        flap_state.snapshot.return_value = []
        runner = ContentOperationRunner(
            MagicMock(),
            run_dir=tmp_path,
            sink=RecordingSink(),
            flap_state=flap_state,
            startup_grace=0,
            runner=fake,
        )
        runner._do_pubsub_pub(
            {"host": 2, "uri": "ccnx:/test/live", "file": "./sample-putfile"}
        )
        pub_argv = fake.starts[0].argv
        # pub_opts does not acquire the disaster 3000 default; omitted stays omitted.
        assert "-e" not in pub_argv
        assert "-t" not in pub_argv


# ---------------------------------------------------------------------------
# put record (ContentOperationRunner)
# ---------------------------------------------------------------------------


class TestPutRecord:
    """_do_put records a runtime Verdict; put failures are no longer silent."""

    @patch("src.runtime.content_ops.run_cefputfile")
    def test_put_success_record(self, mock_put, tmp_path):
        mock_put.return_value = 0
        runner = _make_runner(tmp_path)
        runner._do_put({"host": 9, "uri": "ccnx:/test/seed"})
        record = runner._sink.records[-1]
        assert record["op_type"] == "put"
        assert record["success"] is True
        assert record["exit_code"] == 0
        # exit code is the only runtime evidence: other Factors not applicable.
        assert record["has_completed_log"] is None
        assert record["has_output_file"] is None
        assert record["out_file"] is None
        assert record["publisher_host"] == 9
        assert record["publisher_down"] is False

    @patch("src.runtime.content_ops.run_cefputfile")
    def test_put_failure_record(self, mock_put, tmp_path):
        mock_put.return_value = 1
        runner = _make_runner(tmp_path)
        runner._do_put({"host": 9, "uri": "ccnx:/test/seed"})
        record = runner._sink.records[-1]
        assert record["success"] is False
        assert record["exit_code"] == 1


class TestPubRecordPublisherDown:
    """pub records report publisher_down honestly (audit fix, was hard-coded False)."""

    def test_pub_publisher_down_reflects_flap_state(self, tmp_path):
        fake = FakeCommandRunner()
        flap_state = MagicMock()
        flap_state.snapshot.return_value = [2]
        sink = RecordingSink()
        runner = ContentOperationRunner(
            MagicMock(),
            run_dir=tmp_path,
            sink=sink,
            flap_state=flap_state,
            startup_grace=0,
            runner=fake,
        )
        runner._do_pubsub_pub(
            {"host": 2, "uri": "ccnx:/test/live", "file": "./sample-putfile"}
        )
        pub_rows = sink.of_type("pub")
        assert pub_rows
        assert pub_rows[0]["publisher_down"] is True
        assert pub_rows[0]["down_hosts"] == [2]
