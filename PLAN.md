# PLAN: 候補4 — teardown_scenario seam

Date: 2026-07-01
Branch: feature/seam
Lead: claude-main → codex-main (実装) → codex-review (レビュー)

---

## Context

旧 PLAN.md（候補8+3+5）は commit `e9103db` で既に実装済みのため、この内容で置き換える。

`CONTEXT.md` の「次回実装候補」backlog から **候補4: `teardown_scenario` seam** を選択。
4つの scenario class（disaster.py, connect.py, mesh.py, linear.py）が
`fleet = self.daemon_fleet or build_fleet(...); failures.extend(fleet.stop_all())`
という teardown boilerplate を重複させている。`setup_scenario(net, spec) -> SetupResult`
（commit `08db7c8`, 候補A）と対称な `teardown_scenario(net, spec) -> TeardownResult` を
`src/runtime/scenario_setup.py` に追加し、4 scenario の teardown() をこの seam 経由に統合する。

**重要な発見**（Explore/Plan subagent 調査 + codex mcp gpt-5.5 レビューで検証済み）:
`mesh.py`/`linear.py` の現状の `teardown()` は disaster/connect と異なり、
`fleet.stop_all()` の失敗を **aggregate も raise もせず黙って捨てている**。
つまり4 scenario を単一 seam に統合するのは純粋な機械的抽出ではなく、
mesh/linear の2つは「silent failure → raised exception」という実際の挙動変化を伴う。

## Non-goals

- 候補2 (bridge.py split)、候補6 (result_detect → Verdict)、候補7 (topo.py rename) は着手しない
- 既存の smoke 12/12 + pytest full green を壊さない
- mesh/linear の `_csmgrd_host_ids()` 重複ヘルパーの統合は対象外（別候補として切り出す）
- connect.py の external-bridge cleanup 未実装ギャップは維持する（このリファクタで修正しない）

---

## Design decisions

1. **新規 `TeardownSpec` dataclass**（`ScenarioSetupSpec` の再利用ではない）。
   `ScenarioSetupSpec` は teardown に無関係な必須フィールドを7個持ち、
   `linear.py` は現状 `ScenarioSetupSpec` を一切構築していないため、
   無関係なフィールドをでっち上げさせるのは4行の重複より悪い設計になる。

2. **`teardown_scenario()` は3つの明示的にガードされた cleanup stage について raise しない**
   （daemon-stop の失敗は `DaemonFleet.stop_all()` 自身の per-host try/except で
   捕捉され return される。`bridge_manager.cleanup()` と `cleanup_external_bridges()` は
   seam 内で個別に `try/except BaseException` している）。
   `TeardownResult(failures: list[tuple[str, BaseException]])` を返し、
   raise するかどうかは呼び出し元の scenario の `teardown()` が
   `_propagate_failures(None, result.failures)`（`src/scenarios/base.py:13-44`）で決める。

   **注意点（codex レビューで確認、既存の gap であり新規のものではない）**:
   fleet **取得** 自体はガードされていない —
   `build_fleet()` のフォールバック構築は raise しうる
   （例: `DaemonFleet.__init__` は `readiness_policy` を検証し、不正値で `ValueError`）。
   これは現状の全 scenario の `teardown()` も同様（`fleet = self.daemon_fleet or
   build_fleet(...)` 行を try/except で囲んでいない）ため、seam は既存動作を保存するだけ。
   ここに try/except を追加しないこと（不正な `readiness_policy` はプログラミングエラーであり、
   回復すべき実行時条件ではない — CLAUDE.md の「起こり得ないシナリオへのエラーハンドリング追加禁止」に該当）。

3. **2 slice、2 commit に分割**:
   - **Slice A（抽出、挙動変化なし）**: seam を新設し、4 scenario すべての `teardown()`
     を移行。disaster/connect は既存の aggregate-and-raise を維持。
     mesh/linear は結果を discard したまま（Slice B で変更する旨のコメント付き）。
   - **Slice B（正規化、別コミット）**: mesh/linear も `_propagate_failures` を呼ぶよう変更。
     先に新規テストを書いて RED を確認してから GREEN にする
     （mesh/linear は現状 teardown テストが **ゼロ**）。

---

## Implementation

