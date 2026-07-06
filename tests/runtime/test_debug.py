"""Unit tests for debug artifact collectors."""

from unittest.mock import MagicMock, patch

from src.runtime.command_runner import FakeCommandRunner
from src.runtime.debug import dump_fib


class TestDumpFib:
    def test_creates_fib_files(self, tmp_path):
        fake = FakeCommandRunner()
        for _ in range(3):
            fake.script_run(stdout="FIB dump output")
        with patch("src.runtime.debug.MininetCommandRunner", return_value=fake):
            dump_fib(MagicMock(), [0, 1, 2], tmp_path)
        for idx in range(3):
            fib_file = tmp_path / f"fib_h{idx}.txt"
            assert fib_file.exists()
            assert fib_file.read_text() == "FIB dump output"

    def test_uses_correct_cefstatus_command(self, tmp_path):
        fake = FakeCommandRunner()
        with patch("src.runtime.debug.MininetCommandRunner", return_value=fake):
            dump_fib(MagicMock(), [0], tmp_path)
        assert fake.runs[0]["node"] == "h0"
        assert fake.runs[0]["argv"] == ["cefstatus", "-d", "./h0"]

    def test_creates_dest_dir(self, tmp_path):
        dest = tmp_path / "subdir" / "fib"
        fake = FakeCommandRunner()
        with patch("src.runtime.debug.MininetCommandRunner", return_value=fake):
            dump_fib(MagicMock(), [0], dest)
        assert dest.is_dir()
