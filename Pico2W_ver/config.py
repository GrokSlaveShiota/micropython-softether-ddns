# config.py - 機器ごとの設定（Wi-Fi の SSID / パスワードは secrets.py に分けています）

# ---- ネットワーク（Wi-Fi のみ。IP は DHCP）----
WIFI_TIMEOUT = 30        # 秒。1 回の Wi-Fi 接続待ち（つながらなければ再試行し続ける）

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
NO_SUCCESS_REBOOT_S = 6 * 3600   # この時間 DDNS 登録に一度も成功しなければ再起動（0 で無効）
CRASH_REBOOT_DELAY_S = 10        # 想定外の例外のあと再起動するまでの秒数
USE_LED = True           # 本体 LED で状態表示
LED_PIN = "LED"          # Pico 2 W の LED（Wi-Fi チップ CYW43 につながっている）
