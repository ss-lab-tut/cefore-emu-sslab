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

**run_cefstatus / run_csmgrstatus**:
`cefore.py` helpers that wrap one diagnostic command (cefstatus / csmgrstatus) through CommandRunner: `quiet` suppresses the argv-echo/output `info()` calls, `timeout` forwards to the runner, and the **`CommandResult` itself is returned** (since the monitor-outcome work, 2026-07-16: callers need `returncode`/`timed_out`, not just text). The display string is derived by `status_output(result)` in the same module, which preserves the `"error: command timeout"` sentinel for a `timed_out` result so monitor.json output fields and debug FIB dumps read as before. Their test-injection seams differ: run_cefstatus takes an optional `runner=` kwarg (default: fresh `MininetCommandRunner(net)`); run_csmgrstatus has no such param — it always builds its own `MininetCommandRunner(net)` internally, so tests inject a fake by patching the `MininetCommandRunner` class itself, not by passing a kwarg. run_cefstatus was deepened to this shape (2026-07-12) to match run_csmgrstatus's proven quiet/timeout/timed_out/return-value behavior (not its construction seam); monitoring's cefstatus branch, disaster's webui pre-populate loop, and debug.dump_fib all now call run_cefstatus instead of hand-rolling the `["cefstatus","-d",f"./h{idx}"]` argv. run_csmgrstatus itself is deliberately unchanged.
_Avoid_: hand-built `["cefstatus",...]` / `["csmgrstatus",...]` argv outside cefore.py, a caller constructing its own CommandRunner for this argv, a caller treating the return value as `str` (use `status_output`)

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
Constructed through `build_fleet(net, host_num, csmgrd_host_ids, run_dir, *, cefnetd_timeout, readiness_policy)` (same module): the single place that derives node names, the `csmgrd_nodes` set, and `log_dir`. Every scenario's `configure` and its `teardown` fallback go through it, so the fallback no longer drops `csmgrd_nodes`. A constructor for the seam above, not a separate seam.
_Avoid_: daemon loops, start/stop loops, started_csmgrd_hosts, inline fleet construction

**Daemon log collection**:
Real cefnetd/csmgrd binaries write their operational log to `/tmp/<proc>_<port>_<sockid>.log` (proven against upstream `cef_log.c:204`), never to the `hN-*-log` names older docs mentioned. `src/runtime/daemon_logs.py` — a Mininet-free helper module — copies those files into `run_dir` between `collect_debug_post_teardown` and `cleanup_all` (mn_cleanup deletes `/tmp/*.log`, so the window is fixed). `BaseScenario.daemon_log_collection_enabled` is decided in each scenario's `__init__` before `run_dir.resolve()`, so `run_dir is None or Path(".")` disables collection while an explicit output_dir enables it — this survives Disaster/Connect's absolute-path normalization. `daemon_log_collection_scope() -> list[HostLogScope]` per scenario supplies the (idx, node_dir, has_csmgrd) triples from its own knowledge (`cache_node_set` / `roles` / `_csmgrd_host_ids()`), not from `args.hosts`. Stale-log defence: `start_cefnetd`/`start_csmgrd` each call the daemon-specific `cleanup_stale_*_log` helper so a stale `/tmp` log from a crashed prior run cannot be prepended into the next collection (proven 2026-07-07: 74-byte stale marker did not appear in collected output). `csmgrd.conf` templates set `CEF_LOG_LEVEL=2`, otherwise csmgrd's log stays 0 bytes.
_Avoid_: inline `/tmp/cefnetd_*.log` handling, hN-*-log naming, opt-in debug-artifact daemon_logs (removed — was a no-op), scope hooks reading `args.hosts` instead of scenario-owned state

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
One judgment entry in results.json — a tagged union of three shapes: ContentRecord (one per put/get/pub/sub; 14 fixed keys carrying the Verdict Factors), CcninfoRecord (one per ccninfo probe; 21 fixed keys carrying route/responder evidence and match Factors), and EventRecord (one per non-content scheduler event or host flap). Defined in `src/core/records.py`; the on-disk key sets are frozen — every reader (autotest analyze, smoke checker, webui) depends on them.
_Avoid_: result dict, record dict, results entry

