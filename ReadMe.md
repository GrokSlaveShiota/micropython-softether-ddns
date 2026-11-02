# micropython-softether-ddns

A MicroPython reimplementation of the SoftEther VPN DDNS client (`*.softether.net`) for Raspberry Pi Pico 2 class boards.

**Note:** The source, documentation and web UI contain Japanese text. 日本語の説明は下にあります。

※ This project was developed by Grokbot with the goal of porting functionality from SoftEther VPN running on a Raspberry Pi.

## Features (common to all versions)
1. **New issuance**: Request a hostname (`vpnNNNNNNNN.softether.net`) with a new Key
2. **Hostname change**: Change to a desired name (3–31 characters) from the web interface
3. **Periodic update**: Re-register every 1–2 hours on success (1–5 minutes on failure), and re-register immediately when the global IP changes
4. Web UI for status, hostname change, and DDNS Key export / import / delete (with confirmation dialogs)
5. Server certificate pinning, watchdog, and automatic recovery

## Versions
Each folder is a complete, independent set of files. Use the one that matches your board, and see the README in that folder for setup and usage.

| Folder | Board | Network | Firmware |
| --- | --- | --- | --- |
| [`Pico2W_ver`](Pico2W_ver/) | Raspberry Pi Pico 2 W | Wi-Fi (DHCP) | Official MicroPython for RPI_PICO2_W |
| [`Wiznet W5100S-EVB-Pico2_ver`](Wiznet%20W5100S-EVB-Pico2_ver/) | WIZnet W5100S-EVB-Pico2 | Wired LAN (DHCP, fixed-IP fallback 192.168.14.199) | WIZnet MicroPython (`LWIP-W5100S_EVB_PICO2`) |

Files from different folders cannot be mixed.

## Terms of Use
The softether.net DDNS service is provided free of charge as an academic experiment by the University of Tsukuba SoftEther Project, as-is and without warranty, and may be discontinued without notice. If you incorporate this into a product, explain this to your customers.

## License
The Python files were newly written by analyzing the SoftEther VPN protocol; no SoftEther code was copied. Constants such as URLs and certificate hashes come from the SoftEther VPN source (Apache License 2.0). Firmware components and their licenses differ by version; see `THIRD_PARTY_LICENSES.txt` in each folder.

### Special Thanks
* **Grok (xAI)** for the language model and code analysis/generation that brought this project to life.
* The **University of Tsukuba SoftEther Project**, **Daiyuu Nobori**, and the other developers for providing this DDNS service.

---

# 日本語

SoftEther VPN の DDNS クライアント（`*.softether.net`）を、Raspberry Pi Pico 2 系のボード向けに MicroPython で作り直したものです。

※ 本プロジェクトは、Raspberry Pi 上で動作する SoftEther VPN からの機能移植を目的に、Grokbot によって開発されました。

## 機能（全版共通）
1. **新規発行**：新しい Key でホスト名（`vpnNNNNNNNN.softether.net`）を取得
2. **ホスト名変更**：Web 画面から好きな名前（3〜31 文字）に変更
3. **定期更新**：成功時は 1〜2 時間ごと（失敗時は 1〜5 分ごと）に再登録し、グローバル IP が変わったらすぐに再登録
4. 状態表示、ホスト名変更、DDNS Key の書き出し・読み込み・削除ができる Web 画面（確認ダイアログ付き）
5. サーバー証明書のピン留め、ウォッチドッグ、自動復旧

## 版の一覧
フォルダごとに必要なファイルがすべて揃っています。使うボードに合ったフォルダを選び、設定と使い方はそのフォルダの README を見てください。

| フォルダ | ボード | 接続 | ファーム |
| --- | --- | --- | --- |
| [`Pico2W_ver`](Pico2W_ver/) | Raspberry Pi Pico 2 W | Wi-Fi（DHCP） | MicroPython 公式（RPI_PICO2_W） |
| [`Wiznet W5100S-EVB-Pico2_ver`](Wiznet%20W5100S-EVB-Pico2_ver/) | WIZnet W5100S-EVB-Pico2 | 有線 LAN（DHCP、取れない場合は固定 IP 192.168.14.199） | WIZnet 版 MicroPython（`LWIP-W5100S_EVB_PICO2`） |

違うフォルダのファイルを混ぜて使うことはできません。

## 利用条件
softether.net の DDNS サービスは、筑波大学 SoftEther プロジェクトが学術実験として無償で提供しているもので、無保証です。予告なく終了することがあります。製品に組み込んで納品する場合は、このことをお客様に説明してください。

## ライセンス
Python ファイルは SoftEther VPN の通信仕様を解析して新たに書いたもので、SoftEther のコードはコピーしていません。URL や証明書ハッシュなどの定数は SoftEther VPN のソース（Apache License 2.0）に由来します。ファームに含まれる部品とそのライセンスは版ごとに異なるので、各フォルダの `THIRD_PARTY_LICENSES.txt` を見てください。

### Special Thanks
* 言語モデルとコード解析・生成でこのプロジェクトを形にしてくれた **Grok (xAI)**
* この DDNS サービスを提供している **筑波大学 SoftEther プロジェクト**、**登 大遊** 氏をはじめとする開発者の皆さま
