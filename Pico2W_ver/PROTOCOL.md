# SoftEther DDNS（*.softether.net）通信仕様メモ

SoftEtherVPN（GitHub master、2026-10-21 時点の shallow clone）のソースコードから読み取った内容です。
参照ファイル: `src/Cedar/DDNS.c` `DDNS.h` `Wpc.c` `Wpc.h`、`src/Mayaqua/Pack.c` `Memory.c` `Network.c` `HTTP.c` `Encoding.c`。
「✅ 実測」は 2026-10-21 に実サーバーで確認したもの、「⚠ 未検証」はソースを読んだだけのものです。

## 1. 全体の流れ
1. クライアントは 20 バイトの **Key** を 1 つ持つ（ホスト名はこの Key に結びつく）。
2. `register` を HTTPS POST で呼ぶ。新しい Key なら `vpnNNNNNNNN` 形式のホスト名が自動で割り当てられる。
3. 同じ Key で定期的に `register` を呼び直すと登録が維持され、IP も更新される。
4. `new_hostname` を付けて `register` するとホスト名を変更できる。

## 2. Key
- 長さ 20 バイト（SHA1_SIZE）。`DCGenNewKey` = SHA1(乱数20B + 各種tick + マシンハッシュ) XOR 乱数20B。要するに 20 バイトの乱数。
- 本実装の `new_key()` も同じ式: SHA1(`os.urandom(20)` + `ticks_us` + `ticks_ms` + `time_ns` + マシンハッシュ) XOR `os.urandom(20)`。マシンハッシュ = SHA1(`machine.unique_id()` + Wi-Fi（CYW43）の MAC)。`os.urandom` は rp2 では pico-sdk の `get_rand_64()`（RP2350 ではハードウェア TRNG などをエントロピー源にした乱数）。
- 保存場所（本家）: `vpn_server.config` の `declare DDnsClient { byte Key <Base64> }`。
- 送信時は **大文字 16 進 40 文字**（`key`）。
- この Key を別の機械に移せば同じホスト名を使い続けられる（本実装でも `key_from_vpn_server_config()` で取り込み可能）。

## 3. 接続先 URL
```
https://x{c1}.x{c2}.dev.open.servers.ddns.softether-network.net/ddns/ddns.aspx?v={64bit乱数の10進}
```
- `DDNS_URL_V4_GLOBAL` は `...dev.servers.ddns...` だが、コード内で `.servers` → `.open.servers` に置換される。
- `c1, c2` = SHA1(大文字16進のKey文字列) を **小文字16進** にした文字列の 3 文字目と 4 文字目（index 2, 3）。
- IPv6 用は `servers-v6`、中国向けは `ddns.uxcom.jp`、NTT フレッツ閉域網向けの代替 URL もある（本実装では未対応）。
- ポート 443、メソッド POST。

## 4. TLS
- **SNI はホスト名ではなく文字列 `DDNS`**（`DDNS_SNI_VER_STRING`）。
- CA による証明書検証はしない。代わりに **サーバー証明書（DER）の SHA-1** が `DDNS_CERT_HASH` の 9 個のどれかと一致することを確認（ピン留め）。一致しなければ `ERR_CERT_NOT_TRUSTED`。
- ✅ 実測（2026-10-21）: 証明書は自己署名 1 枚のみ（中間 CA なし）。
  - Subject = Issuer = `CN=ddns-register-1.sehosts.com, O=sehosts.com, C=JP`
  - X.509 v1（拡張なし）、RSA 2048、sha1WithRSAEncryption、有効期間 2012-09-17 〜 **2037-01-19**
  - SHA-1 = `EFAC5FA0CDD14E0F864EED58A73C35D7E33B62F3`（9 個のリストの 3 番目）
  - 256 個の `x?.x?` 名は 2 つの IP（130.158.6.119 / 103.41.63.66、DNS-over-HTTPS で確認）に集約され、両方とも同じ証明書。残り 8 個のハッシュの証明書は観測できず。