**Event outcome**:
The tri-state `outcome` field (`ok` / `not-ok` / `skipped-no-result`) recorded per event in results.json, carried on an EventRecord together with a handler-specific `detail` dict. Handlers that only know pass/fail return a plain boolean and the record omits both fields; a handler with more to say returns `EventOutcome` (`src/runtime/scheduler.py`), today the compute_call handler. `not-ok` is an experiment failure (the operation ran and did not succeed); `skipped-no-result` is an environment cause — the endpoint was unreachable, or the run timed out or was cancelled — so no experiment result exists to judge. `success` is `False` for both, so readers that need the distinction must read `outcome`. Deliberately a different vocabulary from Monitor outcome, whose third value is spelled `skipped` in monitor.json: the two tri-states describe different things (a monitoring sample that was not taken vs. an event whose result the environment prevented) and coexist on purpose.
_Avoid_: the `"skipped"` spelling in results.json event records, collapsing `skipped-no-result` into `success=False`, an `EventOutcome`/Monitor outcome merge

**ResultsSink**:
The single seam through which every ResultsRecord is produced, accumulated, and written. Owns construction from (Verdict + op context) — including `ts` and `publisher_down` derivation — thread-safe accumulation, subscriber broadcast (webui dashboard), and the results.json write. Two adapters: the real sink and a recording fake for tests. Monitoring's observation stream stays outside it (ADR-0001).
_Avoid_: result callback, results list, `_append_result`

**Monitor outcome**:
The tri-state `outcome` field (`ok` / `not-ok` / `skipped`) carried by every monitor.json record (`MONITOR_FIELDS` in `src/runtime/monitoring.py`; derived by `derive_monitor_outcome` from the CommandResult for cefstatus/csmgrstatus, `skipped` when a down host yields no CommandResult at all). ccninfo monitor records do not go through `derive_monitor_outcome` (it has no ccninfo marker table): `Monitor._collect_ccninfo` stamps `ok` only when a reply was parsed and the run was not timed out, not cancelled, and exited with returncode 0 (same fail-closed criteria as `verdict.from_runtime_ccninfo`; 2026-09-02, 9740a80). The webui reads `record["outcome"]` for daemon liveness. Not a class name: there is no `MonitorOutcome` symbol.
_Avoid_: liveness re-derived by sniffing stdout text in webui, the `"skipped-no-result"` spelling in monitor.json (monitoring emits `"skipped"`; `"skipped-no-result"` belongs to Event outcome in results.json)

**ArtifactLayout (`src/core/artifacts.py`)**:
The single owner of experiment artifact naming — every name a run writes to disk and every reader parses back. Pure stdlib module (no `src` imports, so `core`/`runtime`/`log` all import it without cycles) owning three faces: `experiment_dir_name(num, seed, timestamp=False)` (the `ex{num}_seed{label}` / `seed{label}` directory stem incl. the `seed=None→"none"` conversion and timestamp suffix; `resolve_run_dir` and autotest's directory lookup both call it — autotest's former hand-rolled glob lacked the `none` conversion), `topo_png_default_name(num, seed, hosts)` = `{dir_stem}_h{hosts}.png`, and the canonical content-log schema `content_log_name(cmd, phase, host, uri)` = `{cmd}_{phase}_h{host}_{safe_uri_label(uri)}.log` with `parse_content_log_name → ContentLogMeta | None` as its inverse (build→parse round-trip is the test surface). All writers (`content_ops._log_path`, mesh, linear) build through it; the summarizer parses through it and joins op context (`uri`/`success`/`down_hosts`/`publisher_down`) from results.json by `Path(log_file).name` — last-wins, because repeated ops with the same cmd/phase/host/URI overwrite the same log file (status quo; the surviving log matches the last record). Text-parser values win over the join where non-None (plotter semantics preserved). Consequence for `repeat` gets (2026-07-07 workshop): a failed attempt's log is overwritten by a later success on the same host+URI, so outcome comparisons must read results.json, never the surviving log.
Deliberate changes (2026-07-03, R7-2+R8-5): mesh/linear log filenames moved to the canonical shape (were `cefputfile_h9.log` / bare `cefputfile.log`); topo PNG default renamed from `ex{hosts}_seed{s}.png` (hosts masqueraded as experiment number) to the dir-stem form; the 5-regex legacy parser ledger (`src/log/filename.py`) deleted — old-format run dirs are no longer summarizable (use old checkouts for archaeology); CSV dropped dead columns `content_id`/`file_seed`/`get_idx`/`cycle`, gained `label`/`publisher_down`; `cefore.py` content commands require `log_name` (dead fallback names deleted); `ceforeemu-log` revived (`__main__` guard + entry-point reinstall) and proven non-empty against live smoke runs.
_Avoid_: hand-built `ex{...}_seed{...}` or `.log` name literals, regex ledgers over log filenames, re-deriving op context from filenames when results.json carries it, `src/log/filename.py` (deleted)

