# Branch Retirement Record: `feature/test`

Date: 2026-03-04

## Decision
- Retire `feature/test` after selective salvage into the `feature/mesh` architecture.

## Salvaged
- `priority_uris` support:
  - Added URI-priority resolver and config validation/merge support.
  - Integrated priority defaults into disaster scenario put/get operation preparation.
- Flexible failure scenarios:
  - Added `failure_scenarios` config validation.
  - Added runtime failure manager supporting `simple`, `cyclic`, `random`, and `manual`.
  - Wired disaster scenario to use flexible manager when configured.
- Log graph generation:
  - Added `log-summarize --graph` output with PNG/PDF chart generation.
  - Added phase/cycle filename parsing and CSV columns for eval-cycle analysis.

## Not Salvaged
- `feature/test` structural split under `src/topo/*` and wrapper scripts tied to that layout.
- Experiment artifacts and generated data under `logs/`, `out/`, `autotest_runs/`, and image dumps.
- Broad environment-dependent behavior changes (for example large-scale IP range policy shifts).

## Notes
- Salvage was implemented as feature-level ports instead of branch merge/cherry-pick due to architecture divergence.
