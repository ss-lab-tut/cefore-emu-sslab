---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**deferred (2026-07-27 external review) — ccninfo/monitoring known gaps**:
- `.inf` が monitoring.interval validation を通過した後 monitor thread を無限待機で殺す (pre-existing class; isfinite guard は command_timeout のみ適用済み)
- monitor の per-cycle timestamps は cycle 先頭で 1 回だけ打刻 → 後続 serial targets は stale な elapsed_sec を持つ
- webui は ccninfo monitor entries を表示しない; ccninfo を success rate に含めない
- Monitor.stop() の残余 unbounded paths: on_record callback タイムアウトなし; post-kill proc.wait(); fg cefstatus/csmgrstatus timeout=None
- dense ccninfo timeline 下の serial content worker occupancy (ccninfo ~5s/probe が content op latency を圧迫する可能性)

## Status (2026-08-23)

- 全項目未着手 (S7 の outcome field 側は f93245a で DONE — `MONITOR_FIELDS` `monitoring.py:45`、`derive_monitor_outcome` :67)。
- `.inf`: `validator.py:1482-1484` の `monitoring.interval` check は `_is_number`/`<= 0` のみで `isfinite` 無し (対照: `command_timeout` :1486-1500)。
- stale elapsed: `Monitor._run` `monitoring.py:364-370` が cycle 先頭で 1 回 `elapsed` を取り、`_collect_once` :221-247 の serial loop が :240-242 で同じ値を stamp。
- webui: `webui/state.py:69-80` `record_monitor` は cefstatus/csmgrstatus のみ扱う。
- `Monitor.stop` 残余: `on_record` callback `monitoring.py:243-248` に timeout 無し; `command_runner.py:143` `proc.wait()`; fg cefstatus/csmgrstatus `timeout=None` (`monitoring.py:271` / :290)。`_join_budget` docstring :388-393 がこれらを pre-existing として明記。
- serial content worker occupancy: 未計測。