**LogRecordSchema (`src/log/schema.py`)**:
The single owner of parsed content-log record field names — per-command `Field(name, log_label, kind)` tables in `COMMAND_SCHEMAS` from which all three consumers derive: the parser's regexes (`Field.pattern`, with `re.escape` so parenthesised labels like `Rx Frames (All)` stay equivalent to the former hand-written patterns), the summarizer's CSV column order (`csv_columns` = `timestamp` + field names + `success`), and the plotter's metric keys (validated at import via `_require_schema_field`, so a legacy spelling fails at load, not silently plots nothing). Pure stdlib, same pattern as ArtifactLayout: schema owner + round-trip test (`tests/log/test_schema.py` builds a sample log line per field and parses it through the public `PARSERS`). All four commands have static tables — cefsubfile carries the same field set as cefgetfile, cefpubfile the put-side six (real-log evidence). Unknown log labels are not dropped: the parser still picks them up via `_normalise_key`, includes them in the record, and prints one stderr warning pointing at `src/log/schema.py`; the summarizer appends such schema-unknown keys after the schema columns.
Deliberate changes (2026-07-06, R9-1): pub/sub dynamic column discovery replaced by schema tables; pub/sub CSV columns renamed to the canonical unit-suffixed convention (`throughput`→`throughput_bps`, `goodput`→`goodput_bps`, `jitter_*`→`jitter_*_us`, pub `rate`→`rate_mbps`) — old pub/sub CSVs use the old spellings (use old checkouts for archaeology).
_Avoid_: `_PUT_FIELDS`/`_GET_FIELDS`/`_PUTFILE_COLS`/`_GETFILE_COLS` literals (deleted), spelling-guess metric tuples like `("throughput", "throughput_bps")`, unit-suffix-less metric column names, re-spelling record field names outside `src/log/schema.py`

## Scheduling

**EventSchema**:
The canonical, pure-data description of each scheduler/config event type. `EVENT_SCHEMA` maps a type name to an `EventSpec` carrying its `required_fields`, `is_content` flag, and same-time `priority`. Lives in `src/core/events.py`; intentionally pure (dataclass + constant, no `runtime` import) so both the config validator (`core`) and the scheduler (`runtime`) import it without breaking the core→runtime layering. Insertion order is load-bearing — `event_types()` derives the validator's valid-type tuple and the "must be one of: …" error order from it.
Binding is asymmetric, by design: the config validator's missing-field checks are **bound** to `required_fields` (for `fib_*`/`compute_call`/`put`/`pubsub_pub`/`get`/`pubsub_sub`; `link_down`/`link_up`/`bw_set` keep their existing shape checks), and the scheduler derives `_EVENT_PRIORITY`/`_CONTENT_EVENT_TYPES` from it. The scheduler/content-runner handlers' field access (`ev["host"]`, `ev["prefix"]`, …) is **documented by convention** against `required_fields`, not mechanically enforced — so the schema⇄handler drift class is concentrated to one place to read, not eliminated. The publisher set (`is_publication=True` → `publication_event_types()`) is bound for `scenarios/disaster.py` and `scenarios/connect.py` publisher-metadata builders and for `loader.py`'s publication-validation branch, so the loader / scheduler / content_ops / scenarios quadrangle is now drift-free. Conditional publication: `EventSpec.publication_uri_field` names the event key that holds the published URI (`uri` for `put`/`pubsub_pub`, `publish_uri` for `compute_call`); `extract_publications(events, include_conditional=True)` additionally counts conditional publishers (a `compute_call` whose `publish_uri` is set) into `publishers_dict`/`publisher_ids` but never into the seedable `publications` list. Opt-in per scenario: `disaster.py` passes `include_conditional=True` so FIB pre-programming routes consumers toward compute hosts; `connect.py` keeps the default (its publication list is a seeding input and must stay put/pubsub_pub only). Duplicate-URI collisions resolve input-order last-wins across unconditional and conditional publishers alike (FIB computation accepts one host per URI).
`ContentOperationRunner._HANDLERS` in `src/runtime/content_ops.py` maps each content event type name to its handler method name (`"put"→"_do_put"` etc.); an import-time `assert set(_HANDLERS) == content_event_types()` locks the dispatch table to EventSchema so drift is caught at module load, not at runtime.
_Avoid_: `valid_event_types` literal, `_EVENT_PRIORITY`/`_CONTENT_EVENT_TYPES` literals, per-type required-field literals, `("put", "pubsub_pub")` tuple literal, "event type table", if/elif dispatch in content_ops

