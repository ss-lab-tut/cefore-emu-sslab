"""Unit tests for debug artifact collectors."""

from unittest.mock import MagicMock, patch

from src.runtime.command_runner import CommandResult
from src.runtime.debug import dump_fib


def _cr(stdout=""):
    return CommandResult(returncode=0, stdout=stdout)


class TestDumpFib:
    def test_creates_fib_files(self, tmp_path):
        with patch(
            "src.runtime.debug.run_cefstatus", return_value=_cr("FIB dump output")
        ):
            dump_fib(MagicMock(), [0, 1, 2], tmp_path)
        for idx in range(3):
            fib_file = tmp_path / f"fib_h{idx}.txt"
            assert fib_file.exists()
            assert fib_file.read_text() == "FIB dump output"

    def test_calls_run_cefstatus_quietly_per_host(self, tmp_path):
        net = MagicMock()
        with patch(
            "src.runtime.debug.run_cefstatus", return_value=_cr("FIB dump output")
        ) as mock_fn:
            dump_fib(net, [0], tmp_path)
        mock_fn.assert_called_once_with(net, 0, quiet=True)

    def test_creates_dest_dir(self, tmp_path):
        dest = tmp_path / "subdir" / "fib"
        with patch("src.runtime.debug.run_cefstatus", return_value=_cr()):
            dump_fib(MagicMock(), [0], dest)
        assert dest.is_dir()

    def test_timeout_result_writes_diagnostic_string(self, tmp_path):
        cr = CommandResult(returncode=None, stdout="", timed_out=True)
        with patch("src.runtime.debug.run_cefstatus", return_value=cr):
            dump_fib(MagicMock(), [0], tmp_path)
        assert (tmp_path / "fib_h0.txt").read_text() == "error: command timeout"
