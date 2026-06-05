"""Unit tests for debug artifact collectors."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.runtime.command_runner import FakeCommandRunner
from src.runtime.debug import archive_daemon_logs, dump_fib


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


class TestArchiveDaemonLogs:
    def test_copies_existing_logs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "h0-cefnetd-log").write_text("netd log")
        (tmp_path / "h0-csmgrd-log").write_text("csmgrd log")
        dest = tmp_path / "out"
        archive_daemon_logs(1, dest)
        assert (dest / "h0-cefnetd-log").read_text() == "netd log"
        assert (dest / "h0-csmgrd-log").read_text() == "csmgrd log"

    def test_skips_missing_logs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dest = tmp_path / "out"
        archive_daemon_logs(2, dest)
        assert dest.is_dir()
        assert list(dest.iterdir()) == []

    def test_creates_dest_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dest = tmp_path / "nested" / "daemon_logs"
        archive_daemon_logs(0, dest)
        assert dest.is_dir()