**extract_publications**:
The single owner of "which events introduce content into the network and who publishes them". Pure function in `src/core/events.py`: `extract_publications(events: list[dict]) → (publications, publishers_dict, publisher_ids)` where `publications` is the filtered list, `publishers_dict` is `{uri: host_idx}`, and `publisher_ids` is `frozenset[int]` (integer host indices, matching `ScenarioSetupSpec.publisher_ids: set[int]`). Both `DisasterScenario` and `ConnectScenario` derive their publisher state from it; `runtime/external_net.py` re-exports it as the public surface.
_Avoid_: `_prepare_event_publishers` (removed), `_publication_metadata` (removed), per-scenario iteration over `publication_event_types()`

**Compute endpoint**:
The HTTP service that a `compute_call` event's `endpoint` URL points at: something outside the Mininet topology (a Jetson-class box or any HTTP API) that is not a Mininet host and not managed by the emulator. Reachability is the experiment's concern (bridges/NAT), or, in the hermetic tests, a stand-in HTTP server run inside another Mininet host. The host that *executes* the compute_call and republishes the result into the ICN is a Mininet host on the compute_call's `host` index: it, not the endpoint, is the ICN publisher of `publish_uri` (which is why conditional publication routes consumers toward that host, not toward the endpoint).
_Avoid_: edge node, compute box, compute resource, compute node, "compute host" for the endpoint (ADR-0003 uses compute host for the publishing Mininet host)

**ccninfo event**:
A content event type that runs a CCNinfo path/cache trace (RFC 9344) from a designated host. Opt-in assert fields `expected_responder` and `expected_route` pin the responder node name and the ordered route token list respectively; mismatches are recorded as `responder_matched`/`route_matched` Factors in the CcninfoRecord.
_Avoid_: calling ccninfo from a CS_MODE=2 originator without `-c` (upstream Bug2 produces corrupt replies)

**ccninfo monitor target**:
A monitoring target (`type: ccninfo`) that periodically runs a CCNinfo probe from specified hosts. Each collection cycle produces a structured dict (not a string) in `monitor.json` with `parsed.reply_received`, `parsed.route`, `parsed.responder`, `timed_out`, `returncode`, `cancelled`, and `elapsed_ms` (returncode/cancelled added 2026-09-02; outcome is "ok" only when returncode == 0 and neither flag is set). The monitor `output` field is a dict for successful ccninfo probes but stays a plain string for host-down skips and exception wraps (the existing `_collect_once` contract), so the output type for any monitor entry is `dict | str`.
_Avoid_: monitoring ccninfo at intervals below the 5s warning threshold

**FailureManager (legacy `down_*` / `failure_scenarios` cycles)**:
The host-flap mechanism in `src/runtime/failure_manager.py`, separate from EventSchema (which owns scheduler event types only). Observable contract as of 2026-07-09: `down_interval`/`down_duration` default to 0/0, so a config that omits them starts no flap (2026-07-07 fix: a no-failure smoke used to see `[flap] down h1`); `down_count` keeps its default 5 because it doubles as the legacy cache fallback (`down_count + 1` in cache_manager); in cycle mode a host whose `host_up` failed still returns to the next cycle's pool and leaves the monitoring down-set (probes resume), while the `host_up success=False` flap record stays in results.json as evidence (7716a93). `failure_scenarios` cycles: `interval` counts from the previous cycle's down point and a target that is still down is skipped, so `interval` must exceed the previous `duration` or later windows vanish silently. The replacement design (`FailurePolicy`, ADR-0002) is backlog ticket 17.
_Avoid_: zeroing `down_count` alone, retiring legacy `down_*` without redesigning the cache fallback, extracting a shared primitive between `periodic_host_flap` and cycle mode (ADR-0002 deletes one side), cycles with `interval <= duration`

