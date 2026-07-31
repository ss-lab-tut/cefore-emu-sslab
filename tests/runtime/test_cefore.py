"""Unit tests for cefore runtime command construction."""

from unittest.mock import MagicMock, patch

import pytest

import src.runtime.cefore as cefore_mod
from src.runtime.cefore import (
    run_ccninfo,
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefstatus,
    run_csmgrstatus,
    start_cefsubfile,
    status_output,
)
from src.runtime.command_runner import CommandResult, FakeCommandRunner


def _argv_str(argv):
    return " ".join(str(a) for a in argv)


# ---------------------------------------------------------------------------
# run_cefputfile — now argv + CommandRunner based
# ---------------------------------------------------------------------------


class TestRunCefputfile:
    def test_log_path_owns_redirect_not_argv(self):
        fake = FakeCommandRunner()
        run_cefputfile(fake, 2, "ccnx:/test/sample", log_name="/tmp/put.log")
        rec = fake.runs[0]
        assert rec["node"] == "h2"
        assert rec["log_path"] == "/tmp/put.log"
        # Redirection is owned by the seam, never present in argv.
        assert "2>&1" not in _argv_str(rec["argv"])
        assert ">" not in _argv_str(rec["argv"])

    def test_builds_expected_argv(self):
        fake = FakeCommandRunner()
        run_cefputfile(
            fake, 2, "ccnx:/test/sample", "/data/in.bin", log_name="/tmp/put.log"
        )
        argv = fake.runs[0]["argv"]
        assert argv[:4] == ["cefputfile", "ccnx:/test/sample", "-f", "/data/in.bin"]
        assert argv[-2:] == ["-d", "./h2"]

    def test_log_name_is_required(self):
        fake = FakeCommandRunner()
        # 2026-07-03 artifact-layout contract: callers must provide canonical
        # content_log_name paths; cefore no longer invents legacy fallbacks.
        with pytest.raises(TypeError):
            run_cefputfile(fake, 2, "ccnx:/test/sample")

    def test_returns_returncode(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=-15, cancelled=True)
        assert (
            run_cefputfile(fake, 2, "ccnx:/test/sample", log_name="/tmp/put.log") == -15
        )

    def test_passes_timeout_and_cancel_event(self):
        fake = FakeCommandRunner()
        sentinel = object()
        run_cefputfile(
            fake,
            2,
            "ccnx:/test/sample",
            log_name="/tmp/put.log",
            timeout=7,
            cancel_event=sentinel,
        )
        assert fake.runs[0]["timeout"] == 7
        assert fake.runs[0]["cancel_event"] is sentinel


# ---------------------------------------------------------------------------
# run_cefgetfile
# ---------------------------------------------------------------------------


class TestRunCefgetfile:
    def test_builds_expected_argv_and_log(self):
        fake = FakeCommandRunner()
        run_cefgetfile(
            fake, 0, "ccnx:/test/sample", "/tmp/recv", log_name="/tmp/get.log"
        )
        rec = fake.runs[0]
        assert rec["node"] == "h0"
        assert rec["argv"][:4] == ["cefgetfile", "ccnx:/test/sample", "-f", "/tmp/recv"]
        assert rec["log_path"] == "/tmp/get.log"
        assert "2>&1" not in _argv_str(rec["argv"])

    def test_log_name_is_required(self):
        fake = FakeCommandRunner()
        with pytest.raises(TypeError):
            run_cefgetfile(fake, 0, "ccnx:/test/sample", "/tmp/recv")

    def test_timeout_returncode(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=-15, timed_out=True)
        assert (
            run_cefgetfile(
                fake,
                0,
                "ccnx:/test/sample",
                "/tmp/recv",
                log_name="/tmp/get.log",
                timeout=0,
            )
            == -15
        )
        assert fake.runs[0]["timeout"] == 0