### `src/runtime/scenario_setup.py` に追加

```python
@dataclass(frozen=True)
class TeardownSpec:
    host_count: int
    csmgrd_host_ids: set[int]
    fleet_run_dir: Path
    daemon_fleet: DaemonFleet | None = None
    fleet_cefnetd_timeout: int = 10
    fleet_readiness_policy: str = "warn"
    bridge_manager: BridgeManager | None = None
    cleanup_external_bridges: bool = False  # opt-in; disaster.py のみ True

@dataclass(frozen=True)
class TeardownResult:
    failures: list[tuple[str, BaseException]]

def teardown_scenario(net, spec: TeardownSpec) -> TeardownResult:
    failures: list[tuple[str, BaseException]] = []
    fleet = spec.daemon_fleet or build_fleet(
        net, spec.host_count, spec.csmgrd_host_ids, spec.fleet_run_dir,
        cefnetd_timeout=spec.fleet_cefnetd_timeout,
        readiness_policy=spec.fleet_readiness_policy,
    )
    failures.extend(fleet.stop_all())
    if spec.bridge_manager is not None:
        try:
            spec.bridge_manager.cleanup()
        except BaseException as exc:
            failures.append(("bridge_manager.cleanup", exc))
    if spec.cleanup_external_bridges:
        try:
            cleanup_external_bridges()
        except BaseException as exc:
            failures.append(("cleanup_external_bridges", exc))
    return TeardownResult(failures=failures)
```

`cleanup_external_bridges` を既存の `from .bridge import (...)` に追加すること。

順序は disaster.py の現行（最も広い）teardown と完全一致させる:
fleet stop → bridge_manager.cleanup → cleanup_external_bridges (opt-in)。

`fleet_cefnetd_timeout`/`fleet_readiness_policy` は `build_fleet` フォールバック構築の
形状 parity のために転送するが、`DaemonFleet.stop_all()` はどちらも読まない
（`wait_ready()` のみが読み、teardown は `wait_ready()` を呼ばない）。
これは機能的な teardown ポリシーではなく、pass-through parity としてドキュメント化すること。

既存の gap（このseamで新規に導入されるものではない）: `spec.daemon_fleet is None` で
構築されるフォールバック fleet は `started_csmgrd` が空集合になり、
`DaemonFleet.stop_all()` は `started_csmgrd` の分しか csmgrd を止めない —
つまり実際に start されていないフォールバック fleet では csmgrd stop が黙ってスキップされる。
4 scenario すべての現行フォールバックパスに既にある gap であり、seam は意図的にこれを保存する
（このリファクタのスコープ外）。

### Seam-level tests（Slice A の中で、call-site 移行より前に追加）

`tests/runtime/test_scenario_setup.py` に、既存の `setup_scenario` テストパターン
（`patched_seam` スタイル）を踏襲して追加:
- `daemon_fleet` が渡された場合は `build_fleet` を呼ばずそれを使う
- fallback パスでは `build_fleet` に `host_count`, `csmgrd_host_ids`, `fleet_run_dir`,
  `cefnetd_timeout`, `readiness_policy` が正確に転送される
- 呼び出し順序は `fleet.stop_all()` → `bridge_manager.cleanup()` → `cleanup_external_bridges()`
- `stop_all()` が失敗を返しても `bridge_manager.cleanup()` は実行される
- `cleanup_external_bridges()` は `spec.cleanup_external_bridges is True` の時のみ実行
- `bridge_manager=None` の場合はエラーなくスキップ
- `TeardownResult.failures` は3ステージすべての失敗を独立に蓄積する
- 全成功時は `TeardownResult(failures=[])`

### Call-site changes（Slice A）

- **disaster.py** `teardown()`: `TeardownSpec(host_count=self.args.hosts,
  csmgrd_host_ids=self.cache_node_set, fleet_run_dir=self.run_dir,
  daemon_fleet=self.daemon_fleet, fleet_cefnetd_timeout=getattr(self.args,
  "cefnetd_timeout", None) or 10, fleet_readiness_policy="raise",
  bridge_manager=self.bridge_manager, cleanup_external_bridges=True)` を構築し
  `teardown_scenario` を呼び、`if result.failures: _propagate_failures(None,
  result.failures)`。不要になった `cleanup_external_bridges` と `build_fleet` の
  直接 import を削除し、既存の `scenario_setup` import 行に `TeardownSpec, teardown_scenario`
  を追加。
