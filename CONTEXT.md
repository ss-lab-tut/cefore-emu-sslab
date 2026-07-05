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

**ArtifactLayout (`src/core/artifacts.py`)**:
The single owner of experiment artifact naming — every name a run writes to disk and every reader parses back. Pure stdlib module (no `src` imports, so `core`/`runtime`/`log` all import it without cycles) owning three faces: `experiment_dir_name(num, seed, timestamp=False)` (the `ex{num}_seed{label}` / `seed{label}` directory stem incl. the `seed=None→"none"` conversion and timestamp suffix; `resolve_run_dir` and autotest's directory lookup both call it — autotest's former hand-rolled glob lacked the `none` conversion), `topo_png_default_name(num, seed, hosts)` = `{dir_stem}_h{hosts}.png`, and the canonical content-log schema `content_log_name(cmd, phase, host, uri)` = `{cmd}_{phase}_h{host}_{safe_uri_label(uri)}.log` with `parse_content_log_name → ContentLogMeta | None` as its inverse (build→parse round-trip is the test surface). All writers (`content_ops._log_path`, mesh, linear) build through it; the summarizer parses through it and joins op context (`uri`/`success`/`down_hosts`/`publisher_down`) from results.json by `Path(log_file).name` — last-wins, because repeated ops with the same cmd/phase/host/URI overwrite the same log file (status quo; the surviving log matches the last record). Text-parser values win over the join where non-None (plotter semantics preserved).
Deliberate changes (2026-07-03, R7-2+R8-5): mesh/linear log filenames moved to the canonical shape (were `cefputfile_h9.log` / bare `cefputfile.log`); topo PNG default renamed from `ex{hosts}_seed{s}.png` (hosts masqueraded as experiment number) to the dir-stem form; the 5-regex legacy parser ledger (`src/log/filename.py`) deleted — old-format run dirs are no longer summarizable (use old checkouts for archaeology); CSV dropped dead columns `content_id`/`file_seed`/`get_idx`/`cycle`, gained `label`/`publisher_down`; `cefore.py` content commands require `log_name` (dead fallback names deleted); `ceforeemu-log` revived (`__main__` guard + entry-point reinstall) and proven non-empty against live smoke runs.
_Avoid_: hand-built `ex{...}_seed{...}` or `.log` name literals, regex ledgers over log filenames, re-deriving op context from filenames when results.json carries it, `src/log/filename.py` (deleted)

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
The single seam through which every config-driven CLI entry point (`ceforeemu disaster`, `ceforeemu-connect`) walks the canonical bootstrap sequence: `load_config` → legacy-key warning → parser-backed `merge_cli_and_config`（CLI が config に勝つ）→ `validate_merged_args` + raw-config debug-block validation → `resolve_run_dir` → topo_png default → meta.json（11キー、`run_dir == "."` では書かない）→ script.log Tee → `build_debug_config` → try/finally `run_fn`. `bootstrap_scenario(args, *, blocks, run_fn)` in `src/cli/bootstrap.py`; `blocks` は precedence parser を組む OPTION_SPECS CLI block 名、`run_fn(args, run_dir, log_context=, debug_config=)` が scenario runner の契約。debug block は `special_config_merge` で args に乗らないため、この seam が raw config から検証する（merged-args validation はそこに盲目）。mesh/linear は意図的に対象外 — config 非対応で seam の背後に置く behaviour が無い。
Deliberate changes (2026-07-03, R8-1): connect の precedence-inversion bug 修正（parser 無し merge で config が明示 CLI flag を上書きしていた；`merge_cli_and_config` は parser 必須に変更済み）、connect validation を post-merge に統一、connect meta.json を 11キー disaster スキーマに片寄せ（`output_dir` キー廃止 = 読者ゼロ確認済み）、main-level `run_dir.resolve()` 削除（ConnectScenario が内部 resolve）、connect が debug 収集を獲得、fib_dump/daemon_logs collector を DisasterScenario から BaseScenario へ hoist（args namespace を持たない scenario は guard で opt out）。
`tests/cli/test_bootstrap_differential.py` は HEAD 挙動を literal 捕捉した temporary migration gate — この branch の merge 後に削除すること。
_Avoid_: per-entry-point bootstrap コピー, parser 無し merge_cli_and_config, pre-merge validate_config, meta.json output_dir キー, debug_config=None hardcode

