# Monitor stream stays outside ResultsSink

When ResultsSink was introduced as the single seam for experiment judgment records (results.json), we considered routing the Monitor's periodic observation records (monitor.json / monitor.csv) through the same sink. We decided to keep the two streams separate: ResultsSink carries judgment records only (ContentRecord / EventRecord), and Monitor keeps its own output files and webui ring-buffer channel.

## Considered Options

- **Unify into one sink and one results.json** — rejected: the streams differ in cadence (periodic observation vs event-driven judgment) and in consumers (autotest analyze, the smoke checker, and tools/autotest/run.py read results.json and would all need skip-logic for observation records), and interleaving would bloat results.json with observation noise.
- **One module, two channels** — rejected as cosmetic: it unifies code placement without unifying anything callers care about.

## Consequences

Correlating operations with daemon health still requires joining results.json and monitor.json by elapsed time. If that join becomes a recurring need, revisit this ADR.