- ✅ MicroPython v1.29.0（unix 版、mbedTLS 3.6.6、rp2 と同じ共通 TLS 設定）での確認結果:
  - `CERT_REQUIRED` + cadata（この証明書）+ `server_hostname=実ホスト名` → 失敗（「CN 不一致」「署名ハッシュが不可」）。
    SHA-1 署名は mbedTLS の既定プロファイルで拒否されるため、CN を合わせても CA 検証方式は通らない。
  - `getpeercert` は無い（`MBEDTLS_SSL_KEEP_PEER_CERTIFICATE` が無効。Pico 2 W と同じ）。
  - `ssl` モジュール（micropython-lib のラッパー）では `verify_callback` が下の `tls.SSLContext` に渡らない。**`tls` モジュールを直接使う必要がある**。
  - `tls.SSLContext` + `CERT_OPTIONAL` + `verify_callback(cert, depth)` → depth 0 で証明書 DER が渡され、ハッシュ照合可能。callback が 0 以外を返すとハンドシェイク失敗（＝Key 送信前に遮断）。`CERT_NONE` では callback は呼ばれない。
- 本実装の照合先: 本家と同じ **組み込みの 9 個のハッシュ（`DDNS_CERT_HASH`）のみ**（証明書ファイルの読み込みはしない）。照合できない環境では Key を送らずに失敗（fail closed）。
- 本実装の SNI: 実機では `DDNS`。検証環境のプロキシの都合で、PC での試験は実ホスト名を SNI にしている（サーバーは SNI に関係なく同じ証明書を返す）。
- ✅ 実機（Pico 2 W）では TLS 1.2（`TLS-RSA-WITH-AES-128-CBC-SHA`）で接続できる見込み（PC 上の MicroPython で同じ暗号スイートを確認。実機は証明書確認なしで登録成功済み）。

## 5. HTTP リクエスト
本家が送るヘッダ:
```
POST /ddns/ddns.aspx?v=... HTTP/1.1
Keep-Alive: timeout=15; max=19
Connection: Keep-Alive
Accept-Language: ja
User-Agent: Mozilla/5.0 (Windows NT 6.3; WOW64; rv:29.0) Gecko/20100101 Firefox/29.0
Pragma: no-cache
Cache-Control: no-cache
Host: <ホスト名>
Content-Type: application/x-www-form-urlencoded
Content-Length: <本文の長さ>
```
本実装は Host / User-Agent / Content-Type / Content-Length / `Connection: close` のみ送信（✅ これで成功）。
応答は HTTP 200 以外ならエラー、本文は `Content-Length` 分だけ読む。

## 6. 本文の形式（WPC）
ASCII 文字列で、次の「エントリ」を連結したもの:
```
名前4文字（大文字、足りなければ空白埋め） + 長さ10桁（"%010u"） + Safe64(データ)
```
- Safe64 = 改行なし標準 Base64 の `=`→`(`、`+`→`)`、`/`→`_` 置換。
- リクエスト: `PACK`（PACK のバイナリ）、`HASH`（PACK バイナリの SHA-1、20B）。
- 応答も同じ形式。`HASH` があれば SHA-1 を照合。`CERT`/`SIGN`（RSA 署名）が付く場合もあるが DDNS では ✅ 実測で付いていなかった。
- 例: `PACK0000000064AAAAAgAAAA...HASH0000000028y7OPBWG64ynkTLxxymfe0EG13qg(`

## 7. PACK バイナリ（すべてビッグエンディアン）
```
u32 要素数
要素 = u32 (名前長+1) | 名前バイト（NUL なし） | u32 型 | u32 値の個数 | 値...
型: 0=INT(u32) 1=DATA(u32長+バイト) 2=STR(u32長+バイト) 3=UNISTR(u32長+UTF-8、NUL込み) 4=INT64(u64)
```
- 要素名は大文字小文字を区別しない（✅ 応答のエラーは `Error` という名前で返ってきた）。
- bool は INT の 0/1。

