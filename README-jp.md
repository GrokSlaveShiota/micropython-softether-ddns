# SoftEther DDNS クライアント — Raspberry Pi Pico 2 W（Wi-Fi 専用）版

※ 本プロジェクトは、Raspberry Pi 上で動作する SoftEther VPN からの
　機能移植を目的に、Grokbot によって開発されました。

- **開発・作成:** Grokbot
- **プロトコル出典:** SoftEther VPN (`src/Cedar/DDNS.c`, `Wpc.c`, `Pack.c` 等)

### Special Thanks
* 素晴らしい言語モデルと高度なコード解析・生成能力で、本プロジェクトをわずか数時間で形にしてくれた **Grok (xAI)** に深く感謝します。
* 学術実験として高品質な DDNS サービスを無料で開放・維持し続けてくださっている **筑波大学 SoftEther Project** および **登 大遊 氏** をはじめとする開発者の皆様に心より感謝申し上げます。

SoftEther VPN Server に内蔵されている DDNS クライアント（`*.softether.net`）のうち、次の 3 機能だけを
MicroPython で再現したものです。Raspberry Pi **Pico 2 W** の **Wi-Fi** で動きます。

1. **新規発行**: 新しい Key でホスト名（`vpnNNNNNNNN.softether.net`）を割り当ててもらう
2. **ホスト名変更**: Web 画面から好きな名前（3〜31 文字）に変える
3. **定期更新**: 成功時は 1〜2 時間ごと、失敗時は 1〜5 分ごとに登録し直して維持する。
   さらに 10〜20 分ごとにグローバル IP を確認し、変わっていたらすぐ再登録する

通信仕様の詳細は `PROTOCOL.md`、同梱すべきライセンス表示は `THIRD_PARTY_LICENSES.txt` を見てください。

## ファイル構成
| ファイル | 内容 |
|---|---|
| `main.py` | 起動処理・DDNS 維持・状態表示 / ホスト名変更 / 初期化 Web 画面（port 80）・ウォッチドッグ |
| `netif.py` | Wi-Fi 接続（DHCP）と再接続 |
| `ddns_softether.py` | DDNS クライアント本体（register / getmyip / Key 生成 / 証明書のハッシュ照合） |
| `dnsfix.py` | 短いタイムアウトの簡易 DNS（UDP）リゾルバ（Pico 2 W の名前解決不具合対策） |
| `config.py` | 機器ごとの設定（タイムアウト、ウォッチドッグ、LED など） |
| `secrets_example.py` | `secrets.py`（Wi-Fi の SSID / パスワード）の見本 |
| `PROTOCOL.md` | DDNS プロトコルの調査メモ |
| `THIRD_PARTY_LICENSES.txt` | 製品に同梱するライセンス表示 |

本機の中に自動で作られるファイル: `ddns_key.txt`（DDNS Key = ホスト名の持ち主の証明）、
`ddns_hostname.txt`（Web で選んだホスト名）、`bootinfo.json`（起動回数と再起動理由）。

## 1. ファームウェアを入れる（MicroPython 公式 v1.29.x）
- 公式ページ: **https://micropython.org/download/RPI_PICO2_W/**
- 確認した版: `RPI_PICO2_W-20260824-v1.29.0.uf2`
  （直リンク https://micropython.org/resources/firmware/RPI_PICO2_W-20260824-v1.29.0.uf2 ）。
  v1.29.x の新しいパッチ版が出ていればそれでも構いません。自作ファームウェアは不要です。
- 書き込み: **BOOTSEL ボタンを押しながら** USB をつなぐ → PC に `RP2350` ドライブが出る → `.uf2` をコピー → 自動で再起動。

## 2. プログラムを書き込む
1. `secrets_example.py` をコピーして `secrets.py` を作り、`WIFI_SSID` と `WIFI_PASSWORD` を書く。
   **`secrets.py` は共有・公開しないでください**（Web 画面・status.json・ログにはパスワードを出しません）。
2. 必要なら `config.py` を直す（通常はそのままで OK。`HOSTNAME = None` なら初回は `vpnNNNNNNNN` が自動で割り当て）。
3. PC に `mpremote` を入れて（`pip install mpremote`）、このフォルダで:
```
mpremote cp main.py netif.py ddns_softether.py dnsfix.py config.py secrets.py :
mpremote reset
```
   **`ddns_key.txt` は消さないでください**（ホスト名を失います）。
