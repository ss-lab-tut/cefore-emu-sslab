"""Behavior tests for the HostAppFleet lifecycle seam (host_apps: config)."""

import os

from unittest.mock import patch

import src.runtime.host_apps as host_apps_mod
from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.host_apps import HostAppFleet, build_host_app_fleet


def _fleet(fake, **kwargs):
    defaults = dict(
        specs=[],
        host_count=3,
        node_dirs={0: "/x/h0", 1: "/x/h1", 2: "/x/h2"},
        cefore_conf_dirs={0: "/x/h0", 1: "/x/h1", 2: "/x/h2"},
        t0_ms=1700000000000,
        runner=fake,
    )
    defaults.update(kwargs)
    return HostAppFleet(None, **defaults)


# ── start_all: placeholders ──


class TestStartAllPlaceholders:
    def test_expands_all_four_placeholders_in_argv(self):
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {
                    "hosts": [1],
                    "argv": [
                        "sh",
                        "-c",
                        "echo {node} {node_dir} {cefore_conf_dir} {t0_ms}",
                    ],
                }
            ],
        )
        fleet.start_all()

        assert len(fake.starts) == 1
        handle = fake.starts[0]
        assert handle.node == "h1"
        assert handle.argv == [
            "sh",
            "-c",
            "echo h1 /x/h1 /x/h1 1700000000000",
        ]

    def test_unrelated_braces_pass_through_unchanged(self):
        """Not str.format(): a literal brace that is not one of our four
        placeholder names (e.g. a shell parameter expansion) must survive."""
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[{"hosts": [0], "argv": ["sh", "-c", "echo ${HOME} {node}"]}],
        )
        fleet.start_all()

        assert fake.starts[0].argv == ["sh", "-c", "echo ${HOME} h0"]

    def test_hosts_all_resolves_to_every_host_in_order(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": "all", "argv": ["noop"]}])
        fleet.start_all()

        assert [h.node for h in fake.starts] == ["h0", "h1", "h2"]

    def test_multiple_entries_start_in_config_order(self):
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {"hosts": [1], "argv": ["first"]},
                {"hosts": [0], "argv": ["second"]},
            ],
        )
        fleet.start_all()

        assert [(h.node, h.argv[0]) for h in fake.starts] == [
            ("h1", "first"),
            ("h0", "second"),
        ]


# ── start_all: env prefix ──


class TestEnvPrefix:
    def test_env_dict_becomes_env_argv_prefix_with_placeholders_expanded(self):
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {
                    "hosts": [0],
                    "argv": ["./agent"],
                    "env": {"CEFORE_DIR": "{cefore_conf_dir}", "T0": "{t0_ms}"},
                }
            ],
        )
        fleet.start_all()

        assert fake.starts[0].argv == [
            "env",
            "CEFORE_DIR=/x/h0",
            "T0=1700000000000",
            "./agent",
        ]

    def test_absent_env_means_no_prefix(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["./agent"]}])
        fleet.start_all()

        assert fake.starts[0].argv == ["./agent"]

    def test_empty_env_dict_means_no_prefix(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["./agent"], "env": {}}])
        fleet.start_all()

        assert fake.starts[0].argv == ["./agent"]


# ── start_all: cwd / log ──


class TestCwdAndLog:
    def test_cwd_and_log_are_expanded_and_passed_through(self):
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {
                    "hosts": [2],
                    "argv": ["./agent"],
                    "cwd": "{node_dir}",
                    "log": "{node_dir}/{node}.log",
                }
            ],
        )
        fleet.start_all()

        handle = fake.starts[0]
        assert handle.cwd == "/x/h2"
        assert handle.log_path == "/x/h2/h2.log"

    def test_omitted_cwd_and_log_pass_none(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["./agent"]}])
        fleet.start_all()

        handle = fake.starts[0]
        assert handle.cwd is None
        assert handle.log_path is None


# ── seam guard ──