# ---------------------------------------------------------------------------
# run_ccninfo
# ---------------------------------------------------------------------------


class TestRunCcninfo:
    def test_builds_expected_argv_and_log(self):
        fake = FakeCommandRunner()
        run_ccninfo(
            fake, 0, "ccnx:/test/sample", log_name="/tmp/ccninfo.log"
        )
        rec = fake.runs[0]
        assert rec["node"] == "h0"
        assert rec["argv"] == ["ccninfo", "ccnx:/test/sample", "-d", "./h0"]
        assert rec["log_path"] == "/tmp/ccninfo.log"
        assert "2>&1" not in _argv_str(rec["argv"])

    def test_forwards_all_option_kwargs_into_argv(self):
        # port_num removed from run_ccninfo (Cefore 0.12.0 parse-order bug
        # makes -p ineffective); kept in build_ccninfo_argv only.
        fake = FakeCommandRunner()
        run_ccninfo(
            fake,
            0,
            "ccnx:/test/sample",
            log_name="/tmp/ccninfo.log",
            cache_info=True,
            owner_only=True,
            hop_count=5,
            skip_hop=1,
            valid_algo="crc32c",
        )
        argv = fake.runs[0]["argv"]
        assert argv[:5] == ["ccninfo", "ccnx:/test/sample", "-c", "-o", "-r"]
        assert argv[argv.index("-r") + 1] == "5"
        assert argv[argv.index("-s") + 1] == "1"
        assert argv[argv.index("-v") + 1] == "crc32c"
        assert "-p" not in argv
        assert argv[-2:] == ["-d", "./h0"]

    def test_log_name_is_required(self):
        fake = FakeCommandRunner()
        with pytest.raises(TypeError):
            run_ccninfo(fake, 0, "ccnx:/test/sample")

    def test_default_timeout_is_ccninfo_guard_timeout(self):
        fake = FakeCommandRunner()
        run_ccninfo(fake, 0, "ccnx:/test/sample", log_name="/tmp/ccninfo.log")
        # No explicit timeout kwarg: the module's CCNINFO_GUARD_TIMEOUT
        # constant must be what actually reaches the runner, not None —
        # ccninfo self-terminates but a hung binary must still be bounded.
        assert fake.runs[0]["timeout"] == cefore_mod.CCNINFO_GUARD_TIMEOUT

    def test_passes_timeout_and_cancel_event(self):
        fake = FakeCommandRunner()
        sentinel = object()
        run_ccninfo(
            fake,
            0,
            "ccnx:/test/sample",
            log_name="/tmp/ccninfo.log",
            timeout=7,
            cancel_event=sentinel,
        )
        assert fake.runs[0]["timeout"] == 7
        assert fake.runs[0]["cancel_event"] is sentinel

    def test_cefore_env_dir_prepends_env_prefix_to_argv(self):
        fake = FakeCommandRunner()
        run_ccninfo(
            fake, 0, "ccnx:/test/sample",
            log_name="/tmp/ccninfo.log",
            cefore_env_dir="/abs/path/h0/.cefore_env",
        )
        argv = fake.runs[0]["argv"]
        assert argv[0] == "env"
        assert argv[1] == "CEFORE_DIR=/abs/path/h0/.cefore_env"
        assert argv[2] == "ccninfo"

    def test_cefore_env_dir_none_has_no_env_prefix(self):
        fake = FakeCommandRunner()
        run_ccninfo(
            fake, 0, "ccnx:/test/sample",
            log_name="/tmp/ccninfo.log",
            cefore_env_dir=None,
        )
        argv = fake.runs[0]["argv"]
        assert argv[0] == "ccninfo"

    def test_returns_full_command_result_not_just_returncode(self):
        # Unlike run_cefputfile/run_cefgetfile (legacy contract: bare exit
        # code), ccninfo verdict interpretation needs timed_out/cancelled —
        # a timeout and a "no cache found" reply are both exit-code-ish but
        # mean very different things, so the caller needs the full result.
        # Scripting timed_out=True (a non-default value distinct from a
        # plain-success result) is the discriminating case: a caller that
        # reconstructed a partial CommandResult from just the returncode
        # would silently drop this flag and this assertion would catch it.
        #
        # Note: run_ccninfo always passes log_path=log_name, so on the real
        # MininetCommandRunner stdout is redirected to that log file and
        # CommandResult.stdout comes back empty (see MininetCommandRunner
        # .wait()/._spawn()) — the reply text lives in the log file, not in
        # this field. FakeCommandRunner clones scripted stdout regardless of
        # log_path, so the stdout assertion below is Fake-only fiction kept
        # for documentation; it does not hold against the real runner.
        fake = FakeCommandRunner()
        fake.script_run(
            returncode=-15,
            stdout="cache info\n",
            timed_out=True,
            cancelled=False,
        )
        result = run_ccninfo(
            fake, 0, "ccnx:/test/sample", log_name="/tmp/ccninfo.log"
        )
        assert isinstance(result, CommandResult)
        assert result.returncode == -15
        assert result.stdout == "cache info\n"
        assert result.timed_out is True
        assert result.cancelled is False