**Flap descriptor**:
One `failure_scenarios.simple` mapping or one entry of `failure_scenarios.cycles`. `_validate_flap_descriptor` is the single owner of their shared `interval` / `duration` / `count` / `stagger` / `exclude` validation; cycle entries additionally validate `target` and `allow_publishers`. Until FailurePolicy (ADR-0002) replaces this schema, zero-valued numeric fields remain valid and simple descriptors continue to ignore the cycle-only fields.
_Avoid_: duplicating numeric-field validation in simple/cycles branches, tightening `interval` or `duration` before the FailurePolicy migration, validating cycle-only fields in simple descriptors

Empirically established Cefore behaviors that constrain experiment design (pubsub failure beyond hop 2 on 15-host meshes, get availability during failure windows depending on an on-path csmgrd replica) live in [docs/known-cefore-behaviors.md](docs/known-cefore-behaviors.md).

## Scenario setup

**ScenarioSetupSpec**:
The policy bundle a scenario hands to the setup seam. Carries the topology snapshot (`mesh_links`, `scheme`, `host_count`, `publisher_ids`), the chosen `CacheStrategy`, fleet options (`fleet_run_dir`, `fleet_cefnetd_timeout`, `fleet_readiness_policy`), FIB inputs (`fib_k`, `fib_strategy`, `fib_uri_publishers`), optional bridges/bw/ext/PNG. Lives in `src/runtime/scenario_setup.py`; ordering is owned by the seam, not by spec fields.
_Avoid_: per-scenario setup recipes, configure() copy-paste

**TeardownSpec / TeardownResult / teardown_scenario**:
The teardown-side seam symmetric with `setup_scenario`, living beside it in `src/runtime/scenario_setup.py`. `teardown_scenario(net, spec) -> TeardownResult` runs `fleet.stop_all()` → `bridge_manager.cleanup()` when present → `cleanup_external_bridges()` only when `spec.cleanup_external_bridges` opts in (currently disaster only). All four scenarios call it from `teardown()` and propagate non-empty `result.failures` through `_propagate_failures(None, result.failures)`, normalizing the old mesh/linear silent-discard behavior.
_Avoid_: per-scenario teardown boilerplate, reintroducing mesh/linear silent-discard behavior