4. ログを見る: `mpremote repl`（抜けるのは Ctrl+]）。
   `wifi: connected, IP (DHCP) = 192.168.x.x ...` → `ntp: synced via ...` → `ddns: OK vpnXXXX.softether.net -> グローバルIP` と出れば成功。

## 3. 動作
- 起動 → Wi-Fi に接続（DHCP）→ NTP で時刻合わせ → getmyip でグローバル IP 確認 → DDNS 登録。
  初回は Key を作って `ddns_key.txt` に保存します（Key は本機が作る 20 バイトの乱数。本家と同じく乱数・時刻・本機の ID / MAC を SHA-1 で混ぜて作ります）。
- Wi-Fi が切れたら自動で再接続します。つながらない間も再試行を続けます（固定 IP に切り替わることはありません）。
- 登録先はサーバーが見た送信元 = **ルーターのグローバル IP** です。外から機器に届かせるにはルーターのポート転送などが別途必要です。

### Web 画面（http://<本機の IP>/）
IP はルーターの DHCP 割り当て一覧で確認します。**認証はありません。LAN 内専用**で使い、port 80 を外部に公開しないでください。
DHCPの配布をルーター等で確認できない場合、"ping Pico2W -4"で割り当てられたIPｖ4アドレスを確認できます（Windowsの場合）。
- **状態ページ `/`**（30 秒ごとに自動更新）: Wi-Fi の状態 / SSID / 電波強度 / MAC / IP・ゲートウェイ・DNS / グローバル IP /
  ホスト名・FQDN / 最後の結果（0 = 正常、132〜137、-1 = 通信エラー）/ 最後と次回の登録 / 稼働時間 / 空きメモリ / 時刻 /
  起動回数と前回の再起動理由 / ウォッチドッグ / 証明書確認の結果。`/status.json` で同じ内容を JSON で取得できます。
- **ホスト名の変更**: 状態ページ下の欄に新しい名前を入れて **OK**（確認ダイアログあり）。3〜31 文字、英数字と `-`（先頭・末尾は不可）。
  結果（成功 / 133 = 使用中 など）を日本語で表示します。選んだ名前は `ddns_hostname.txt` に保存され、再起動後も維持されます。
  古い名前は手放されます。
- **初期化ページ `/init`**（状態ページ下のリンク「初期化（DDNS Key の削除）」）: 下の「初期化」参照。

## 4. 初期化（DDNS Key の削除）— Wi-Fi 版の方式
有線版にある「DHCP 失敗時に固定 IP で起動する初期化モード」は、Wi-Fi では PC を直結できないため作っていません。
代わりに、いちばん単純で確実な方法として **通常の Web 画面の中に初期化ページ** を置いています。
1. `http://<本機の IP>/init` を開く（状態ページ下のリンクからも行けます）。MAC、IP、今のホスト名、Key の有無が表示されます。
2. 「確認のため DELETE と入力」に大文字で `DELETE` と入れ、**Key を削除する** → 確認ダイアログで OK。
3. `ddns_key.txt` と `ddns_hostname.txt` を削除し、5 秒後に自動で再起動します。削除から再起動までは DDNS 登録を止めます。
4. 再起動後、新しい Key で新しいホスト名（`vpnNNNNNNNN`）が割り当てられます。状態ページで確認してください。
- `DELETE` 以外の文字（小文字の `delete` など）では何も削除しません。`GET /reset` は存在しません（404）。
- 登録処理の最中は受け付けず「少し待ってから」と表示します。
- **Wi-Fi につながらない場合**（SSID・パスワード変更など）は Web 画面に入れないので、USB で操作します:
  - Wi-Fi 設定を直す: `secrets.py` を書き直して `mpremote cp secrets.py :` → `mpremote reset`
  - Key を消す: `mpremote rm :ddns_key.txt` と `mpremote rm :ddns_hostname.txt` → `mpremote reset`
  - WDT が動いていると作業中にリセットされることがあるので、先に下の「セーフモード」にしてください。

> ⚠ **Key を消すと、今のホスト名は二度と取り戻せません。** 残したい場合は先に
> `mpremote cp :ddns_key.txt ddns_key_backup.txt` でバックアップ（戻すときは `mpremote cp ddns_key_backup.txt :ddns_key.txt`）。
> 同じ Key を 2 台で同時に動かさないでください（交互に IP が書き換わります）。
> 同じ LAN の誰でも初期化ページを開けます（ホスト名変更と同じく認証なし）。LAN 内専用で使ってください。

