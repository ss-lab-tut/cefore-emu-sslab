---
status: closed
type: prototype
claimed-by: claude-code
blocked-by: [09]
---
## Question

（post-v1）GitHub-hosted runner 上で Cefore 0.12.0 をソースビルド（キャッシュ
付き）+ apt mininet + `min_putget.yaml` 1 本の smoke が成立するかを、捨て可能な
workflow_dispatch ブランチで実証する。成立したら non-required job としての追加を
新たな decision ticket に切る。不成立なら「smoke はローカル恒久」を ADR-0004 に
追記して close。

判断材料: ビルド時間 / キャッシュヒット率 / Mininet が runner のカーネル
機能（netns, OVS）で安定動作するか / flakiness。

## Resolution (2026-09-17)

**成立**。cold / warm の 2 run × matrix 3 本 = 6 サンプルすべて green。
release 時のみ起動する形での組み込みを [12](12-smoke-release-integration.md) に切った。

### 実施形（Question からの変更点）

- **トリガー**: workflow_dispatch ではなく `ci/smoke-prototype` への push にした。
  - UI の "Run workflow" ボタンは workflow ファイルが default branch にあるときだけ出る（GitHub Docs「Events that trigger workflows」の workflow_dispatch 節）。`gh` の dispatch 作成は 403。
  - 最終形は release 時のみ起動する（ユーザー決定 2026-09-17）。
- **controller**: ラボのパッチ版 openflow `controller` ではなく、apt の `ovs-testcontroller`（Mininet DefaultController のフォールバック先）を使った。
  - ラボのパッチ（GCC14 ビルド修正と `MAX_SWITCHES` 16→4096）は 3 switch の `min_putget` では機能差がない。
  - 17 switch 以上の config を CI に載せるときは、この差を再確認する。
- **ビルド成果の受け渡し**: `make install DESTDIR=` によるステージングは不可だった。
  - Cefore の `config/Makefile.am` と `utils/Makefile.am` の独自 `install:` が `DESTDIR` を無視して `/usr/local` に直接書くため。
  - 代わりに make 済みソースツリーを `actions/cache` に保存し、各 job で `sudo make install` する。保存は `make` 直後に明示的に行う（job 失敗時も cache を残すため）。
- **合否判定**: `run_cefore_checks.py --skip-pytest --configs min_putget`。ローカルの cefore-run-tests と同じ判定器を使った。
  - ADR-0004 が却下したのは unit gate をこの runner 経由にする案で、smoke 判定器としての利用とは別。

### 計測結果

環境: `ubuntu-24.04`、Cefore `a9564bb`（v0.12.0）を `--enable-csmgr --enable-cache --enable-debug` でビルド、apt の mininet 2.3.0-1.1 / openvswitch-switch・openvswitch-testcontroller 3.3.9。
workflow は `ci/smoke-prototype` の b258b5d（warm run は空コミット 4b7bbeb）。

| run | cache-hit | configure | make | install | apt mininet/OVS | smoke | job 全体 | 結果 |
|---|---|---|---|---|---|---|---|---|
| 35202408130 (cold) | miss ×3 | 4–15s | 13s | 1–2s | 8–11s | 46–47s | 89–109s | 3/3 green |
| 35202670896 (warm) | hit ×3 | skip | skip | 2–7s | 7–11s | 45–46s | 69–81s | 3/3 green |

- **ビルド時間**: configure + make で 17–28 秒。job 全体の平均は cold 97 秒 → warm 76 秒で 21 秒減り、warm では configure/make が skip された。差は別 runner 上の 2 run の比較で、全部がキャッシュによるとは言えない。
- **キャッシュヒット率**: warm で 3/3。
  - cold では 3 本が並列にビルドし、保存に成功したのは 1 本だけだった（残りは "Unable to reserve cache" の警告で続行）。想定どおり。
  - warm の install ログにある `libtool: install: (… --mode=relink …)` は csmgrd プラグイン 4 つの relink で、再ビルドではない（autoreconf も compile もなし）。
- **Mininet 安定性**: netns と OVS kernel datapath は hosted runner のカーネルで問題なく動いた。TCLink は min_putget にリンクパラメータが無いため `tc` を実質使っておらず、未検証。6 サンプルとも put 1 行・get 3 行が `success=true`、get は completed_log と出力ファイルが揃っている。
- **flakiness**: 6/6 green。6 サンプルで言えるのは「この回数で失敗は出なかった」までで、失敗率は確定していない。
- **artifact**: smoke 出力 3 つをダウンロードして `*private-key*` は 0 件。

### 試作で見つかった不要な処理（12 で本採用するときに削る）

- `systemctl stop/disable openvswitch-testcontroller` は Ubuntu 24.04 に unit が存在せず空振りしていた。サービスが自動起動しないので、そもそも不要。
