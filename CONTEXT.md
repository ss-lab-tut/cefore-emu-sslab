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
Constructed through `build_fleet(net, host_num, csmgrd_host_ids, run_dir, *, cefnetd_timeout, readiness_policy)` (same module): the single place that derives node names, the `csmgrd_nodes` set, and `log_dir`. Every scenario's `configure` and its `teardown` fallback go through it, so the fallback no longer drops `csmgrd_nodes`. A constructor for the seam above, not a separate seam.
_Avoid_: daemon loops, start/stop loops, started_csmgrd_hosts, inline fleet construction

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

## Scheduling

**EventSchema**:
The canonical, pure-data description of each scheduler/config event type. `EVENT_SCHEMA` maps a type name to an `EventSpec` carrying its `required_fields`, `is_content` flag, and same-time `priority`. Lives in `src/core/events.py`; intentionally pure (dataclass + constant, no `runtime` import) so both the config validator (`core`) and the scheduler (`runtime`) import it without breaking the core→runtime layering. Insertion order is load-bearing — `event_types()` derives the validator's valid-type tuple and the "must be one of: …" error order from it.
Binding is asymmetric, by design: the config validator's missing-field checks are **bound** to `required_fields` (for `fib_*`/`compute_call`/`put`/`pubsub_pub`/`get`/`pubsub_sub`; `link_down`/`link_up`/`bw_set` keep their existing shape checks), and the scheduler derives `_EVENT_PRIORITY`/`_CONTENT_EVENT_TYPES` from it. The scheduler/content-runner handlers' field access (`ev["host"]`, `ev["prefix"]`, …) is **documented by convention** against `required_fields`, not mechanically enforced — so the schema⇄handler drift class is concentrated to one place to read, not eliminated. The publisher set (`is_publication=True` → `publication_event_types()`) is bound for `scenarios/disaster.py` and `scenarios/connect.py` publisher-metadata builders and for `loader.py`'s publication-validation branch, so the loader / scheduler / content_ops / scenarios quadrangle is now drift-free.
`ContentOperationRunner._HANDLERS` in `src/runtime/content_ops.py` maps each content event type name to its handler method name (`"put"→"_do_put"` etc.); an import-time `assert set(_HANDLERS) == content_event_types()` locks the dispatch table to EventSchema so drift is caught at module load, not at runtime.
_Avoid_: `valid_event_types` literal, `_EVENT_PRIORITY`/`_CONTENT_EVENT_TYPES` literals, per-type required-field literals, `("put", "pubsub_pub")` tuple literal, "event type table", if/elif dispatch in content_ops

**extract_publications**:
The single owner of "which events introduce content into the network and who publishes them". Pure function in `src/core/events.py`: `extract_publications(events: list[dict]) → (publications, publishers_dict, publisher_ids)` where `publications` is the filtered list, `publishers_dict` is `{uri: host_idx}`, and `publisher_ids` is `frozenset[int]` (integer host indices, matching `ScenarioSetupSpec.publisher_ids: set[int]`). Both `DisasterScenario` and `ConnectScenario` derive their publisher state from it; `runtime/external_net.py` re-exports it as the public surface.
_Avoid_: `_prepare_event_publishers` (removed), `_publication_metadata` (removed), per-scenario iteration over `publication_event_types()`

## Scenario setup

**ScenarioSetupSpec**:
The policy bundle a scenario hands to the setup seam. Carries the topology snapshot (`mesh_links`, `scheme`, `host_count`, `publisher_ids`), the chosen `CacheStrategy`, fleet options (`fleet_run_dir`, `fleet_cefnetd_timeout`, `fleet_readiness_policy`), FIB inputs (`fib_k`, `fib_strategy`, `fib_uri_publishers`), optional bridges/bw/ext/PNG. Lives in `src/runtime/scenario_setup.py`; ordering is owned by the seam, not by spec fields.
_Avoid_: per-scenario setup recipes, configure() copy-paste

**TeardownSpec / TeardownResult / teardown_scenario**:
The teardown-side seam symmetric with `setup_scenario`, living beside it in `src/runtime/scenario_setup.py`. `teardown_scenario(net, spec) -> TeardownResult` runs `fleet.stop_all()` → `bridge_manager.cleanup()` when present → `cleanup_external_bridges()` only when `spec.cleanup_external_bridges` opts in (currently disaster only). All four scenarios call it from `teardown()` and propagate non-empty `result.failures` through `_propagate_failures(None, result.failures)`, normalizing the old mesh/linear silent-discard behavior.
_Avoid_: per-scenario teardown boilerplate, reintroducing mesh/linear silent-discard behavior