## 次回実装候補 — Architecture review backlog (2026-06-26 round)

このセクションは domain glossary ではなく、未着手の deepening candidate を次のセッションで再提案されないよう pin する backlog。`/tmp/architecture-review-20260626-165236.html` のレポート由来。完了したら該当エントリを削除し、上の domain section に正式名を追記すること。

**候補6 — `runtime/result_detect.py` を Verdict に吸収**:
74 LOC の薄い adapter。`detect_*` 5 関数は `from_runtime_*` Verdict factory の evidence-unpacking wrapper で、CONTEXT.md の Verdict `_Avoid_` リスト ("detect result") に名前が抵触。5 関数を `src/core/verdict.py` の runtime-adapter section に移管 + `timestamp_utc` は `src/core/paths.py` 等に分離 → `result_detect.py` 削除。Worth exploring。
_Avoid_: 名前を `result_detect` のまま残すこと、Verdict factory と別モジュールに散らすこと

**R8候補 — legacy 障害サイクル (down_\*) + legacy キャッシュ設定 (cache_count) の廃止**:
2026-07-02 の R7-1 grilling で user が廃止意向を表明、behavior-preserving な OptionSpec 統合と混ぜると differential gate が無意味になるため分離した。現状の依存: `min_failure.yaml` smoke（gate 自身）が down_\* で host_down/host_up cycle 証拠を生成、smoke の min_\*.yaml 全部が cache_config 無し = legacy k-centers 経路（`cache_count`/`down_count+1`）を通る。廃止するなら (1) min_failure を `failure_scenarios` へ移行 + smoke checker 期待値更新、(2) デフォルトキャッシュ方針の再設計（全 smoke config 書き換え）、(3) disaster.py の cycle code + summarizer キー削除、が同時に要る独立プロジェクト。OptionSpec 完成済みなので option 面は「spec entry 削除 + dead code 削除」に縮み、導出3面と test が機械的に追従する。
_Avoid_: OptionSpec 系 refactor と混ぜて differential gate を殺すこと、min_failure の gate 証拠を代替なしで消すこと

**候補7 — `runtime/topo.py` を `runtime/mesh_topo.py` にリネーム**:
`runtime/topo.py` (Mininet Topo subclasses) と `core/topology.py` (TopologyModel pure query) の名前近接 (4文字+1ディレクトリ差) が読者を混乱させる純 housekeeping。Speculative — 上記候補が片付いた後の cleanup pass で。
_Avoid_: 単独でこのリネームに取り掛かること (他の deepening が optimal の後でまとめて)

**完了 (2026-07-06) — test-gap 解消 (途中 /tdd 移行で direct test が無かったコード)**:
11 slice / 11 commit (fc6abe8..c8687e0) で +212 tests、全体 76%→89%。ゼロカバレッジだった plotter/log-cli/parsing/tee/links/topo と「spy 化で本体未実行」だった bandwidth/viz/cleanup、および monitoring lifecycle / webui state・server / CLI dispatch / base hooks / mesh・linear init 検証を direct test 化。到達不能分岐は file:line 根拠付きでテスト対象外として各テストファイルと commit message に明文化。残る意図的低カバレッジ: disaster.py 59% 等の Mininet-live 経路 (cefore-run-tests smoke が integration gate)。
_Avoid_: 到達不能と記録済みの分岐に fake-rng/import-hook で無理にテストを足すこと、Mininet-live 経路の unit test 化
