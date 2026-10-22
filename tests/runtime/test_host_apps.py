"""Behavior tests for the HostAppFleet lifecycle seam (host_apps: config)."""

import os
import threading
import time

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
        """A scripted wait() result with timed_out=False/cancelled=False is
        CommandRunner's contract for "the process had already finished on
        its own" (see command_runner.py's "observe natural exit first")."""
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
        """timed_out=True is wait()'s contract for "the deadline fired and we
        had to terminate a still-running process" -- the expected case for
        a long-running host app, which must not warn."""
        fake = FakeCommandRunner()
        fake.script_wait(returncode=-15, timed_out=True)
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            fleet.stop_all()

        mock_info.assert_not_called()

    def test_no_warning_when_a_host_app_wait_was_cancelled(self):
        """A cancelled wait is also not "already exited" and must not warn."""
        fake = FakeCommandRunner()
        fake.script_wait(returncode=-15, cancelled=True)
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            fleet.stop_all()

        mock_info.assert_not_called()

    def test_one_stop_failure_still_lets_other_handles_warn(self):
        """The warning check for a surviving handle must not be skipped just
        because a different handle's wait() raised."""
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


# ── restart_host ──
# The host_app_restart scheduler event's seam: stop, wait downtime_s, then
# start the exact same argv/cwd again (only the log path changes -- see
# _life_log).


class TestRestartHost:
    """restart_host(): stop the named host's launches, wait downtime_s,
    then start a new life with the same argv/cwd (only the log changes)."""

    def test_stops_old_handle_and_starts_a_new_one_with_the_same_argv_and_cwd(self):
        """The restarted life's argv/cwd must be byte-identical to the
        first life's -- only the handle (new process) and log differ."""
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {"hosts": [1], "argv": ["./agent", "{t0_ms}"], "cwd": "{node_dir}"}
            ],
        )
        fleet.start_all()
        first = fake.starts[0]

        assert fleet.restart_host(1, downtime_s=0) is True

        assert [h.node for h in fake.waits] == ["h1"]
        assert fake.waits[0] is first
        assert len(fake.starts) == 2
        second = fake.starts[1]
        assert second.node == "h1"
        assert second.argv == first.argv
        assert second.cwd == first.cwd

    def test_restart_without_a_log_leaves_log_path_none(self):
        """No log: configured means _life_log has nothing to suffix."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["./agent"]}])
        fleet.start_all()

        fleet.restart_host(0, downtime_s=0)

        assert fake.starts[1].log_path is None

    def test_restart_suffixes_the_log_path_with_life_2(self):
        """A restarted life's log must not reuse the first life's exact
        path, or CommandRunner.start()'s "wb" open would truncate it."""
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {"hosts": [0], "argv": ["./agent"], "log": "{node_dir}/{node}.log"}
            ],
        )
        fleet.start_all()
        assert fake.starts[0].log_path == "/x/h0/h0.log"

        fleet.restart_host(0, downtime_s=0)

        assert fake.starts[1].log_path == "/x/h0/h0.log.life2"

    def test_second_restart_suffixes_with_life_3(self):
        """life 3's suffix must be computed from the ORIGINAL log, not
        stacked onto life 2's already-suffixed one (".life3", never
        ".life2.life3")."""
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {"hosts": [0], "argv": ["./agent"], "log": "{node_dir}/{node}.log"}
            ],
        )
        fleet.start_all()
        fleet.restart_host(0, downtime_s=0)

        fleet.restart_host(0, downtime_s=0)

        assert fake.starts[2].log_path == "/x/h0/h0.log.life3"

    def test_restart_only_touches_the_named_host(self):
        """restart_host(1) must not disturb h0's tracked launch at all."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0, 1], "argv": ["noop"]}])
        fleet.start_all()

        fleet.restart_host(1, downtime_s=0)

        # h0's original launch is untouched: stop_all() must still reach it.
        assert [h.node for h in fake.waits] == ["h1"]
        assert fleet.stop_all() == []
        assert [h.node for h in fake.waits] == ["h1", "h0", "h1"]

    def test_downtime_s_is_actually_waited(self):
        """restart_host() must not start the new life immediately; it
        waits downtime_s between stop and start."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        start = time.monotonic()
        fleet.restart_host(0, downtime_s=0.2)
        elapsed = time.monotonic() - start

        assert elapsed >= 0.15

    def test_warns_before_restart_when_the_old_process_already_exited(self):
        """_stop_launches' "already exited" warning uses restart_host's own
        context word ("before restart"), not stop_all's ("before
        shutdown") -- a mutant that drops the `context` kwarg would still
        pass every other test here since none of them inspect the log."""
        fake = FakeCommandRunner()
        fake.script_wait(returncode=1)
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        with patch.object(host_apps_mod, "info") as mock_info:
            fleet.restart_host(0, downtime_s=0)

        mock_info.assert_called_once_with(
            "[host-apps] warning: h0 exited rc=1 before restart\n"
        )

    def test_stop_failure_raises_and_no_new_process_is_started(self):
        """A failed stop must not be swallowed into a "restarted anyway"
        false success, and must not risk a second process on top of a
        host we could not confirm stopped."""
        fake = FakeCommandRunner()
        boom = RuntimeError("host vanished")

        def on_wait(handle):
            raise boom

        fake.on_wait = on_wait
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        try:
            fleet.restart_host(0, downtime_s=0)
            raised = None
        except RuntimeError as exc:
            raised = exc

        assert raised is boom
        assert len(fake.starts) == 1


# ── shutdown race: a restart racing scenario shutdown must not leave an
# orphan process ──


class TestRestartShutdownRace:
    """A restart racing scenario shutdown must not leave an orphan process:
    whichever of stop_all()/restart_host() runs first, shutdown wins and no
    process is ever started after stop_all() has already swept the fleet."""

    def test_stop_all_first_means_a_later_restart_is_a_noop(self):
        """stop_all() already swept the fleet; a restart_host() call that
        starts after it must not start an orphan nothing will ever stop."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        assert fleet.stop_all() == []
        assert fleet.restart_host(0, downtime_s=0) is False
        assert len(fake.starts) == 1

    def test_stop_all_during_the_downtime_wait_interrupts_it_and_skips_the_restart(
        self,
    ):
        """A restart whose downtime_s wait is still in progress must notice
        a concurrent stop_all(), not sleep out the full duration and start
        a process after shutdown already swept the fleet."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        results = []
        thread = threading.Thread(
            target=lambda: results.append(fleet.restart_host(0, downtime_s=5))
        )
        start = time.monotonic()
        thread.start()
        time.sleep(0.1)  # let the thread enter the downtime_s wait

        fleet.stop_all()
        thread.join(timeout=2)
        elapsed = time.monotonic() - start

        assert not thread.is_alive()
        assert elapsed < 2  # interrupted, not the full 5s downtime_s
        assert results == [False]
        assert len(fake.starts) == 1  # no second life was ever started

    def test_stop_all_after_a_completed_restart_stops_the_restarted_process(self):
        """The ordinary case: restart_host() finishes well before shutdown.
        stop_all() must still reclaim the new (restarted) handle -- the
        orphan-process failure mode this seam exists to prevent -- not
        just the handles that existed before the restart."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        assert fleet.restart_host(0, downtime_s=0) is True
        restarted_handle = fake.starts[1]

        failures = fleet.stop_all()

        assert failures == []
        assert restarted_handle in fake.waits
