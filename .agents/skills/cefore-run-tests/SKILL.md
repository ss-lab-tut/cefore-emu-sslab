---
name: cefore-run-tests
description: Run the CeforeEmu regression checks — the full unit pytest suite (root/env-gated tests auto-skip), plus minimal end-to-end `src disaster --config ... --no-cli` smoke runs with `config/examples/min_putget.yaml`, `min_putget_class_a.yaml` (Class A 10.0.0.0/16 addressing — guards the ifconfig classful-netmask bug), `min_pubsub.yaml`, `min_pubsub_verify.yaml`, `min_empty.yaml`, `min_mixed.yaml`, `min_event_putget.yaml`, `min_event_pubsub.yaml`, `min_failure.yaml` (host_down/host_up cycle evidence), `min_event_link.yaml` (link_down/link_up outcome records), and `min_monitoring.yaml` (monitor.json), and `min_compute.yaml` (compute_call tri-state: unreachable endpoint records outcome=skipped-no-result), plus a `connect` ConnectScenario (ceforeemu-connect) plain-mesh smoke run. Use when Codex needs to validate recent code changes, reproduce a failing test, or sanity-check this repository before or after edits.
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

- `tests/` — the full unit suite (the integration placeholder and the
  root/env-gated synthetic tests skip themselves without root)
- `config/examples/min_putget.yaml`
- `config/examples/min_putget_class_a.yaml` (Class A 10.0.0.0/16 — guards the ifconfig classful-netmask regression)
- `config/examples/min_pubsub.yaml`
- `config/examples/min_pubsub_verify.yaml`
- `config/examples/min_empty.yaml`
- `config/examples/min_mixed.yaml`
- `config/examples/min_event_putget.yaml`
- `config/examples/min_event_pubsub.yaml`
- `config/examples/min_compute.yaml` (compute_call tri-state: guaranteed-unreachable TEST-NET-3 endpoint must record `outcome=skipped-no-result`)
- `connect` — ConnectScenario plain-mesh run (`ceforeemu-connect`, no config)

The disaster smoke configs validate `results.json` contents after each run instead of only trusting exit codes. The `connect` case is different: ConnectScenario (`ceforeemu-connect`) has no `--results-json` and writes no `results.json`, so it is validated by exit 0 plus the topology PNG that proves the configure stage completed (mesh built, daemons started, FIB applied). It is run via `python -c "from src.runtime.external_net import main; main()" --hosts 3 --switches 2 --seed 42 --no-cli --no-script-log` because `ceforeemu-connect` is only registered as a console script after `pip install -e .`. Expected result shapes are summarized in `references/test-matrix.md`.

Disaster content configs that opt in also run `python -m src.log.cli <run_dir> --stdout` and require non-empty canonical-parse CSV output with `label` and `success` columns. 2026-07-03 artifact-layout: this guards the writer/parser filename drift class that previously left `ceforeemu-log` dead for disaster logs.

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
