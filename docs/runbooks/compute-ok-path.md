# compute_call ok 経路の検証 runbook

arch-backlog ticket 24（2026-09-25）で整備した、`compute_call` の **ok 経路**
（HTTP 2xx → `output_file` 保存 → `publish_uri` を cefputfile → 別ホストの cefgetfile でバイト一致）
を実 Mininet + Cefore で確かめる手順。以前 `config/examples/min_compute.yaml` のコメントにあった
手動 runbook（実行証跡の無いまま残っていた）はこの文書と自動テストに置き換えた。

用語は CONTEXT.md の **Compute endpoint**（`endpoint` URL が指す Mininet 外の HTTP サービス）と
**Event outcome**（`ok` / `not-ok` / `skipped-no-result`）に従う。

## 2 段構えのテスト

| テスト | 何を証明するか | 必要なもの |
|---|---|---|
| `tests/synthetic/test_compute_ok_path_synthetic.py`（hermetic） | Mininet 内の別ホストで動く echo サーバを endpoint にして、scheduler handler の `EventOutcome(outcome="ok")` と三者バイト一致（配った payload == `output_file` == cefgetfile 出力）まで | この機だけ（root） |
| `tests/synthetic/test_compute_ok_path_hpc.py`（HPC） | 同じ到達点を、bridges + root ns の MASQUERADE 経由で **実機の endpoint** に対して | root + `CEFEMU_COMPUTE_ENDPOINT` + 相手側で echo サーバ稼働 |

どちらも `CEFEMU_SYNTHETIC_ROOT=1` かつ root でのみ走り、それ以外では skip する。
cefore-run-tests skill の pytest フェーズは非 root なので **skill 経由では常に skip**。
CI（unit surface のみ、ADR-0004）でも走らない。

## 実行手順

### hermetic 版

```bash
sudo env CEFEMU_SYNTHETIC_ROOT=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python3 -m pytest -p no:cacheprovider tests/synthetic/test_compute_ok_path_synthetic.py
```

`sudo` は venv を落とすので `.venv/bin/python3` を直接指定する。`-p no:cacheprovider` と
`PYTHONDONTWRITEBYTECODE=1` は、共有リポジトリに root 所有の `.pytest_cache` / `__pycache__` を
残さないため（CI と同じ）。10〜13 秒で終わる。

### HPC 版

1. endpoint 側（例: `hpc-debian`）に echo サーバと既知の payload を置いて起動する。
   テストは endpoint 側に ssh しない。起動・停止は人が行う。

   ```bash
   scp tools/compute_echo_server.py <payload.bin> hpc-debian:~/compute-endpoint/
   ssh hpc-debian 'cd ~/compute-endpoint && setsid nohup python3 compute_echo_server.py \
     --bind 0.0.0.0 --port 18080 --payload-file payload.bin > echo_server.out 2> echo_server.err < /dev/null &'
   ssh hpc-debian 'cat ~/compute-endpoint/echo_server.out'   # → listening on 0.0.0.0:18080
   ```

   stdlib のみで動くので endpoint 側に何も入れない（Python 3.7 以降。HPC の 3.13 で確認済み）。80 番は他用途で使用中の
   ことが多いので既定は 18080。`--payload-file` モードでは GET も POST も同じバイト列を返す。

2. この機の root ns から素の `curl` で疎通を取る（bridges 以前の問題を切り分ける）。

   ```bash
   curl -s -o /tmp/probe.bin -w '%{http_code} %{size_download}\n' --max-time 5 \
     -X POST -H 'Content-Type: application/json' -d '{"query":"analyze"}' \
     http://133.15.70.55:18080/api/process
   ```

3. テストを走らせる。

   ```bash
   sudo env CEFEMU_SYNTHETIC_ROOT=1 CEFEMU_COMPUTE_ENDPOINT=http://133.15.70.55:18080/api/process \
     PYTHONDONTWRITEBYTECODE=1 \
     .venv/bin/python3 -m pytest -p no:cacheprovider tests/synthetic/test_compute_ok_path_hpc.py
   ```

4. 終わったら endpoint 側のサーバを止める。

   ```bash
   ssh hpc-debian 'pkill -f "compute_echo_[s]erver"'
   # `pkill -f compute_echo_server.py` だと ssh のリモートシェル自身の引数にもマッチして
   # シェルが先に落ち（exit 255）、サーバが残ることがある。[s] で自己マッチを避ける。
   ```

## 経路の仕組み（HPC 版）

テストは disaster と同じ経路で bridges を組む（`ScenarioSetupSpec.bridge_manager` / `bridge_configs`、
teardown は `TeardownSpec.bridge_manager`）。config は次の 1 件。

```python
{"switch": 0, "root_ip": "auto", "local_routes": "192.168.0.0/16",
 "vm_host_network": "<endpoint IP>/32", "nat": True}
```

