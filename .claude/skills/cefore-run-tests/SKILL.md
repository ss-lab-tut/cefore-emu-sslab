---
name: cefore-run-tests
description: Run the CeforeEmu regression checks that cover runtime wrapper logging behavior and disaster pub/sub success detection, plus minimal end-to-end `src disaster --config ... --no-cli` smoke runs with `config/examples/min_putget.yaml`, `min_pubsub.yaml`, `min_pubsub_verify.yaml`, `min_empty.yaml`, `min_mixed.yaml`, `min_event_putget.yaml`, and `min_event_pubsub.yaml`. Use when Codex needs to validate recent code changes, reproduce a failing test, or sanity-check this repository before or after edits.
---

# Cefore Run Tests

## Overview

Use this skill to run the narrow pytest suite and the config-driven smoke checks together. Prefer the bundled script instead of rebuilding commands by hand.

## Workflow

1. Work from the repository root or pass `--repo-root`.
2. Use the repo venv interpreter and keep ad hoc shell commands prefixed with `rtk`, because this repository requires it.
3. Run the bundled helper from the active skill directory. For the repo-local copy:

```bash
./.venv/bin/python3 .claude/skills/cefore-run-tests/scripts/run_cefore_checks.py --repo-root .
```

For the home-skill copy:

```bash
./.venv/bin/python3 ~/.codex/skills/cefore-run-tests/scripts/run_cefore_checks.py --repo-root .
```

4. Use focused modes when needed. Replace the script path with the copy you are using:

```bash
./.venv/bin/python3 <skill-dir>/scripts/run_cefore_checks.py --repo-root . --skip-smoke
./.venv/bin/python3 <skill-dir>/scripts/run_cefore_checks.py --repo-root . --skip-pytest
./.venv/bin/python3 <skill-dir>/scripts/run_cefore_checks.py --repo-root . --configs min_pubsub min_mixed
```

## What The Script Verifies

- `tests/runtime/test_cefore.py`
- `tests/scenarios/test_disaster_pubsub.py`
- `config/examples/min_putget.yaml`
- `config/examples/min_pubsub.yaml`
- `config/examples/min_pubsub_verify.yaml`
- `config/examples/min_empty.yaml`
- `config/examples/min_mixed.yaml`
- `config/examples/min_event_putget.yaml`
- `config/examples/min_event_pubsub.yaml`

The smoke phase validates `results.json` contents after each run instead of only trusting exit codes. Expected result shapes are summarized in `references/test-matrix.md`.

## Failure Handling

If pytest fails, stop and report the failing test names.

If smoke fails before the scenario starts, check these prerequisites and report which one is missing:

- `sudo -n` access
- Cefore commands installed on the machine
- Mininet available to the selected interpreter
- `sample-putfile` present at the repo root

If a smoke run completes but validation fails, include:

- the config name
- the command that was run
- the artifact base directory printed by the helper
- the parsed `results.json` mismatch

## Sandbox & Privileges

If you are running under the Claude Code sandbox, mind these constraints:

- **The smoke phase requires the sandbox to be OFF.** It launches Mininet as root via `sudo -n`, but the sandbox sets the `no_new_privs` flag, which blocks `sudo` from becoming root. Run smoke with the sandbox disabled. The pytest phase needs no privileges and runs fine under the sandbox.
- **Default output base now honors `$TMPDIR`.** Under the sandbox, `/tmp` is not writable, so the default lands in `$TMPDIR` (e.g. `/tmp/claude-xxxx`) and pytest-only runs with no extra flags. Only on the rare environment where `$TMPDIR` is unset, pass `--output-base "${TMPDIR:?}/cefore-run-tests"`. Do not pass a bare `/tmp/...` path to `--output-base` under the sandbox — it is not writable.
- **The helper runs `sudo -n mn -c` automatically** before the smoke phase and after each config (best-effort, non-fatal). You do not need to run `mn -c` by hand between configs.

## Notes

Use `--output-base /tmp/some-dir` to control where smoke artifacts land.

Use `--cleanup` only when the run passed and you do not need logs afterward. Smoke artifacts are created via `sudo`, so they are root-owned; `--cleanup` (a non-root `shutil.rmtree`) may fail to remove them — run `sudo rm -rf <output-base>` if needed.

Read `references/test-matrix.md` when you need the exact expected outcomes for each config.