**MeshBuildSpec / MeshBuildResult / build_mesh_scenario**:
The build-side seam that extends the scenario lifecycle trilogy to the pre-net stage (2026-07-06, R9-2), living beside setup/teardown in `src/runtime/scenario_setup.py`. Owns the mesh-shape construction sequence the three mesh scenarios (disaster, connect, mesh) previously copied byte-identically: `assign_roles` → `provision_node_dirs` → `MeshTopo`, with the rng resolved **once** (`spec.rng or random.Random()`) and shared across role assignment and topology construction — splitting that stream would keep unit tests green while silently changing seeded experiment topology. `publisher_ids: frozenset[int]` defaults empty, which is equivalent to `assign_roles(publishers=None)` (mesh's historical omission). `switch_limit` is the semantic name for MeshTopo's legacy `swhich_num` kwarg (a typo that also hides the meaning: an upper bound on the emergent switch count — see the backlog 修正案). Scenarios keep only policy: building the spec from their own arg source and wiring `MeshBuildResult` (`roles`/`node_dirs`/`topo`) into instance state (mesh keeps `roles` for RolesCacheStrategy). linear is deliberately outside — LineTopo, not mesh-shaped. Proven by seeded characterization: 20 golden snapshots byte-identical across the fold.
`create_tclink_mininet(topo, **kwargs)` (same module) owns the TCLink Mininet construction disaster/connect duplicated; mesh deliberately keeps the base non-TCLink default.
_Avoid_: per-scenario roles/provision/MeshTopo copies, call-site `self.rng or random.Random()` fallbacks, two independent RNGs for roles vs topology, `swhich_num` spelling in new interfaces

**ConfigDrivenMeshScenario**:
The intermediate base (`src/scenarios/config_driven_mesh.py`) between BaseScenario and the two config-driven mesh scenarios (disaster, connect). Owns the glue they used to copy byte-identically: `build_topology`, `create_mininet`, `daemon_log_collection_scope`, `should_run_cli`, and the before_cli/after_cli tee swap. Deliberately preserved divergence: disaster's rng is always a fresh `Random()` (failure-manager scheduling needs one even when unseeded) while connect falls back to `None`; disaster's only override is `before_cli` (monitor to background, then `super()`).
_Avoid_: re-copying this glue into a scenario, "mesh CLI scenario base" or other ad-hoc names

**setup_scenario / SetupResult**:
The single seam through which every scenario's network configuration walks the canonical order: `apply_ip_addr` → bridges → ifconfig log → bw → ext → render_png → cache_strategy.place → forwarding_config.apply → build_fleet + start + wait_ready → apply_fib → cefstatus + print_mesh_links. Returns `SetupResult(daemon_fleet, cache_node_set, fib_routes)` so the scenario can wire them back into `self.daemon_fleet` / `self.cache_node_set` / `self._fib_routes` for downstream (monitoring, webui, FIB-restore). Forwarding strategy is written to every hN/cefnetd.conf before daemon start because post-start edits do not affect cefnetd. All three scenarios (disaster, connect, mesh) use it; pre-canonical drift (connect's bw/ext-after-everything, mesh/connect `time.sleep(1)`, mesh debug print) was removed once smoke 12/12 confirmed it carried no semantic load.
_Avoid_: per-scenario IP/bridge/cache/fleet/FIB sequencing, ordering knobs

