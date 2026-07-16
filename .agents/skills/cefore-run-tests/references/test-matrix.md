# Test Matrix

## Pytest Targets

- `tests/` — the full unit suite. No root needed: `tests/integration/test_smoke.py`
  is a self-skipping placeholder and `tests/synthetic/` skips unless
  `CEFEMU_SYNTHETIC_ROOT=1` and running as root.
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

### `min_monitoring`

- File: `config/examples/min_monitoring.yaml`
- monitoring (cefstatus 収集) の gate 検証。
- Expected: results.json (put + get rows) に加え、case output 配下に
  `monitor.json`（Monitor.stop() 時に書き出される収集記録）
- Required checks:
  - every row has `success == true`
  - `monitor.json` exists with at least 1 entry

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
