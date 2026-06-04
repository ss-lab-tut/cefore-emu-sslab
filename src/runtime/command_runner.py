"""CommandRunner seam: the single place every host command is executed.

This is the one seam through which every command sent to a Mininet host (or
the root namespace) is run. It owns argv execution, output redirection, and the
lifecycle of long-running processes. Callers never hold a raw ``Popen``; they
receive a :class:`CommandResult` (finished) or a :class:`CommandHandle`
(still running) and act on the latter only through the runner.

See ``CONTEXT.md`` for the domain vocabulary (CommandRunner / CommandResult /
CommandHandle / Node name / Root sentinel).
"""

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
import threading
from collections import deque
from dataclasses import dataclass
from typing import IO, Any, Callable, Optional, Sequence, Union

# Reserved Node name that selects the root namespace (plain subprocess) instead
# of a host netns.
ROOT_SENTINEL = "root"


@dataclass
class CommandResult:
    """The value a CommandRunner returns for a finished command.

    Deadline/cancellation is expressed through ``timed_out``/``cancelled``,
    never through a sentinel ``returncode``.
    """

    returncode: Optional[int]
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    log_path: Optional[str] = None


class CommandHandle:
    """Opaque token for a still-running command.

    Callers wait/poll/terminate/kill it through the runner; they never touch
    the underlying process object directly.
    """

    def __init__(self, node: str, argv: Sequence[str], log_path: Optional[str]):
        self.node = node
        self.argv = list(argv)
        self.log_path = log_path


