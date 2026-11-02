# SoftEther DDNS クライアント — WIZnet W5100S-EVB-Pico2（有線 LAN 専用）版

※ 本プロジェクトは、Raspberry Pi 上で動作する SoftEther VPN からの
　機能移植を目的に、Grokbot によって開発されました。

- **開発・作成:** Grokbot
- **プロトコル出典:** SoftEther VPN (`src/Cedar/DDNS.c`, `Wpc.c`, `Pack.c` 等)

### Special Thanks
* 素晴らしい言語モデルと高度なコード解析・生成能力で、本プロジェクトをわずか数時間で形にしてくれた **Grok (xAI)** に深く感謝します。
* 学術実験として高品質な DDNS サービスを無料で開放・維持し続けてくださっている **筑波大学 SoftEther Project** および **登 大遊 氏** をはじめとする開発者の皆様に心より感謝申し上げます。

SoftEther VPN Server に内蔵されている DDNS クライアント（`*.softether.net`）のうち、次の 3 機能だけを
MicroPython で再現したものです。WIZnet **W5100S-EVB-Pico2**（RP2350 + W5100S）の **有線 LAN** で動きます。

1. **新規発行**: 新しい Key でホスト名（`vpnNNNNNNNN.softether.net`）を割り当ててもらう
2. **ホスト名変更**: Web 画面から好きな名前（3〜31 文字）に変える
3. **定期更新**: 成功時は 1〜2 時間ごと、失敗時は 1〜5 分ごとに登録し直して維持する。
   さらに 10〜20 分ごとにグローバル IP を確認し、変わっていたらすぐ再登録する

通信仕様の詳細は `PROTOCOL.md`、同梱すべきライセンス表示は `THIRD_PARTY_LICENSES.txt` を見てください。

## ファイル構成
| ファイル | 内容 |
|---|---|
| `main.py` | 起動処理・DDNS 維持・状態表示 / ホスト名変更 / 初期化・機器入れ替え Web 画面（port 80）・ウォッチドッグ |
| `netif.py` | 有線 LAN（W5100S）の初期化、DHCP、固定 IP へのフォールバック、ケーブル抜き差しへの対応 |
| `ddns_softether.py` | DDNS クライアント本体（register / getmyip / Key 生成 / 証明書のハッシュ照合） |
| `initpw.py` | 設定ページ `/init` のパスワード（HTTP Basic 認証、既定は MAC アドレス） |
| `netcfg.py` | 固定 IP 設定（`netcfg.json`）の入力チェック・保存・削除と設定画面 |
| `dnsfix.py` | 短いタイムアウトの簡易 DNS（UDP）リゾルバ |
| `keyxfer.py` | DDNS Key の書き出し・読み込み（機器入れ替え用） |
| `config.py` | 機器ごとの設定（ネットワーク、タイムアウト、ウォッチドッグ、LED など） |
| `PROTOCOL.md` | DDNS プロトコルの調査メモ |
| `THIRD_PARTY_LICENSES.txt` | 製品に同梱するライセンス表示 |

本機の中に自動で作られるファイル: `ddns_key.txt`（DDNS Key = ホスト名の持ち主の証明）、
`ddns_hostname.txt`（Web で選んだホスト名）、`bootinfo.json`（起動回数と再起動理由）、`netcfg.json`（Web で固定 IP を設定したときだけ）、`initpw.json`（パスワードを変更したときだけ。salt 付きハッシュのみ）。
Wi-Fi を使わないので `secrets.py` は不要です。

## 1. ファームウェアを入れる（WIZnet 版 MicroPython v1.29.0-preview）
- 配布元: **https://github.com/WIZnet-ioNIC/WIZnet-EVB-Pico-micropython/releases**
- 使用するファイル: リリース `v1.29.0-WIZnet-timeout` の **`LWIP-W5100S_EVB_PICO2-v1.29.0-preview.uf2`**
  （リリースページ https://github.com/WIZnet-ioNIC/WIZnet-EVB-Pico-micropython/releases/tag/v1.29.0-WIZnet-timeout ）。
  名前が `LWIP-` で始まるもの（lwIP 版）を選んでください。`TOE-` 版や MicroPython 公式の Pico 2 用ファームでは動きません。