## 5. LED（本体の LED）
| 表示 | 意味 |
|---|---|
| 点灯 | 正常（DDNS 登録成功） |
| ゆっくり点滅（1 秒点灯 / 1 秒消灯） | Wi-Fi はつながっているが DDNS 未登録・エラー |
| 速い点滅 | Wi-Fi 未接続（接続中・再試行中） |
| 2 回ずつ点滅 | Key 削除後、再起動待ち |
| 起動直後 3 秒間の速い点滅 | セーフモード受付中（このとき BOOTSEL を押すとセーフモード） |
`config.py` の `USE_LED = False` で無効。

## 6. 止まった時の備え（自動復旧）
- **ウォッチドッグ**（`USE_WDT = True`、8 秒）: 専用タスクが 1 秒ごとに給餌。メインループが 2 分以上止まると給餌をやめ、本機がリセットされます。
  ソケット操作は 3 秒、DNS は 1 回 2 秒でタイムアウトし、TLS・DNS の合間にも給餌します。
- **例外ガード**: 想定外の例外が起きたらログを出し、10 秒後に再起動。
- **長時間失敗で再起動**: 6 時間（`NO_SUCCESS_REBOOT_S`）DDNS 登録に一度も成功しなければ再起動。
- **起動回数・再起動理由**: `bootinfo.json` に記録し状態ページに表示（書き込みは起動時と意図的な再起動の直前だけ）。

## 7. 復旧・開発時の操作（セーフモード）
rp2 のウォッチドッグは一度動くと止められません（Ctrl+C で REPL に入っても約 8 秒でリセット）。ファイル操作の前にどちらかにします:
- **セーフモード**（main.py の処理を始めない・WDT も動かない）:
  - 電源投入・リセット後、**LED が速く点滅している最初の 3 秒間に BOOTSEL を押す**
    （電源を入れる「前」から押していると USB 書き込みモードになるので、起動してから押す）。
  - または `mpremote touch :safemode` → `mpremote reset`。戻すときは `mpremote rm :safemode` → `mpremote reset`。
- **WDT だけ無効**: `mpremote touch :nowdt`（戻すときは `mpremote rm :nowdt`）、または `config.py` で `USE_WDT = False`。
- それでも動かない場合: ファームウェアを入れ直す（BOOTSEL を押しながら USB 接続 → `.uf2` をコピー）。
  ファイルは残りますが、念のため `ddns_key.txt` はバックアップしておいてください。

## 8. Pico 2 W の名前解決（DNS）について
Pico 2 W の MicroPython で `socket.getaddrinfo()` が `OSError -2` になる現象を確認しています（UDP 通信自体は可能）。
`dnsfix.py` が DHCP で受け取った DNS → 8.8.8.8 → 1.1.1.1 の順に自前で問い合わせます（1 台 2 秒、2 回まで）。
NTP も `ntptime` を使わず main.py 内の小さな SNTP 処理で合わせます。

## 9. 証明書の確認（なりすまし対策）
Key を送る前に、DDNS サーバーの証明書の SHA-1 ハッシュを本家と同じ組み込みの 9 個（`DDNS_CERT_HASH`）と照合し、
一致しなければ **Key を送らずに失敗** します（`tls` モジュールの `CERT_OPTIONAL` + `verify_callback`）。証明書ファイルは不要です。
状態ページの「サーバー証明書」欄に `pinned via verify_callback EFAC5FA0` のように表示されます。

## 10. 実機確認の状況
- Pico 2 W（公式 v1.29 系ファーム）+ Wi-Fi で、DDNS 登録・証明書確認（verify_callback）・Web 画面からのホスト名変更は確認済み

## 11. 利用条件
- softether.net の DDNS は筑波大学の SoftEther プロジェクトが**学術実験として無料で提供**しているサービスで、無保証・予告なしの停止があり得ます。
  本来は SoftEther VPN Server 用の機能です。製品に組み込んで納品する場合はこの点をお客様に説明してください。
- 送信内容で `product_str="SoftEther OSS"` などを名乗っています（本家と同じ値）。登録間隔も本家と同じです。
