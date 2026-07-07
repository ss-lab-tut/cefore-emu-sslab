# Monitor stream stays outside ResultsSink

When ResultsSink was introduced as the single seam for experiment judgment records (results.json), we considered routing the Monitor's periodic observation records (monitor.json / monitor.csv) through the same sink. We decided to keep the two streams separate: ResultsSink carries judgment records only (ContentRecord / EventRecord), and Monitor keeps its own output files (monitor.json / monitor.csv) plus a live webui feed of host status.

Note (2026-07-07): the webui side of that feed originally accumulated into a `DashboardState._monitor_records` ring buffer (`MAX_MONITOR` capacity). It was removed because no production code ever read it — `snapshot()` never touched it and no server/asset route exposed it, so deleting it changed zero observable behavior. `record_monitor()` itself is unchanged: it still updates each host's last-known cefstatus/csmgrstatus fields, which `snapshot()` does read. The separation decision above (Monitor stays outside ResultsSink) is unaffected by this cleanup. If a history/audit view of raw monitor records is ever needed, resurrect the buffer together with a real consuming route (an endpoint or webui panel) rather than reintroducing a write-only accumulator.

## Considered Options

- **Unify into one sink and one results.json** — rejected: the streams differ in cadence (periodic observation vs event-driven judgment) and in consumers (autotest analyze, the smoke checker, and tools/autotest/run.py read results.json and would all need skip-logic for observation records), and interleaving would bloat results.json with observation noise.
- **One module, two channels** — rejected as cosmetic: it unifies code placement without unifying anything callers care about.

## Consequences

Correlating operations with daemon health still requires joining results.json and monitor.json by elapsed time. If that join becomes a recurring need, revisit this ADR.