- 書き込み: **BOOTSEL ボタンを押しながら** USB をつなぐ → PC に `RP2350` ドライブが出る → `.uf2` をコピー → 自動で再起動。

## 2. プログラムを書き込む
1. 必要なら `config.py` を直す（通常はそのままで OK。`HOSTNAME = None` なら初回は `vpnNNNNNNNN` が自動で割り当て）。
2. PC に `mpremote` を入れて（`pip install mpremote`）、このフォルダで:
```
mpremote cp main.py netif.py netcfg.py initpw.py ddns_softether.py dnsfix.py keyxfer.py config.py :
mpremote reset
```
   **`ddns_key.txt` は消さないでください**（ホスト名を失います）。
3. LAN ケーブルをつなぐ。ログを見る: `mpremote repl`（抜けるのは Ctrl+]）。
   `lan: connected, IP (DHCP) = 192.168.x.x ...` → `ntp: synced via ...` → `ddns: OK vpnXXXX.softether.net -> グローバルIP` と出れば成功。

### config.py の主な設定
| 設定 | 既定値 | 内容 |
|---|---|---|
| `LAN_PINS` | `None` | W5100S の配線（SPI0: MISO=GP16, CS=GP17, SCK=GP18, MOSI=GP19, RSTn=GP20, INTn=GP21）。`None` でボード既定。変えるときだけ差分を書く（例 `{"baudrate": 10_000_000}`） |
| `LAN_DHCP_TIMEOUT` | `12` | リンク確立後、この秒数で DHCP が取れなければ固定 IP へ |
| `LAN_LINK_WAIT` | `4` | この秒数リンクが立たなければ「ケーブル未接続」とみなして固定 IP へ |
| `LAN_DHCP_RETRY` | `60` | 固定 IP の間の DHCP 再試行間隔（秒。0 で再試行しない） |
| `LAN_FALLBACK_IP` | `("192.168.14.199", "255.255.255.0", "192.168.14.1", "192.168.14.1")` | 固定 IP（IP, マスク, ゲートウェイ, DNS） |
| `NET_HOSTNAME` | `"Pico2W"` | DHCP サーバーに送る機器名 |
| `HOSTNAME` | `None` | DDNS のホスト名。Web 画面で変えた名前が優先 |
| `MACHINE_NAME` | `"micropython"` | DDNS サーバーに送る機器名 |
| `WEB_PORT` | `80` | Web 画面のポート |
| `TZ_OFFSET` | `9 * 3600` | 表示用のタイムゾーン（JST） |
| `USE_NTP` / `NTP_HOST` | `True` / `"pool.ntp.org"` | 時刻合わせ |
| `USE_WDT` / `WDT_TIMEOUT_MS` | `True` / `8000` | ウォッチドッグ |
| `NO_SUCCESS_REBOOT_S` | `6 * 3600` | この秒数 DDNS 登録に一度も成功しなければ再起動（0 で無効。DHCP 失敗による固定 IP の間は再起動しない。固定 IP 設定で動作中は DHCP と同じく対象） |
| `CRASH_REBOOT_DELAY_S` | `10` | 想定外の例外のあと再起動するまでの秒数 |
| `USE_LED` / `LED_PIN` | `True` / `25` | 本体 LED（GP25）での状態表示 |

## 3. 動作
- 起動 → W5100S を初期化 → リンク確認 → DHCP → NTP で時刻合わせ → getmyip でグローバル IP 確認 → DDNS 登録。
  初回は Key を作って `ddns_key.txt` に保存します（Key は本機が作る 20 バイトの乱数。本家と同じく乱数・時刻・本機の ID / MAC を SHA-1 で混ぜて作ります。MAC は W5100S のもの）。
