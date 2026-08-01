# CI guards the unit surface only; Mininet-live paths stay with the local smoke gate

Status: accepted (2026-08-01). Workflow implemented in `.github/workflows/ci.yml`;
triggers are PR to main and push to main.

## Context

Until 2026-08 this repository had no CI at all (issue 16 §0 records the
correction: "coverage guaranteed by CI" was never true — `.github/` did not
exist). Every gate — tests, lint, types, coverage — ran only when a human ran
it. main gained branch protection on 2026-08-01, but there were no status
checks to require.

Two constraints shape what CI can guard here:

1. The end-to-end smoke evidence (cefore-run-tests) needs root + Mininet +
   Cefore binaries; a GitHub-hosted runner has none of them, and a self-hosted
   runner on a public repository would execute fork-PR code on lab hardware.
2. The unit suite is hermetic: 1493 tests in ~15 s, non-root, with mininet
   satisfied by the PyPI wheel — nothing about it needs the lab environment.

## Decision

CI guards the unit surface only: pytest + coverage, ruff check, mypy,
`uv lock --check`, and an entry-points install check. Mininet-live paths keep
their existing gate — the local, root cefore-run-tests smoke battery.

Gate semantics:

- **mypy** — zero-error gate on the *default* config (pyproject `[tool.mypy]`:
  python_version, warn_unused_ignores, `mininet.*` override). Not `--strict`
  mode (measured at 826 errors — a different debt class). No baseline/ratchet
  machinery: the pre-CI debt was small enough to repay outright (68 errors,
  38 of them missing stubs), so suppression infrastructure isn't worth owning.
  Escapes are individual `# type: ignore[code]` with a reason comment;
  `warn_unused_ignores` detects rot. Tripwire: if repayment had needed more
  than 10 ignores (a third of the real debt), the repay-first premise would
  have been wrong and the decision revisited.
- **coverage** — `fail_under=85` with `precision=2` is an *outage floor*, not
  a regression tracker: it catches wholesale coverage collapse, while local
  untested additions can hide in the aggregate (accepted; a tight 89 floor was
  considered and rejected as churn-prone — measured baseline is 89.93%).
  Every run uploads `.coverage` as a 14-day artifact: mutation campaigns
  derive their covering test set from it via
  `CoverageData.contexts_by_lineno()` (the reproduction path issue 16
  documents), and issue 16 warns that set goes stale as tests move.
  Implementation-time finding: a `show_contexts` cov.json of the same data
  measured 142 MB, so CI uploads only the SQLite data file — the contexts
  live there, and `relative_files=true` keeps it portable off-runner.
- **uv discipline** — every job runs `uv lock --check`, then
  `uv sync --locked`, then `uv run --no-sync`. A bare `uv run` auto-locks and
  auto-syncs, which would self-heal a stale lock and defeat the lock gate.
  uv itself is pinned (0.10.11) so the toolchain cannot drift away from local
  measurements. Actions are pinned by floating major tag where the publisher
  maintains one (checkout@v7, upload-artifact@v7 — verified to exist);
  setup-uv publishes no floating major tag, so it is pinned to the exact
  version tag (v9.0.0). Full SHA pinning declined as maintenance the repo
  doesn't need yet (trusted publishers only).
- **packaging** — `uv sync` never installs the project itself (virtual
  project), so `[project.scripts]` breakage is invisible to the unit suite;
  the job does an editable install and requires exit code 0 from each CLI's
  `--help` (help text itself is not a contract).

Branch protection: the four job names (test / lint / typecheck / packaging)
become required checks, with up-to-date-before-merge (strict) on and no merge
queue (adding one would require a `merge_group` trigger the workflow does not
have). Bootstrap exception, recorded once: the debt-payoff PR merged before
the workflow existed, and the workflow PR itself could not be required at its
own merge time — both were covered by local evidence plus external review
instead.

## Consequences

- A PR can be green while breaking a Mininet-live path; the smoke battery
  remains the gate for that class and runs outside CI. The
  hosted-runner-smoke prototype (Cefore source build + one min_putget run) is
  future work — if it proves out, it joins as a non-required job.
- Rejected alternatives, so they are not re-proposed: self-hosted runner
  (fork-PR code execution on lab hardware), `ruff format` gate (54-file
  reformat + blame noise, revisitable), routing CI through
  run_cefore_checks.py (it is the smoke-inclusive local judge; CI steps stay
  single-purpose commands), mypy baseline/ratchet (see above), `--strict`
  mode, merge queue, tight coverage floor 89.
- config/examples schema validation lives as a pytest test
  (tests/core/config/test_example_configs.py), so it runs identically in CI
  and in the local runner's pytest phase; its oracle is raw parse +
  validate_config acceptance only — it does not replace the smoke battery.