class CommandRunner(ABC):
    """The single seam through which host commands are executed."""

    @abstractmethod
    def run(
        self,
        node: str,
        argv: Sequence[str],
        *,
        log_path: Optional[str] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        cancel_event=None,
        capture: bool = True,
    ) -> CommandResult:
        """Run a command to completion and return its result.

        When ``log_path`` is given, combined stdout+stderr is redirected to that
        file and ``CommandResult.stdout`` is empty. When ``log_path`` is None and
        ``capture`` is True, combined output is captured into the result.
        """

    @abstractmethod
    def start(
        self,
        node: str,
        argv: Sequence[str],
        *,
        log_path: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> CommandHandle:
        """Start a long-running command and return a handle immediately."""

    @abstractmethod
    def wait(
        self,
        handle: CommandHandle,
        *,
        deadline: Optional[float] = None,
        cancel_event=None,
    ) -> CommandResult:
        """Wait for a started command until an absolute monotonic deadline.

        On deadline expiry the process is terminated and ``timed_out`` is set;
        on cancellation it is terminated and ``cancelled`` is set.
        """

    @abstractmethod
    def poll(self, handle: CommandHandle) -> Optional[int]:
        """Return the exit code if the command has finished, else None."""

    @abstractmethod
    def terminate(self, handle: CommandHandle) -> None:
        """Send SIGTERM to the command (best effort)."""

    @abstractmethod
    def kill(self, handle: CommandHandle) -> None:
        """Send SIGKILL to the command (best effort)."""


def _terminate_proc(proc) -> None:
    """Terminate a process and escalate to kill if it does not promptly exit."""
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        proc.wait()


class _MininetHandle(CommandHandle):
    def __init__(self, node, argv, log_path, proc, log_file):
        super().__init__(node, argv, log_path)
        self._proc = proc
        self._log_file = log_file

    def _close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None


class MininetCommandRunner(CommandRunner):
    """CommandRunner backed by a real Mininet network.

    Commands run in the target host's netns via ``host.popen`` with an argv
    list (no shell). The root sentinel routes to a plain subprocess so bridge /
    external-network setup uses the same seam.
    """

    def __init__(self, net):
        self._net = net

    def _spawn(self, node, argv, log_path, cwd, capture) -> _MininetHandle:
        argv = [str(a) for a in argv]
        log_file: Optional[IO[bytes]] = None
        stdout: Union[int, IO[bytes], None]
        stderr: Optional[int]
        if log_path is not None:
            log_file = open(log_path, "wb")
            stdout = log_file
            stderr = subprocess.STDOUT
        elif capture:
            stdout = subprocess.PIPE
            stderr = subprocess.STDOUT
        else:
            stdout = None
            stderr = None
        kwargs: dict[str, Any] = dict(
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr
        )
        if cwd is not None:
            kwargs["cwd"] = str(cwd)
        try:
            if node == ROOT_SENTINEL:
                proc = subprocess.Popen(argv, **kwargs)
            else:
                proc = self._net.get(node).popen(argv, **kwargs)
        except BaseException:
            # Seam owns redirection: do not leak the log fd if spawn fails.
            if log_file is not None:
                log_file.close()
            raise
        return _MininetHandle(node, argv, log_path, proc, log_file)

    def run(
        self,
        node,
        argv,
        *,
        log_path=None,
        cwd=None,
        timeout=None,
        cancel_event=None,
        capture=True,
    ) -> CommandResult:
        # Captured PIPE output must be drained with communicate() to avoid a
        # pipe-full deadlock; that path supports a timeout but not mid-flight
        # cancellation, so route cancellable captured runs through start/wait.
        if log_path is None and capture and cancel_event is None:
            return self._run_captured(node, argv, cwd, timeout)
        handle = self._spawn(node, argv, log_path, cwd, capture=capture)
        deadline = time.monotonic() + timeout if timeout is not None else None
        return self.wait(handle, deadline=deadline, cancel_event=cancel_event)

    def _run_captured(self, node, argv, cwd, timeout) -> CommandResult:
        """One-shot capture path (PIPE) using communicate to avoid deadlock."""
        handle = self._spawn(node, argv, None, cwd, capture=True)
        proc = handle._proc
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_proc(proc)
            out, _ = proc.communicate()
        stdout = out.decode(errors="replace") if isinstance(out, bytes) else (out or "")
        return CommandResult(
            returncode=proc.returncode,
            stdout=stdout,
            timed_out=timed_out,
            log_path=None,
        )

    def start(self, node, argv, *, log_path=None, cwd=None) -> CommandHandle:
        return self._spawn(node, argv, log_path, cwd, capture=False)

    def wait(self, handle, *, deadline=None, cancel_event=None) -> CommandResult:
        proc = handle._proc
        timed_out = False
        cancelled = False
        while True:
            # Observe natural exit first: a process that already finished must
            # report its real returncode, never be marked timed_out/cancelled.
            if proc.poll() is not None:
                break
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _terminate_proc(proc)
                break
            wait_time = 0.1
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _terminate_proc(proc)
                    break
                wait_time = min(wait_time, remaining)
            try:
                proc.wait(timeout=wait_time)
                break
            except subprocess.TimeoutExpired:
                continue
        handle._close_log()
        return CommandResult(
            returncode=proc.returncode,
            timed_out=timed_out,
            cancelled=cancelled,
            log_path=handle.log_path,
        )

    def poll(self, handle) -> Optional[int]:
        return handle._proc.poll()

    def terminate(self, handle) -> None:
        try:
            handle._proc.terminate()
        except ProcessLookupError:
            pass

    def kill(self, handle) -> None:
        try:
            handle._proc.kill()
        except ProcessLookupError:
            pass


class _FakeHandle(CommandHandle):
    def __init__(self, node, argv, log_path, cwd=None):
        super().__init__(node, argv, log_path)
        self.cwd = cwd
        self.terminated = False
        self.killed = False
        self.result: Optional[CommandResult] = None


class FakeCommandRunner(CommandRunner):
    """Recording test adapter for CommandRunner.

    Records every call and returns scripted results. Two axes can be driven
    independently for pub/sub tests: scripted ``wait`` outcomes
    (returncode/timed_out/cancelled) and ``on_start``/``on_wait`` side-effect
    hooks (e.g. to create artifact files the way a real command would).
    """

    def __init__(self):
        self.runs: list[dict] = []
        self.starts: list[_FakeHandle] = []
        self.waits: list[_FakeHandle] = []
        self.wait_calls: list[dict] = []
        self._run_results: deque[CommandResult] = deque()
        self._wait_results: deque[CommandResult] = deque()
        self.on_start: Optional[Callable[[_FakeHandle], None]] = None
        self.on_wait: Optional[Callable[[_FakeHandle], None]] = None
        self._lock = threading.Lock()

    def script_run(
        self, returncode=0, stdout="", stderr="", timed_out=False, cancelled=False
    ) -> None:
        self._run_results.append(
            CommandResult(returncode, stdout, stderr, timed_out, cancelled, None)
        )

    def script_wait(
        self, returncode=0, stdout="", stderr="", timed_out=False, cancelled=False
    ) -> None:
        self._wait_results.append(
            CommandResult(returncode, stdout, stderr, timed_out, cancelled, None)
        )

    @staticmethod
    def _clone(res: CommandResult, log_path) -> CommandResult:
        return CommandResult(
            res.returncode,
            res.stdout,
            res.stderr,
            res.timed_out,
            res.cancelled,
            log_path,
        )

    def run(
        self,
        node,
        argv,
        *,
        log_path=None,
        cwd=None,
        timeout=None,
        cancel_event=None,
        capture=True,
    ) -> CommandResult:
        with self._lock:
            self.runs.append(
                {
                    "node": node,
                    "argv": [str(a) for a in argv],
                    "log_path": log_path,
                    "cwd": cwd,
                    "timeout": timeout,
                    "capture": capture,
                    "cancel_event": cancel_event,
                }
            )
            res = self._run_results.popleft() if self._run_results else None
        if res is not None:
            return self._clone(res, log_path)
        return CommandResult(0, log_path=log_path)

    def start(self, node, argv, *, log_path=None, cwd=None) -> CommandHandle:
        handle = _FakeHandle(node, argv, log_path, cwd=cwd)
        with self._lock:
            self.starts.append(handle)
        if self.on_start is not None:
            self.on_start(handle)
        return handle

    def wait(self, handle, *, deadline=None, cancel_event=None) -> CommandResult:
        with self._lock:
            self.waits.append(handle)
            self.wait_calls.append(
                {"handle": handle, "deadline": deadline, "cancel_event": cancel_event}
            )
        if self.on_wait is not None:
            self.on_wait(handle)
        if handle.result is not None:
            return self._clone(handle.result, handle.log_path)
        with self._lock:
            res = self._wait_results.popleft() if self._wait_results else None
        if res is not None:
            return self._clone(res, handle.log_path)
        return CommandResult(0, log_path=handle.log_path)

    def poll(self, handle) -> Optional[int]:
        return None

    def terminate(self, handle) -> None:
        handle.terminated = True

    def kill(self, handle) -> None:
        handle.killed = True
