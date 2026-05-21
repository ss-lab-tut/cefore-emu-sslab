# Test Matrix

## Pytest Targets

- `tests/runtime/test_cefore.py`
  Confirms the runtime wrappers build commands with `2>&1`, keep log filenames stable, and avoid passing `stderr=DEVNULL` style kwargs for the covered call sites.
- `tests/scenarios/test_disaster_pubsub.py`
  Confirms `_detect_sub_success()` handles empty directories, zero-byte files, non-zero exit codes, and discovered `RNP0x*.out` artifacts correctly.

## Smoke Configs

### `min_putget`

- File: `config/examples/min_putget.yaml`
- Expected `results.json`: one or more entries (put + get rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "get"` row has `has_completed_log == true`
  - every `op_type == "get"` row has `has_output_file == true`

### `min_pubsub`

- File: `config/examples/min_pubsub.yaml`
- Expected `results.json`: one or more entries (pub + sub rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "sub"` row has `has_output_file == true`
  - every `op_type == "sub"` row keeps `has_completed_log == false`
  - every `op_type == "sub"` `out_file` points at a discovered `RNP0x*.out` artifact

### `min_pubsub_verify`

- File: `config/examples/min_pubsub_verify.yaml`
- 手動検証の自動再現: min_empty トポロジ (hosts=3, switches=6, k=2)、h0→publisher / h2→subscriber、URI `ccnx:/test/example2`
- Expected `results.json`: one or more entries (pub + sub rows)
- Required checks:
  - every row has `success == true`
  - every `op_type == "sub"` row has `has_output_file == true`
  - every `op_type == "sub"` row keeps `has_completed_log == false`
  - every `op_type == "sub"` `out_file` points at a discovered `RNP0x*.out` artifact

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
  - every `op_type == "sub"` row keeps `has_completed_log == false`

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

## Helper Script

Run the bundled helper from the repository root:

```bash
./.venv/bin/python3 <skill-dir>/scripts/run_cefore_checks.py --repo-root .
```

Add `--skip-smoke` for unit-only validation.
Add `--skip-pytest` for environment smoke only.
Add `--configs ...` to narrow the smoke set.