- **固定 IP 設定（`netcfg.json`）があるとき**は DHCP を使わず、通信できるかどうかに関係なく常にその IP で動作します（下の「固定 IP 設定」参照）。
- **DHCP が取れない・ケーブル未接続のとき**は、固定 IP `192.168.14.199/24`（ゲートウェイ・DNS `192.168.14.1`）で起動します。
  固定 IP の間は 60 秒ごとに DHCP を再試行し、取れれば自動で DHCP に切り替わります。
- ケーブルを抜くと「切断」と表示し、挿し直すと最初からやり直します（DHCP → 取れなければ固定 IP）。
  DHCP のアドレスが 60 秒以上なくなった場合も初期化し直します。経路が変わったときはすぐにグローバル IP の確認と登録を行います。
- NTP の時刻合わせは起動後と、その後 24 時間ごとに行います（失敗時は 60 秒後に再試行）。時刻は表示用で、登録間隔には使いません。
- 登録先はサーバーが見た送信元 = **ルーターのグローバル IP** です。外から機器に届かせるにはルーターのポート転送などが別途必要です。

### 固定 IP 設定
`/init` ページの「ネットワーク設定（固定 IP）」で、IP アドレス・サブネットマスク・ゲートウェイ・DNS を入力して
**保存して再起動**（確認ダイアログあり）を押すと `netcfg.json` に保存され、再起動後はその IP で動作します。
- 入力は保存前に確認します（IPv4 の形式、IP とゲートウェイが同じサブネットにあること、ネットワークアドレス・ブロードキャストアドレスでないこと など）。
- 保存後の画面に新しい URL（`http://<設定した IP>/`）が表示され、約 20 秒後に自動で移動します。PC が同じサブネットにある必要があります。
- **削除して DHCP に戻す**（確認ダイアログあり）で設定を消し、再起動後は DHCP で動作します。
- `netcfg.json` が壊れている・値が不正な場合は無視して DHCP で起動し、状態ページに警告を表示します。

**設定した IP が分からない・つながらないとき**
1. USB で接続して `netcfg.json` を削除し、再起動します（DHCP で起動します）:
   `mpremote rm :netcfg.json` → `mpremote reset`（Thonny ならファイル一覧から `netcfg.json` を削除）。
   プログラムが動いていて接続しにくいときは「セーフモード」で起動してから操作します。
2. 設定した IP に PC から届く場合は、`http://<設定した IP>/init` から直接変更・削除できます。

### Web 画面（http://<本機の IP>/）
IP はルーターの DHCP 割り当て一覧で確認します。状態ページは認証なし、設定ページ `/init` はパスワードが必要です。**LAN 内専用**で使い、port 80 を外部に公開しないでください。
DHCPの配布をルーター等で確認できない場合、"ping Pico2W -4"で割り当てられたIPｖ4アドレスを確認できます（Windowsの場合）。
固定 IP で動作している場合は `http://192.168.14.199/` です（PC 側を同じ 192.168.14.x のアドレスにして開きます）。
- **状態ページ `/`**（30 秒ごとに自動更新。表示専用でパスワード不要）: 接続方式 / リンク（ケーブル）/ IP の取得方法（固定（設定）・DHCP・固定（フォールバック）、DHCP 再試行までの時間）/
  MAC / IP・サブネットマスク・ゲートウェイ・DNS / グローバル IP / ホスト名・FQDN / 登録された IPv4 / 最後の結果（0 = 正常、132〜137、-1 = 通信エラー）/
  最後と次回の登録 / 稼働時間 / 空きメモリ / 時刻 / 起動回数と前回の再起動理由 / ウォッチドッグ / 証明書確認の結果。
  固定 IP で動作中はページ上部に注意表示が出ます。`/status.json` で同じ内容を JSON で取得できます。
- **設定ページ `/init`**（状態ページ下のリンク「設定・初期化」。**パスワードが必要**）: 項目ごとに折りたたまれていて、見出しをクリックすると開きます。
  ホスト名の変更 / パスワードの変更 / ネットワーク設定（固定 IP）/ 初期化・機器入れ替え（DDNS Key）。