- **connect.py** `teardown()`: 同じ形だが `cleanup_external_bridges=False`
  （connect の既存 gap を保存 — ext_args を setup 時に渡すが teardown で
  clean up したことは一度もない。このリファクタは修正しない）。
  `build_fleet` の直接 import を削除。
- **mesh.py** `teardown()`: `TeardownSpec(host_count=self.host_num,
  csmgrd_host_ids=self._csmgrd_host_ids(), fleet_run_dir=self.run_dir,
  daemon_fleet=self.daemon_fleet)`、`teardown_scenario(net, spec)` を呼び、
  結果は discard（Slice B で変更する旨のコメント付き）。`build_fleet` の直接 import を削除。
- **linear.py** `teardown()`: mesh.py と同じ。`linear.py` は現状 `scenario_setup`
  を import していないため新規追加。`configure()` が直接 `build_fleet` を呼び続けるため
  既存の `build_fleet` import は維持（スコープ外）。

### 必須の stale patch target 修正（Slice A）

`tests/scenarios/test_teardown_lifecycle.py` は
`"src.scenarios.disaster.cleanup_external_bridges"` を **8箇所** で patch している
（grep で確認済み: 187, 221, 265, 419, 794, 843, 930, 977 行目）。
すべて `"src.runtime.scenario_setup.cleanup_external_bridges"` に retarget すること
（呼び出しがそこに移動するため）。古い patch target を生かすために disaster.py に
不要な import を残さないこと — patch されない実物の `cleanup_external_bridges()` が
unit test 中に実際の `ip link` コマンドを実行してしまう。
（repo 全体を grep して確認済み: これが完全なリストであり、`build_fleet` を
scenario module 経由で patch しているテストはどこにも存在しない —
それらは低レベルの `src.runtime.daemon_fleet.stop_cefnetd`/`stop_csmgrd` を
patch しており、これらは移動しない。）

### Slice B — mesh.py / linear.py の正規化

新規 `tests/scenarios/test_mesh.py`（現状存在しない）と `tests/scenarios/test_linear.py`
の拡張（現状 FIB/IP テストのみ、teardown カバレッジなし）を、`test_connect.py` の
既存 teardown テスト形状を踏襲して追加。
キーとなる新規テスト: `stop_cefnetd` を raise するよう patch し、
`scenario.teardown(net)` から `pytest.raises(BaseException)` を assert する —
これは現状 fail する（mesh/linear は黙って握りつぶす）が、変更後は pass しなければならない。
`MeshScenario(host_num=3, swhich_num=2, seed=1, k_paths=1, run_dir=tmp_path)` は
有効な構築（`src/runtime/topo.py` の `min_required_links`/`max_possible_links` で検証済み）。

その後 mesh.py/linear.py の `teardown()` に
`if result.failures: _propagate_failures(None, result.failures)` を追加し、
両ファイルに `_propagate_failures` の import を新規追加（`.base` から）。

**これは実際の CLI 挙動を変える**: `ceforeemu mesh`/`ceforeemu linear` は現状、
teardown 中にデーモン停止が失敗しても exit 0 で終了する。Slice B 後は失敗が
uncaught exception として伝播し（非ゼロ exit）、`src/cli/main.py` には
scenario 実行を囲む例外握りつぶしラッパーが存在しない
（disaster path 用の log ファイル stdout/stderr リダイレクトのための
`try/finally` のみで `except` 節はない）ため、これは disaster/connect の
既存挙動と完全に一致する。Slice B のコミットメッセージでこれを
「意図的な正規化であり regression ではない」と明示すること。

---

## 実装フロー（役割分担）

実装は claude-main が直接書かず、agmsg 経由で codex-main に委譲する。
各フェーズ完了ごとに codex-review にレビューさせ、blocking finding があれば
codex-main に差し戻す。全体完了後、advisor と codex-review の両方による
最終ダブルチェックを経てから完了とする。

