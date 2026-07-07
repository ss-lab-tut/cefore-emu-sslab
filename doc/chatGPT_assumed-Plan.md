## レビュー結果：**変更はまだ採用不可**

今回の tarball はレビュー対象として成立しています。`.codex -> .claude/` と `buffer.sh` の mode は保持され、意味的差分は remediation 対象の source / docs / tests に入っています。提供されたテストログも **`481 passed, 1 skipped`** です。

ただし、`bridge.py` と lifecycle 修正に **採用を止めるべき欠陥が4件**あります。テストが全部通っていることは、これらの経路をテストしていない、またはテストが空振りしていることを示しているだけです。

---

# Findings

## 1. High: External bridge cleanup retry が部分成功後に永久失敗し得る

**場所:** `src/runtime/bridge.py:418-474`

`cleanup_external_bridges()` は cleanup の一部が失敗した場合に record を保持します。しかし、すでに成功した cleanup に対応する ownership flag を更新していません。

```python
if record.get("veth_created"):
    rc, _, err = _run_root_cmd_vec(["ip", "link", "del", veth_root])
    ...

if record.get("phy_enslaved"):
    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "nomaster"])
    ...

if cleanup_ok:
    cleaned.append(host_name)
```

### 再現可能な失敗経路

1. `veth_root` の削除に成功。
2. physical interface の `nomaster` に失敗。
3. bridge 削除には成功。
4. record は保持されるが、`veth_created=True` と `bridge_created=True` のまま。
5. retry cleanup は、既に削除済みの veth / bridge を再削除する。
6. `not found` で再び失敗し、record が消えない。

実装を同じ状態で呼び出して確認したところ、初回 cleanup 後に record がそのまま残り、retry は削除済み `veth-h0-root` と `br-h0` の削除失敗で再度 `ExternalBridgeError` になります。

### 影響

* cleanup retry の設計目的を満たさない。
* partial cleanup failure 後に、自動回復不能な residual record が残る。
* 実際のホスト状態は片付いていても、ソフトウェア上は永久に cleanup failure を報告し得る。
* 逆に、残存資源の一部だけが未回復の場合も、正確な outstanding state を失う。

### 必要な修正

record は「作ったことがある資源」ではなく、**まだ cleanup が必要な資源**を表すべきです。

* veth 削除成功後に `record["veth_created"] = False`
* unmaster 成功後に `record["phy_enslaved"] = False`
* DOWN 復元成功後に `record["phy_up_changed"] = False`
* bridge 削除成功後に `record["bridge_created"] = False`
* 全 outstanding state が消えた場合だけ record を削除

setup rollback 側も同様で、成功した undo action を record へ反映する必要があります。

### 欠けている test

* `veth delete succeeds → unmaster fails → retry succeeds and clears record`
* `unmaster succeeds → bridge delete fails → retry succeeds and clears record`
* setup rollback で一部 undo 成功・一部失敗した後、retry が outstanding action のみを実行する test

---

## 2. High: DOWN だった physical interface が enslave 失敗後に UP のまま残る

**場所:** `src/runtime/bridge.py:311-331`

現在の setup 順序は次です。

```python
if not prior_up:
    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "up"])
    ...
    record["phy_up_changed"] = True

rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "master", bridge_name])
if rc != 0:
    rb_failures = _rollback(rollback_actions, "phy-enslave failure")
    ...
```

しかし、physical interface を DOWN に戻す rollback action は、**enslave 成功後**にしか登録されません。

```python
record["phy_enslaved"] = True
rollback_actions.append(("unmaster phy", ...))
if record["phy_up_changed"]:
    rollback_actions.append(("restore phy DOWN", ...))
```

### 再現可能な失敗経路

1. 実行前の NIC は administratively DOWN。
2. bridge 作成成功。
3. bridge UP 成功。
4. `ip link set <phy> up` 成功。
5. `ip link set <phy> master <bridge>` が失敗。
6. rollback は bridge を削除するだけ。
7. physical interface は **UP のまま残る**。
8. record は削除されるため、後続 cleanup でも復元できない。

