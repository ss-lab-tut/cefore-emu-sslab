---
status: open
type: task
claimed-by:
blocked-by: [06]
---
## Task

**P1 (保留) — template.py `_set_config_value` の underscore 解消**: cache_manager.py:8/159・forwarding.py:6/50 が外部 import 済みだが、検証側は「package 内 sibling 共有の単一 underscore は _propagate_failures と同じ通常 pattern」と減衰評価。W1 (read 側集約) と同時にだけ判断。

## Status (2026-08-23)

- 保留のまま。`_set_config_value` は `template.py:192`、外部 import は `cache_manager.py:8` (使用 :159) / `forwarding.py:6` (使用 :50) で現存。`verdict.py:235` がコメントで言及。
- [06 W1](06-w1-read-conf-value.md) の read 側集約と同時にのみ判断 (blocked-by)。
