# PLAN: R7-4 — bridge.py 3分割（split-by-concern）

Date: 2026-07-03
Branch: feature/seam（base: bd04ef5）
Lead: claude-main → codex-main (実装) → codex-review (per-slice レビュー)
Plan review: Codex MCP gpt-5.5 済（verdict: アーキテクチャ approve / 実行計画 revise → 本書は revise 指摘反映済み）

---

## Context

旧 PLAN.md（候補4 teardown_scenario seam）は commit `2e963ad` で実装済みのため、この内容で置き換える。

`src/runtime/bridge.py`（1240 LOC）は3つの独立 interface を同居させる god-module：

1. **external-NIC attach 状態機械**（~580 LOC）— `attach_external_via_bridge` + `cleanup_external_bridges` + `_created_bridges` module ledger + `_RollbackAction` rollback 機構
2. **BridgeManager root-namespace**（~560 LOC）— NAT / proxy-ARP / IP forwarding + `CleanupAction` ledger + `setup_bridges` orchestration
3. **引数パース純関数**（~100 LOC）— `parse_bridge_args` / `parse_ext_args`

裏取り済み事実（Explore + Codex MCP 検証）：

- 真に共有される関数は **`_validate_static_ip`（bridge.py:166-188）1つだけ**（attach:220 と `BridgeManager.connect_to_root_ns`:701 が呼ぶ）
- `_run_root_cmd_vec` / `_run_host_cmd_vec` は名前に反して **external-attach 専用**（BridgeManager は `self._root_runner()` 経由）
- `setup_bridges`（1151-1240）は **root-ns 側しか呼ばない**（external-attach と完全独立）
- 2つの ledger（`_created_bridges`+`_RollbackAction` vs `cleanup_actions`+`CleanupAction`）はコードパス共有ゼロ
- `parse_ext_args` は **CIDR 検証をしない**（フィールド数・IP 欠落・MTU parse のみ）— 新 test は現行挙動を assert すること（検証追加は behavior change なので禁止）
- `attach_external_interface` wrapper（511-513）は `scenario_setup._apply_bw_ext()`:158 が実際に呼ぶ — **削除不可、move のみ**
- `min_*.yaml` smoke は bridge 経路を踏まない → runtime 証明は unit 2518行 + synthetic root suite（5本、`CEFEMU_SYNTHETIC_ROOT=1` + root）
- naming 衝突なし。README.md:368 / README_ja.md:315 の tree 行が bridge.py に言及

## 決定（grilling 済み、2026-07-03）

| # | 決定 |
|---|---|
| Q1 | フラット3 module（`bridge_external.py` / `bridge_root.py` / `bridge_args.py`）。`setup_bridges` は root しか呼ばない事実に従い `bridge_root.py` に同居 |
| Q2 | `bridge.py` は最終 slice で**削除**（shim なし）。importer 書き換え。`src/runtime/__init__.py` の公開再 export 4シンボルは新 module 向きに差し替えて外向き安定面を維持 |
| Q3 | `_validate_static_ip` → `bridge_args.validate_static_ip` に公開化。external / root 両方が bridge_args を import（external↔root の直接依存ゼロ） |
| Q4 | test は move-only 分割（`test_bridge_external.py` ~13 class / `test_bridge_root.py` ~12 class、assert 不変・patch target 付け替えのみ）+ 新規 `test_bridge_args.py`（純関数の初 test）。`TestConnectToRootNsCidrValidation` は BridgeManager 経由なので root 側 |
| Q5 | 3-slice bottom-up + synthetic gate。事前 Codex MCP plan review（本書）済み |

**Pinned 制約**: ledger 統一（旧候補3）は絶対に混ぜない。全 slice behavior-preserving move-only（logic 編集禁止）。

## Module 配置

```
src/runtime/
├─ bridge_args.py      (純関数 leaf — import: stdlib + ipaddress のみ、Mininet 不要)
│    parse_bridge_args / parse_ext_args / validate_static_ip（公開化）
├─ bridge_external.py  (attach 状態機械)
│    _created_bridges / ExternalBridgeError / _run_root_cmd_vec / _run_host_cmd_vec
│    _inspect_link / _inspect_addresses / _get_admin_up
│    attach_external_via_bridge / cleanup_external_bridges / attach_external_interface
│    _rollback_* ×3 / _OUTSTANDING_FLAGS / _record_has_outstanding_state / _RollbackAction / _rollback
│    import: dataclass, Callable, mininet.log.info, mininet.net.Mininet,
│            ROOT_SENTINEL, MininetCommandRunner, bridge_args.validate_static_ip
└─ bridge_root.py      (root-namespace + orchestration)
     CleanupAction / TeardownError / _result_to_rc_detail / BridgeManager
     extract_gateway_from_ip / _resolve_root_ip / _find_host_intf / setup_bridges
     import: dataclass, Any, Callable, info, Mininet, Node, AddressingScheme,
             TopologyModel, ROOT_SENTINEL, MininetCommandRunner, bridge_args.validate_static_ip
```