```
Phase 1 — Seam + seam-level tests
  codex-main: scenario_setup.py に TeardownSpec/TeardownResult/teardown_scenario 追加
              + tests/runtime/test_scenario_setup.py にテスト追加
  → gate: sudo .venv/bin/python3 -m pytest tests/runtime/test_scenario_setup.py -x
  → codex-review レビュー（blocking finding があれば codex-main に差し戻し）

Phase 2 — Slice A（disaster/connect/mesh/linear 移行 + 8箇所 patch target 修正）
  codex-main: 4 scenario の teardown() 移行、import 整理、
              test_teardown_lifecycle.py の patch target 修正
  → gate: 下記 Verification/Slice A の pytest コマンド
  → codex-review レビュー（mesh/linear が意図的に result 破棄している点を
    見落としていないか、8箇所すべて retarget されているかを重点確認）

Phase 3 — Slice B（mesh/linear 正規化、別コミット）
  codex-main: test_mesh.py 新規作成 + test_linear.py 拡張（先に RED）
              → mesh.py/linear.py teardown() に _propagate_failures 追加
  → gate: 下記 Verification/Slice B の pytest + 手動実行コマンド
  → codex-review レビュー（CLI 終了コード変更が commit message で
    明示されているかを重点確認）

Final gate
  /cefore-run-tests（pytest full + smoke 12/12; mesh/linear は手動実行で補完）
  → advisor によるダブルチェック
  → codex-review によるダブルチェック（両方 approve するまで完了扱いにしない）
```

---

## Critical files

- `src/runtime/scenario_setup.py` — `TeardownSpec`/`TeardownResult`/`teardown_scenario` 追加
- `src/scenarios/disaster.py` — `teardown()` 移行
- `src/scenarios/connect.py` — `teardown()` 移行
- `src/scenarios/mesh.py` — `teardown()` 移行 (Slice A)、正規化 (Slice B)
- `src/scenarios/linear.py` — `teardown()` 移行 (Slice A)、正規化 (Slice B)
- `tests/runtime/test_scenario_setup.py` — `teardown_scenario` 新規テスト
- `tests/scenarios/test_teardown_lifecycle.py` — 8箇所 patch target 修正
- `tests/scenarios/test_mesh.py` — 新規ファイル、Slice B
- `tests/scenarios/test_linear.py` — 拡張、Slice B
- `CONTEXT.md` — 候補4 backlog entry を出荷後に削除、`TeardownSpec`/`teardown_scenario`
  の glossary entry を既存の `ScenarioSetupSpec` entry の隣に追加

## Verification

Slice A:
```bash
sudo .venv/bin/python3 -m pytest tests/runtime/test_scenario_setup.py tests/scenarios/test_teardown_lifecycle.py tests/scenarios/test_connect.py tests/scenarios/test_linear.py -x
sudo .venv/bin/python3 -m pytest -x
```

Slice B:
```bash
sudo .venv/bin/python3 -m pytest tests/scenarios/test_mesh.py tests/scenarios/test_linear.py -x
sudo .venv/bin/python3 -m src mesh --hosts 3 --switches 2 --seed 1 --k 1
sudo .venv/bin/python3 -m src linear --hosts 3
```

Final: `/cefore-run-tests` skill（pytest full + smoke 12/12 — mesh/linear は
その skill の smoke matrix に含まれない、disaster/connect のみ。上記の手動実行が
その2つの Slice B の実質的な検証になる）+ ruff。

## Risks

| Risk | Mitigation |
|---|---|
| mesh/linear の挙動変化 (Slice B) は実際の CLI exit code 変化 | 別の明示的にラベル付けされたコミットとして出荷し、新規テストを先に書く |
| stale な `cleanup_external_bridges` patch target（8箇所）が黙って壊れる、または実際の呼び出しを intercept しなくなる | Slice A の必須ステップとして8箇所すべて retarget、grep で検証済み |
| `fleet_cefnetd_timeout`/`fleet_readiness_policy` は挙動に関係しそうに見えるが実際は無関係 | `DaemonFleet.stop_all()` はどちらのフィールドも読まない（`wait_ready()` のみ、teardown では呼ばれない）— 形状 parity/ドキュメント目的のみで保持、機能的な修正ではない |
| connect.py の external-bridge cleanup gap | このリファクタで意図的に保存、修正しない — connect.py の teardown docstring にインラインで明記 |
