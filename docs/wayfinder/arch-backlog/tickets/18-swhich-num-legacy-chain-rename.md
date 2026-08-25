---
status: open
type: task
claimed-by:
blocked-by: [19]
---
## Task

**修正案 — `swhich_num` typo の是正 (semantic 名 `switch_limit` へ)**:
`MeshTopo(swhich_num=...)` は typo (`switch_num` が正) であるうえ、意味的には「emergent に生成される switch 数の上限」— 超過すると ValueError (`runtime/topo.py` の `switch count N exceeds limit M`)。つまり名前は綴りと意味の両方で実態とズレている。修正案 (2026-07-06, user 提案 `limit_sw_num` 系 → 採用候補 `switch_limit`): 新規コードは最初から semantic 名を使う — R9-2 の `MeshBuildSpec` は field 名 `switch_limit` を採用し、docstring で legacy kwarg `swhich_num` への対応を記す。既存 chain (config `switches:` → `args.switches` → scenario 属性 `swhich_num` → `MeshTopo(swhich_num=)`) の一括リネームは CLI/config 互換に触るため独立 housekeeping — 候補7 (topo.py リネーム) と同じ pass でまとめて行うのが合理的。
_Avoid_: 新規 interface に `swhich_num` 綴りを伝播させること、R9-2 の fold と既存 chain リネームを混ぜること

## Status (2026-08-23)

- **新 interface 側は DONE**: `MeshBuildSpec.switch_limit` (`scenario_setup.py:124`)、adapter :167 で `swhich_num=spec.switch_limit` に変換。
- **legacy chain は未着手** (`swhich_num` 現存): `cli/main.py:45`、`scenarios/mesh.py:36/50/73/76/79/89/181/196`、`runtime/topo.py:59/146/148/152/153/195`、`tools/workshop/topo_fingerprint.py:120`、tests `test_mesh.py:16/32`、`test_init_validation.py:32/43/54/65/81` (+ test 名 :49/:60/:71)。
- [19 候補7](19-kouho7-rename-topo-module.md) と同じ pass でまとめる (blocked-by)。
