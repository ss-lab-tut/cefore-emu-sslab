---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W1 — Cefore conf key=value read の単一 owner**: `cefore_conf.py:6-22` / `daemon_logs.py:23-35` / `:38-54` の同形 3 loop + `template.py:176-189` の regex 版 (計 4 実装)。read 側を cefore_conf.py の `read_conf_value(path, key, default=None)` に集約。実測 divergence: manual loop は '=' 後の最初の whitespace token、regex は行末まで — 統一時に semantics を決める。_set_config_value の扱いは P1 と同時判断。

## Status (2026-08-23)

- 未着手。reader 4 実装が現存: `cefore_conf.py` `read_port_num` :6 (loop :11-21)、`daemon_logs.py` `read_local_sock_id` :23 (loop :28-34) / `read_csmgr_port_num` :38 (loop :43-53)、`template.py` `_read_config_value` :176-189 (元記述 :145-181 から更新)。
- writer `_set_config_value` は `template.py:192-212`。
- `read_conf_value` は src/tests で 0 hits (未作成)。
- [14 P1](14-p1-set-config-value-underscore.md) はこの ticket に blocked。
