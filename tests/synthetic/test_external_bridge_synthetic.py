"""External-bridge synthetic product test (E1, E2, E3, E4a, E4b).

Verifies the remediation contract against REAL disposable veth + netns
resources using traced wrapper-level command injection. The test:
- never touches a production interface;
- never uses DHCP, NAT, live sysctl, proxy_arp dynamic validation, or `mn -c`;
- enforces the Linux IFNAMSIZ - 1 = 15-byte interface-name limit;
- writes evidence to pytest `tmp_path` by default and optionally also to an
  out-of-repo directory pointed to by CEFEMU_SYNTHETIC_EVIDENCE_DIR.

Skipped unless CEFEMU_SYNTHETIC_ROOT=1 AND running as root.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import string
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Synthetic tests are env-gated. Skip the entire module if the gate is closed
# or if not running as root, so the default non-root suite ignores it.
SYNTHETIC_GATE = os.environ.get("CEFEMU_SYNTHETIC_ROOT") == "1"

pytestmark = [
    pytest.mark.synthetic,
    pytest.mark.skipif(
        not SYNTHETIC_GATE,
        reason="CEFEMU_SYNTHETIC_ROOT=1 not set",
    ),
    pytest.mark.skipif(
        SYNTHETIC_GATE and os.geteuid() != 0,
        reason="synthetic tests require root",
    ),
]


# ---------------------------------------------------------------------------
# Evidence directory plumbing
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Resolve the repository root from this file's path."""
    return Path(__file__).resolve().parents[2]


def _resolve_export_dir() -> Path | None:
    """If CEFEMU_SYNTHETIC_EVIDENCE_DIR is set, validate it resolves OUTSIDE
    the repo and return the absolute Path. Otherwise return None."""
    val = os.environ.get("CEFEMU_SYNTHETIC_EVIDENCE_DIR")
    if not val:
        return None
    p = Path(val).resolve()
    repo = _repo_root()
    try:
        p.relative_to(repo)
    except ValueError:
        # Outside the repo — good.
        return p
    pytest.skip(
        f"CEFEMU_SYNTHETIC_EVIDENCE_DIR={p} resolves inside the repository {repo}; "
        "refusing to write evidence inside the working tree"
    )
    return None


def _export_evidence(tmp_path: Path) -> None:
    """If an out-of-repo evidence directory is configured, copy every file
    from `tmp_path` into it."""
    export = _resolve_export_dir()
    if export is None:
        return
    export.mkdir(parents=True, exist_ok=True)
    for entry in tmp_path.iterdir():
        if entry.is_file():
            shutil.copy2(entry, export / entry.name)


# ---------------------------------------------------------------------------
# Linux-valid name derivation (IFNAMSIZ - 1 = 15 bytes)
# ---------------------------------------------------------------------------


