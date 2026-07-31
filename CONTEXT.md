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
`cefore.py` helpers that wrap one diagnostic command (cefstatus / csmgrstatus) through CommandRunner and normalize the result: `quiet` suppresses the argv-echo/output `info()` calls, `timeout` forwards to the runner, a `timed_out` CommandResult becomes `"error: command timeout"`, and the (possibly-converted) output is returned instead of only printed. Their test-injection seams differ: run_cefstatus takes an optional `runner=` kwarg (default: fresh `MininetCommandRunner(net)`); run_csmgrstatus has no such param — it always builds its own `MininetCommandRunner(net)` internally, so tests inject a fake by patching the `MininetCommandRunner` class itself, not by passing a kwarg. run_cefstatus was deepened to this shape (2026-07-12) to match run_csmgrstatus's proven quiet/timeout/timed_out/return-value behavior (not its construction seam); monitoring's cefstatus branch, disaster's webui pre-populate loop, and debug.dump_fib all now call run_cefstatus instead of hand-rolling the `["cefstatus","-d",f"./h{idx}"]` argv. run_csmgrstatus itself is deliberately unchanged.
_Avoid_: hand-built `["cefstatus",...]` / `["csmgrstatus",...]` argv outside cefore.py, a caller constructing its own CommandRunner for this argv

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

**ResultsSink**:
The single seam through which every ResultsRecord is produced, accumulated, and written. Owns construction from (Verdict + op context) — including `ts` and `publisher_down` derivation — thread-safe accumulation, subscriber broadcast (webui dashboard), and the results.json write. Two adapters: the real sink and a recording fake for tests. Monitoring's observation stream stays outside it (ADR-0001).
_Avoid_: result callback, results list, `_append_result`

**ArtifactLayout (`src/core/artifacts.py`)**:
The single owner of experiment artifact naming — every name a run writes to disk and every reader parses back. Pure stdlib module (no `src` imports, so `core`/`runtime`/`log` all import it without cycles) owning three faces: `experiment_dir_name(num, seed, timestamp=False)` (the `ex{num}_seed{label}` / `seed{label}` directory stem incl. the `seed=None→"none"` conversion and timestamp suffix; `resolve_run_dir` and autotest's directory lookup both call it — autotest's former hand-rolled glob lacked the `none` conversion), `topo_png_default_name(num, seed, hosts)` = `{dir_stem}_h{hosts}.png`, and the canonical content-log schema `content_log_name(cmd, phase, host, uri)` = `{cmd}_{phase}_h{host}_{safe_uri_label(uri)}.log` with `parse_content_log_name → ContentLogMeta | None` as its inverse (build→parse round-trip is the test surface). All writers (`content_ops._log_path`, mesh, linear) build through it; the summarizer parses through it and joins op context (`uri`/`success`/`down_hosts`/`publisher_down`) from results.json by `Path(log_file).name` — last-wins, because repeated ops with the same cmd/phase/host/URI overwrite the same log file (status quo; the surviving log matches the last record). Text-parser values win over the join where non-None (plotter semantics preserved).
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

**ccninfo event**:
A content event type that runs a CCNinfo path/cache trace (RFC 9344) from a designated host. Opt-in assert fields `expected_responder` and `expected_route` pin the responder node name and the ordered route token list respectively; mismatches are recorded as `responder_matched`/`route_matched` Factors in the CcninfoRecord.
_Avoid_: calling ccninfo from a CS_MODE=2 originator without `-c` (upstream Bug2 produces corrupt replies)

**ccninfo monitor target**:
A monitoring target (`type: ccninfo`) that periodically runs a CCNinfo probe from specified hosts. Each collection cycle produces a structured dict (not a string) in `monitor.json` with `parsed.reply_received`, `parsed.route`, `parsed.responder`, `timed_out`, and `elapsed_ms`. The monitor `output` field is a dict for successful ccninfo probes but stays a plain string for host-down skips and exception wraps (the existing `_collect_once` contract), so the output type for any monitor entry is `dict | str`.
_Avoid_: monitoring ccninfo at intervals below the 5s warning threshold

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
_Avoid_: option literals in argparse builders, `config_keys` tuple literal, `_NULL_MEANS_DEFAULT` literal, per-entry-point hand-written parsers, side exclusion sets like `{"debug", "cache_config"}`

