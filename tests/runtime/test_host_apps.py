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

    def test_stop_failure_leaves_the_launch_reachable_for_shutdown_to_retry(self):
        """2026-10-22 fix (review finding): restart_host() used to remove
        ``mine`` from _launches before attempting to stop it. If that stop
        then raised, the handle -- which may still be a running process --
        was permanently forgotten, and a subsequent stop_all() at shutdown
        could never retry reclaiming it. It must stay tracked until a stop
        is actually confirmed."""
        fake = FakeCommandRunner()
        boom = RuntimeError("host vanished")

        def on_wait(handle):
            raise boom

        fake.on_wait = on_wait
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()
        original_handle = fake.starts[0]

        try:
            fleet.restart_host(0, downtime_s=0)
        except RuntimeError:
            pass

        # Shutdown must still see the un-confirmed-stopped launch and
        # retry waiting on it -- not silently have zero launches left.
        failures = fleet.stop_all()

        assert failures == [("stop_host_app h0", boom)]
        assert fake.waits == [original_handle, original_handle]

    def test_partial_restart_failure_still_lets_stop_all_reclaim_the_started_replacement(
        self,
    ):
        """2026-10-22 fix (review finding): two apps on one host. The first
        app's replacement starts fine; the second's start() raises.
        Registering handles into _launches only after the whole loop
        finished would have left the first app's already-running
        replacement untracked -- an orphan nothing could ever stop. Each
        successful start must be registered immediately."""
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {"hosts": [0], "argv": ["./agent1"]},
                {"hosts": [0], "argv": ["./agent2"]},
            ],
        )
        fleet.start_all()
        assert len(fake.starts) == 2

        boom = RuntimeError("agent2 replacement failed to start")

        def on_start(handle):
            if handle.argv[0] == "./agent2":
                raise boom

        fake.on_start = on_start

        try:
            fleet.restart_host(0, downtime_s=0)
            raised = None
        except RuntimeError as exc:
            raised = exc

        assert raised is boom
        fake.on_start = None

        # agent1's already-started replacement (fake.starts[2]: index 0/1
        # are the two original start_all() launches) is reachable:
        # stop_all() finds and waits on THAT SPECIFIC handle, not merely
        # some handle with the same argv, proving it was not lost.
        failures = fleet.stop_all()

        assert failures == []
        assert fake.waits[-1] is fake.starts[2]

    def test_restarting_a_host_with_no_tracked_launches_returns_false(self):
        """2026-10-22 fix: a host_app_restart whose host has nothing left
        in _launches must not fall through the stop/start loops as a
        silent no-op and report True -- that is exactly the "success with
        no launches" a reviewer called out. Config validation already
        rejects this for a real event (host_app_restart requires
        host_apps: coverage), so this exercises the fleet-level guard
        directly."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [1], "argv": ["noop"]}])
        fleet.start_all()

        assert fleet.restart_host(0, downtime_s=0) is False
        assert fake.starts == [fake.starts[0]]  # nothing new was started
        assert fake.waits == []  # nothing was stopped either


# ── restart_host: cross-entry log collision ──
# 2026-10-23 (review finding): _life_log() only guarantees a restarted
# life's log differs from ITS OWN earlier lives. A sibling host_apps entry
# on the same host can configure its own log at exactly the path a
# restart's suffixing computes, and CommandRunner.start()'s "wb" open
# would then truncate the sibling's still-live output.


class TestRestartLogCollision:
    """restart_host() must reject a restart whose next life's log would
    land on another host_apps entry's reserved (life-1) log path, before
    stopping or starting anything."""

    def test_restart_colliding_with_a_sibling_entrys_log_is_rejected(self, tmp_path):
        """Two host_apps entries on the same host: entry A's log is
        "a.log", entry B's log is "a.log.life2". Restarting A once
        computes A's life-2 log as "a.log.life2" -- the exact literal
        path B's life-1 process already opened and is still writing to.
        The restart must raise before either entry is touched, and B's
        already-started process must stay the only thing ever written
        to that path."""
        a_log = str(tmp_path / "a.log")
        b_log = a_log + ".life2"
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[
                {"hosts": [0], "argv": ["./agent-a"], "log": a_log},
                {"hosts": [0], "argv": ["./agent-b"], "log": b_log},
            ],
        )
        fleet.start_all()
        assert [h.log_path for h in fake.starts] == [a_log, b_log]

        try:
            fleet.restart_host(0, downtime_s=0)
            raised = None
        except ValueError as exc:
            raised = exc

        assert raised is not None
        assert str(raised) == (
            f"host_apps restart for h0 would write its next life's log to "
            f"{b_log!r}, which collides with another host_apps entry's "
            "reserved log path"
        )
        # Rejected before either side effect: neither app was stopped,
        # and no third process (which would have reused b_log) started.
        assert fake.waits == []
        assert [h.log_path for h in fake.starts] == [a_log, b_log]

    def test_restart_with_no_sibling_collision_is_unaffected(self):
        """Control: a restart whose next life's log does not match any
        OTHER entry's reserved log must still proceed normally -- proves
        the collision check does not reject on seeing its own (different)
        log path."""
        fake = FakeCommandRunner()
        fleet = _fleet(
            fake,
            specs=[{"hosts": [0], "argv": ["./agent"], "log": "/x/h0/h0.log"}],
        )
        fleet.start_all()

        assert fleet.restart_host(0, downtime_s=0) is True
        assert fake.starts[1].log_path == "/x/h0/h0.log.life2"


# ── shutdown race: a restart racing scenario shutdown must not leave an
# orphan process ──


class _LockAcquireProbe:
    """Test double standing in for a real ``threading.Lock``: forwards
    acquire()/release() to the wrapped lock, but signals an Event the
    instant acquire() is CALLED -- before it may block waiting for the
    real lock -- so a test can prove a thread actually attempted to take
    the lock, rather than merely inferring it from elapsed wall-clock
    time (which cannot tell "genuinely blocked on the lock" apart from
    "the OS just hasn't scheduled this thread yet").

    ``threading.Lock`` instances do not support arbitrary attribute
    assignment, so this wraps one as a drop-in substitute for
    HostAppFleet._lock, which production code only ever uses through
    acquire()/release()/__enter__/__exit__ (``with self._lock:``).
    """

    def __init__(self, real_lock, on_acquire):
        self._real_lock = real_lock
        self._on_acquire = on_acquire

    def acquire(self, *args, **kwargs):
        self._on_acquire()
        return self._real_lock.acquire(*args, **kwargs)

    def release(self):
        self._real_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


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
        a process after shutdown already swept the fleet.

        2026-10-22: this used to synchronize with the restart thread via a
        blind ``time.sleep(0.1)`` ("probably long enough to have entered
        the wait by now"), which is exactly the kind of race a slow CI box
        can flake on. Wrapping ``fleet._stopping.wait`` to signal an Event
        right before calling through to the real wait gives a
        deterministic "the thread is now blocked in the downtime_s wait"
        handshake instead.
        """
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        entered_wait = threading.Event()
        real_wait = fleet._stopping.wait

        def wait_and_signal(timeout=None):
            """Stand-in for fleet._stopping.wait(): signal entered_wait
            right before delegating to the real wait, so the test can
            block until the restart thread has genuinely reached (not
            merely is about to reach) the downtime_s wait."""
            entered_wait.set()
            return real_wait(timeout)

        results = []
        thread = threading.Thread(
            target=lambda: results.append(fleet.restart_host(0, downtime_s=5))
        )
        start = time.monotonic()
        with patch.object(fleet._stopping, "wait", side_effect=wait_and_signal):
            thread.start()
            assert entered_wait.wait(5)  # thread is now in the downtime_s wait

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

    def test_post_wait_stopping_recheck_prevents_a_late_start_after_shutdown(self):
        """2026-10-22 test (mutation gap, review finding): a mutant that
        drops the ``self._stopping.is_set()`` recheck right before
        starting the new life (the second ``with self._lock`` block)
        survived the existing suite. Every other race test here lets
        stop_all() arrive WHILE ``_stopping.wait()`` is still blocked, so
        ``wait()`` itself returns True and the EARLIER check (``if
        self._stopping.wait(downtime_s): return False``) already catches
        it -- that check alone cannot prove the later recheck is load
        -bearing. This drives the other ordering instead: stop_all() runs
        and finishes to completion DURING the call standing in for
        ``_stopping.wait()``, which then reports a genuine timeout (False)
        -- so only the post-wait recheck can still catch that shutdown
        already happened, by the time this method is about to start a new
        process."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()

        def fake_wait(downtime_s):
            """Stand in for fleet._stopping.wait(): report a genuine
            timeout (False), but have shutdown land and finish INSIDE
            that same window, so only the post-wait recheck (not the
            earlier wait() return value) can still catch it."""
            fleet.stop_all()
            return False

        with patch.object(fleet._stopping, "wait", side_effect=fake_wait):
            result = fleet.restart_host(0, downtime_s=0)

        assert result is False
        assert len(fake.starts) == 1  # no second life started after shutdown

    def test_restart_stop_phase_blocks_stop_all_until_confirmed_or_restored(self):
        """2026-10-22 fix (review finding): restart_host() used to remove
        ``mine`` from _launches, release the lock, and only THEN attempt
        its stop. A stop_all() that ran in that released-lock window
        snapshotted _launches without ``mine``, stopped nothing for this
        host, and returned -- so when the restart's own stop then raised,
        the still-running original process was put back only after
        shutdown had already finished, and nothing would ever stop it
        (an orphan).

        This reproduces that handshake directly: the restart's first stop
        attempt blocks inside ``on_wait`` until released, then raises.
        While it is blocked, stop_all() is started on another thread --
        with the fix, it must stay blocked on ``_lock`` (not race ahead
        with a stale snapshot) until the stop attempt is released and the
        failed launch is put back. Once both threads finish, stop_all()'s
        own retry must reach the SAME original handle a second time.

        2026-10-23 fix (review finding): proving "stop_all() is still
        blocked" used to rely on ``shutdown_thread.join(timeout=0.5)``
        returning False -- but a thread that simply has not been
        scheduled by the OS yet also reports ``is_alive() is True``,
        which the reverted (unlocked) implementation would eventually
        satisfy too if the join raced ahead of the scheduler. Wrapping
        the real lock in ``_LockAcquireProbe`` and waiting on an Event it
        sets replaces that guess with proof that stop_all() actually
        called ``_lock.acquire()`` (and is therefore genuinely blocked
        inside it, since restart_thread still holds the real lock) before
        the ``is_alive()`` assertion runs."""
        fake = FakeCommandRunner()
        fleet = _fleet(fake, specs=[{"hosts": [0], "argv": ["noop"]}])
        fleet.start_all()
        original_handle = fake.starts[0]

        entered = threading.Event()
        release = threading.Event()

        def on_wait(handle):
            """Block the restart's OWN first stop attempt until
            released, then fail it. stop_all()'s later retry on the
            same handle must fall through normally -- ``entered`` is
            already set by then, so this branch is skipped."""
            if not entered.is_set():
                entered.set()
                release.wait(5)
                raise RuntimeError("stop failed")

        fake.on_wait = on_wait

        restart_result = []

        def run_restart():
            """Run restart_host() on its own thread and capture
            whatever it raises, so the main thread can assert on the
            outcome once both threads have finished."""
            try:
                restart_result.append(fleet.restart_host(0, downtime_s=0))
            except RuntimeError as exc:
                restart_result.append(exc)

        restart_thread = threading.Thread(target=run_restart)
        restart_thread.start()
        assert entered.wait(5)  # restart's stop attempt is now blocked,
        # and -- per restart_host's fix -- is holding _lock the whole
        # time it stays blocked here.

        # Swap in the probe around the SAME real lock restart_thread is
        # already holding. This reassignment is safe even though
        # restart_thread is mid-``with self._lock:``: that statement
        # evaluated ``self._lock`` once at entry and will call __exit__
        # on the object it captured then, unaffected by this swap.
        acquire_attempted = threading.Event()
        fleet._lock = _LockAcquireProbe(fleet._lock, acquire_attempted.set)

        shutdown_result = []
        shutdown_thread = threading.Thread(
            target=lambda: shutdown_result.append(fleet.stop_all())
        )
        shutdown_thread.start()
        # Proof, not a timing guess: stop_all() has genuinely called
        # _lock.acquire() -- and is therefore now blocked inside it,
        # since restart_thread still holds the real lock -- before this
        # assertion runs.
        assert acquire_attempted.wait(5)
        assert shutdown_thread.is_alive()

        release.set()
        restart_thread.join(5)
        shutdown_thread.join(5)

        assert isinstance(restart_result[0], RuntimeError)
        # stop_all()'s retry on the put-back launch succeeds (on_wait no
        # longer raises the second time), so it reports no failure of its
        # own -- the restart's own raise is what the caller sees.
        assert shutdown_result[0] == []
        assert fake.waits.count(original_handle) == 2