def _short_token(n: int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _derive_names(case_no: str, token_len: int) -> dict[str, str]:
    """Derive a fully-Linux-valid set of synthetic interface names for one
    case. Asserts every derived name <= 15 bytes."""
    token = _short_token(token_len)
    host_name = f"q{case_no}{token}"
    phy = f"p{case_no}{token}a"
    peer = f"p{case_no}{token}b"
    names = {
        "host_name": host_name,
        "phy": phy,
        "peer": peer,
        "bridge": f"br-{host_name}",
        "veth_root": f"veth-{host_name}-root",
        "veth_host": f"veth-{host_name}",
        "ns": host_name,
    }
    for k, v in names.items():
        assert len(v) <= 15, (
            f"derived name {k}={v!r} exceeds Linux IFNAMSIZ-1=15 limit (len={len(v)})"
        )
    return names


def _interface_exists(name: str) -> bool:
    rc = subprocess.run(
        ["ip", "link", "show", "dev", name],
        capture_output=True,
    ).returncode
    return rc == 0


# ---------------------------------------------------------------------------
# Traced status-aware command wrapper
# ---------------------------------------------------------------------------


@dataclass
class InjectionEntry:
    """An injection table entry: when the wrapper matches `cmd_tuple`, it
    returns the configured (rc, stderr) without delegating to the real
    command. After firing, the entry is decremented (`remaining`) or
    removed if `remaining` reaches zero. If `remaining` is None, the entry
    persists indefinitely."""

    rc: int
    stderr: str
    remaining: int | None = 1


class TracedWrapper:
    """Wraps `_run_root_cmd_vec` with status-aware failure injection and
    JSONL tracing. Also traces (but does NOT inject) `SyntheticHost.pexec`
    host-namespace commands for evidence.

    Host-command injection is intentionally out of scope for E1–E4b, which
    only need to fail root-namespace commands. If a future case needs to
    inject host-namespace failures, extend `SyntheticHost.pexec` to consult
    `injections` analogously to `run_root_cmd_vec`.
    """

    def __init__(self, trace_path: Path):
        self.trace_path = trace_path
        # Maps tuple(args) -> InjectionEntry
        self.injections: dict[tuple, InjectionEntry] = {}
        self._trace_fp = open(trace_path, "w", encoding="utf-8")
        self.last_calls: list[tuple] = []

    def close(self) -> None:
        try:
            self._trace_fp.close()
        except Exception:
            pass

    def _write_trace(
        self,
        source: str,
        args: tuple,
        executed: bool,
        injected: bool,
        rc: int,
        stderr: str,
    ) -> None:
        record = {
            "ts": time.monotonic(),
            "source": source,
            "args": list(args),
            "executed": executed,
            "injected_failure": injected,
            "rc": rc,
            "stderr": stderr,
        }
        self._trace_fp.write(json.dumps(record) + "\n")
        self._trace_fp.flush()

    def inject(
        self, args: list[str], rc: int, stderr: str, times: int | None = 1
    ) -> None:
        key = tuple(args)
        self.injections[key] = InjectionEntry(rc=rc, stderr=stderr, remaining=times)

    def clear_injections(self) -> None:
        self.injections.clear()

    def run_root_cmd_vec(self, args: list[str]) -> tuple[int, str, str]:
        """Wrapped replacement for `_run_root_cmd_vec`."""
        key = tuple(args)
        self.last_calls.append(key)
        entry = self.injections.get(key)
        if entry is not None:
            self._write_trace(
                "root",
                key,
                executed=False,
                injected=True,
                rc=entry.rc,
                stderr=entry.stderr,
            )
            if entry.remaining is not None:
                entry.remaining -= 1
                if entry.remaining <= 0:
                    self.injections.pop(key, None)
            return entry.rc, "", entry.stderr
        # Delegate to the real implementation.
        result = subprocess.run(args, shell=False, capture_output=True, text=True)
        self._write_trace(
            "root",
            key,
            executed=True,
            injected=False,
            rc=result.returncode,
            stderr=(result.stderr or "").strip(),
        )
        return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Namespace-shim host (no Mininet)
# ---------------------------------------------------------------------------


@dataclass
class SyntheticHost:
    """Mininet-host shim backed by a disposable network namespace.

    Exposes `pid` and `pexec(cmd) -> (stdout, stderr, rc)` like a Mininet
    `Node`. Commands run inside the namespace via `ip netns exec`.
    """

    ns: str
    pid: int
    wrapper: TracedWrapper

    def pexec(self, cmd: str) -> tuple[str, str, int]:
        full = ["ip", "netns", "exec", self.ns, "sh", "-c", cmd]
        # Note: pexec returns (stdout, stderr, rc) per the Mininet contract.
        # We still trace the call.
        result = subprocess.run(full, capture_output=True, text=True)
        self.wrapper._write_trace(
            "host",
            tuple(full),
            executed=True,
            injected=False,
            rc=result.returncode,
            stderr=(result.stderr or "").strip(),
        )
        return result.stdout, (result.stderr or ""), result.returncode

    def popen(self, argv, **kwargs):
        """Like Mininet ``Node.popen``: run an argv list inside the namespace.

        The CommandRunner seam now executes host commands via ``popen(argv)``
        (no shell) instead of ``pexec(cmd_str)``, so the shim provides it. The
        argv is prefixed with ``ip netns exec <ns>`` and the runner's stdio
        kwargs are forwarded to a real ``subprocess.Popen``.
        """
        full = ["ip", "netns", "exec", self.ns, *[str(a) for a in argv]]
        self.wrapper._write_trace(
            "host",
            tuple(full),
            executed=True,
            injected=False,
            rc=None,
            stderr="",
        )
        return subprocess.Popen(full, **kwargs)


class SyntheticNet:
    """Minimal `mininet.net.Mininet`-style shim exposing `get(host_name)`."""

    def __init__(self) -> None:
        self._hosts: dict[str, SyntheticHost] = {}

    def add(self, host: SyntheticHost) -> None:
        self._hosts[host.ns] = host

    def get(self, name: str) -> SyntheticHost | None:
        return self._hosts.get(name)


def _create_netns_holder(ns_name: str) -> int:
    """Create a network namespace `ns_name` and start a `sleep infinity`
    holder inside it. Returns the holder PID. The holder keeps the netns
    alive even if `ip netns exec` exits."""
    rc = subprocess.run(["ip", "netns", "add", ns_name], capture_output=True).returncode
    assert rc == 0, f"ip netns add {ns_name} failed (rc={rc})"
    # Spawn the holder. `nsenter` is too coupled; use `ip netns exec` + sh.
    proc = subprocess.Popen(
        ["ip", "netns", "exec", ns_name, "sh", "-c", "echo $$; exec sleep infinity"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # The first line of stdout is the PID inside the namespace as seen from
    # the host (Linux 3.8+: PID is the same in the host PID namespace).
    line = proc.stdout.readline().decode().strip()
    holder_pid = int(line)
    # Sanity check: /proc/<holder_pid>/ns/net (a symlink like net:[<inum>])
    # must reference the same nsfs inode as /var/run/netns/<ns_name>
    # (a regular file bind-mounted from nsfs).
    link_target = os.readlink(f"/proc/{holder_pid}/ns/net")
    # link_target looks like "net:[4026532912]"; extract the inode number.
    proc_inum: int | None = None
    if link_target.startswith("net:[") and link_target.endswith("]"):
        try:
            proc_inum = int(link_target[len("net:[") : -1])
        except ValueError:
            proc_inum = None
    netns_inum = os.stat(f"/var/run/netns/{ns_name}").st_ino
    if proc_inum is None or proc_inum != netns_inum:
        # Tear down before failing
        try:
            os.kill(holder_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        subprocess.run(["ip", "netns", "del", ns_name], capture_output=True)
        raise AssertionError(
            f"namespace-PID mismatch: /proc/{holder_pid}/ns/net={link_target!r} "
            f"(parsed inode={proc_inum}) != /var/run/netns/{ns_name} inode={netns_inum}"
        )
    return holder_pid


def _cleanup_case(ns: str, holder_pid: int | None, *links: str) -> None:
    """Unconditionally clean up case-owned resources in `finally`."""
    if holder_pid is not None:
        try:
            os.kill(holder_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for link in links:
        subprocess.run(["ip", "link", "del", link], capture_output=True)
    subprocess.run(["ip", "netns", "del", ns], capture_output=True)


# ---------------------------------------------------------------------------
# Case setup helpers
# ---------------------------------------------------------------------------


def _setup_case(case_no: str, token_len: int = 3) -> dict[str, Any]:
    """Allocate disposable resources for one case.

    Returns a dict with `names`, `holder_pid`, `host`, `net`, plus a list of
    interface names to delete on teardown.
    """
    names = _derive_names(case_no, token_len)
    ns = names["ns"]
    phy = names["phy"]
    peer = names["peer"]
    # All names must not already exist
    for n in (names["bridge"], names["veth_root"], names["veth_host"], phy, peer):
        assert not _interface_exists(n), (
            f"pre-existing interface {n!r} would collide with the synthetic "
            "case; rerun the test"
        )
    # Create the netns holder (also performs PID/ns sanity check)
    holder_pid = _create_netns_holder(ns)
    # Create the synthetic phy + peer veth pair (this is the "physical"
    # interface the production code will treat as `phy_intf`).
    rc = subprocess.run(
        ["ip", "link", "add", phy, "type", "veth", "peer", "name", peer],
        capture_output=True,
    ).returncode
    assert rc == 0, f"creating synthetic veth pair {phy}/{peer} failed"
    return {
        "names": names,
        "holder_pid": holder_pid,
    }


def _link_admin_state(name: str) -> str:
    """Return the administrative flag set (text) for `name` via `ip -j link`."""
    proc = subprocess.run(
        ["ip", "-j", "link", "show", "dev", name], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return ""
    arr = json.loads(proc.stdout) if proc.stdout.strip() else []
    if not arr:
        return ""
    return ",".join(arr[0].get("flags", []))


def _snapshot_link(name: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["ip", "-j", "link", "show", "dev", name], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return {"exists": False}
    arr = json.loads(proc.stdout) if proc.stdout.strip() else []
    return {"exists": True, "show": arr}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=repr))


# ---------------------------------------------------------------------------
# Synthetic cases
# ---------------------------------------------------------------------------


class TestExternalBridgeSynthetic:
    """E1, E2, E3, E4a, E4b — synthetic verification of the remediation
    contract against real disposable veth + netns resources."""

    def _attach_full(
        self, ctx: dict[str, Any], wrapper: TracedWrapper, monkeypatch
    ) -> None:
        """Run attach_external_via_bridge() to a fully-attached state."""
        from src.runtime import bridge_external as bridge_mod

        monkeypatch.setattr(bridge_mod, "_run_root_cmd_vec", wrapper.run_root_cmd_vec)
        names = ctx["names"]
        net = SyntheticNet()
        host = SyntheticHost(ns=names["ns"], pid=ctx["holder_pid"], wrapper=wrapper)
        net.add(host)
        ctx["net"] = net
        ctx["host"] = host
        bridge_mod.attach_external_via_bridge(
            net,
            names["host_name"],
            names["phy"],
            ip="10.0.0.2/24",
        )

    def test_E1_partial_cleanup_unmaster_fails_then_retry(self, tmp_path, monkeypatch):
        """E1: full attach; FIRST nomaster cleanup is injected to fail.
        Retry runs only the outstanding nomaster command."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        ctx = _setup_case("1")
        names = ctx["names"]
        wrapper = TracedWrapper(tmp_path / "E1.trace.jsonl")
        snap_before = _snapshot_link(names["phy"])

        try:
            _created_bridges.clear()
            self._attach_full(ctx, wrapper, monkeypatch)
            snap_after_attach = _snapshot_link(names["phy"])
            registry_after_attach = dict(_created_bridges)

            # Inject failure ONLY on the FIRST nomaster invocation; allow
            # subsequent calls to delegate (so retry succeeds).
            wrapper.inject(
                ["ip", "link", "set", names["phy"], "nomaster"],
                rc=1,
                stderr="injected nomaster failure",
                times=1,
            )

            # First cleanup pass — must raise
            with pytest.raises(ExternalBridgeError):
                cleanup_external_bridges()

            # Verify outstanding state
            rec = _created_bridges[names["host_name"]]
            assert rec["phy_enslaved"] is True, "phy_enslaved must remain True"
            assert rec["veth_created"] is False
            assert rec["bridge_created"] is False
            # Snapshot after first cleanup
            registry_after_first = dict(_created_bridges)

            # Retry — should issue only the outstanding nomaster
            wrapper.last_calls.clear()
            cleanup_external_bridges()

            second_calls = [c for c in wrapper.last_calls]
            # Only one mutating retry: nomaster
            assert (
                tuple(["ip", "link", "set", names["phy"], "nomaster"]) in second_calls
            )
            # No re-call of already-discharged actions
            assert tuple(["ip", "link", "del", names["veth_root"]]) not in second_calls
            assert tuple(["ip", "link", "del", names["bridge"]]) not in second_calls

            assert names["host_name"] not in _created_bridges
            snap_after_cleanup = _snapshot_link(names["phy"])
            registry_after_cleanup = dict(_created_bridges)

            _write_json(tmp_path / "E1.snapshot-before.json", snap_before)
            _write_json(tmp_path / "E1.snapshot-after-attach.json", snap_after_attach)
            _write_json(tmp_path / "E1.snapshot-after-cleanup.json", snap_after_cleanup)
            _write_json(
                tmp_path / "E1.registry.json",
                {
                    "after_attach": registry_after_attach,
                    "after_first": registry_after_first,
                    "after_cleanup": registry_after_cleanup,
                },
            )
            _write_json(
                tmp_path / "E1.namespace.json",
                {
                    "ns": names["ns"],
                    "holder_pid": ctx["holder_pid"],
                    "names": names,
                },
            )
        finally:
            wrapper.close()
            _cleanup_case(
                names["ns"],
                ctx.get("holder_pid"),
                names["veth_root"],
                names["bridge"],
                names["phy"],
                names["peer"],
            )
            _created_bridges.clear()
            _export_evidence(tmp_path)

    def test_E2_partial_cleanup_bridge_del_fails_then_retry(
        self, tmp_path, monkeypatch
    ):
        """E2: full attach; FIRST bridge-del cleanup is injected to fail.
        Retry runs only the outstanding bridge-del command."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        ctx = _setup_case("2")
        names = ctx["names"]
        wrapper = TracedWrapper(tmp_path / "E2.trace.jsonl")
        snap_before = _snapshot_link(names["phy"])

        try:
            _created_bridges.clear()
            self._attach_full(ctx, wrapper, monkeypatch)
            registry_after_attach = dict(_created_bridges)

            wrapper.inject(
                ["ip", "link", "del", names["bridge"]],
                rc=1,
                stderr="injected bridge-del failure",
                times=1,
            )

            with pytest.raises(ExternalBridgeError):
                cleanup_external_bridges()

            rec = _created_bridges[names["host_name"]]
            assert rec["bridge_created"] is True, "bridge_created must remain True"
            assert rec["bridge_up"] is False, "bridge_up cleared via successful down"
            assert rec["phy_enslaved"] is False
            assert rec["veth_created"] is False
            registry_after_first = dict(_created_bridges)

            wrapper.last_calls.clear()
            cleanup_external_bridges()

            second_calls = wrapper.last_calls[:]
            assert tuple(["ip", "link", "del", names["bridge"]]) in second_calls
            # No re-call
            assert tuple(["ip", "link", "del", names["veth_root"]]) not in second_calls
            assert (
                tuple(["ip", "link", "set", names["phy"], "nomaster"])
                not in second_calls
            )
            assert (
                tuple(["ip", "link", "set", names["phy"], "down"]) not in second_calls
            )
            assert (
                tuple(["ip", "link", "set", names["bridge"], "down"])
                not in second_calls
            )

            assert names["host_name"] not in _created_bridges
            snap_after_cleanup = _snapshot_link(names["phy"])

            _write_json(tmp_path / "E2.snapshot-before.json", snap_before)
            _write_json(tmp_path / "E2.snapshot-after-cleanup.json", snap_after_cleanup)
            _write_json(
                tmp_path / "E2.registry.json",
                {
                    "after_attach": registry_after_attach,
                    "after_first": registry_after_first,
                    "after_cleanup": dict(_created_bridges),
                },
            )
            _write_json(
                tmp_path / "E2.namespace.json",
                {
                    "ns": names["ns"],
                    "holder_pid": ctx["holder_pid"],
                    "names": names,
                },
            )
        finally:
            wrapper.close()
            _cleanup_case(
                names["ns"],
                ctx.get("holder_pid"),
                names["veth_root"],
                names["bridge"],
                names["phy"],
                names["peer"],
            )
            _created_bridges.clear()
            _export_evidence(tmp_path)

    def test_E3_phy_up_then_enslave_failure_restores_down(self, tmp_path, monkeypatch):
        """E3: phy DOWN; bridge-add/up + phy-up delegated; enslave injected
        to fail. After raise: phy admin-state DOWN, bridge gone, no record."""
        from src.runtime import bridge_external as bridge_mod
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        ctx = _setup_case("3")
        names = ctx["names"]
        wrapper = TracedWrapper(tmp_path / "E3.trace.jsonl")

        try:
            # Ensure phy is DOWN before the call (it is by default after `ip
            # link add ... type veth`; assert and force just in case).
            subprocess.run(
                ["ip", "link", "set", names["phy"], "down"], capture_output=True
            )
            flags = _link_admin_state(names["phy"])
            assert "UP" not in flags, (
                f"synthetic phy {names['phy']} must start DOWN; got flags={flags}"
            )
            snap_before = _snapshot_link(names["phy"])

            _created_bridges.clear()
            monkeypatch.setattr(
                bridge_mod, "_run_root_cmd_vec", wrapper.run_root_cmd_vec
            )

            # Inject failure ONLY for enslave; do NOT pre-enslave.
            wrapper.inject(
                ["ip", "link", "set", names["phy"], "master", names["bridge"]],
                rc=1,
                stderr="injected enslave failure",
                times=1,
            )

            net = SyntheticNet()
            host = SyntheticHost(ns=names["ns"], pid=ctx["holder_pid"], wrapper=wrapper)
            net.add(host)

            with pytest.raises(ExternalBridgeError, match="phy-enslave failure"):
                attach_external_via_bridge(
                    net,
                    names["host_name"],
                    names["phy"],
                    ip="10.0.0.2/24",
                )

            flags_after = _link_admin_state(names["phy"])
            assert "UP" not in flags_after, (
                f"phy must be administratively DOWN after rollback; got flags={flags_after}"
            )
            assert not _interface_exists(names["bridge"]), (
                f"owned bridge {names['bridge']} must be removed by rollback"
            )
            assert names["host_name"] not in _created_bridges

            _write_json(tmp_path / "E3.snapshot-before.json", snap_before)
            _write_json(
                tmp_path / "E3.snapshot-after.json", _snapshot_link(names["phy"])
            )
            _write_json(
                tmp_path / "E3.namespace.json",
                {
                    "ns": names["ns"],
                    "holder_pid": ctx["holder_pid"],
                    "names": names,
                },
            )
        finally:
            wrapper.close()
            _cleanup_case(
                names["ns"],
                ctx.get("holder_pid"),
                names["veth_root"],
                names["bridge"],
                names["phy"],
                names["peer"],
            )
            _created_bridges.clear()
            _export_evidence(tmp_path)

    def test_E4a_duplicate_phy_intf_vs_successful_active_record_rejected(
        self, tmp_path, monkeypatch
    ):
        """E4a: real attach for host_name_1; second attach with same phy
        but different host_name_2 is rejected pre-mutation."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        ctx = _setup_case("4a", token_len=1)  # tight budget for veth-...-root
        names = ctx["names"]
        wrapper = TracedWrapper(tmp_path / "E4a.trace.jsonl")

        # Second host_name reusing the same phy. We need a name that does not
        # collide with the first record AND yields ≤15-byte derived names.
        host2 = f"x{names['host_name'][1:]}"  # swap leading 'q' → 'x'
        for v in (host2, f"br-{host2}", f"veth-{host2}-root", f"veth-{host2}"):
            assert len(v) <= 15, f"derived name {v!r} exceeds 15 bytes"

        try:
            _created_bridges.clear()
            self._attach_full(ctx, wrapper, monkeypatch)

            calls_before = len(wrapper.last_calls)
            with pytest.raises(
                RuntimeError, match=rf"(?i){names['phy']}.*already.*attached"
            ):
                attach_external_via_bridge(
                    ctx["net"],
                    host2,
                    names["phy"],
                    ip="10.0.0.3/24",
                )

            # No mutating commands issued by the second attach.
            new_calls = wrapper.last_calls[calls_before:]
            for c in new_calls:
                # Allow inspection-only commands; reject any link mutation.
                if c[:2] == ("ip", "link"):
                    assert c[2] not in ("add", "set", "del"), (
                        f"unexpected mutation during duplicate rejection: {c}"
                    )

            assert host2 not in _created_bridges
            # The original record must still be there.
            assert names["host_name"] in _created_bridges

            _write_json(tmp_path / "E4a.trace-tail.json", [list(c) for c in new_calls])
            _write_json(
                tmp_path / "E4a.namespace.json",
                {
                    "ns": names["ns"],
                    "holder_pid": ctx["holder_pid"],
                    "names": names,
                    "second_host_name": host2,
                },
            )
        finally:
            wrapper.close()
            _cleanup_case(
                names["ns"],
                ctx.get("holder_pid"),
                names["veth_root"],
                names["bridge"],
                names["phy"],
                names["peer"],
            )
            _created_bridges.clear()
            _export_evidence(tmp_path)

    def test_E4b_duplicate_phy_intf_vs_rollback_failed_retained_rejected(
        self, tmp_path, monkeypatch
    ):
        """E4b: fabricated rollback-failed retained record for h1 owning phy;
        second attach reusing the same phy is rejected pre-mutation."""
        from src.runtime import bridge_external as bridge_mod
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        ctx = _setup_case("4b", token_len=1)
        names = ctx["names"]
        wrapper = TracedWrapper(tmp_path / "E4b.trace.jsonl")

        host2 = f"x{names['host_name'][1:]}"
        for v in (host2, f"br-{host2}", f"veth-{host2}-root", f"veth-{host2}"):
            assert len(v) <= 15, f"derived name {v!r} exceeds 15 bytes"

        try:
            _created_bridges.clear()
            # Fabricate a rollback-failed retained record: only phy_enslaved
            # outstanding, no real attach performed.
            _created_bridges[names["host_name"]] = {
                "bridge": names["bridge"],
                "veth_root": names["veth_root"],
                "veth_host": names["veth_host"],
                "phy_intf": names["phy"],
                "prior_up": False,
                "bridge_created": False,
                "bridge_up": False,
                "phy_up_changed": False,
                "phy_enslaved": True,
                "veth_created": False,
                "veth_root_mastered": False,
                "veth_root_up": False,
                "veth_host_ns_moved": False,
                "veth_host_up": False,
                "mtu_set": False,
                "ip_assigned": False,
            }

            monkeypatch.setattr(
                bridge_mod, "_run_root_cmd_vec", wrapper.run_root_cmd_vec
            )

            net = SyntheticNet()
            host = SyntheticHost(ns=names["ns"], pid=ctx["holder_pid"], wrapper=wrapper)
            net.add(host)

            with pytest.raises(
                RuntimeError, match=rf"(?i){names['phy']}.*already.*attached"
            ):
                attach_external_via_bridge(
                    net,
                    host2,
                    names["phy"],
                    ip="10.0.0.3/24",
                )

            # No mutating commands at all (rejection fires before any).
            for c in wrapper.last_calls:
                if c[:2] == ("ip", "link"):
                    assert c[2] not in ("add", "set", "del"), (
                        f"unexpected mutation during duplicate rejection: {c}"
                    )

            assert host2 not in _created_bridges
            assert names["host_name"] in _created_bridges

            _write_json(
                tmp_path / "E4b.trace-tail.json", [list(c) for c in wrapper.last_calls]
            )
            _write_json(
                tmp_path / "E4b.namespace.json",
                {
                    "ns": names["ns"],
                    "holder_pid": ctx["holder_pid"],
                    "names": names,
                    "second_host_name": host2,
                },
            )
        finally:
            wrapper.close()
            _cleanup_case(
                names["ns"],
                ctx.get("holder_pid"),
                names["veth_root"],
                names["bridge"],
                names["phy"],
                names["peer"],
            )
            _created_bridges.clear()
            _export_evidence(tmp_path)
