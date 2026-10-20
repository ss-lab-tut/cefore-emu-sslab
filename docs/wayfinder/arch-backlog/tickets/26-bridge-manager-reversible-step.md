---
status: open
type: task
claimed-by: claude-main
blocked-by: [25]
---
## Task

**BridgeManager の「元に戻せる操作」を 1 つの部品に集める**:
`bridge_root.py` の BridgeManager で状態を変える操作は 8 つあり、作りが二手に分かれている。
sysctl 2 つ（`enable_ip_forwarding` / `enable_proxy_arp`）と `enable_nat` は事前値の退避・戻り値の確認・
成功時だけの取消登録を持つ。一方 `connect_to_root_ns` / `add_root_route` / `enable_normal_flow` は戻り値を見ず
取消を無条件に登録し（root ns に元からあった経路を teardown で消しうる）、`setup_bridges` の resolv.conf 書き込みは
取消を登録しない（Mininet ホストは mount ns を共有するため **実機の `/etc/resolv.conf` を復元無しに上書き** する）。
0adede1 は `add_host_route` だけを直した。知識に locality が無いので、直すたびに 1 操作ずつの修正になっている。

決定事項（2026-10-20 architecture review の grilling）:

1. 対象は `bridge_root.py` の BridgeManager に限る。`bridge_external.py` の `_RollbackAction` / フラグ台帳には触れない
   （台帳の統一は CONTEXT.md「Bridge modules」で禁止。runner seam は [03](03-s6-bridge-external-runner-seam.md)）。
2. 新しい部品の責務は「自分で行った変更と取消の組」だけ: 実行 → fail-closed で結果を読む → 成功時のみ取消を登録、
   失敗は warn して続行。使うのは `add_host_route` / `connect_to_root_ns` / `add_root_route` / `enable_normal_flow`。
   sysctl 2 つと NAT は固有の手順を残し、結果の読み方だけ共有する（全部入りのオプション束は shallow になる）。
3. root 側経路 2 つを net-tools から iproute2（`ip route add`、既存経路は EEXIST → warn、取消は登録しない）へ移す。
   挙動が変わるのはここだけなのでコミットを分ける。
4. fail-closed な `CommandResult → (rc, detail)` の読み方を 1 つにする（bridge_external の `_fail_closed_rc` の基準）。
   置き場所は `bridge_args.py`（2026-10-20 決定）。CONTEXT.md「Bridge modules」の「共有するのは `bridge_args` だけ」
   「root と attach の相互 import 禁止」を守り、`command_runner.py` には置かない（中断を `rc=-1` で表す約束を
   CommandResult の seam に持ち込むと、「CommandResult」の項の「returncode に特別な値を入れない」に反する）。
   関数は属性を読むだけなので stdlib のみで書ける。bridge_external の今の出力（stderr をそのまま、中断時は理由を追記）
   に合わせ、bridge_root 側はその結果の空白を取り除くだけにする。正常終了したコマンドの出力は両側とも変わらない。
5. resolv.conf: 最初の書き込み前に runner 経由で 1 回だけ退避し、書き戻しを mandatory で登録する。退避に失敗したら
   上書きしない（warn）。Tailscale のようにこのファイルを自前管理する環境は考慮しない。
6. `add_host_route` の default 分岐は `replace` のまま、docstring に「default だけは上書きし、teardown で消す」と書く。

テストの seam: BridgeManager の公開メソッド + `FakeCommandRunner`。失敗時に取消を登録せず warn すること、
fail-closed の読み方の表（timed_out / cancelled / `None` / 非 0 / 0）、resolv の退避と書き戻し（退避失敗で書き込まない）。

[24](24-compute-call-ok-path-test.md) Follow-up の「root ns 側 net-tools」「resolv 書き込み」の 2 項目は本 ticket に移した。

## Status (2026-10-20)

- 起票のみ。[25](25-restore-event-validation.md) の PR の後に着手。
- 2026-10-20 着手（branch `feat/bridge-reversible-step`）。決定 4 の置き場所を `bridge_args.py` に決定。
