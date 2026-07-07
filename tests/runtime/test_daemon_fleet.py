"""Behavior tests for the DaemonFleet lifecycle seam."""

from pathlib import Path
from unittest.mock import patch

import pytest

import src.runtime.cefore as cefore_mod
from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.daemon_fleet import DaemonFleet, build_fleet


def _fleet(fake, **kwargs):
    defaults = dict(
        node_names=["h0", "h1", "h2"],
        csmgrd_nodes={"h1"},
        runner=fake,
    )
    defaults.update(kwargs)
    return DaemonFleet(None, **defaults)


class TestBuildFleet:
    def test_builds_node_names_and_csmgrd_nodes_from_host_ids(self):
        fleet = build_fleet(None, 4, {1, 3}, Path("."))

        assert fleet.node_names == ["h0", "h1", "h2", "h3"]
        assert fleet.csmgrd_nodes == {"h1", "h3"}
        assert fleet._log_dir is None

    def test_uses_run_dir_as_log_dir_when_not_current_directory(self):
        run_dir = Path("/tmp/cefore-run")
        fleet = build_fleet(None, 2, [], run_dir)

        assert fleet.node_names == ["h0", "h1"]
        assert fleet.csmgrd_nodes == set()
        assert fleet._log_dir == str(run_dir)


class TestStartAll:
    def test_starts_csmgrd_before_cefnetd_through_the_runner(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake)
        with patch.object(cefore_mod.time, "sleep"):
            fleet.start_all()
        commands = [(run["node"], run["argv"][0]) for run in fake.runs]
        assert commands == [
            ("h1", "csmgrdstart"),
            ("h1", "csmgrstatus"),  # readiness poll inside start_csmgrd
            ("h0", "cefnetdstart"),
            ("h1", "cefnetdstart"),
            ("h2", "cefnetdstart"),
        ]
        assert fleet.started_csmgrd == {"h1"}


def _not_ready_on(*nodes):
    """on_run hook: cefstatus fails on the given nodes (cefnetd not ready)."""

    def hook(node, argv):
        if argv[0] == "cefstatus" and node in nodes:
            return CommandResult(returncode=1)
        return None

    return hook


class TestWaitReady:
    def test_all_ready_returns_empty_list(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake)
        assert fleet.wait_ready() == []

    def test_warn_policy_reports_not_ready_hosts_and_continues(self):
        fake = FakeCommandRunner()
        fake.on_run = _not_ready_on("h1")
        fleet = _fleet(fake, cefnetd_timeout=0.05)
        with patch.object(cefore_mod.time, "sleep"):
            assert fleet.wait_ready() == ["h1"]

    def test_raise_policy_aborts_with_not_ready_hosts(self):
        fake = FakeCommandRunner()
        fake.on_run = _not_ready_on("h0", "h2")
        fleet = _fleet(fake, cefnetd_timeout=0.05, readiness_policy="raise")
        with patch.object(cefore_mod.time, "sleep"):
            with pytest.raises(RuntimeError) as exc:
                fleet.wait_ready()
        assert "h0, h2" in str(exc.value)
        assert "aborting before FIB programming" in str(exc.value)


class TestStopAll:
    def test_stops_cefnetd_everywhere_then_only_started_csmgrd(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake)
        with patch.object(cefore_mod.time, "sleep"):
            fleet.start_all()
        fake.runs.clear()
        assert fleet.stop_all() == []
        commands = [(run["node"], run["argv"][0]) for run in fake.runs]
        assert commands == [
            ("h0", "cefnetdstop"),
            ("h1", "cefnetdstop"),
            ("h2", "cefnetdstop"),
            ("h1", "csmgrdstop"),
        ]

    def test_unstarted_csmgrd_is_not_stopped(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake)  # start_all never called
        fleet.stop_all()
        assert all(run["argv"][0] == "cefnetdstop" for run in fake.runs)

    def test_one_stop_failure_does_not_skip_remaining_stops(self):
        fake = FakeCommandRunner()
        boom = RuntimeError("host vanished")

        def hook(node, argv):
            if argv[0] == "cefnetdstop" and node == "h1":
                raise boom
            return None

        fleet = _fleet(fake)
        with patch.object(cefore_mod.time, "sleep"):
            fleet.start_all()
        fake.runs.clear()
        fake.on_run = hook
        failures = fleet.stop_all()
        assert failures == [("stop_cefnetd h1", boom)]
        commands = [(run["node"], run["argv"][0]) for run in fake.runs]
        assert ("h2", "cefnetdstop") in commands
        assert ("h1", "csmgrdstop") in commands