- **パスワード**: 誤操作を防ぐためのもので、強いセキュリティではありません（通信は暗号化されません）。
  ブラウザが聞いてきたら、ユーザー名は何でもよく（空でも可）、パスワードは**既定では本機の MAC アドレス**（状態ページに表示。
  大文字小文字・`:` `-` の有無は問いません。例 `02:00:00:00:00:01` / `020000000001`）を入力します。
  間違えると少しずつ応答が遅くなります。
  変更は `/init` の「パスワードの変更」で、現在のパスワード・新しいパスワード（4〜64 文字）・確認を入力して **変更**（確認ダイアログあり）。
  本機には salt 付きのハッシュだけを `initpw.json` に保存します。
  **忘れたとき**は USB で `mpremote rm :initpw.json` → `mpremote reset`（Thonny ならファイル一覧から削除）で MAC アドレスに戻ります。
- **ホスト名の変更**: `/init` の「ホスト名の変更」に新しい名前を入れて **OK**（確認ダイアログあり）。3〜31 文字、英数字と `-`（先頭・末尾は不可）。
  結果（成功 / 133 = 使用中 など）を日本語で表示します。選んだ名前は `ddns_hostname.txt` に保存され、再起動後も維持されます。
  古い名前は手放されます。
- 固定 IP 設定と初期化・機器入れ替えは、上の「固定 IP 設定」と下の「初期化・機器入れ替え」参照。

## 4. 初期化・機器入れ替え（DDNS Key）
`http://<本機の IP>/init` を開く（パスワードが必要）と、MAC、IP、今のホスト名、Key の有無、起動回数が表示されます。
操作は 3 つで、どれもボタンを押したあと**確認ダイアログで OK** を押したときだけ実行されます（JavaScript やダイアログが動かない場合は何もしません）。
- **Key の書き出し**: **Key を書き出す（ddns_key.txt）** で、この機器の `ddns_key.txt` をダウンロードします。
  新しい機器に読み込むと、同じホスト名を引き継げます。
- **Key の読み込み**: 古い機器から書き出した `ddns_key.txt` を選んで **Key を読み込む**。今の Key を上書きし、
  `ddns_hostname.txt` を消して 5 秒後に再起動し、その Key に結びついたホスト名で登録を続けます。
  Key は 16 進数 40 文字（大文字・小文字、前後の空白・改行は可）。
- **Key の削除**: **Key を削除する** で `ddns_key.txt` と `ddns_hostname.txt` を削除し、5 秒後に自動で再起動します。
  再起動後、新しい Key で新しいホスト名（`vpnNNNNNNNN`）が割り当てられます。
- 再起動を伴う操作のあとは、画面が再起動を待って自動でトップページに戻ります。削除・読み込みから再起動までは DDNS 登録を止めます。
- 登録処理の最中は受け付けず「少し待ってから」と表示します。`GET /reset` などは存在しません（404）。
- **Web 画面に入れない場合**は USB で操作します:
  - Key を消す: `mpremote rm :ddns_key.txt` と `mpremote rm :ddns_hostname.txt` → `mpremote reset`
  - WDT が動いていると作業中にリセットされることがあるので、先に下の「セーフモード」にしてください。

> ⚠ **書き出した `ddns_key.txt` は秘密にしてください。** このファイルを持っている人は誰でもこのホスト名の持ち主になれます
> （メールやチャットで送らない・共有フォルダに置かない）。Key はログ・状態ページ・status.json には出しません。
> ⚠ **Key を書き出さずに削除すると、今のホスト名は二度と取り戻せません。** USB でのバックアップは
> `mpremote cp :ddns_key.txt ddns_key_backup.txt`（戻すときは `mpremote cp ddns_key_backup.txt :ddns_key.txt`）。
> 同じ Key を 2 台で同時に動かさないでください（交互に IP が書き換わります）。機器を入れ替えるときは古い機器の電源を切ってから。
> このページはパスワードで保護されていますが、誤操作防止のためのものです。LAN 内専用で使ってください。

