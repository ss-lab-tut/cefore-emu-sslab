---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**deferred (2026-07-27 external review) — ccninfo/monitoring known gaps**:
- 修正済み (2026-09-02, validator isfinite + Monitor ctor guard): `.inf` が monitoring.interval validation を通過した後 monitor thread を無限待機で殺す (command_timeout と同じ isfinite guard を interval にも適用)
- monitor の per-cycle timestamps は cycle 先頭で 1 回だけ打刻 → 後続 serial targets は stale な elapsed_sec を持つ
- webui は ccninfo monitor entries を表示しない; ccninfo を success rate に含めない
- Monitor.stop() の残余 unbounded paths: on_record callback タイムアウトなし; post-kill proc.wait(); fg cefstatus/csmgrstatus timeout=None
- dense ccninfo timeline 下の serial content worker occupancy (ccninfo ~5s/probe が content op latency を圧迫する可能性)
- 修正済み (2026-09-02): monitor target ccninfo の outcome が returncode/cancelled を見ず false-green になり得た (event 側 from_runtime_ccninfo と基準を揃えた)

## Status (2026-08-23, 2026-09-17 に main defeeb4 で訂正・再測)

- `.inf` と ccninfo monitor outcome の 2 項目は修正済み、残りは未着手 (S7 の outcome field 側は f93245a で DONE — `MONITOR_FIELDS` `monitoring.py:46`、`derive_monitor_outcome` :68)。
- `.inf`: **修正済み (3c30cd0)**。`validator.py:1440-1453` の `monitoring.interval` check が `math.isfinite` を含む (command_timeout :1454-1470 と同形、OverflowError も reject)。加えて `Monitor.__init__` `monitoring.py:185-198` が非有限 interval を `ValueError` で拒否。
- ccninfo monitor outcome: **修正済み (9740a80)**。`Monitor._collect_ccninfo` `monitoring.py:356-371` は `derive_monitor_outcome` を経由せず、`reply_received` かつ `not timed_out` かつ `not cancelled` かつ `returncode == 0` のときだけ "ok" (event 側 `verdict.from_runtime_ccninfo` と同じ fail-closed 基準)。
- stale elapsed: `Monitor._run` `monitoring.py:394-400` が cycle 先頭で 1 回 `elapsed` を取り、`_collect_once` :236-264 の serial loop が :254-256 で同じ値を stamp。
- webui: `webui/state.py:69-80` `record_monitor` は cefstatus/csmgrstatus のみ扱う。
- `Monitor.stop` 残余: `on_record` callback `monitoring.py:259-264` に timeout 無し; `command_runner.py:143` `proc.wait()`; fg cefstatus/csmgrstatus `timeout=None` (`monitoring.py:287` / :305、`timeout=self.command_timeout if bg else None`)。`_join_budget` :409 (docstring :410-425) がこれらを pre-existing として明記。
- serial content worker occupancy: 未計測。
