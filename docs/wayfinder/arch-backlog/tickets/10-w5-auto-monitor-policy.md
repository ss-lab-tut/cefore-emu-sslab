---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W5 — auto-monitor dashboard-default policy の interface 化**: `disaster.py:319-348` _start_monitoring に inline の default-target/interval 正規化を pure function へ抽出。`tests/webui/test_webui.py:112-125` が現状 6 行を手 copy ("Simulate the disaster.py auto-monitor setup") しており、抽出後は import して直接テスト。

## Status (2026-08-23)

- 未着手。`_start_monitoring` は `disaster.py:319-348`、default targets / `setdefault("interval", 5)` の inline 正規化は :323-328 (元記述 :373-402 から更新)。
- `tests/webui/test_webui.py:112-125` の `_run_auto_monitor_logic` (def :115) が手 copy のまま (元記述 :89-95 から更新)。
