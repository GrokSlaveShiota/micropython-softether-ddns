# config.py - 機器ごとの設定（WIZnet W5100S-EVB-Pico2 / 有線 LAN 専用。secrets.py は不要）

# ---- ネットワーク（有線 LAN のみ）----
# 起動時は DHCP。DHCP が取れない、またはケーブル未接続なら固定 IP（LAN_FALLBACK_IP）で起動し、
# 固定 IP の間は LAN_DHCP_RETRY 秒ごとに DHCP を再試行します（取得できれば自動で DHCP に切り替わります）。
# W5100S の配線はボード上で固定（SPI0: MISO=GP16, CS=GP17, SCK=GP18, MOSI=GP19, RSTn=GP20, INTn=GP21）。
# LAN_PINS は None のままでボード既定の設定を使います。変えるときだけ差分を書きます。例:
#   LAN_PINS = {"baudrate": 10_000_000}   # 通信が不安定なら SPI のクロックを下げる
LAN_PINS = None
LAN_DHCP_TIMEOUT = 12    # 秒。リンク確立後、この時間で DHCP が取れなければ固定 IP へ
LAN_LINK_WAIT = 4        # 秒。この時間リンクが立たなければ「ケーブル未接続」とみなして固定 IP へ
LAN_DHCP_RETRY = 60      # 秒。固定 IP の間の DHCP 再試行間隔（0 で再試行しない）
LAN_FALLBACK_IP = ("192.168.14.199", "255.255.255.0", "192.168.14.1", "192.168.14.1")   # IP, mask, GW, DNS
NET_HOSTNAME = "Pico2W"  # DHCP サーバーに送る機器名

# ---- DDNS ----
HOSTNAME = None          # 例 "myhome-pico"。None なら自動割り当て。Web UI で変えた名前が優先
MACHINE_NAME = "micropython"

# ---- Web / 時刻 ----
WEB_PORT = 80
TZ_OFFSET = 9 * 3600     # 表示用 (JST)
USE_NTP = True
NTP_HOST = "pool.ntp.org"

# ---- 堅牢化 ----
USE_WDT = True           # ウォッチドッグ。開発中は False（または本体に nowdt ファイルを置く）
WDT_TIMEOUT_MS = 8000    # RP2350 の上限は 16777
NO_SUCCESS_REBOOT_S = 6 * 3600   # この時間 DDNS 登録に一度も成功しなければ再起動（0 で無効。固定 IP の間は再起動しない）
CRASH_REBOOT_DELAY_S = 10        # 想定外の例外のあと再起動するまでの秒数
USE_LED = True           # 本体 LED で状態表示
LED_PIN = 25             # W5100S-EVB-Pico2 の LED は GPIO25（Wi-Fi チップは無い）