- `nat: True` は **opt-in**。無いと ip_forward も MASQUERADE も FORWARD ACCEPT も入らず、
  Mininet ホストからの往復は成立しない（`bridge_root.py` の `use_nat = config.get("nat", False)`）。
- `vm_host_network` は各 Mininet ホストに「endpoint /32 は root ns の .254 経由」の経路を足すだけ。
  2026-09-25 以前の `add_host_route` は net-tools の `route add -net X/32` を使っていて `/32` を黙って
  取りこぼしていた（`SIOCADDRT: Invalid argument`、戻り値未確認）。iproute2 に揃えた修正込みで動く。
  症状は「MASQUERADE も ip_forward も入っているのに h1 の `ip route` に endpoint 向けの行が無い」。
  **`external_routes` は使わない**: 指定すると各ホスト経由で `nameserver 8.8.8.8` が
  **この機の実 /etc/resolv.conf に復元無しで上書き**される（Mininet ホストは mount ns を共有）。
- 送信元は MASQUERADE でこの機のアドレス（133.15.70.25）になるので、endpoint 側に
  Mininet 内部レンジ向けの経路や NAT は不要。戻りは conntrack → root-eth0 の connected route → s0 → h1。
- **前提**: この機の LAN が `192.168.0.0/16` と重ならないこと。root ns にその範囲の経路と
  MASQUERADE `-s 192.168.0.0/16` が入るため、重なる LAN では実機の経路を奪う。

## 詰まったときの診断

テストは h1 からの `curl` 疎通に失敗すると、以下を集めて assert メッセージに載せる。手で見る場合も同じ。

```bash
sudo iptables -t nat -S POSTROUTING     # MASQUERADE -s 192.168.0.0/16 -o ens18 があるか
sudo iptables -S FORWARD | grep -e '^-P' -e root-eth0   # policy と、enable_nat が入れる root-eth0 の ACCEPT / RELATED,ESTABLISHED
sysctl net.ipv4.ip_forward              # テスト中は 1、終了後は元の値（この機は 0）に戻る
ip route                                # root ns: 192.168.0.0/16 dev root-eth0 が一時的に入る
sudo mnexec -a <h1 の cefnetd の PID> ip route  # h1: <endpoint>/32 via 192.168.1.254 dev h1-eth0 が無ければホスト経路が落ちている
```

順に切り分ける: (1) root ns から endpoint に届くか（手順 2）→ (2) `nat: True` が入っているか
→ (3) h1 に endpoint /32 の経路が入っているか（無ければ `add_host_route` の warning を探す）
→ (4) endpoint 側が 133.15.70.25 に返せるか（ファイアウォール、/32 アドレスの経路）。

### fallback: ssh ポートフォワード

endpoint 側で外向きにポートを開けられない場合は、この機で `ssh -L` を張り、**この機自身のアドレス**
（例 133.15.70.25）を endpoint にする。テストは基準バイト列を root ns から取り、Mininet ホストからは
bridge（`vm_host_network` = この機の /32、`nat: true`）経由で root ns に届いたパケットがローカル配送される
ので、config も手順も通常経路と同じ。bridge の `.254` は bridge 作成前には存在しないため endpoint にはできない。

```bash
ssh -N -L 0.0.0.0:18080:localhost:18080 hpc-debian &
sudo env CEFEMU_SYNTHETIC_ROOT=1 CEFEMU_COMPUTE_ENDPOINT=http://133.15.70.25:18080/api/process \
  PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python3 -m pytest -p no:cacheprovider tests/synthetic/test_compute_ok_path_hpc.py
```

`CEFEMU_COMPUTE_ENDPOINT` のホスト部は **数値 IPv4** に限る（Mininet ホストに DNS は無い）。

## 後片付けと注意

- テストの teardown は bridge の経路・iptables・ip_forward を元に戻し、cefnetd を止め、`net.stop()` する。
  `cleanup_all()` / `mn -c` は **使わない**（同じ機の他の Mininet を巻き込む）。
- **smoke（cefore-run-tests）と並行実行しない**。cefnetd のソケット `/tmp/cef_{port}.{idx}` を共有するうえ、
  teardown の `kill_cef_processes` は `pkill -f` で PID namespace 全体の Cefore プロセスを止める。
- 失敗時に root 所有のディレクトリが `/tmp/pytest-of-root/` に残る。消すなら `sudo rm -rf`。
- 実行の証跡は結果行だけで十分だが、初回や環境変更後は 3 回連続 green を確認する。

## 関連

- 計画と決定事項: arch-backlog ticket 24（`docs/wayfinder/arch-backlog/tickets/24-compute-call-ok-path-test.md`）
- 設計の境界: ADR-0003（compute_call は edge-side HTTP に留める）
- glossary: CONTEXT.md「Compute endpoint」「Event outcome」
