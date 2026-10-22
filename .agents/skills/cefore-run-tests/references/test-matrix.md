# Test Matrix

## Pytest Targets

- `tests/` — the full unit suite. No root needed: `tests/integration/test_smoke.py`
  is a self-skipping placeholder and `tests/synthetic/` skips unless
  `CEFEMU_SYNTHETIC_ROOT=1` and running as root.
  `tests/synthetic/test_compute_ok_path_synthetic.py` (and `_hpc.py`, which also needs
  `CEFEMU_COMPUTE_ENDPOINT`) are the compute_call ok-path product tests; the script never
  runs them (see SKILL.md "Optional step").
  Notable coverage includes the runtime wrapper logging behavior
  (`tests/runtime/test_cefore.py`) and disaster pub/sub success detection
  (`tests/scenarios/test_disaster_pubsub.py`) that the gate previously ran in
  isolation.

## Smoke Configs

### `min_putget`

- File: `config/examples/min_putget.yaml`
- Expected `results.json`: one or more entries (put + get rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "get"` row has `has_completed_log == true`
  - every `op_type == "get"` row has `has_output_file == true`
  - `python -m src.log.cli <run_dir> --stdout` emits at least 2 canonical CSV rows with `label` and `success` columns, and at least one command section matches an `op_type` present in `results.json`

### `min_putget_class_a`

- File: `config/examples/min_putget_class_a.yaml`
- Same put/get topology as `min_putget` but on a Class A network
  (`addressing.network_cidr: 10.0.0.0/16`).
- Regression guard for the `ifconfig` classful-default-netmask bug: a bare
  `ifconfig <iface> 10.0.x.y` gets `/8` (class A default), collapsing every
  interface onto one flat `10.0.0.0/8` and breaking per-link routing so get
  times out with `Rx Frames = 0`. `min_putget` (192.168) cannot catch this
  because class C defaults to `/24`.
- Required checks: identical to the `min_putget` results.json checks (`PUTGET_EXPECT`).

### `min_pubsub`

- File: `config/examples/min_pubsub.yaml`
- Expected `results.json`: one or more entries (pub + sub rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "sub"` row has `has_output_file == true`
  - every `op_type == "sub"` row keeps `has_completed_log` falsy (`null`: the marker Factor is not applicable to sub)
  - every `op_type == "sub"` `out_file` points at a discovered `RNP0x*.out` artifact

### `min_pubsub_verify`

- File: `config/examples/min_pubsub_verify.yaml`
- 手動検証の自動再現: min_empty トポロジ (hosts=3, switches=6, k=2)、h0→publisher / h2→subscriber、URI `ccnx:/test/example2`
- Expected `results.json`: one or more entries (pub + sub rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "sub"` row has `has_output_file == true`
  - every `op_type == "sub"` row keeps `has_completed_log` falsy (`null`: the marker Factor is not applicable to sub)
  - every `op_type == "sub"` `out_file` points at a discovered `RNP0x*.out` artifact
  - `python -m src.log.cli <run_dir> --stdout` emits at least 2 canonical CSV rows with `label` and `success` columns, and at least one command section matches an `op_type` present in `results.json`

### `min_empty`

- File: `config/examples/min_empty.yaml`
- Expected `results.json`: empty array
- Required checks:
  - scenario exits cleanly
  - `results.json` exists
  - parsed JSON equals `[]`

### `min_mixed`

- File: `config/examples/min_mixed.yaml`
- Expected `results.json`: one or more entries (put + get + pub + sub rows)
- Required checks:
  - all entries have `success == true`
  - every `op_type == "get"` row has `has_completed_log == true`
  - every `op_type == "sub"` row has `has_output_file == true`
  - every `op_type == "sub"` row keeps `has_completed_log` falsy (`null`: the marker Factor is not applicable to sub)

### `min_event_putget`

- File: `config/examples/min_event_putget.yaml`
- イベント指定 put/get の最小サンプル: events セクションで時刻を指定して put (at=5) / get (at=15) を実行
- Expected `results.json`: one or more entries (put + get rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "get"` row has `has_completed_log == true`
  - every `op_type == "get"` row has `has_output_file == true`

### `min_event_pubsub`

- File: `config/examples/min_event_pubsub.yaml`
- イベント指定 pub/sub の最小サンプル: events セクションで時刻を指定して pubsub_sub / pubsub_pub (at=10) を実行
- Expected `results.json`: one or more entries (pub + sub rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "sub"` row has `has_output_file == true`
  - every `op_type == "sub"` `out_file` points at a discovered `RNP0x*.out` artifact

### `min_failure`

- File: `config/examples/min_failure.yaml`
- 障害サイクル (legacy --down-* 相当) の outcome record 証拠。publisher (h2) は自動除外、
  h0 は down_exclude で除外 → h1 が flap する。
- Expected `results.json`: put row + `op_type == "event"` の host_down/host_up rows
- Required checks (cycle evidence only — content rows are NOT gated because gets
  during a failure window may legitimately fail):
  - at least 1 `event_type == "host_down"` and 1 `event_type == "host_up"` record
  - every event record has `success == true`

### `min_event_link`

- File: `config/examples/min_event_link.yaml`
- link_down/link_up イベントの outcome record + 復旧後 get。seed=42 トポロジの
  h1-h2 リンク（get 経路 h0→s1→h2 に影響しない側）を down/up する。
- Expected `results.json`: put + get rows + link_down/link_up event rows
- Required checks:
  - every row has `success == true`（イベント失敗も gate で検出される）
  - at least 1 `link_down` and 1 `link_up` event record
  - every `op_type == "get"` row has `has_completed_log == true` and
    `has_output_file == true`

### `min_explicit_line`

- File: `config/examples/min_explicit_line.yaml`
- 明示トポロジ (`links: [[0,1],[1,2]]`) による 3 ホスト直線。`link_down`/
  `link_up [1, 2]` は h0→h2 の唯一の経路そのものを切る (min_event_link の
  h1-h2 とは違い get 経路に乗る)。before/during/after という3つの URI に
  分け、各フェーズで切断前に一度も取得していない新規コンテンツを使うことで、
  「事前キャッシュから返った」では説明できない成功/失敗だけを要求する。
- Expected `results.json`: put + get rows (3 pairs) + link_down/link_up
  event rows
- Required checks:
  - every event record (`link_down`/`link_up`) has `success == true`
  - every `op_type == "put"` row has `success == true` (failed なら後続の
    get が「経路ではなく put 自体の失敗」で ok/ng になり、以下の
    get_outcomes が別の理由で成立してしまう)
  - `ccnx:/test/explicitline/before` get row has `success == true`
    (切断前: 経路が動くことの前提確認)
  - `ccnx:/test/explicitline/during` get row has `success == false`
    (切断中に初めて要求する URI なので、失敗がキャッシュでは説明できない)
  - `ccnx:/test/explicitline/after` get row has `success == true`
    (復旧後に初めて put/get する URI なので、成功が事前キャッシュでは説明
    できず、復旧したリンクを実際に通ったことの証拠になる)
  - NOT gated by a blanket `all_success` (the `during` row is expected to
    fail by design)

### `min_prefix_routes`

- File: `config/examples/min_prefix_routes.yaml`
- `prefix_routes: {<ccnx prefix>: <host index>}` is a static prefix-to-host
  FIB route announcement fed into `core.fib.compute_fib_for_uris`,
  independent of any put/pubsub_pub publisher. 3-host line
  (`links: [[0,1],[1,2]]`), two entries (`to-h2` to host 2, `to-h0` to host
  0), plus a put (h2) / get (h0) pair on an unrelated URI so
  `self.uri_publishers` is also non-empty (proving prefix_routes still
  lands in the FIB alongside it, the requirement this config exists to
  pin). `debug: {artifacts: [fib_dump]}` captures each host's `cefstatus`
  output to `debug/fib/fib_hN.txt`. `cefroute add`'s own `script.log` line
  only proves the command was issued, not that cefnetd installed it, so
  the dump is the only real evidence.
- Expected `results.json`: put + get rows (same shape as `min_putget`)
- Required checks:
  - every row has `success == true`, every `get` row has
    `has_completed_log == true` and `has_output_file == true`
  - `fib_dump` (`require`): `fib_h0.txt`'s FIB section contains
    `ccnx:/test/prefixroutes/to-h2`; `fib_h1.txt`'s contains both
    `to-h2` and `to-h0`; `fib_h2.txt`'s contains `to-h0`
  - `fib_dump` (`forbid`): `fib_h2.txt` does NOT contain `to-h2` and
    `fib_h0.txt` does NOT contain `to-h0`. A route announcement is
    one-directional (every OTHER host routes toward the named one), so the
    named host itself must never get a FIB entry for its own prefix

### `min_monitoring`

- File: `config/examples/min_monitoring.yaml`
- monitoring (cefstatus 収集) の gate 検証。
- Expected: results.json (put + get rows) に加え、case output 配下に
  `monitor.json`（Monitor.stop() 時に書き出される収集記録）
- Required checks:
  - every row has `success == true`
  - `monitor.json` exists with at least 1 entry

### `min_ccninfo`

- File: `config/examples/min_ccninfo.yaml`
- ccninfo (path/cache trace) の最小検証。originator (h1) は CS_MODE=0 (Bug2 回避)。
  cache_count=1 で h0 のみキャッシュノード。NODE_NAME 注入でトークンはノード名。
- Expected `results.json`: put + get + ccninfo rows
- Required checks:
  - every row has `success == true`
  - at least 1 `op_type == "ccninfo"` row
  - every ccninfo row has `reply_received == true`, `responder_matched == true`,
    `route_matched == true`
  - `monitor.json` exists with at least 1 entry of `type == "ccninfo"`
  - every ccninfo monitor entry has `output.parsed.reply_received == true`
    and `output.timed_out == false`

### `min_compute`

- File: `config/examples/min_compute.yaml`
- compute_call の tri-state outcome 検証。autotest mode は ext/bridges を禁止する
  ため外部経路が存在せず、TEST-NET-3 (203.0.113.1) 宛の curl は必ず接続失敗する
  （到達不能の実保証は RFC 5737 そのものではなく、この topology isolation）。
- Expected `results.json`: compute_call event row（success == false は仕様どおり）
- Required checks:
  - at least 1 `compute_call` event record
  - every `compute_call` record has `outcome == "skipped-no-result"`
    （環境要因が実験失敗 not-ok と区別されること — tri-state seam の回帰ガード）

### `min_host_apps`

- File: `config/examples/min_host_apps.yaml`
- host_apps: one process per host (`sh -c "echo {node} {t0_ms} > {node_dir}/host_app_marker; exec sleep 1000"`), started after cefnetd/csmgrd and stopped before teardown. No content operations run, so this is a lifecycle/placeholder check, not a put/get check.
- Expected `results.json`: empty array (same shape as `min_empty`).
- Required checks:
  - parsed `results.json` equals `[]`
  - `debug/node_dirs/h{0,1,2}/host_app_marker` all exist (via `debug.artifacts: node_dirs`, which is what keeps the marker files around after teardown deletes the live `hN/` working directories)
  - each marker's content is exactly `"hN <t0_ms>"`, with its own node name (catches a mix-up where every host wrote to the same file)
  - all three markers carry the identical `<t0_ms>` value (the regression this case guards: host apps must receive the same t0 the scheduler's `"at: 0"` origin uses, not each reading its own clock)

### `min_host_app_restart`

- File: `config/examples/min_host_app_restart.yaml`
- A 3-host line (`links`), one `host_apps` entry covering every host
  (`sh -c "echo {node} {t0_ms} $$ >> {node_dir}/host_app_marker; exec sleep 1000"`),
  and one `host_app_restart` event (`host: 1, downtime_s: 2`) that stops and
  restarts only h1's process. `host_app_restart` is a non-`put` event, so it
  runs in autotest's eval phase, same as `link_down`/`link_up`.
- Expected `results.json`: one `host_app_restart` event record with
  `success == true` (the content-free rows, like `min_host_apps`).
- Required checks:
  - at least 1 `host_app_restart` event record, and every event record
    (there is only the one) has `success == true`
  - `debug/node_dirs/h{0,1,2}/host_app_marker` (via `debug.artifacts:
    node_dirs`): h1 has exactly 2 lines (one per life), h0/h2 exactly 1
    (never restarted)
  - every line's node name and `t0_ms` match `hN`/the shared origin, same
    as `min_host_apps`
  - h1's two lines carry two DIFFERENT pids (the only direct evidence that
    `HostAppFleet.restart_host()` started a second OS process, rather than
    being a no-op that left the first life's single line alone)
  - the host_apps entry also carries `log: "{node_dir}/{node}.log"`, and
    `debug/node_dirs/h{0,1,2}/` must show: h1 both `h1.log` (life 1) and
    `h1.log.life2` (life 2), h0/h2 only their own `hN.log` (never a
    `.life2`) -- live proof of `_life_log()`'s per-life suffixing
    (host_apps.py), which was previously unit-tested only

### `connect`

- Path: ConnectScenario via `ceforeemu-connect` (no config file). The helper runs
  it as `python -c "from src.runtime.external_net import main; main()" --hosts 3
  --switches 2 --seed 42 --no-cli --no-script-log` because the console script is
  only registered after `pip install -e .`.
- Plain mesh: no bridges/ext, no events, so no external infrastructure is needed
  and `run_experiment()` publication seeding is a no-op.
- Expected output: no `results.json` (connect has no `--results-json`); a topology
  PNG under the case output directory.
- Required checks:
  - scenario exits 0 (exercises the ConnectScenario lifecycle through
    `BaseScenario.execute`: build → configure → teardown → `cleanup_all`)
  - at least one `*.png` exists (proves the configure stage reached visualization)
  - no `results.json` is produced (guards against connect silently gaining
    autotest output)

## Helper Script

Run the bundled helper from the repository root:

```bash
./.venv/bin/python3 <skill-dir>/scripts/run_cefore_checks.py --repo-root .
```

Add `--skip-smoke` for unit-only validation.
Add `--skip-pytest` for environment smoke only.
Add `--configs ...` to narrow the smoke set.
