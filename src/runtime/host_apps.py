"""HostAppFleet: lifecycle of the ``host_apps:`` config entries for one experiment.

``host_apps:`` lets a config start one or more arbitrary, long-running
processes per host alongside cefnetd/csmgrd. This module owns exactly two
things: substituting the four placeholders a ``host_apps`` entry may use in
``argv``/``env``/``cwd``/``log``, and launching/stopping those processes
through CommandRunner. It has no knowledge of what a host app actually is or
does -- not a sync protocol, not any other domain a future caller's app
might implement -- see CONTEXT.md (Daemon lifecycle: HostAppFleet).
"""

import os
import threading
import time

from mininet.log import info

from .command_runner import MininetCommandRunner

# The four placeholders a host_apps entry may use in argv/env/cwd/log.
# {node}: Node name ("h3"). {node_dir} / {cefore_conf_dir}: both resolve to
# the same absolute path today (the directory that directly holds that
# host's cefnetd.conf, os.path.abspath(f"h{idx}")) but are kept as two
# separately named placeholders because they answer two different
# questions -- "this host's own working directory" vs. "the directory
# cefpyco's create_handle(ceforedir=...) must be pointed at" -- so a future
# change that moves one without the other does not force renaming every
# existing host_apps config. {t0_ms}: the epoch-ms time.time() reading taken
# at the same single capture point whose paired time.monotonic() reading
# becomes the EventScheduler's "at: 0" origin, so a host app's own
# relative-time math and the scheduler's schedule describe the same instant
# without this module brokering any further synchronization.
_PLACEHOLDER_NAMES = ("node", "node_dir", "cefore_conf_dir", "t0_ms")


def _expand(text, ctx):
    """Substitute the four known placeholders in one string.

    Deliberately not str.format()/format_map(): those raise on any brace
    that is not one of our four names, and a host app's own argv (a JSON
    payload, a shell ${VAR} reference, ...) is likely to contain one. Plain
    substring replacement only ever touches the exact "{name}" tokens this
    module defines, leaving everything else in the string untouched.
    """
    for name in _PLACEHOLDER_NAMES:
        text = text.replace("{" + name + "}", str(ctx[name]))
    return text


def _env_argv_prefix(env):
    """Build the ``env K=V ...`` argv prefix for an arbitrary env dict.

    CommandRunner.start() has no env kwarg (see its docstring in
    command_runner.py). cefore_env_prefix() in cefore.py established the
    same "prepend `env KEY=VAL` to argv" mechanism for the single
    CEFORE_DIR variable; this generalizes it to an arbitrary dict since a
    host_apps entry's env is user-defined, not fixed to one key.
    """
    return ["env", *(f"{key}={value}" for key, value in env.items())]


def _resolve_hosts(hosts, host_count):
    """"all" means every host in the experiment; otherwise the literal list."""
    if hosts == "all":
        return list(range(host_count))
    return list(hosts)


def _placeholder_context(idx, node_dir, cefore_conf_dir, t0_ms):
    """Build the {name: value} mapping _expand() substitutes for one host."""
    return {
        "node": f"h{idx}",
        "node_dir": node_dir,
        "cefore_conf_dir": cefore_conf_dir,
        "t0_ms": str(t0_ms),
    }


def _life_log(log, life):
    """Pick the log path for one host_apps process's Nth life.

    2026-10-22: CommandRunner.start() opens log_path with "wb" (truncate,
    see command_runner.py), so restarting a host_apps process onto the same
    log path would erase whatever the previous life already wrote there.
    life 1 (start_all's only life) returns ``log`` unchanged -- that is what
    keeps start_all's own behavior byte-identical to before restart_host
    existed. life >= 2 (a restart) gets a ".lifeN" suffix instead, so each
    life's CommandRunner.start() truncates a path nothing else has written
    to, rather than needing CommandRunner itself to grow an append mode.
    argv/env/cwd are never touched by this -- only the log path.
    """
    if log is None or life <= 1:
        return log
    return f"{log}.life{life}"


