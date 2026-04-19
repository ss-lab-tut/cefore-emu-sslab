# Test Matrix

## Pytest Targets

- `tests/runtime/test_cefore.py`
  Confirms the runtime wrappers build commands with `2>&1`, keep log filenames stable, and avoid passing `stderr=DEVNULL` style kwargs for the covered call sites.
- `tests/scenarios/test_disaster_pubsub.py`
  Confirms `_detect_sub_success()` handles empty directories, zero-byte files, non-zero exit codes, and discovered `RNP0x*.out` artifacts correctly.

## Smoke Configs

### `min_putget`

- File: `config/examples/min_putget.yaml`
- Expected `results.json`: one or more cycle entries
- Required checks:
  - every row has `success == true`
  - every row has `has_completed_log == true`
  - every row has `has_output_file == true`

### `min_pubsub`

- File: `config/examples/min_pubsub.yaml`
- Expected `results.json`: one or more cycle entries
- Required checks:
  - every row has `success == true`
  - every row has `has_output_file == true`
  - every row keeps `has_completed_log == false`
  - every `out_file` points at a discovered `RNP0x*.out` artifact

### `min_empty`

- File: `config/examples/min_empty.yaml`
- Expected `results.json`: empty array
- Required checks:
  - scenario exits cleanly
  - `results.json` exists
  - parsed JSON equals `[]`

### `min_mixed`

- File: `config/examples/min_mixed.yaml`
- Expected `results.json`: one or more entries per cycle for both URIs
- Required checks:
  - all entries have `success == true`
  - every row for URI `ccnx:/test/file` has `has_completed_log == true`
  - every row for URI `ccnx:/test/stream` has `has_output_file == true`
  - every row for URI `ccnx:/test/stream` keeps `has_completed_log == false`

## Helper Script

Run the bundled helper from the repository root:

```bash
rtk ./.venv/bin/python3 <skill-dir>/scripts/run_cefore_checks.py --repo-root .
```

Add `--skip-smoke` for unit-only validation.
Add `--skip-pytest` for environment smoke only.
Add `--configs ...` to narrow the smoke set.