# ---------------------------------------------------------------------------
# start_cefsubfile — non-blocking, returns a CommandHandle
# ---------------------------------------------------------------------------


class TestStartCefsubfile:
    def test_starts_and_records_handle(self):
        fake = FakeCommandRunner()
        handle = start_cefsubfile(
            fake,
            0,
            "ccnx:/test/stream",
            output_path="/tmp/recvdir",
            log_name="/tmp/sub.log",
        )
        assert handle is fake.starts[0]
        assert handle.node == "h0"
        assert handle.log_path == "/tmp/sub.log"
        assert "2>&1" not in _argv_str(handle.argv)

    def test_log_name_is_required(self):
        fake = FakeCommandRunner()
        with pytest.raises(TypeError):
            start_cefsubfile(fake, 0, "ccnx:/test/stream")


# ---------------------------------------------------------------------------
# run_cefpubfile — non-blocking, returns a CommandHandle
# ---------------------------------------------------------------------------


class TestRunCefpubfile:
    def test_starts_and_records_handle(self):
        fake = FakeCommandRunner()
        handle = run_cefpubfile(
            fake, 2, "ccnx:/test/stream", "/tmp/pub.bin", log_name="/tmp/pub.log"
        )
        assert handle is fake.starts[0]
        assert handle.node == "h2"
        assert handle.argv[:4] == [
            "cefpubfile",
            "ccnx:/test/stream",
            "-f",
            "/tmp/pub.bin",
        ]
        assert handle.log_path == "/tmp/pub.log"

    def test_log_name_is_required(self):
        fake = FakeCommandRunner()
        with pytest.raises(TypeError):
            run_cefpubfile(fake, 2, "ccnx:/test/stream", "/tmp/pub.bin")


# ---------------------------------------------------------------------------
# run_csmgrstatus — now argv + CommandRunner based
# ---------------------------------------------------------------------------