**ConfigValidator**:
The single owner of every config-validation rule. Lives in `src/core/config/validator.py`; pure-fn module composed of per-block validators (`_validate_flat_keys` over `_FLAT_SPECS`, `_validate_cache_config`, `_validate_failure_scenarios`, `_validate_bridges`, `_validate_events`) and the public `validate_config(config) → list[str]` / `validate_merged_args(args) → list[str]` entries. The loader (`src/core/config/loader.py`) shrinks to I/O (`load_config`, YAML/JSON), legacy-key warning (`warn_ignored_legacy_content_keys`), and CLI/config merge (`merge_cli_and_config`); it re-exports `_FLAT_SPECS`, `validate_config`, `validate_merged_args` so external import sites (`runtime/external_net`, `cli/main`, `tools/autotest`, `tests/core/config`) stay stable. Event-type missing-field checks bind to `EVENT_SCHEMA[etype].required_fields` (the EventSchema scope's loader edge); error append order and message strings are mechanically preserved across the extraction (verified by 137 tests + a HEAD-vs-new differential test over 6 cross-block malformed configs, 38 error strings byte-identical).
_Avoid_: validation rules in loader.py, per-block hand-rolled if/elif chains, duplicate event-type required-field lists, splitting `_FLAT_SPECS` from the validator

**ScenarioBootstrap**:
The single seam through which every config-driven CLI entry point (`ceforeemu disaster`, `ceforeemu-connect`) walks the canonical bootstrap sequence: `load_config` → legacy-key warning → parser-backed `merge_cli_and_config`（CLI が config に勝つ）→ `validate_merged_args` + raw-config debug-block validation → `resolve_run_dir` → topo_png default → meta.json（12キー、`run_dir == "."` では書かない）→ script.log Tee → `build_debug_config` → try/finally `run_fn`. `bootstrap_scenario(args, *, blocks, run_fn)` in `src/cli/bootstrap.py`; `blocks` は precedence parser を組む OPTION_SPECS CLI block 名、`run_fn(args, run_dir, log_context=, debug_config=)` が scenario runner の契約。debug block は `special_config_merge` で args に乗らないため、この seam が raw config から検証する（merged-args validation はそこに盲目）。mesh/linear は意図的に対象外 — config 非対応で seam の背後に置く behaviour が無い。
Deliberate changes (2026-07-03, R8-1): connect の precedence-inversion bug 修正（parser 無し merge で config が明示 CLI flag を上書きしていた；`merge_cli_and_config` は parser 必須に変更済み）、connect validation を post-merge に統一、connect meta.json を 12キー disaster スキーマに片寄せ（`output_dir` キー廃止 = 読者ゼロ確認済み）、main-level `run_dir.resolve()` 削除（ConnectScenario が内部 resolve）、connect が debug 収集を獲得、fib_dump/daemon_logs collector を DisasterScenario から BaseScenario へ hoist（args namespace を持たない scenario は guard で opt out）。
The temporary differential gate for HEAD-vs-branch bootstrap behavior was removed after the workshop branch merge; the bootstrap seam is now guarded by direct behavior tests.
_Avoid_: per-entry-point bootstrap コピー, parser 無し merge_cli_and_config, pre-merge validate_config, meta.json output_dir キー, debug_config=None hardcode

## 次回実装候補 — Architecture review backlog (2026-06-26 round)

このセクションは domain glossary ではなく、未着手の deepening candidate を次のセッションで再提案されないよう pin する backlog。`/tmp/architecture-review-20260626-165236.html` のレポート由来。完了したら該当エントリを削除し、上の domain section に正式名を追記すること。

**R10 backlog (2026-07-09 review 完了) — 次セッションの作業キュー**:
feature/seam (= main, PR#13 マージ後) を対象に 8 subsystem 並列探索 + 候補ごと adversarial 検証を実施、21 raw 候補中 20 生存。bug 級 B1・B2 は 2026-07-09 に解消済み (下記)。Strong S1 (run_cefstatus deepening)・S2 (dead per-content label param 削除) は 2026-07-12 に実装完了、エントリ削除済み。残る優先順: (1) Strong S3〜S9、(2) Worth exploring W1〜W8 は余力で、Speculative P1〜P2 は保留。独立 housekeeping 負債は変わらず: repo 全体 `mypy src` 71 errors / 32 files (fresh-cache 実測 2026-07-12; 旧記載 57/24 は incremental-cache による過小計数)・`ruff check src tests` 14 errors (main 由来)。

**解消済み (2026-07-09) — B1: validate_merged_args の present-but-empty structured config 素通し**:
73ca40b で fix。structured-key 取り込みを truthiness から presence (`hasattr`) に変更し、`failure_scenarios: {}` / `null` が ADR-0002:21-24 通り validation error になった。presence が成立する根拠: config-only key は merge_cli_and_config が config 実在時のみ setattr する。bw/ext は argparse append (default `[]`) で常に attr が在るが、空リストは無害に検証通過。cache_config/forwarding_config は structured_option_keys() が special_config_merge を除外するため元々この経路外 — bootstrap raw revalidation が唯一の検証経路のまま (fold 不要と実証、exactly-once エラーを test で pin)。codex-review approve (findings ゼロ)。**発見した残課題 → R8 エントリに追記済み**: `failure_scenarios: "none"` (文字列) が現状 `'must be a dict'` で error になり、ADR-0002 の「省略と等価で許可」と矛盾する。
_Avoid_: bw/ext の常時 presence を bug として再報告すること、"none" 許可を R8 の FailurePolicy 解決と切り離して実装すること

**解消済み (2026-07-09) — B3: validate_merged_args の scalar 側 explicit-null 素通し (B1 完了監査で発見)**:
d2680b1 で fix。B1 の gpt-5.5 完了監査が指摘した同型 bug — scalar loop の `val is not None or nullable` gate が non-nullable scalar の明示 null (`hosts: null` 等) を捨て、後段で生 TypeError になっていた。fix は scalar も presence forward 化。安全性の invariant: **non-nullable かつ cli_allowed=True の scalar は全て argparse default が非 None** (4 CLI block 全列挙で実証; これが崩れると素の CLI 実行が全部 validation error になる)。唯一の違反だった `num` (argparse default None・非 nullable) は nullable=True 化 — None は「実験番号なし」の正当な状態。cli_allowed=False scalar (cefnetd_timeout) は parser 非搭載なので hasattr が config-presence 証拠 (structured 側と同メカニズム)。no-flag+empty-config の false-positive guard test を disaster/connect 両 parser で pin。codex-review approve (findings ゼロ)。
_Avoid_: 新規 scalar OptionSpec に「argparse default None かつ非 nullable かつ cli_allowed=True」の組合せを導入すること (invariant 違反 → 全デフォルト実行が error 化)

**解消済み (2026-07-09) — B2: failure_manager cycle-mode の host 恒久除外**:
7716a93 で fix。cycle-mode do_up の `shared_down.discard` を restored_hosts gate から down_set 無条件へ変更 (periodic_host_flap :80 と同 semantics)。復帰失敗 host も次 cycle の available pool へ戻り、monitoring down-set からも外れる (probe 再開は periodic と同じ既存挙動で意図通り)。`_record_flap` の success=False 記録は維持 — 失敗証拠は results.json に残る。regression test は up 失敗 host が次 cycle で再選択されることを pin (pre-fix fail 確認・20 連続 flake なし)。共有 primitive 抽出は意図的に不採用 (ADR-0002 R8 が periodic_host_flap を削除予定 → one-adapter seam 化するため)。
_Avoid_: periodic_host_flap と cycle-mode の共有 primitive 抽出 (R8 で片側が消える)

**S3 — Disaster/Connect wiring 重複 collapse**: lifecycle quartet の外側の glue — build_topology (17行 byte-identical) / create_mininet / daemon_log_collection_scope (11行) / should_run_cli / before_cli・after_cli の tee-swap / __init__ prologue — が両 scenario に copy。BaseScenario と両者の間に mesh-CLI-scenario 中間 base を置き hoist。注意: connect の rng init 位置、disaster の rng fallback (failure-manager scheduling 用に常に fresh Random()) の差は保持。

**S4 — pub_lifetime_by_uri 二重導出**: `event_batch.py:55-64` の module-private helper を public 化し、`disaster.py:274-280` (_make_content_runner 内の inline 再実装) を置換。warmup 経路が seam 外なのは意図 (CONTEXT の EventBatchSpec 項) — 導出関数だけ共有する。

**S5 — _validate_failure_scenarios の simple/cycles 重複検査 collapse**: `validator.py:729-878` が同一 flap-descriptor 検査を simple 用と cycles[idx] 用に 2 実装し、negative count/stagger は同一エラー文字列が 2 回返る (実測: 2 violation で 4 errors)。`_validate_flap_descriptor(errors, prefix, descriptor, *, allow_target=, allow_publishers=)` へ抽出。R8 が同関数の schema を変える予定 (duration/interval >= 1) なので R8 着手前に済ませるか R8 に同梱するかは着手時に判断。

**S6 — bridge_external に CommandRunner seam**: attach_external_via_bridge / cleanup_external_bridges / attach_external_interface に optional `runner` param を追加し `_run_root_cmd_vec` (bridge_external.py:51-64 が MininetCommandRunner(None) を hardcode) へ thread。現行テストは internal patch 41 箇所 (_run_root_cmd_vec 37 + MininetCommandRunner 4: test 行 218/388/967/1015) — recording fake 注入へ移行可能に。bridge_root.py:74-89 BridgeManager の _root_runner/_host_runner pattern を mirror。

**S7 — Monitor が CommandResult.returncode を捨て webui が text sniffing で liveness 再導出**: MONITOR_FIELDS (`monitoring.py:19`) に outcome field を追加し webui/state.py の hand-maintained keyword list を置換。tri-state 必須 (ok / not-ok / skipped-no-result — down-host skip :171-177 は CommandResult 自体が無い)。run_csmgrstatus が stdout str のみ返す interface も拡張が要る。ADR-0001 とは無関係 (stream 位置は変えない)。

**S8 — fib.py の next-hop selection 3 重複 collapse**: `:75-95` (compute_fib inline) / `:125-150` (_add_routes closure) / `:227-247` (_add_ecmp closure) が同一の candidate-build + sort + next_hop_ip 解決。共有 primitive へ。variation 軸は 2 つ: k-selection 規則 (top-k slice vs all-tied-minimum) と `seen` cross-call dedup (compute_fib のみ持たない)。

**S9 — adjacency-graph builder 2 重複 unify**: `viz.py:35-47` build_host_graph (sparse — 0-edge host を含まない) と `fib.py:30-47` build_graph_and_subnets (dense — 全 host pre-populate) が同じ TopologyModel.edges() walk。しかも CacheContext.host_graph は viz 経由 (`scenario_setup.py:265`) で、cache 配置の graph 出所が可視化 module になっている。TopologyModel.adjacency() 等へ一本化。注意: dense/sparse の挙動差は実在 — 統一時に 0-edge host の扱いを明示的に決めること。

**W1 — Cefore conf key=value read の単一 owner**: `cefore_conf.py:6-22` / `daemon_logs.py:23-35` / `:38-54` の同形 3 loop + `template.py:145-181` の regex 版 (計 4 実装)。read 側を cefore_conf.py の `read_conf_value(path, key, default=None)` に集約。実測 divergence: manual loop は '=' 後の最初の whitespace token、regex は行末まで — 統一時に semantics を決める。_set_config_value の扱いは P1 と同時判断。

**W2 — sub-artifact double-glob 解消**: `content_ops.py:409-414` (log 用) と `result_detect.py:66-67` (detect_sub_success) が同一 `RNP0x*.out` glob + non-empty filter。clear_sub_output_artifacts (:49) も同 glob の 3 つ目。候補6 (result_detect → Verdict 吸収) と同時に行うのが合理的。

**W3 — daemon_log_collection_enabled の 4 __init__ copy hoist**: 同一 3-line 式が disaster/connect/mesh/linear の __init__ に copy、対応 test も 4 重複。base.py の helper へ。注意: mesh/linear は run_dir を resolve しないので、constraint の実体は「raw param のうちに計算」(disaster/connect のみ resolve 前後の話)。

**W4 — cefroute_add/del/enable の boilerplate collapse**: `net_config.py:51-85` / `:154-177` / `:180-203` が verb 以外同形の 12 行 (drift 実在: add のみ非ゼロ returncode の failure logging を持つ)。verb-parametrized private helper へ。

**W5 — auto-monitor dashboard-default policy の interface 化**: `disaster.py:373-402` _start_monitoring に inline の default-target/interval 正規化を pure function へ抽出。`tests/webui/test_webui.py:89-95` が現状 6 行を手 copy ("Simulate the disaster.py auto-monitor setup") しており、抽出後は import して直接テスト。

**W6 — campaign.py/supervise.sh の job-done semantics 統一**: `supervise.sh:32` は ok/failed/skipped_memory を done 扱い、`campaign.py:303-304` _load_completed_job_ids は ok のみ — 2 プロセスが campaign 完了判定で食い違う。単純に ok-only へ寄せると deterministically-broken job で infinite-relaunch になるため、per-job give-up status の永続化とセットで `campaign.py --check-done` 等の単一判定点を作る。

**W7 — topo_fingerprint.py を MeshBuildSpec seam 経由に**: `topo_fingerprint.py:116-126` が rng→assign_roles→MeshTopo の RNG-order invariant を手写し (docstring 自身が fragility を明記)。scenario_setup.py に filesystem-free な rng-only sub-step (または provision skip flag) を作り両者が呼ぶ。

**W8 — plots.py の job-discovery layer 分離**: 1095 LOC に dataviz chrome + Job/discovery layer (:153-310、加えて _m1_jobs_by_seed/_m1_groups は fig セクション内に混在) + 10 fig_* が同居。`report.py:37` は discovery 到達のためだけに matplotlib ごと import し、underscore 4 関数 × 12 call sites が実質 interface。matplotlib-free な campaign_jobs.py へ抽出。

**P1 (保留) — template.py `_set_config_value` の underscore 解消**: cache_manager.py:8/159・forwarding.py:6/50 が外部 import 済みだが、検証側は「package 内 sibling 共有の単一 underscore は _propagate_failures と同じ通常 pattern」と減衰評価。W1 (read 側集約) と同時にだけ判断。

**P2 (保留) — campaign.py retry policy の injectable seam**: `_run_job_attempts` が _mem_available_fraction/_run_job_subprocess を hardwire、tools/ 配下は現状テストゼロ。seam 欠如がテスト不在の blocker とは未立証 — tools/ のテスト方針決定とセットで。

**候補6 — `runtime/result_detect.py` を Verdict に吸収**:
74 LOC の薄い adapter。`detect_*` 5 関数は `from_runtime_*` Verdict factory の evidence-unpacking wrapper で、CONTEXT.md の Verdict `_Avoid_` リスト ("detect result") に名前が抵触。5 関数を `src/core/verdict.py` の runtime-adapter section に移管 + `timestamp_utc` は `src/core/paths.py` 等に分離 → `result_detect.py` 削除。Worth exploring。
_Avoid_: 名前を `result_detect` のまま残すこと、Verdict factory と別モジュールに散らすこと

**R8候補 — legacy 障害サイクル (down_\*) + legacy キャッシュ設定 (cache_count) の廃止**:
2026-07-02 の R7-1 grilling で user が廃止意向を表明、behavior-preserving な OptionSpec 統合と混ぜると differential gate が無意味になるため分離した。2026-07-07 の即時fixで `down_interval`/`down_duration` の省略 default は 0/0 になり、no-failure config は暗黙 flap を起動しなくなった。残るR8決定は [ADR-0002](docs/adr/0002-failure-config-resolves-to-explicit-policy.md): bootstrap 時に `FailurePolicy` へ一度だけ解決し、legacy `down_*` OptionSpec 4つ・`periodic_host_flap`・summarizer legacy metadata・`min_failure.yaml` smoke 証拠・`cache_count`/`down_count+1` fallback を同時に整理する。追記 (2026-07-09, B1 fix 時に発見): `failure_scenarios: "none"` (文字列リテラル) は ADR-0002 が「省略と等価で許可」と定めるのに、現状 `_validate_failure_scenarios` が `'must be a dict'` で reject する — ADR 未実装ギャップ。"none" 許可は FailurePolicy 解決 (mode=none) の一部として R8 で実装すること。`down_count=5` は cache fallback の二役が残るため即時fixでは維持した。
_Avoid_: `down_count` default だけを単独で 0 化すること、legacy down_\* 廃止を cache fallback 再設計なしで進めること、min_failure の gate 証拠を代替なしで消すこと

**修正案 — `swhich_num` typo の是正 (semantic 名 `switch_limit` へ)**:
`MeshTopo(swhich_num=...)` は typo (`switch_num` が正) であるうえ、意味的には「emergent に生成される switch 数の上限」— 超過すると ValueError (`runtime/topo.py` の `switch count N exceeds limit M`)。つまり名前は綴りと意味の両方で実態とズレている。修正案 (2026-07-06, user 提案 `limit_sw_num` 系 → 採用候補 `switch_limit`): 新規コードは最初から semantic 名を使う — R9-2 の `MeshBuildSpec` は field 名 `switch_limit` を採用し、docstring で legacy kwarg `swhich_num` への対応を記す。既存 chain (config `switches:` → `args.switches` → scenario 属性 `swhich_num` → `MeshTopo(swhich_num=)`) の一括リネームは CLI/config 互換に触るため独立 housekeeping — 候補7 (topo.py リネーム) と同じ pass でまとめて行うのが合理的。
_Avoid_: 新規 interface に `swhich_num` 綴りを伝播させること、R9-2 の fold と既存 chain リネームを混ぜること

**候補7 — `runtime/topo.py` を `runtime/mesh_topo.py` にリネーム**:
`runtime/topo.py` (Mininet Topo subclasses) と `core/topology.py` (TopologyModel pure query) の名前近接 (4文字+1ディレクトリ差) が読者を混乱させる純 housekeeping。Speculative — 上記候補が片付いた後の cleanup pass で。
_Avoid_: 単独でこのリネームに取り掛かること (他の deepening が optimal の後でまとめて)

**完了 (2026-07-06) — test-gap 解消 (途中 /tdd 移行で direct test が無かったコード)**:
11 slice / 11 commit (fc6abe8..c8687e0) で +212 tests、全体 76%→89%。ゼロカバレッジだった plotter/log-cli/parsing/tee/links/topo と「spy 化で本体未実行」だった bandwidth/viz/cleanup、および monitoring lifecycle / webui state・server / CLI dispatch / base hooks / mesh・linear init 検証を direct test 化。到達不能分岐は file:line 根拠付きでテスト対象外として各テストファイルと commit message に明文化。残る意図的低カバレッジ: disaster.py 59% 等の Mininet-live 経路 (cefore-run-tests smoke が integration gate)。
_Avoid_: 到達不能と記録済みの分岐に fake-rng/import-hook で無理にテストを足すこと、Mininet-live 経路の unit test 化

**完了 (2026-07-31) — mutation testing 第1回 (`src/core/config/validator.py`, base 86f6f90)**:
mutmut 2.5.1 で 1568 mutant。raw score 58.67%→59.18% (killed 920→928、退行 0)。既存テストメソッドへの 5 パターン追加 (parametrize タプル 1 + 完全一致アサートへの狭化 4) で 8 体 kill。5 パターンは全て leave-one-out (そのパターンだけ外すと生存に戻る) を pytest 出力つきで実証、副次 3 体 (728/729/1242) は DB 差分からの推論と明記。**生存メカニズムは 2 つある: (A) 分岐そのものが未到達 — mutant 727 の `validator.py:725` は baseline で UNCOVERED、(B) 実行されているが検証が緩い — `validate_config()` の戻り値である診断文に対し、base の `test_loader.py` は部分一致 (`for e in errors`) 140 箇所 / 完全一致 (`assert ... in errors`) 11 箇所。mutmut は文字列を `XX…XX` で包むので部分一致は素通しする**。完全一致は本文だけでなく prefix 組み立て (`_validate_ccninfo_options(errors, f"events[{idx}]", ...)`) まで固定する。併せて `tests/core/test_fib.py` の `assert ... or True` (恒真＝ループ本体が無検証) を除去 — ただし残る `source != next_hop` は `test_compute_fib_no_self_routes` の `source != dest` とは**別の不変条件**なので redundant ではない。`expected_responder`/`expected_route` は狭化を見送った: src の文言 "non-empty" が実際の判定 (`.strip()`) と食い違い、`"   "` は len 3 で非 empty — 不正確な文言を契約化するとテストが誤った説明を保護する (src 修正禁止のため指摘に留めた)。`routing` バリデーション (`validator.py:1494/1496`) は UNCOVERED だが**到達可能**で、単に検証テストが無いだけ。残 640 生存は未分類 (うち 50 が uncovered 行)。**再現に必要な情報はこのエントリに集約してある** (base commit / ツール版 / runner 構成 / _Avoid_)。GitHub issue・PR 化は PAT に `issues=write`/`pull_requests=write` が無く 403 (repo は public なので可視性の問題ではない)。
_Avoid_: **mutmut 3.6.0** をこの runbook で使うこと (`record_trampoline_hit` の `assert not name.startswith("src.")` が literal `src` パッケージを拒否、かつ `--paths-to-mutate`/`--runner`/`--use-coverage`/`result-ids` が無い別方言 — 静的確認のみ、実行 TB 未採取。3.x 更新時はこの 2 点を再検証すること)、`mutmut result-ids` の出力を正規化せず `while read` に渡すこと (全 ID が 1 行スペース区切りで来るのでループが 1 回しか回らず、部分集合判定が等号で偽陽性合格する)、**キャッシュ済み** `mutmut run <id>` の status を単独の判定根拠にすること (生存する mutant に `ok_killed` を返した実測あり — fresh cache か直接 A/B で確認する)、A/B の判定を returncode だけで行うこと (**落ちたテストの node ID が期待したものか必ず突き合わせる** — 本 campaign 自身が worktree 汚染で 1046 の A アームに hop_count テストの失敗を見て誤判定しかけた)、in-place mutation を共有ツリーで走らせること (専用 detached worktree で実行する)、スコープ内テストだけの runner で得た survived を全被覆確認なしに gap として報告すること (実測で 790 件中 143 件が偽の生存者だった)、UNCOVERED であることだけを根拠に「新規テストメソッド無しでは埋められない」と結論すること (mutant 727 は UNCOVERED 行だが既存 parametrize へのケース追加だけで到達・kill できた)

**解消済み (2026-07-07) — down_\* default の「暗黙の flap 有効」即時fix**:
workshop smoke で no-failure のつもりの m1_smoke が `[flap] down h1` を発生させ、eval get が exit 1、repeat get の 5s 間隔も flap 由来の scheduler 遅延で 1s 連発に崩れる問題を実測した。即時fixとして `down_interval`/`down_duration` の OptionSpec default を 0/0 に変更し、省略 config は legacy failure manager を起動しないようにした。`down_count=5` は cache_count=0 の legacy cache fallback (`down_count + 1`) も兼ねるため default 維持。R8候補は legacy down_\* と cache_count fallback の廃止として残す。また関連の罠として、repeat 付き get は同一 host+uri だと content log が同名で上書きされ、失敗した実行のログが後続成功で消える（判定比較は results.json を使うこと）。
_Avoid_: down_count default だけを単独で 0 化すること、legacy down_\* 廃止を cache fallback 再設計なしで進めること

**発見 (2026-07-07 workshop 計測) — pubsub が 15-host mesh で系統的に失敗**:
cefpubfile/cefsubfile ペアは 3〜5 host mesh では成功するが、15h/48sw では pub が
Trigger Interest を受信できないまま deadline (lifetime+15s) で terminate する
(exit -15, stdout 0B)。sub が publisher に隣接していても再現 (m2_disaster seed401)。
同一 seed で 10/10 決定的に再現 (m1_repro seed42)。put/get は同一 topology で全成功
のため FIB/接続性の問題ではなく、pubsub の Trigger 経路固有。cefnetd は
FwdStr:flooding で起動している点も関連候補。hop距離相関 (M1 20-topology 分析): hop=1で5/5成功, hop=2で5/7, hop=3で0/8 — 距離依存を定量確認。ワークショップ計測では pubsub 行を
5-host に縮小して測定し、15-host の失敗は「エミュレータによる再現性つき問題検出」
として報告する。恒久対応は Cefore 側 pubsub の hop/スケール挙動の調査が必要。
追記 (2026-07-07 Commit 4): archived campaign artifact 全件を grep しても
Trigger-Interest retry 回数を示すラベルは存在しない (0-byte FAILURE ログ + SUCCESS
ログの固定2行のみ)。この2行 (`Send Trigger Interest.` / `Receive Trigger Data,
finish application.`) を `trigger_interest_sent`/`trigger_data_received` として
schema 化した (src/log/schema.py)。`from_log` は marker 存在時のみ pub success を
definitive True と判定するよう更新済み (src/core/verdict.py) — marker 不在側
(0-byte FAILURE ログ) の log-only 判定は依然 unknown のままで、これはログ欠損と
区別不能という構造的限界であり today の fix では解消しない。
_Avoid_: 実験 config の pubsub を無検証で 10+ hosts に置くこと

**発見 (2026-07-14 M5e 時系列実験) — 障害窓中の get 可用性は「FIB 経路上の csmgrd」で決まる**:
機構を対照実験で確定: (1) 非cacheノードは CS_MODE=0 (テンプレ既定) で一切キャッシュを
持たず、他ホストの取得は誰にも再供給されない (2) csmgrd が複製を持つのは「そのノード
自身が取得した場合」または「consumer→publisher の FIB 経路上にいて取得が通過した場合」
のみ (3) publisher 停止中に get が成功する必要十分条件 ≒ 経路上の csmgrd に複製がある
こと。flooding (FwdStr) は実質 FIB 経路のみで、経路外の csmgrd 複製は救わない。
m5a の 85〜96% の正体もこれ (5秒間隔ポーリングの直近複製が経路上に生きていた)。
オフライン再現: k_centers 配置は topo_fingerprint の隣接 + src/core/graph.select_k_centers
で実行時と完全一致 (seed 1101 で実測検証済) → per-seed の役割選定
(tools/workshop/gen_m5e_config.py) が可能になった。
failure_scenarios cycles の罠: interval は前 cycle の down 時点起点で、down 中の
target は skip される → **interval > 前 cycle の duration が必須** (でないと後続窓が
無言で消える)。
_Avoid_: 「一度取得した content は網内キャッシュに乗る」と仮定した実験設計
(非cacheノードの取得は乗らない)。cycles の interval ≤ duration。

**deferred (2026-07-27 external review) — ccninfo/monitoring known gaps**:
- `.inf` が monitoring.interval validation を通過した後 monitor thread を無限待機で殺す (pre-existing class; isfinite guard は command_timeout のみ適用済み)
- monitor の per-cycle timestamps は cycle 先頭で 1 回だけ打刻 → 後続 serial targets は stale な elapsed_sec を持つ
- webui は ccninfo monitor entries を表示しない; ccninfo を success rate に含めない
- Monitor.stop() の残余 unbounded paths: on_record callback タイムアウトなし; post-kill proc.wait(); fg cefstatus/csmgrstatus timeout=None
- dense ccninfo timeline 下の serial content worker occupancy (ccninfo ~5s/probe が content op latency を圧迫する可能性)