class TestSeamGuard:
    def test_only_start_and_wait_are_used_never_run(self):
        """Design constraint: launch through CommandRunner.start only."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": "all", "argv": ["noop"]}])
        fleet.start_all()
        fleet.stop_all()

        assert fake.runs == []


# ── stop_all ──


class TestStopAll:
    def test_stops_every_started_host_app(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": "all", "argv": ["noop"]}])
        fleet.start_all()

        assert fleet.stop_all() == []
        assert [h.node for h in fake.waits] == ["h0", "h1", "h2"]

    def test_one_stop_failure_does_not_skip_remaining_stops(self):
        fake = FakeCommandRunner()
        boom = RuntimeError("host vanished")

        def on_wait(handle):
            if handle.node == "h1":
                raise boom

        fake.on_wait = on_wait
        fleet = _fleet(fake, specs=[{"hosts": "all", "argv": ["noop"]}])
        fleet.start_all()

        failures = fleet.stop_all()

        assert failures == [("stop_host_app h1", boom)]
        assert [h.node for h in fake.waits] == ["h0", "h1", "h2"]

    def test_stop_passes_an_already_expired_deadline(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod.time, "monotonic", return_value=12345.0):
            fleet.stop_all()

        assert fake.wait_calls[0]["deadline"] == 12345.0

    def test_stopping_an_empty_fleet_is_a_noop(self):
        fake = FakeCommandRunner()
        fleet = _fleet(fake)
        assert fleet.stop_all() == []

    def test_warns_when_a_host_app_already_exited_before_shutdown(self):
        # A scripted wait() result with timed_out=False/cancelled=False is
        # CommandRunner's contract for "the process had already finished on
        # its own" (see command_runner.py's "observe natural exit first").
        fake = FakeCommandRunner()
        fake.script_wait(returncode=1)
        fleet = _fleet(fake, specs=[{"hosts": [1], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            fleet.stop_all()

        mock_info.assert_called_once_with(
            "[host-apps] warning: h1 exited rc=1 before shutdown\n"
        )

    def test_no_warning_when_a_host_app_was_still_running_at_shutdown(self):
        # timed_out=True is wait()'s contract for "the deadline fired and we
        # had to terminate a still-running process" -- the expected case for
        # a long-running host app, which must not warn.
        fake = FakeCommandRunner()
        fake.script_wait(returncode=-15, timed_out=True)
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            fleet.stop_all()

        mock_info.assert_not_called()

    def test_no_warning_when_a_host_app_wait_was_cancelled(self):
        fake = FakeCommandRunner()
        fake.script_wait(returncode=-15, cancelled=True)
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            fleet.stop_all()

        mock_info.assert_not_called()

    def test_one_stop_failure_still_lets_other_handles_warn(self):
        # The warning check for a surviving handle must not be skipped just
        # because a different handle's wait() raised.
        fake = FakeCommandRunner()
        boom = RuntimeError("host vanished")

        def on_wait(handle):
            if handle.node == "h0":
                raise boom
            handle.result = CommandResult(returncode=1)

        fake.on_wait = on_wait
        fleet = _fleet(fake, specs=[{"hosts": [0, 1], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            failures = fleet.stop_all()

        assert failures == [("stop_host_app h0", boom)]
        mock_info.assert_called_once_with(
            "[host-apps] warning: h1 exited rc=1 before shutdown\n"
        )


# ── build_host_app_fleet ──


class TestBuildHostAppFleet:
    def test_node_dir_and_cefore_conf_dir_are_the_same_absolute_h_paths(self):
        fleet = build_host_app_fleet(None, 3, [], 1234, runner=FakeCommandRunner())

        expected = {idx: os.path.abspath(f"h{idx}") for idx in range(3)}
        assert fleet._node_dirs == expected
        assert fleet._cefore_conf_dirs == expected

    def test_specs_and_t0_ms_are_forwarded(self):
        specs = [{"hosts": [0], "argv": ["noop"]}]
        fleet = build_host_app_fleet(
            None, 1, specs, 999, runner=FakeCommandRunner()
        )

        assert fleet._specs == specs
        assert fleet._t0_ms == 999
