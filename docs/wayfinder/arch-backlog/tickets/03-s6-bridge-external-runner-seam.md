---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**S6 — bridge_external に CommandRunner seam**: attach_external_via_bridge / cleanup_external_bridges / attach_external_interface に optional `runner` param を追加し `_run_root_cmd_vec` (bridge_external.py:81-95、`MininetCommandRunner(None)` hardcode は :90) へ thread。現行テストは internal patch 41 箇所 (_run_root_cmd_vec 37 + MininetCommandRunner 4: test 行 218/388/986/1034) — recording fake 注入へ移行可能に。bridge_root.py:83-89 BridgeManager の _root_runner/_host_runner pattern を mirror。

## Status (2026-08-23, file:line は 2026-09-17 に main defeeb4 で再測)

- 未着手。**両方** open:
  - root 側: `_run_root_cmd_vec` (`bridge_external.py:81`) が :90 で `MininetCommandRunner(None)` を hardcode。
  - host 側: `attach_external_via_bridge` (:173) 内部 :226 で `host_runner = MininetCommandRunner(net)` を自前生成。
- `attach_external_via_bridge` :173 / `cleanup_external_bridges` :438 / `attach_external_interface` :516 はいずれも `runner` param を取らない。
- テストの patch 箇所 (test_bridge_external.py): `bridge_external._run_root_cmd_vec` 38 箇所、`bridge_external.MininetCommandRunner` 6 箇所 (:218/388/986/1034/1763/1797; :1763/:1797 は 420ef1e で追加)。
- 追記 (2026-09-02, 420ef1e): `_run_root_cmd_vec`/`_run_host_cmd_vec` が returncode None を 0 に変換し timed_out/cancelled を見ない fail-open を修正 (新設 `_fail_closed_rc` :51 が None/timed_out/cancelled を rc=-1 にし rollback へ)。runner seam 自体は未着手。行番号のずれ (+30) はこの commit による。
- mirror 先 `BridgeManager._root_runner` / `_host_runner` は `bridge_root.py:83-89`。