依存方向: bridge_external → bridge_args ← bridge_root（一方向、循環なし）

## Slice 計画

### S1 — bridge_args.py 抽出（純関数 leaf）

- `bridge_args.py` 新設: `parse_bridge_args`（bridge.py:1088-1115 から move）、`parse_ext_args`（609-641 から move）、`validate_static_ip`（166-188 から move + 公開化）
- **互換 alias（Codex 指摘①）**: bridge.py は `from .bridge_args import validate_static_ip as _validate_static_ip` で内部参照（:220, :701）と旧 test の `_validate_static_ip` import（test_bridge.py:1500）を無傷に保つ
- importer 付け替え: disaster.py / connect.py の `parse_bridge_args`、scenario_setup.py と runtime/__init__.py の `parse_ext_args` を bridge_args 向きに
- 新規 `tests/runtime/test_bridge_args.py`: **現行挙動を assert**（parse_ext_args は CIDR 非検証のまま、validate_static_ip は直接 test）
- Gate: red-first（新 test）→ full pytest green → ruff

### S2 — bridge_root.py 抽出

- move: `CleanupAction` / `TeardownError` / `_result_to_rc_detail` / `BridgeManager` / `extract_gateway_from_ip` / `_resolve_root_ip` / `_find_host_intf` / `setup_bridges`
- **例外 identity（Codex 指摘②）**: `TeardownError` の import を同一 slice 内で全部 bridge_root 向きに付け替える（bridge.py に旧 class を残さない — `pytest.raises` の identity 不一致を防ぐ）。対象: scenario_setup.py / tests/scenarios/test_teardown_lifecycle.py:16 / move する root 系 test class
- importer 付け替え: scenario_setup.py（`BridgeManager`, `setup_bridges`）、disaster.py / connect.py（`BridgeManager`）
- test move: root 系 12 class → `test_bridge_root.py`（patch target を `src.runtime.bridge_root.*` に付け替え — `_resolve_root_ip`:135 / `info`:916 / `TestProducerCleanupContract` の `info` patch 含む）+ `extract_gateway_from_ip` の新 test をここに追加
- external 系 test class は test_bridge.py に残置（patch target は `src.runtime.bridge` のまま — S3 で移動）
- Gate: full pytest green → ruff

### S3 — bridge_external.py 抽出 + bridge.py 削除

- move: 残り全部（attach 状態機械一式、`attach_external_interface` wrapper **維持**）
- `bridge.py` / `tests/runtime/test_bridge.py` 削除
- external 系 13 class → `test_bridge_external.py`（patch target `src.runtime.bridge_external.*`、`_created_bridges` 直接操作の class 群含む）
- **synthetic 付け替え（Codex 指摘③）**: `tests/synthetic/test_external_bridge_synthetic.py` の `from src.runtime import bridge as bridge_mod` + `bridge_mod._run_root_cmd_vec` monkeypatch + `_created_bridges` import を bridge_external 向きに
- `src/runtime/__init__.py` 再 export 4シンボルを bridge_external 向きに
- README.md:368 / README_ja.md:315 の tree 行を3 module に更新
- **stale-import grep gate（Codex 指摘④、必須）**: `rg -n "src\.runtime\.bridge|from src\.runtime import bridge|from \.bridge |\.\.runtime\.bridge"` が archival docs（doc/chatGPT_assumed-Plan.md）以外で 0 hit であること
- Gate: full pytest green → ruff

### S4 — 検証 gate + docs

- full pytest（.venv）
- **synthetic root suite**: `sudo CEFEMU_SYNTHETIC_ROOT=1 .venv/bin/python3 -m pytest tests/synthetic/ -v`（5本、実 veth/netns で external-attach を実証）
- 代表 smoke: min_putget + connect（bridge 非経路のリグレッション確認）
- CONTEXT.md: backlog の候補2 entry を削除し、正式 glossary entry（Bridge modules）を追記
- memory 更新、PLAN.md の完了マーク

## 検証マトリクス

| 検証 | 対象 | slice |
|---|---|---|
| test_bridge_args.py（新規） | 純関数3つの初 test | S1 |
| test_bridge_root.py（move+新1） | BridgeManager / setup_bridges / CleanupAction ledger | S2 |
| test_bridge_external.py（move） | attach / rollback / cleanup / _created_bridges | S3 |
| stale-import grep | 旧 module 参照ゼロ | S3 |
| synthetic ×5（root 実行） | 実 veth/netns の attach/cleanup/rollback | S4 |
| smoke min_putget + connect | bridge 非経路リグレッション | S4 |

## リスクと対策

- **patch target の付け替え漏れ** → slice ごとに「moved class の patch は新 module / 残置 class は旧 module」を review 観点に明記。S3 の grep gate が最終防衛線
- **TeardownError の二重 identity** → S2 で同時付け替え（bridge.py に残さない）
- **synthetic の module monkeypatch** → S3 で bridge_mod 参照ごと付け替え、S4 の root 実行で実証
- **codex-main usage limit**（R7-1 の教訓）→ 各 slice は preflight 事実を RESULT に引用させる