この経路を呼出しレベルで確認すると、`ip link set eth0 down` は一度も呼ばれず、registry は空になります。

### 影響

* 「事前状態を復元する」という external bridge の安全要件に違反。
* 専用 NIC であっても、失敗実行がホスト状態を変更したまま返る。
* synthetic validation の F3/F4 は bridge-up 直後の failure しか検査しておらず、この経路を覆っていません。

### 必要な修正

`phy_intf` を UP に変更した直後に restore action を登録してください。

正しい mutation journal の順序は概念的に次です。

```python
create bridge        -> append(delete bridge)
set phy up           -> append(restore phy down)
enslave phy          -> append(unmaster phy)
create veth          -> append(delete veth)
```

rollback の逆順は、

```text
delete veth → unmaster phy → restore phy down → delete bridge
```

になります。

### 欠けている test

* prior interface DOWN
* bridge create / bridge-up / phy-up は成功
* enslave が失敗
* rollback が `phy down` を実行すること
* record が消える前に prior state が復元されること

現在の `test_enslave_failure_rolls_back()` は link inspection を `flags=["BROADCAST", "UP"]` で返しており、この欠陥をテストしていません。

---

## 3. High: Proxy ARP の部分 rollback 失敗が握り潰され、復元不能になる

**場所:** `src/runtime/bridge.py:810-849`

`enable_proxy_arp()` は二つの sysctl を順に変更します。

```python
sysctl -w net.ipv4.conf.<iface>.proxy_arp=1
sysctl -w net.ipv4.conf.all.proxy_arp=1
```

二つ目が失敗した場合、一つ目を戻そうとします。

```python
if rc != 0:
    for undo in reversed(local_undo):
        undo()
    raise RuntimeError(...)
```

問題は、`undo()` の return code を確認していないことです。

### 再現可能な失敗経路

1. prior values は正常に取得。
2. interface-level `proxy_arp=1` は成功。
3. all-level `proxy_arp=1` は失敗。
4. interface-level の rollback `proxy_arp=<prior>` も失敗。
5. rollback failure は無視される。
6. global `cleanup_actions` は一件も登録されない。
7. interface-level Proxy ARP が変更されたまま残り得る。

この経路を呼出しレベルで確認すると、返される例外は二つ目の write failure だけで、rollback failure は失われ、`cleanup_actions` は空のままです。

### 影響

* root-level host network sysctl が変更されたまま残る可能性がある。
* teardown で retry する情報も失われる。
* pass II-A で要求していた「rollback failure を surface する」という契約を満たしていない。

### 必要な修正

local rollback を unchecked function call にしないでください。

* interface-level mutation 成功直後に、retryable restoration ownership を登録する。
* 二つ目の write failure 時は rollback を実行し、exit code を検査する。
* rollback 成功時のみ temporary restoration ownership を解除。
* rollback 失敗時は、setup failure と rollback failure の双方を例外へ含め、後続 `cleanup()` が retry できる restoration action を保持。

### 欠けている test

現在の `test_second_write_failure_rolls_back_first()` は、「rollback が呼ばれた」しか確認していません。

追加すべき test:

* second write failure + first rollback failure
* 例外に rollback failure detail が含まれる
* retryable cleanup action が残る
* 後続 `cleanup()` 成功で prior value に復元できる

---

## 4. Medium: `content_runner.wait_all()` の例外で `stop()` が実行されない

**場所:** `src/scenarios/disaster.py:617-623`
**関連実装:** `src/runtime/content_ops.py:84-137`

現在の lifecycle code は、`wait_all()` と `stop()` を同じ `try` にまとめています。

```python
if self.content_runner is not None:
    try:
        if not self.content_runner.wait_all(timeout=60):
            info("[warning] content operation shutdown exceeded 60s deadline\n")
        self.content_runner.stop()
    except BaseException as exc:
        cleanup_failures.append(("content_runner.stop", exc))
```

`wait_all()` が例外を出した場合、`stop()` は呼ばれません。

`ContentOperationRunner.stop()` は、

* cancel event の設定
* stop event の設定
* queued item の破棄
* worker thread join
* pending subscriber process の終了処理