## 5. LED（本体の LED、GP25）
| 表示 | 意味 |
|---|---|
| 点灯 | 正常（DDNS 登録成功） |
| ゆっくり点滅（1 秒点灯 / 1 秒消灯） | ネットワークはつながっているが DDNS 未登録・エラー |
| 2 秒に 1 回短く点灯 | 固定 IP（DHCP なし）で動作中 |
| 速い点滅 | ネットワーク未接続（ケーブル抜け・初期化失敗） |
| 2 回ずつ点滅 | Key の削除・読み込み後、再起動待ち |
| 起動直後 3 秒間の速い点滅 | セーフモード受付中（このとき BOOTSEL を押すとセーフモード） |

`config.py` の `USE_LED = False` で無効。

## 6. 止まった時の備え（自動復旧）
- **ウォッチドッグ**（`USE_WDT = True`、8 秒）: 専用タスクが 1 秒ごとに給餌。メインループが 2 分以上止まると給餌をやめ、本機がリセットされます。
  ソケット操作は 3 秒、DNS は 1 回 2 秒でタイムアウトし、TLS・DNS の合間にも給餌します。
- **例外ガード**: 想定外の例外が起きたらログを出し、10 秒後に再起動。
- **長時間失敗で再起動**: 6 時間（`NO_SUCCESS_REBOOT_S`）DDNS 登録に一度も成功しなければ再起動（DHCP 失敗による固定 IP 192.168.14.199 で動作中は再起動しません）。
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

## 8. 名前解決（DNS）について
`dnsfix.py` が DHCP で受け取った DNS（固定 IP の間は `LAN_FALLBACK_IP` の DNS）→ 8.8.8.8 → 1.1.1.1 の順に自前で問い合わせます（1 台 2 秒、2 回まで）。
ウォッチドッグが有効なときは、タイムアウトを短く抑えられない内蔵の `getaddrinfo` は使いません。
NTP も `ntptime` を使わず main.py 内の小さな SNTP 処理で合わせます。

## 9. 証明書の確認（なりすまし対策）
Key を送る前に、DDNS サーバーの証明書の SHA-1 ハッシュを本家と同じ組み込みの 9 個（`DDNS_CERT_HASH`）と照合し、
一致しなければ **Key を送らずに失敗** します（`tls` モジュールの `CERT_OPTIONAL` + `verify_callback`）。証明書ファイルは不要です。
状態ページの「サーバー証明書」欄に `pinned via verify_callback EFAC5FA0` のように表示されます。

## 10. 利用条件
- softether.net の DDNS は筑波大学の SoftEther プロジェクトが**学術実験として無料で提供**しているサービスで、無保証・予告なしの停止があり得ます。
  本来は SoftEther VPN Server 用の機能です。製品に組み込んで納品する場合はこの点をお客様に説明してください。
- 送信内容で `product_str="SoftEther OSS"` などを名乗っています（本家と同じ値）。登録間隔も本家と同じです。

## 11. ライセンス
- 本パッケージの Python ファイル（`main.py`, `netif.py`, `netcfg.py`, `initpw.py`, `ddns_softether.py`, `dnsfix.py`, `keyxfer.py`, `config.py`）は、
  SoftEther VPN のプロトコルを読み解いて新たに書いたもので、SoftEther のコードはコピーしていません。
  ただし定数（URL、証明書ハッシュ `DDNS_CERT_HASH` など）は SoftEther VPN（Apache License 2.0）のソースに由来します。
- ファームウェア（WIZnet 版 MicroPython、本パッケージには同梱していません）には次のソフトウェアが含まれます:
  MicroPython（MIT）、micropython-lib（MIT）、Raspberry Pi pico-sdk（BSD-3-Clause）、TinyUSB（MIT）、lwIP（BSD-3-Clause）、
  Mbed TLS（Apache-2.0）、WIZnet ioLibrary_Driver（MIT）。
- 製品として納品する場合は `THIRD_PARTY_LICENSES.txt` を（印刷物・PDF・ファイルのいずれかで）お客様に渡してください。