class HostAppFleet:
    """Start and stop the ``host_apps:`` processes of one experiment.

    Mirrors DaemonFleet's start_all()/stop_all() shape:
    - start_all() launches every configured app via CommandRunner.start
      (long-running, non-blocking) and does not catch per-host failures
      itself, same as DaemonFleet.start_all() -- a partial start still
      stays recoverable, because each handle is recorded as soon as its
      start() call returns, and stop_all() always runs during shutdown,
      before the Cefore daemons are torn down, to reclaim it.
    - stop_all() attempts every started handle independently and aggregates
      ``(stage, exception)`` failures instead of aborting on the first,
      same as DaemonFleet.stop_all().

    Launches exclusively through CommandRunner.start (never ``.run()``) --
    see CONTEXT.md CommandRunner for why that is the one seam every host
    command goes through.
    """

    def __init__(
        self,
        net,
        *,
        specs,
        host_count,
        node_dirs,
        cefore_conf_dirs,
        t0_ms,
        runner=None,
    ):
        self._net = net
        self._specs = list(specs)
        self._host_count = host_count
        self._node_dirs = node_dirs
        self._cefore_conf_dirs = cefore_conf_dirs
        self._t0_ms = t0_ms
        self._runner = runner or MininetCommandRunner(net)
        # Each entry is {"idx", "argv", "cwd", "log", "life", "handle"}: the
        # exact CommandRunner.start() call that produced "handle", recorded
        # so restart_host() can replay argv/cwd verbatim instead of
        # re-expanding the spec a second time (see restart_host).
        self._launches = []
        # Guards _launches against stop_all() (shutdown) and restart_host()
        # (scheduler thread) running concurrently -- see restart_host for
        # the race this closes: a restart whose downtime_s sleep overlaps
        # shutdown must not start a process after stop_all() has already
        # swept the fleet.
        self._lock = threading.Lock()
        self._stopping = threading.Event()

    def _expand_launch(self, spec, idx):
        """Expand one host_apps spec's argv/env/cwd/log for host idx.

        Pure expansion, no CommandRunner call -- start_all() and
        restart_host()'s first life both go through this so the two can
        never compute argv/env/cwd differently.
        """
        ctx = _placeholder_context(
            idx, self._node_dirs[idx], self._cefore_conf_dirs[idx], self._t0_ms
        )
        argv = [_expand(arg, ctx) for arg in spec["argv"]]
        env = spec.get("env") or {}
        if env:
            env = {key: _expand(value, ctx) for key, value in env.items()}
            argv = _env_argv_prefix(env) + argv
        cwd = spec.get("cwd")
        if cwd is not None:
            cwd = _expand(cwd, ctx)
        log = spec.get("log")
        if log is not None:
            log = _expand(log, ctx)
        return argv, cwd, log

    def start_all(self):
        """Launch every configured host app on its resolved hosts, in order."""
        for spec in self._specs:
            for idx in _resolve_hosts(spec["hosts"], self._host_count):
                argv, cwd, log = self._expand_launch(spec, idx)
                handle = self._runner.start(f"h{idx}", argv, log_path=log, cwd=cwd)
                self._launches.append(
                    {"idx": idx, "argv": argv, "cwd": cwd, "log": log, "life": 1, "handle": handle}
                )

    def _stop_one_launch(self, launch, context):
        """Stop one launch's handle; return its failure tuple, or None.

        ``wait(deadline=time.monotonic())`` is the codebase's established
        "reclaim a started handle now" idiom -- ContentOperationRunner.stop()
        uses the identical already-expired-deadline call to stop a leftover
        cefsubfile handle at shutdown. The deadline is already in the past,
        so CommandRunner.wait() terminates the process (SIGTERM, escalating
        to SIGKILL after its own grace period), closes the redirected log
        file, and reaps it; a bare terminate() call does neither of the
        last two.

        A host app is expected to still be running at this point (it is a
        long-running process by contract), so CommandRunner.wait() observes
        natural exit first (see command_runner.py) and only reports
        ``timed_out``/``cancelled`` False when the process had already
        finished on its own before this call ever reached it. 2026-10-22
        fix: without this check, a host app that crashed right after
        start_all() (missing binary, bad args, ...) stopped silently --
        stop_all() still "succeeded" and nothing in script.log said the
        process never actually ran.

        2026-10-22: this is split out of _stop_launches() so restart_host()
        can learn WHICH of several launches a stop failed for (not just
        that the batch had a failure) -- see restart_host's "put failed
        launches back" comment.
        """
        handle = launch["handle"]
        try:
            result = self._runner.wait(handle, deadline=time.monotonic())
            if not result.timed_out and not result.cancelled:
                info(
                    f"[host-apps] warning: {handle.node} exited "
                    f"rc={result.returncode} before {context}\n"
                )
            return None
        except BaseException as exc:
            return (f"stop_host_app {handle.node}", exc)

    def _stop_launches(self, launches):
        """Stop every started host app at shutdown; aggregate failures.

        stop_all()'s only caller, and always for every tracked launch at
        once, so "shutdown" is hardcoded rather than threaded through as a
        parameter (restart_host() needs per-launch pass/fail -- which of
        several launches stopped and which did not -- so it calls
        _stop_one_launch() directly instead of this batch wrapper; see
        restart_host). stop_all()'s own tests pin the "shutdown" wording
        byte-for-byte.
        """
        failures = []
        for launch in launches:
            failure = self._stop_one_launch(launch, "shutdown")
            if failure is not None:
                failures.append(failure)
        return failures

    def stop_all(self):
        """Stop every started host app independently; aggregate failures.

        Sets ``_stopping`` first: a restart_host() call whose downtime_s
        wait is interrupted by this (see restart_host) must see it set and
        skip starting a new process, or shutdown could race a restart and
        leave an orphan nothing ever stops.
        """
        with self._lock:
            self._stopping.set()
            launches = list(self._launches)
        return self._stop_launches(launches)

    def restart_host(self, idx, downtime_s=0):
        """Stop, wait ``downtime_s``, then restart host ``idx``'s host_apps.

        The scheduler's host_app_restart event handler calls this. Every
        launch currently tracked for ``idx`` is stopped through the same
        _stop_one_launch() helper stop_all() uses (SIGTERM, 2s grace,
        SIGKILL); a stop failure is raised rather than swallowed, since
        starting a new process on top of a host we could not confirm
        stopped would risk two processes racing the same log path.

        2026-10-22 fix: ``mine`` is removed from ``_launches`` up front (so
        a concurrent stop_all() does not also try to stop the same handles
        a second time), but a launch whose stop raises is put BACK into
        ``_launches`` before raising. Discarding every selected launch
        unconditionally meant a process that survived a failed stop became
        permanently invisible to stop_all(), so shutdown could never retry
        reclaiming it. A launch that DID stop cleanly is left out of that
        put-back: its process is already confirmed gone, so there is
        nothing left to retry.

        The restarted life replays the ORIGINAL _expand_launch() result
        (argv/cwd verbatim, from the launch record -- never re-expanded),
        with the same t0_ms the fleet was built with (never re-captured),
        so it is "the same process" by every placeholder-visible fact
        except the log path, which _life_log() suffixes (see its
        docstring) so the new life cannot truncate the old life's output.

        Shutdown race: the wait below is an Event.wait, not time.sleep, so
        a concurrent stop_all() (which sets _stopping) wakes it immediately
        instead of leaving it to sleep out the full downtime_s past the
        point where shutdown already swept the fleet. The _stopping check
        is repeated under the lock right before starting the new process,
        closing the remaining window between the wait returning (by
        timeout) and this method resuming. Either way shutdown wins: no
        process is started after stop_all() has run, so stop_all() never
        misses one -- which is exactly the orphan-process failure mode a
        plain, uninterruptible time.sleep() here would risk.
        Returns False (no restart performed) when shutdown won the race,
        True otherwise; callers that want a scheduler-recordable outcome
        should treat False as a failed event, same as returning False from
        any other scheduler handler.
        """
        with self._lock:
            mine = [launch for launch in self._launches if launch["idx"] == idx]
            self._launches = [launch for launch in self._launches if launch["idx"] != idx]

        if not mine:
            # 2026-10-22: config validation rejects a host_app_restart
            # whose host has no host_apps: coverage, so this is normally
            # unreachable -- but without it, a host with nothing left
            # tracked (e.g. a prior restart's put-back landing on a
            # DIFFERENT idx, or any future caller this validation does not
            # cover) would fall through the two loops below as no-ops and
            # return True: a restart that touched zero processes reporting
            # success. False matches the existing "no restart performed"
            # convention the shutdown-race case below already uses.
            return False

        failures = []
        unstopped = []
        for launch in mine:
            failure = self._stop_one_launch(launch, context="restart")
            if failure is not None:
                failures.append(failure)
                unstopped.append(launch)

        if failures:
            # See the fix note above the docstring: put back exactly the
            # launches whose stop could not be confirmed, so stop_all() at
            # shutdown still sees them and can retry.
            with self._lock:
                self._launches.extend(unstopped)
            raise failures[0][1]

        if self._stopping.wait(downtime_s):
            return False

        with self._lock:
            if self._stopping.is_set():
                return False
            node = f"h{idx}"
            for launch in mine:
                life = launch["life"] + 1
                # launch["log"] is always the ORIGINAL (life 1) expanded log
                # -- never the suffixed one a previous restart used -- so
                # life 3's suffix is computed from the same base as life
                # 2's, not stacked on top of it ("h0.log.life3", never
                # "h0.log.life2.life3"). Only "life"/"handle" change below;
                # "log" is deliberately carried forward unmodified.
                log = _life_log(launch["log"], life)
                handle = self._runner.start(node, launch["argv"], log_path=log, cwd=launch["cwd"])
                # 2026-10-22 fix: append to _launches IMMEDIATELY after each
                # start() call, not after this whole loop via a local list
                # extended at the end. A reviewer reproduced the
                # alternative's bug with two apps on one host: the first
                # start() succeeds, the second raises, and accumulating
                # into a local list first left the first app's
                # already-running replacement untracked -- an orphan
                # stop_all() could never reach.
                self._launches.append({**launch, "life": life, "handle": handle})
        return True


def build_host_app_fleet(net, host_count, host_apps_config, t0_ms, *, runner=None):
    """Build a HostAppFleet from host_apps: config entries.

    node_dir and cefore_conf_dir are both derived here as
    os.path.abspath(f"h{idx}") -- the same convention start_cefnetd /
    start_csmgrd use for the directory they pass to ``-d`` (see their
    log_dir branch in cefore.py) -- so a host_apps config sees the exact
    directory those daemons were pointed at.
    """
    node_dirs = {idx: os.path.abspath(f"h{idx}") for idx in range(host_count)}
    return HostAppFleet(
        net,
        specs=host_apps_config,
        host_count=host_count,
        node_dirs=node_dirs,
        cefore_conf_dirs=node_dirs,
        t0_ms=t0_ms,
        runner=runner,
    )