を担当しています。`wait_all()` の失敗時こそ `stop()` を必ず試行すべきです。

### 影響

* content operation worker thread や pending subscriber process が残留し得る。
* staged teardown の「全 cleanup stage を独立に試行する」という目的に違反。

### 必要な修正

`wait_all()` と `stop()` を別々の guarded stage にしてください。

```python
try:
    completed = self.content_runner.wait_all(timeout=60)
except BaseException as exc:
    cleanup_failures.append(("content_runner.wait_all", exc))

try:
    self.content_runner.stop()
except BaseException as exc:
    cleanup_failures.append(("content_runner.stop", exc))
```

### 欠けている test

現在の lifecycle test は `content_runner.stop()` が失敗する場合だけを確認しています。
`wait_all()` が例外を出しても `stop()` と後続 cleanup が実行される test が必要です。

---

# Test quality issue

## `test_duplicate_physical_interface_rejected()` はテストになっていない

**場所:** `tests/runtime/test_bridge.py:1269-1296`

この test は名称上、

```python
def test_duplicate_physical_interface_rejected(self):
```

ですが、実際には次のように何も呼び出していません。

```python
with patch(...):
    pass
```

さらにコメントは、

```python
# Current implementation does NOT check for duplicate phy_intf.
# This test documents actual behavior
```

と述べています。

これは coverage matrix で `COVERED` と扱ってはいけない test です。少なくとも、

* test 名を characterization に変更する
* 本当に duplicate physical interface を拒否する実装と test を追加する

のどちらかが必要です。

この件単独で adoption を止める必要はありませんが、**「全安全条件を tests が保証している」という主張は成立しません。**

---

# 変更範囲とテスト結果

## 確認できた変更対象

Tracked modifications:

* `CLAUDE.md`
* `README.md`
* `README_ja.md`
* `src/cli/args.py`
* `src/cli/main.py`
* `src/runtime/bridge.py`
* `src/runtime/monitoring.py`
* `src/runtime/result_detect.py`
* `src/scenarios/base.py`
* `src/scenarios/disaster.py`
* `tests/runtime/test_bridge.py`
* `tests/runtime/test_result_detect.py`

New regression tests:

* `tests/core/test_path_containment.py`
* `tests/scenarios/test_teardown_lifecycle.py`

提供された test log は、

```text
481 passed, 1 skipped in 4.15s
```

です。

ただし、上記4件は passing suite に含まれていない failure paths、または test が誤って通過している箇所です。**green suite は採用許可になりません。**

## Packaging hygiene

展開した tarball には `git-status.txt` に記録されていない untracked file として、

```text
.claude/settings.local.json
```

が含まれています。

今回の remediation patch に含めてはいけません。以前の監査でも Git 操作許可を含む local settings が危険要素になっていたため、採用対象から明示的に除外してください。

---

# 最終判断

| 項目                                | 判定                            |
| --------------------------------- | ----------------------------- |
| Path containment 修正               | 概ね妥当                          |
| Timeout / `ProcessLookupError` 修正 | 妥当                            |
| Documentation / CLI contract      | 妥当                            |
| Lifecycle orchestration           | 追加修正必要                        |
| BridgeManager Proxy ARP           | **採用阻害 defect あり**            |
| External bridge rollback / retry  | **採用阻害 defect あり**            |
| Synthetic validation              | 今回見つかった failure paths を覆っていない |
| 現在の変更セットの採用                       | **不可**                        |

## 必須修正順

1. `proxy_arp` の rollback failure を保持・報告・retry 可能にする。
2. external bridge の setup rollback / normal cleanup record を outstanding-state ベースに修正する。
3. physical NIC を UP にした直後から restore action を登録する。
4. `content_runner.wait_all()` と `stop()` を独立 cleanup stage に分ける。
5. 上記の fail-before regression tests を追加する。
6. synthetic validation は、新たに追加した external failure paths だけを disposable veth で再検証する。

この4件を直さずに原本へ取り込むと、**失敗時にホストの network state を残したまま、cleanup retry が機能しないコードを採用する**ことになります。

