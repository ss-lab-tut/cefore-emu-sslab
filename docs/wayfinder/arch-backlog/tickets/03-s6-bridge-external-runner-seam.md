---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**S6 — bridge_external に CommandRunner seam**: attach_external_via_bridge / cleanup_external_bridges / attach_external_interface に optional `runner` param を追加し `_run_root_cmd_vec` (bridge_external.py:51-64、`MininetCommandRunner(None)` hardcode は :60) へ thread。現行テストは internal patch 41 箇所 (_run_root_cmd_vec 37 + MininetCommandRunner 4: test 行 218/388/986/1034) — recording fake 注入へ移行可能に。bridge_root.py:83-89 BridgeManager の _root_runner/_host_runner pattern を mirror。

## Status (2026-08-23)

- 未着手。**両方** open:
  - root 側: `_run_root_cmd_vec` (`bridge_external.py:51`) が :60 で `MininetCommandRunner(None)` を hardcode。
  - host 側: `attach_external_via_bridge` (:143) 内部 :196 で `host_runner = MininetCommandRunner(net)` を自前生成。
- `attach_external_via_bridge` :143 / `cleanup_external_bridges` :408 / `attach_external_interface` :486 はいずれも `runner` param を取らない。
- テストの patch 箇所: `_run_root_cmd_vec` 38 hits、`bridge_external.MininetCommandRunner` 4 箇所 (test_bridge_external.py:218/388/986/1034; 元記述 967/1015 から更新)。
- mirror 先 `BridgeManager._root_runner` / `_host_runner` は `bridge_root.py:83-89`。