**setup_scenario / SetupResult**:
The single seam through which every scenario's network configuration walks the canonical order: `apply_ip_addr` → bridges → ifconfig log → bw → ext → render_png → cache_strategy.place → build_fleet + start + wait_ready → apply_fib → cefstatus + print_mesh_links. Returns `SetupResult(daemon_fleet, cache_node_set, fib_routes)` so the scenario can wire them back into `self.daemon_fleet` / `self.cache_node_set` / `self._fib_routes` for downstream (monitoring, webui, FIB-restore). All three scenarios (disaster, connect, mesh) use it; pre-canonical drift (connect's bw/ext-after-everything, mesh/connect `time.sleep(1)`, mesh debug print) was removed once smoke 12/12 confirmed it carried no semantic load.
_Avoid_: per-scenario IP/bridge/cache/fleet/FIB sequencing, ordering knobs

**CacheStrategy**:
Polymorphic decision module for "which hosts run csmgrd as cache nodes". One protocol `place(ctx: CacheContext) -> set[int]` with three real adapters in `src/runtime/cache_strategy.py`: `KCentersStrategy` (graph/manual/degree_based via CachePlacement; disaster + connect use it, connect with `exclude_publishers=False`), `RandomCSModeStrategy` (per-host random CS_MODE 0/1/2 with `apply_cs_modes` side effect; disaster's `cache_config.strategy="random"`), `RolesCacheStrategy` (csmgrd hosts from `assign_roles`; mesh). The scenario picks one; setup_scenario calls `.place()` polymorphically. `CacheContext` is the immutable snapshot (`host_count`, `host_graph`, `publisher_ids`) every adapter reads from.
_Avoid_: cache strategy branching in scenarios, `_configure_cache_nodes`, inline `assign_random_cs_modes` calls

## Configuration

**ConfigValidator**:
The single owner of every config-validation rule. Lives in `src/core/config/validator.py`; pure-fn module composed of per-block validators (`_validate_flat_keys` over `_FLAT_SPECS`, `_validate_cache_config`, `_validate_failure_scenarios`, `_validate_bridges`, `_validate_events`) and the public `validate_config(config) → list[str]` / `validate_merged_args(args) → list[str]` entries. The loader (`src/core/config/loader.py`) shrinks to I/O (`load_config`, YAML/JSON), legacy-key warning (`warn_ignored_legacy_content_keys`), and CLI/config merge (`merge_cli_and_config`); it re-exports `_FLAT_SPECS`, `validate_config`, `validate_merged_args` so external import sites (`runtime/external_net`, `cli/main`, `tools/autotest`, `tests/core/config`) stay stable. Event-type missing-field checks bind to `EVENT_SCHEMA[etype].required_fields` (the EventSchema scope's loader edge); error append order and message strings are mechanically preserved across the extraction (verified by 137 tests + a HEAD-vs-new differential test over 6 cross-block malformed configs, 38 error strings byte-identical).
_Avoid_: validation rules in loader.py, per-block hand-rolled if/elif chains, duplicate event-type required-field lists, splitting `_FLAT_SPECS` from the validator

## 次回実装候補 — Architecture review backlog (2026-06-26 round)

このセクションは domain glossary ではなく、未着手の deepening candidate を次のセッションで再提案されないよう pin する backlog。`/tmp/architecture-review-20260626-165236.html` のレポート由来。完了したら該当エントリを削除し、上の domain section に正式名を追記すること。

**候補2 — `runtime/bridge.py` を3 module に split**:
1240 LOC の god-module が3つの独立 interface (external-NIC attach + 取消し用 state machine / `BridgeManager` root-namespace + NAT/proxy-ARP / `parse_bridge_args` 純 data) を同居させている。`bridge_external.py` / `bridge_root.py` / `bridge_args.py` に分割。Strong。memory `gate-bug-discovery` の候補3 (cleanup 二台帳統合) とは別角度 — こちらは「split-by-concern」、候補3 は「ledger 統一」。
_Avoid_: cleanup-only 統一に絞ること (interface 3つ同居問題が残る)

**候補6 — `runtime/result_detect.py` を Verdict に吸収**:
74 LOC の薄い adapter。`detect_*` 5 関数は `from_runtime_*` Verdict factory の evidence-unpacking wrapper で、CONTEXT.md の Verdict `_Avoid_` リスト ("detect result") に名前が抵触。5 関数を `src/core/verdict.py` の runtime-adapter section に移管 + `timestamp_utc` は `src/core/paths.py` 等に分離 → `result_detect.py` 削除。Worth exploring。
_Avoid_: 名前を `result_detect` のまま残すこと、Verdict factory と別モジュールに散らすこと

**候補7 — `runtime/topo.py` を `runtime/mesh_topo.py` にリネーム**:
`runtime/topo.py` (Mininet Topo subclasses) と `core/topology.py` (TopologyModel pure query) の名前近接 (4文字+1ディレクトリ差) が読者を混乱させる純 housekeeping。Speculative — 上記候補が片付いた後の cleanup pass で。
_Avoid_: 単独でこのリネームに取り掛かること (他の deepening が optimal の後でまとめて)