class TestRunCsmgrstatus:
    def test_default_runs_argv_and_emits_output(self):
        fake = FakeCommandRunner()
        fake.script_run(stdout="status output")
        with (
            patch.object(cefore_mod, "MininetCommandRunner", return_value=fake),
            patch.object(cefore_mod, "info") as mock_info,
        ):
            out = run_csmgrstatus(MagicMock(), 1, uri="ccnx:/", host="127.0.0.1")
        assert out.stdout == "status output"
        rec = fake.runs[0]
        assert rec["node"] == "h1"
        assert rec["argv"] == ["csmgrstatus", "ccnx:/", "-h", "127.0.0.1"]
        assert ">" not in _argv_str(rec["argv"])
        mock_info.assert_any_call("status output")

    def test_quiet_suppresses_print_and_info(self, capsys):
        fake = FakeCommandRunner()
        fake.script_run(stdout="status output")
        with (
            patch.object(cefore_mod, "MininetCommandRunner", return_value=fake),
            patch.object(cefore_mod, "info") as mock_info,
        ):
            out = run_csmgrstatus(
                MagicMock(), 1, uri="ccnx:/", host="127.0.0.1", quiet=True
            )
        assert out.stdout == "status output"
        mock_info.assert_not_called()
        assert "command:" not in capsys.readouterr().out

    def test_log_name_redirects_stdout_only(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_csmgrstatus(
                MagicMock(), 1, host="127.0.0.1", log_name="/tmp/c.log", quiet=True
            )
        rec = fake.runs[0]
        assert rec["log_path"] == "/tmp/c.log"
        # stdout-only-to-log: stderr kept separate so the log stays stdout-only.
        assert rec["capture_stderr"] is True

    def test_timeout_forwarded(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_csmgrstatus(MagicMock(), 1, host="127.0.0.1", quiet=True, timeout=10)
        assert fake.runs[0]["timeout"] == 10

    def test_port_num_builds_two_token_argv(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_csmgrstatus(MagicMock(), 1, port_num=9799, host="127.0.0.1", quiet=True)
        argv = fake.runs[0]["argv"]
        assert argv == ["csmgrstatus", "-p", "9799", "-h", "127.0.0.1"]

    def test_timeout_returns_command_result_with_timed_out_flag(self):
        fake = FakeCommandRunner()
        fake.script_run(timed_out=True)
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            out = run_csmgrstatus(MagicMock(), 1, host="127.0.0.1", quiet=True)
        assert out.timed_out is True
        assert status_output(out) == "error: command timeout"


# ---------------------------------------------------------------------------
# run_cefstatus — 2026-07-12: quiet/timeout/timed_out->"error: command
# timeout" shape aligned with run_csmgrstatus (run_csmgrstatus itself has
# no runner= parameter; that injection seam is run_cefstatus-only).
# ---------------------------------------------------------------------------


class TestRunCefstatus:
    def test_default_runs_argv_and_emits_output(self):
        fake = FakeCommandRunner()
        fake.script_run(stdout="fib output")
        with (
            patch.object(cefore_mod, "MininetCommandRunner", return_value=fake),
            patch.object(cefore_mod, "info") as mock_info,
        ):
            out = run_cefstatus(MagicMock(), 1)
        assert out.stdout == "fib output"
        rec = fake.runs[0]
        assert rec["node"] == "h1"
        assert rec["argv"] == ["cefstatus", "-d", "./h1"]
        mock_info.assert_any_call("h1 command: ['cefstatus', '-d', './h1']\n")
        mock_info.assert_any_call("fib output")

    def test_quiet_suppresses_print_and_info(self, capsys):
        fake = FakeCommandRunner()
        fake.script_run(stdout="fib output")
        with (
            patch.object(cefore_mod, "MininetCommandRunner", return_value=fake),
            patch.object(cefore_mod, "info") as mock_info,
        ):
            out = run_cefstatus(MagicMock(), 1, quiet=True)
        assert out.stdout == "fib output"
        mock_info.assert_not_called()
        assert "command:" not in capsys.readouterr().out

    def test_timeout_forwarded(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_cefstatus(MagicMock(), 1, quiet=True, timeout=10)
        assert fake.runs[0]["timeout"] == 10

    def test_timeout_returns_command_result_with_timed_out_flag(self):
        fake = FakeCommandRunner()
        fake.script_run(timed_out=True)
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            out = run_cefstatus(MagicMock(), 1, quiet=True)
        assert out.timed_out is True
        assert status_output(out) == "error: command timeout"

    def test_runner_injection_skips_mininet_command_runner_construction(self):
        fake = FakeCommandRunner()
        fake.script_run(stdout="fib output")
        with patch.object(cefore_mod, "MininetCommandRunner") as mock_ctor:
            out = run_cefstatus(MagicMock(), 1, quiet=True, runner=fake)
        mock_ctor.assert_not_called()
        assert out.stdout == "fib output"
        assert fake.runs[0]["node"] == "h1"
        assert fake.runs[0]["argv"] == ["cefstatus", "-d", "./h1"]


def test_start_cefnetd_removes_stale_socket_and_cefnetd_log_before_start():
    fake = FakeCommandRunner()
    calls = []

    def cleanup_socket(node_dir, idx):
        calls.append(("socket", node_dir, idx))

    def cleanup_log(node_dir, idx):
        calls.append(("cefnetd_log", node_dir, idx))

    with (
        patch.object(cefore_mod, "cleanup_cefnetd_socket", side_effect=cleanup_socket),
        patch.object(cefore_mod, "cleanup_stale_cefnetd_log", side_effect=cleanup_log),
        patch.object(cefore_mod.time, "sleep"),
    ):
        cefore_mod.start_cefnetd(MagicMock(), 2, runner=fake)

    assert ("socket", "h2", 2) in calls
    assert ("cefnetd_log", "h2", 2) in calls
    assert fake.runs[0]["node"] == "h2"


def test_start_csmgrd_removes_only_stale_csmgrd_log_before_start():
    fake = FakeCommandRunner()

    with (
        patch.object(cefore_mod, "cleanup_stale_csmgrd_log") as cleanup_csmgrd_log,
        patch.object(cefore_mod, "cleanup_stale_cefnetd_log") as cleanup_cefnetd_log,
        patch.object(cefore_mod, "wait_for_csmgrd"),
    ):
        cefore_mod.start_csmgrd(MagicMock(), 1, runner=fake)

    cleanup_csmgrd_log.assert_called_once_with("h1", 1)
    cleanup_cefnetd_log.assert_not_called()
    assert fake.runs[0]["node"] == "h1"


# ---------------------------------------------------------------------------
# Daemon control — runner DI (N: DaemonFleet)
# ---------------------------------------------------------------------------


class TestDaemonRunnerInjection:
    def test_start_csmgrd_runs_through_injected_runner(self):
        fake = FakeCommandRunner()
        cefore_mod.start_csmgrd(None, 1, runner=fake)
        assert fake.runs[0]["node"] == "h1"
        assert fake.runs[0]["argv"][0] == "csmgrdstart"
        # The readiness poll (csmgrstatus) goes through the same runner.
        assert fake.runs[1]["argv"][0] == "csmgrstatus"

    def test_start_cefnetd_runs_through_injected_runner(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod.time, "sleep"):
            cefore_mod.start_cefnetd(None, 2, runner=fake)
        assert fake.runs[0]["node"] == "h2"
        assert fake.runs[0]["argv"][0] == "cefnetdstart"

    def test_stop_daemons_run_through_injected_runner(self):
        fake = FakeCommandRunner()
        cefore_mod.stop_cefnetd(None, 0, runner=fake)
        cefore_mod.stop_csmgrd(None, 0, runner=fake)
        assert fake.runs[0]["argv"][0] == "cefnetdstop"
        assert fake.runs[1]["argv"][0] == "csmgrdstop"

    def test_wait_for_cefnetd_polls_through_injected_runner(self):
        fake = FakeCommandRunner()
        assert cefore_mod.wait_for_cefnetd(None, 3, runner=fake) is True
        assert fake.runs[0]["node"] == "h3"
        assert fake.runs[0]["argv"][0] == "cefstatus"

    def test_wait_for_csmgrd_polls_through_injected_runner(self):
        fake = FakeCommandRunner()
        assert cefore_mod.wait_for_csmgrd(None, 3, runner=fake) is True
        assert fake.runs[0]["argv"] == ["csmgrstatus"]