## 8. register の送信項目
| 名前 | 型 | 本家の値 | 本実装 |
|---|---|---|---|
| key | STR | Key の大文字16進 | 同じ |
| build | INT | ビルド番号（既定 5187） | 5187 |
| osinfo | INT | OS 種別（Linux=3100） | 3100 |
| is_64bit | INT | 0/1 | 0 |
| is_softether | INT | 1 | 1 |
| is_packetix | INT | 0 | 0 |
| machine_key | STR | マシン情報の SHA-1 大文字16進 | Key から作った固定値 |
| machine_name | STR | ホスト名（小文字） | 引数（既定 `micropython`） |
| lasterror_ipv4 / lasterror_ipv6 | INT | 直前の getmyip のエラー | 0 |
| use_azure | INT | VPN Azure 使用 | 0 |
| product_str | STR | `SoftEther OSS` | 同じ |
| ddns_protocol_version | INT | 1 | 1 |
| ddns_oss | INT | 1 | 1 |
| new_hostname | STR | ホスト名変更時のみ | 同じ |
| function | STR | `register`（WpcCall が付加） | 同じ |

Windows 版のみ `is_windows_64bit`、Azure 有効時のみ `current_azure_ip` が付く（本実装では送らない）。
⚠ どの項目がサーバー側で必須かは不明。全項目を送る形で ✅ 成功を確認済み（項目を減らす試験は登録回数を増やすため行っていない）。

## 9. 応答の項目
| 名前 | 意味 |
|---|---|
| error | 0=成功（✅ 実際は `Error`） |
| current_hostname / current_fqdn | 現在のホスト名 / FQDN |
| current_ipv4 / current_ipv6 | サーバーが見た送信元 IP（＝登録された IP） |
| dns_suffix | `.softether.net` |
| current_region | 地域（✅ `US`） |
| DynList | 本家の動的設定値（DATA） |
| current_azure_ip, current_azure_timestamp, current_azure_signature, azure_cert_hash, snat_t | Azure / SecureNAT 用（本実装では無視） |

## 10. エラーコード（Cedar.h）
| 番号 | 意味 | 本家の動作 |
|---|---|---|
| 0 | 成功 | |
| 132 | Key 重複 | 新しい Key を作ってすぐ再登録 |
| 133 | 指定したホスト名は使用中 | |
| 134 | 使えない文字 | |
| 135 | 長すぎる（最大31文字。クライアント側でも 32 超を拒否） | |
| 136 | 空 | |
| 137 | 短すぎる | |
| 139 | DDNS サーバーとの通信切断 | |
本実装ではネットワーク例外も「失敗」として扱う。

## 11. タイマー（DCThread）
| 処理 | 成功時 | 失敗時 |
|---|---|---|
| register | 1〜2 時間後（乱数） | 1〜5 分後（乱数） |
| getmyip（本家・本実装とも） | 10〜20 分後 | 1〜5 分後 |
- getmyip: `GET http://get-my-ip.ddns.softether-network.net/ddns/getmyip.ashx?v=<乱数>`（平文 HTTP、Key などは送らない）。
  応答本文は `IP=x.x.x.x`（2026-10-21 に同サーバーの HTTPS 版で `IP=140.248.50.116` の形を確認。HTTP 版は検証環境で port 80 が塞がれていたため未確認）。
  本家は IP 変化を検知すると即 register する。本実装も同じ間隔・同じ動作（変化したら即再登録）。
  初回（前回値なし）の取得では再登録しない（起動直後に register 済みのため）。
- 接続タイムアウト 15 秒、通信タイムアウト 60 秒。

## 12. 実測結果（2026-10-21、新規の乱数 Key で 1 回だけ）
```
current_fqdn: vpn890664560.softether.net
current_hostname: vpn890664560
current_ipv4: 140.248.50.59（検証環境の出口 IP）
current_ipv6: ''
current_region: US
dns_suffix: .softether.net
Error: 0
```
dns.google と Cloudflare の DoH で `vpn890664560.softether.net` → `140.248.50.59`（TTL 60）を確認。
登録直後の 1 回目の問い合わせだけ別の IP（173.136.106.234）が返った理由は不明。
ホスト名変更: 同じテスト Key で `new_hostname=rocktest63667` を 1 回送信 → `error 0`、`current_fqdn: rocktest63667.softether.net`（✅ 2026-10-21、DoH でも 140.248.50.74 を確認）。
ホスト名の規則: 長さ 3〜31（`strtable` の ERR_135 / ERR_137 の文言より）。使える文字はクライアントのソースに規定がなく、サーバーが判定（ERR_134）。
定期更新ループは実サーバーでは長時間は試していない（⚠ 未検証）。
