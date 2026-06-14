# CeforeEmu Context

CeforeEmu emulates Content-Centric Networking (Cefore) deployments on Mininet. This glossary fixes the project-specific language so code and future architecture reviews stay consistent. General programming concepts are intentionally excluded.

## Command execution

**CommandRunner**:
The single seam through which every command sent to a Mininet host (or the root namespace) is executed. Owns argv execution, output redirection, and the lifecycle of long-running processes. Has two adapters: a real Mininet-backed one and a recording fake for tests.
_Avoid_: shell helper, exec wrapper, "host.cmd()" path

**CommandResult**:
The value a CommandRunner returns for a finished command: `returncode`, `stdout`, `stderr`, `timed_out`, `cancelled`, `log_path`. Deadline/cancellation is expressed through the `timed_out`/`cancelled` flags, not through a sentinel returncode.
_Avoid_: output, return tuple, proc result

**CommandHandle**:
The token a CommandRunner returns for a still-running command. Callers wait/poll/terminate/kill it through the runner; they never hold a raw `Popen`.
_Avoid_: proc, process handle, popen object

## Host identity

**Node name**:
The canonical identifier of a host in runner and config interfaces — the string `"h{idx}"` (e.g. `"h3"`). This is the one identity used everywhere; integer host indices are an internal/topology detail, not an interface identity.
_Avoid_: host index, idx, host id (as an interface argument)

**Root sentinel**:
The reserved Node name that tells the CommandRunner to execute in the root namespace (plain subprocess) instead of a host netns. Used by bridge/external-network setup.
_Avoid_: root ns flag, "root" special case

## Node provisioning

**provision_node_dirs**:
The single owner of creating each host's `hN` directory from its role template. Takes the `assign_roles` result as an argument (never re-derives roles, so callers make one `assign_roles` call with no rng save/restore dance), takes an explicit `base_dir`, raises `NodeDirError` instead of `sys.exit` (the scenario's staged cleanup runs instead of the process dying), and is atomic — a mid-loop failure removes the directories that call created and leaves any unmanaged directory intact. Lives in `src/runtime/template.py`; a function, not a runner seam — its only substrate is the filesystem, tested through `tmp_path`. Paired with `cleanup_node_dirs` via the STAMP_FILENAME marker.
_Avoid_: ensure_node_dirs, role re-derivation, rng save/restore dance, sys.exit on bad dir

## Daemon lifecycle

**DaemonFleet**:
The single seam through which the Cefore daemons (csmgrd + cefnetd) of one experiment are started, readiness-checked, and stopped. Owns the csmgrd→cefnetd startup order, the readiness policy (`warn` logs and continues; `raise` aborts before FIB programming), stop-failure aggregation, and started-csmgrd tracking. Lives in `src/runtime/daemon_fleet.py`; speaks Node names at its interface and drives every command through a CommandRunner. All four scenarios construct one in `configure` and reuse it in `teardown`.
_Avoid_: daemon loops, start/stop loops, started_csmgrd_hosts

## Cache placement

**CachePlacement**:
The single owner of the "which hosts are cache nodes" decision. Resolves the strategy (cache_config via CacheConfigManager, or legacy k-centers with `cache_count`/`down_count + 1`), applies the publisher-exclusion policy as an explicit argument (`exclude_publishers`: disaster True, connect False), the last-host fallback, the cache-node log, and the settings application. Lives in `src/runtime/cache_manager.py`; `decide()` is the side-effect-free decision, `place()` applies it.
_Avoid_: cache node selection (inline), k-centers branching, cache epilogue

## Topology

**TopologyModel**:
The single owner of the mesh_links schema. Consumers (FIB computation, link state ops, bandwidth, IP assignment, visualization, bridge root-IP resolution, webui topology view) query it — `find_link`, `links_for_host`, `edges`, `subnet_of_switch`, `peer_of`, `links` — instead of branching on the link dict shape. Lives in `src/core/topology.py`; absorbs both the canonical multi-host shape MeshTopo emits and the legacy point-to-point shape at construction.
_Avoid_: mesh_links parsing, `"hosts" in link` branching, raw link dict

**Link**:
The value object a TopologyModel query returns for one switch-mediated link: `switch`, `subnet`, `hosts` (every host sharing the switch), `eth_of(host)`.
_Avoid_: link dict, link entry

## Experiment results

**Verdict**:
The single judgment of one experiment operation's outcome (put/get/pub/sub). Owns the per-op success criteria, the completed-marker and failure-pattern strings, and the Factors. Lives in `src/core/verdict.py`; every consumer (results.json records, CSV log pipeline, autotest analyze, smoke checker) reads recorded Verdict Factors instead of re-deriving success. Produced through three adapters: runtime (CommandResult + log + artifacts), log-only (post-hoc log text; unseen Factors stay unknown), stored-factors (a results.json record).
_Avoid_: success detection, detect result, classify result

**Factor**:
One named piece of Verdict evidence (`has_completed_log`, `has_output_file`, exit status). Tri-state: `True`, `False`, or `None` meaning unknown *or* not-applicable for that op type (e.g. completed-marker for pub/sub). A Factor that is `None` is never counted as a failure reason. Each op type has a definitive Factor for log-only judgment (get: completed-marker; put: result fields + no failure pattern); ops without an in-log definitive Factor (sub/pub) stay unknown there.
_Avoid_: flag, boolean column

**ResultsRecord**:
One judgment entry in results.json — a tagged union of two shapes: ContentRecord (one per put/get/pub/sub; 14 fixed keys carrying the Verdict Factors) and EventRecord (one per non-content scheduler event or host flap). Defined in `src/core/records.py`; the on-disk key sets are frozen — every reader (autotest analyze, smoke checker, webui) depends on them.
_Avoid_: result dict, record dict, results entry

**ResultsSink**:
The single seam through which every ResultsRecord is produced, accumulated, and written. Owns construction from (Verdict + op context) — including `ts` and `publisher_down` derivation — thread-safe accumulation, subscriber broadcast (webui dashboard), and the results.json write. Two adapters: the real sink and a recording fake for tests. Monitoring's observation stream stays outside it (ADR-0001).
_Avoid_: result callback, results list, `_append_result`
