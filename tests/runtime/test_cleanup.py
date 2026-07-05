"""Unit tests for scenario shutdown cleanup helpers.

Mirrors the FakeCommandRunner-injection pattern established in
tests/runtime/test_debug.py (TestDumpFib): the real MininetCommandRunner is
swapped for a FakeCommandRunner via patch("src.runtime.cleanup.MininetCommandRunner", ...)
so pkill invocations are recorded instead of touching a real host namespace.

cleanup_all() additionally reaches into mininet.clean.cleanup (imported into
this module as mn_cleanup) and src.runtime.template.cleanup_node_dirs. Both
are patched out here: mn_cleanup would tear down real Mininet state on the
host machine, and cleanup_node_dirs's own behaviour is already covered by
tests/runtime/test_template.py — re-testing it here would just be redundant.
"""

from unittest.mock import MagicMock, patch

from src.runtime.cleanup import _CEF_PATTERNS, cleanup_all, kill_cef_processes
from src.runtime.command_runner import FakeCommandRunner


class TestKillCefProcesses:
    def test_issues_pkill_for_every_host_and_pattern(self):
        """Every (host, pattern) combination must reach the runner exactly once,
        in host-major order, so no daemon variant is left running on any host.
        """
        fake = FakeCommandRunner()
        net = MagicMock()
        net.hosts = [MagicMock(name="h0"), MagicMock(name="h1")]
        net.hosts[0].name = "h0"
        net.hosts[1].name = "h1"

        with patch("src.runtime.cleanup.MininetCommandRunner", return_value=fake):
            kill_cef_processes(net)

        expected = [
            (host_name, pattern)
            for host_name in ("h0", "h1")
            for pattern in _CEF_PATTERNS
        ]
        actual = [(run["node"], run["argv"][-1]) for run in fake.runs]
        assert actual == expected
        # pkill -9 -f <pattern> is the exact argv the old shell script issued.
        assert fake.runs[0]["argv"] == ["pkill", "-9", "-f", _CEF_PATTERNS[0]]

    def test_swallows_shell_busy_and_continues_remaining_hosts(self):
        """A busy host namespace raises AssertionError from the runner; that one
        (host, pattern) pair must be skipped without aborting the sweep over
        the rest of the hosts and patterns.
        """
        fake = FakeCommandRunner()
        net = MagicMock()
        net.hosts = [MagicMock(name="h0"), MagicMock(name="h1")]
        net.hosts[0].name = "h0"
        net.hosts[1].name = "h1"

        def raise_for_h0_first_pattern(node, argv):
            if node == "h0" and argv[-1] == _CEF_PATTERNS[0]:
                raise AssertionError("shell busy")
            return None

        fake.on_run = raise_for_h0_first_pattern

        with patch("src.runtime.cleanup.MininetCommandRunner", return_value=fake):
            kill_cef_processes(net)

        # The failing call was still recorded (it fails after being logged in
        # fake.runs), and every other host/pattern combination completed.
        recorded = [(run["node"], run["argv"][-1]) for run in fake.runs]
        expected = [
            (host_name, pattern)
            for host_name in ("h0", "h1")
            for pattern in _CEF_PATTERNS
        ]
        assert recorded == expected


class TestCleanupAll:
    def test_runs_collaborators_in_kill_stop_mncleanup_dirs_order(self, tmp_path):
        """The shutdown sequence is order-sensitive: process kill must happen
        while host namespaces still exist (before net.stop()), Mininet's own
        state teardown (mn_cleanup) must follow net.stop(), and generated
        directory removal happens last since it does not depend on network
        state at all.
        """
        fake = FakeCommandRunner()
        net = MagicMock()
        net.hosts = []
        call_order = []
        net.stop.side_effect = lambda: call_order.append("net.stop")
        generated_dirs = [tmp_path / "h0"]

        with patch(
            "src.runtime.cleanup.MininetCommandRunner", return_value=fake
        ), patch(
            "src.runtime.cleanup.mn_cleanup",
            side_effect=lambda: call_order.append("mn_cleanup"),
        ), patch(
            "src.runtime.cleanup.cleanup_node_dirs",
            side_effect=lambda dirs: call_order.append(("cleanup_node_dirs", dirs)),
        ) as mock_cleanup_node_dirs:
            cleanup_all(net, generated_dirs)

        assert call_order == [
            "net.stop",
            "mn_cleanup",
            ("cleanup_node_dirs", generated_dirs),
        ]
        mock_cleanup_node_dirs.assert_called_once_with(generated_dirs)

    def test_kill_cef_processes_runs_before_net_stop(self):
        """kill_cef_processes must issue its pkill runs before net.stop() tears
        down the host namespaces it depends on.
        """
        fake = FakeCommandRunner()
        net = MagicMock()
        net.hosts = [MagicMock(name="h0")]
        net.hosts[0].name = "h0"
        call_order = []
        net.stop.side_effect = lambda: call_order.append("net.stop")

        with patch(
            "src.runtime.cleanup.MininetCommandRunner", return_value=fake
        ), patch("src.runtime.cleanup.mn_cleanup"), patch(
            "src.runtime.cleanup.cleanup_node_dirs"
        ):
            cleanup_all(net, [])

        # All pkill runs were recorded before net.stop() fired.
        assert len(fake.runs) == len(_CEF_PATTERNS)
        assert call_order == ["net.stop"]

    def test_passes_generated_dirs_through_unchanged(self, tmp_path):
        """generated_dirs must reach cleanup_node_dirs verbatim, since it is the
        caller-owned list of directories to remove after teardown.
        """
        fake = FakeCommandRunner()
        net = MagicMock()
        net.hosts = []
        generated_dirs = [tmp_path / "h0", tmp_path / "h1"]

        with patch(
            "src.runtime.cleanup.MininetCommandRunner", return_value=fake
        ), patch("src.runtime.cleanup.mn_cleanup"), patch(
            "src.runtime.cleanup.cleanup_node_dirs"
        ) as mock_cleanup_node_dirs:
            cleanup_all(net, generated_dirs)

        mock_cleanup_node_dirs.assert_called_once_with(generated_dirs)

    def test_calls_net_stop_and_mn_cleanup_exactly_once(self):
        """net.stop() and mn_cleanup() are one-shot teardown calls; calling them
        more than once per scenario would be a sign of a caller-level bug.
        """
        fake = FakeCommandRunner()
        net = MagicMock()
        net.hosts = []

        with patch(
            "src.runtime.cleanup.MininetCommandRunner", return_value=fake
        ), patch("src.runtime.cleanup.mn_cleanup") as mock_mn_cleanup, patch(
            "src.runtime.cleanup.cleanup_node_dirs"
        ):
            cleanup_all(net, [])

        net.stop.assert_called_once_with()
        mock_mn_cleanup.assert_called_once_with()
