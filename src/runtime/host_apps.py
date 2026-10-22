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
        self._handles = []

    def start_all(self):
        """Launch every configured host app on its resolved hosts, in order."""
        for spec in self._specs:
            for idx in _resolve_hosts(spec["hosts"], self._host_count):
                node = f"h{idx}"
                ctx = _placeholder_context(
                    idx,
                    self._node_dirs[idx],
                    self._cefore_conf_dirs[idx],
                    self._t0_ms,
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
                handle = self._runner.start(node, argv, log_path=log, cwd=cwd)
                self._handles.append(handle)

    def stop_all(self):
        """Stop every started host app independently; aggregate failures.

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
        """
        failures = []
        for handle in self._handles:
            try:
                result = self._runner.wait(handle, deadline=time.monotonic())
                if not result.timed_out and not result.cancelled:
                    info(
                        f"[host-apps] warning: {handle.node} exited "
                        f"rc={result.returncode} before shutdown\n"
                    )
            except BaseException as exc:
                failures.append((f"stop_host_app {handle.node}", exc))
        return failures


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