**CacheStrategy**:
Polymorphic decision module for "which hosts run csmgrd as cache nodes". One protocol `place(ctx: CacheContext) -> set[int]` with three real adapters in `src/runtime/cache_strategy.py`: `KCentersStrategy` (graph/manual/degree_based via CachePlacement; disaster + connect use it, connect with `exclude_publishers=False`), `RandomCSModeStrategy` (per-host random CS_MODE 0/1/2 with `apply_cs_modes` side effect; disaster's `cache_config.strategy="random"`), `RolesCacheStrategy` (csmgrd hosts from `assign_roles`; mesh). The scenario picks one; setup_scenario calls `.place()` polymorphically. `CacheContext` is the immutable snapshot (`host_count`, `host_graph`, `publisher_ids`) every adapter reads from.
_Avoid_: cache strategy branching in scenarios, `_configure_cache_nodes`, inline `assign_random_cs_modes` calls

## External connectivity

**Bridge modules (`bridge_args` / `bridge_external` / `bridge_root`)**:
The former `runtime/bridge.py` god-module (1240 LOC, three unrelated interfaces) split by concern (2026-07-03, R7-4, behavior-preserving move):
`bridge_args.py` — pure parsing/validation leaf (`parse_bridge_args`, `parse_ext_args`, `validate_static_ip`); stdlib-only, imported by both siblings, the only code they share. Note `parse_ext_args` does not validate CIDR — `validate_static_ip` owns strictness and is called at attach/connect time.
`bridge_external.py` — the external-NIC attach state machine: `attach_external_via_bridge` / `cleanup_external_bridges` / `attach_external_interface` with the module-level `_created_bridges` ledger and `_RollbackAction` transactional rollback (setup-side) plus the flag-gated teardown cascade. Proven by unit tests and the root-gated synthetic suite (`CEFEMU_SYNTHETIC_ROOT=1`, real veth/netns).
`bridge_root.py` — root-namespace bridging: `BridgeManager` (NAT / proxy-ARP / IP forwarding, per-instance `cleanup_actions` `CleanupAction` ledger, `TeardownError`) and the `setup_bridges` orchestration, which only ever drives the root side.
The two cleanup ledgers are deliberately separate — the attach side's 7-flag veth-deletion cascade cannot be expressed as a flat `CleanupAction` list (pinned decision; do not unify).
_Avoid_: `runtime/bridge.py` (deleted), importing attach machinery from the root module or vice versa, ledger unification, adding CIDR validation to `parse_ext_args`

## Scenario run

**EventBatchSpec / EventBatchResult / run_event_batch**:
The run-side seam completing the scenario lifecycle trilogy (setup_scenario / teardown_scenario / run_event_batch), living in `src/runtime/event_batch.py`. `run_event_batch(net, spec) -> EventBatchResult` owns the ContentOperationRunner + EventScheduler lifecycle for one batch of events: both collaborators are fully constructed before either is started (a scheduler constructor error can no longer leak a running content worker), the runner is built only when the batch contains content events, and `pub_lifetime_by_uri` is derived from the events inside the seam. `wait_timeout=None` means deferred — the caller assigns `result.content_runner` / `result.event_scheduler` back to `self.*` so `shutdown_runtime_resources` owns the stop; a numeric `wait_timeout` runs the sync discipline with starts and waits inside try/finally and both stops attempted independently (`failures` is `_propagate_failures`-compatible). Deadline handling is policy-dependent and byte-preserves the pre-seam wording via `scheduler_label`/`runner_label`: `deadline_policy="raise"` (disaster seed) short-circuits the runner wait after a scheduler miss and raises RuntimeError after stopping; `"warn"` (connect) never short-circuits and warns per miss with a fresh timeout. Callers: disaster normal/seed/eval and connect. Warmup stays runner-only through `_make_content_runner` (submit-pacing is a different contract, deliberately outside the seam); mesh/linear run event-less direct commands and never touch it. `spec.command_runner` passes a CommandRunner fake through to the runner so seam tests inject instead of patching internals.
_Avoid_: per-scenario runner+scheduler 手配線, EventScheduler direct construction in scenarios, per-site runner-construction condition variants, finally 内 stop 例外の握り潰し

## Configuration

**OptionSpec / OPTION_SPECS**:
The single owner of CLI/config option identity — one entry per option carrying `key`, `kind` (`bool`/`str`/`int`/`number`/`enum`/`structured`), `default`, `minimum`, `nullable`, `message`, and the CLI face (`flag`, `action`, `choices`, `metavar`, `help`, `block`, `cli_order`) plus routing flags (`config_allowed`, `cli_allowed`, `special_config_merge`). Lives in `src/core/config/validator.py` beside the validators that consume it. Four derived views replace the former five hand-maintained ledgers: `_FLAT_SPECS` (flat-scalar validation view, old names/messages byte-preserved), `config_option_keys()` (loader merge keys), `nullable_option_keys()` (the once-diverging null sets, now one), and `_add_args_for_block` in `src/cli/args.py` (argparse generation for the `common`/`mesh`/`disaster`/`debug`/`linear`/`connect` blocks — `add_*_args` builders, used by `ceforeemu` and `ceforeemu-connect` alike). Binding is asymmetric like EventSchema: identity is fully bound; deep validation of `structured` entries stays with the bespoke `_validate_*` functions; merge specials (`cache_config` unconditional setattr, `debug` union semantics) stay bespoke but are marked `special_config_merge` so the exclusion is table-driven, not a side literal. Adding an option = one spec entry; argparse, merge, and validation all follow.
Deliberate behavior change recorded here: `--topo-layout` typos are argparse-rejected on every entry point (was: silent spring fallback in viz), and formerly unvalidated `down_exclude`/`topo_png`/`bw`/`ext`/`host_degree_max` now have type-level checks.
Presence semantics of `validate_merged_args` (2026-07-09 fixes 73ca40b / d2680b1): structured and scalar keys are both forwarded on **presence** (`hasattr`), not truthiness, so `failure_scenarios: {}` / `null` and `hosts: null` reach validation instead of being silently skipped or raising a raw TypeError. Config-only keys exist on args only when the config set them (merge_cli_and_config does `setattr` only then), so `hasattr` is config-presence evidence; `bw`/`ext` always exist (argparse `append`, default `[]`) and an empty list passes harmlessly, which is not a bug. `cache_config`/`forwarding_config` are `special_config_merge` and never travel through args: the bootstrap raw-config revalidation is their only, exactly-once validation path. **Invariant**: every non-nullable scalar with `cli_allowed=True` must have a non-None argparse default, otherwise a plain CLI run fails validation; `num` is therefore `nullable=True` (None = no experiment number).
_Avoid_: option literals in argparse builders, `config_keys` tuple literal, `_NULL_MEANS_DEFAULT` literal, per-entry-point hand-written parsers, side exclusion sets like `{"debug", "cache_config"}`, reporting bw/ext's constant presence as a bug, a new scalar spec combining argparse default None + non-nullable + cli_allowed=True

**ConfigValidator**:
The single owner of every config-validation rule. Lives in `src/core/config/validator.py`; pure-fn module composed of per-block validators (`_validate_flat_keys` over `_FLAT_SPECS`, `_validate_cache_config`, `_validate_failure_scenarios`, `_validate_bridges`, `_validate_events`) and the public `validate_config(config) → list[str]` / `validate_merged_args(args) → list[str]` entries. The loader (`src/core/config/loader.py`) shrinks to I/O (`load_config`, YAML/JSON), legacy-key warning (`warn_ignored_legacy_content_keys`), and CLI/config merge (`merge_cli_and_config`); it re-exports `_FLAT_SPECS`, `validate_config`, `validate_merged_args` so external import sites (`runtime/external_net`, `cli/main`, `tools/autotest`, `tests/core/config`) stay stable. Event-type missing-field checks bind to `EVENT_SCHEMA[etype].required_fields` (the EventSchema scope's loader edge); error append order and message strings are mechanically preserved across the extraction (verified by 137 tests + a HEAD-vs-new differential test over 6 cross-block malformed configs, 38 error strings byte-identical).
_Avoid_: validation rules in loader.py, per-block hand-rolled if/elif chains, duplicate event-type required-field lists, splitting `_FLAT_SPECS` from the validator

**ScenarioBootstrap**:
The single seam through which every config-driven CLI entry point (`ceforeemu disaster`, `ceforeemu-connect`) walks the canonical bootstrap sequence: `load_config` → legacy-key warning → parser-backed `merge_cli_and_config`（CLI が config に勝つ）→ `validate_merged_args` + raw-config debug-block validation → `resolve_run_dir` → topo_png default → meta.json（12キー、`run_dir == "."` では書かない）→ script.log Tee → `build_debug_config` → try/finally `run_fn`. `bootstrap_scenario(args, *, blocks, run_fn)` in `src/cli/bootstrap.py`; `blocks` は precedence parser を組む OPTION_SPECS CLI block 名、`run_fn(args, run_dir, log_context=, debug_config=)` が scenario runner の契約。debug block・`cache_config`・`forwarding_config` は `special_config_merge` で args に乗らないため、この seam の raw-config 検証が唯一の（exactly-once の）検証経路（merged-args validation はそこに盲目）。mesh/linear は意図的に対象外 — config 非対応で seam の背後に置く behaviour が無い。
Deliberate changes (2026-07-03, R8-1): connect の precedence-inversion bug 修正（parser 無し merge で config が明示 CLI flag を上書きしていた；`merge_cli_and_config` は parser 必須に変更済み）、connect validation を post-merge に統一、connect meta.json を 12キー disaster スキーマに片寄せ（`output_dir` キー廃止 = 読者ゼロ確認済み）、main-level `run_dir.resolve()` 削除（ConnectScenario が内部 resolve）、connect が debug 収集を獲得、fib_dump/daemon_logs collector を DisasterScenario から BaseScenario へ hoist（args namespace を持たない scenario は guard で opt out）。
The temporary differential gate for HEAD-vs-branch bootstrap behavior was removed after the workshop branch merge; the bootstrap seam is now guarded by direct behavior tests.
_Avoid_: per-entry-point bootstrap コピー, parser 無し merge_cli_and_config, pre-merge validate_config, meta.json output_dir キー, debug_config=None hardcode

## Backlog

未着手の deepening 候補（2026-06-26 architecture review round と 2026-07-09 R10 review の残り、deferred ccninfo/monitoring gaps、ReCefore 改称）は [docs/wayfinder/arch-backlog/map.md](docs/wayfinder/arch-backlog/map.md) のチケットで管理する。完了したら該当 ticket を `status: closed` にし、正式名をこのファイルの該当節に追記すること。mutation testing の runbook は [docs/runbooks/mutation-testing.md](docs/runbooks/mutation-testing.md)。

リリースノートは当面 `docs/releases/<tag>.md`（release workflow が `--notes-file` で読む。無ければ自動生成のみ）。将来は CHANGELOG.md に統合する（2026-08-25 決定）。
