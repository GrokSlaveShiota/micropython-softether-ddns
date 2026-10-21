# main.py - SoftEther DDNS クライアント（Raspberry Pi Pico 2 W / Wi-Fi 専用）
# Wi-Fi (DHCP)、DDNS 維持 (register + getmyip)、状態・ホスト名変更 Web UI、初期化（Key 削除）ページ、
# ウォッチドッグ、例外時の自動再起動、起動回数の記録、LED 表示、セーフモード。
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio
import time, json, gc, struct, os, sys
try:
    import usocket as socket
except ImportError:
    import socket
import dnsfix          # UDP DNS fallback (Pico 2 W: built-in getaddrinfo -> OSError -2)
import ddns_softether as d
import netif
try:
    import config
except ImportError:
    config = None
try:
    import machine
except ImportError:    # CPython / unix test
    machine = None

def cfg(name, default):
    return getattr(config, name, default)

WIFI_TIMEOUT = cfg("WIFI_TIMEOUT", 30)
HOSTNAME = cfg("HOSTNAME", None)       # Web UI で変えた名前 (HOSTNAME_FILE) が優先
HOSTNAME_FILE = "ddns_hostname.txt"
KEY_FILE = "ddns_key.txt"
MACHINE_NAME = cfg("MACHINE_NAME", "micropython")
WEB_PORT = cfg("WEB_PORT", 80)
TZ_OFFSET = cfg("TZ_OFFSET", 9 * 3600)
USE_NTP = cfg("USE_NTP", True)
NTP_HOST = cfg("NTP_HOST", "pool.ntp.org")
USE_WDT = cfg("USE_WDT", True)
WDT_TIMEOUT_MS = cfg("WDT_TIMEOUT_MS", 8000)
NO_SUCCESS_REBOOT_S = cfg("NO_SUCCESS_REBOOT_S", 6 * 3600)
CRASH_REBOOT_DELAY_S = cfg("CRASH_REBOOT_DELAY_S", 10)
USE_LED = cfg("USE_LED", True)
LED_PIN = cfg("LED_PIN", "LED")      # Pico 2 W: CYW43 側の LED
ALIVE_LIMIT_MS = 120000     # メインループがこの時間止まったら WDT への給餌をやめる (=リセット)
BOOTINFO_FILE = "bootinfo.json"
GETMYIP_OK = (600, 1200)    # 上流と同じ: 成功後 10〜20 分
GETMYIP_NG = (60, 300)      #            失敗後 1〜5 分

ERR_JA = {
    None: "未実行",
    -1: "通信エラー（ネットワーク / TLS / 応答不正）",
    0: "正常（登録成功）",
    132: "Key 重複（新しい Key を作って再登録します）",
    133: "そのホスト名は既に使われています",
    134: "ホスト名に使えない文字が含まれています（英数字と - のみ。先頭と末尾に - は不可）",
    135: "ホスト名が長すぎます（最大 31 文字）",
    136: "ホスト名が空です",
    137: "ホスト名が短すぎます（3 文字以上）",
}
NAME_ERRORS = (133, 134, 135, 136, 137)

try:
    ticks_ms, ticks_diff, ticks_add = time.ticks_ms, time.ticks_diff, time.ticks_add
except AttributeError:   # CPython
    ticks_ms = lambda: int(time.monotonic() * 1000)
    ticks_diff = lambda a, b: a - b
    ticks_add = lambda a, b: a + b

BOOT = ticks_ms()
ddns = None
net = None
wdt = None
MODE = "normal"          # Wi-Fi 版は常に normal（初期化は /init ページ）

def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False

def load_wanted():
    try:
        with open(HOSTNAME_FILE) as f:
            n = f.read().strip()
            if n:
                return n.lower()
    except OSError:
        pass
    return HOSTNAME.lower() if HOSTNAME else None

def save_wanted(name):
    try:
        with open(HOSTNAME_FILE, "w") as f:
            f.write(name)
    except OSError as e:
        print("hostname: cannot save", e)

st = {"last_ticks": None, "next_ticks": None, "last_wall": None, "ok_ticks": None,
      "ntp": False, "wanted": load_wanted(), "name_note": None,
      "alive": ticks_ms(), "myip": None, "myip_ticks": None, "myip_err": None, "myip_next": None,
      "web_ticks": ticks_ms(), "fatal": None, "boot": {}, "resetting": False}
lock = asyncio.Lock()   # register / change_hostname を同時に走らせない

def uptime():
    return ticks_diff(ticks_ms(), BOOT) // 1000

def wall(t=None):
    if not st["ntp"]:
        return None
    tm = time.localtime((time.time() if t is None else t) + TZ_OFFSET)
    return "%04d-%02d-%02d %02d:%02d:%02d" % tm[:6]

def alive():
    st["alive"] = ticks_ms()

# ---------------- watchdog / reset / boot info ----------------
def feed():
    """Feed the hardware WDT directly (called between blocking steps of TLS/DNS)."""
    if wdt:
        wdt.feed()

async def wdt_task():
    while True:
        if wdt and ticks_diff(ticks_ms(), st["alive"]) < ALIVE_LIMIT_MS:
            wdt.feed()                       # main loop is alive -> keep feeding
        await asyncio.sleep(1)

def _reset_cause():
    if machine is None:
        return "unknown"
    try:
        c = machine.reset_cause()
    except Exception:
        return "unknown"
    for n in ("PWRON_RESET", "WDT_RESET", "HARD_RESET", "SOFT_RESET", "DEEPSLEEP_RESET"):
        if getattr(machine, n, None) == c:
            return n
    return str(c)

def boot_record():
    """Read bootinfo.json, increment boot count, write ONCE per boot (flash wear)."""
    info = {}
    try:
        with open(BOOTINFO_FILE) as f:
            info = json.loads(f.read())
    except Exception:
        pass
    cause = _reset_cause()
    pending = info.get("pending")
    # rp2: machine.reset() is implemented by the watchdog -> WDT_RESET; the reason file tells them apart
    reason = pending or {"WDT_RESET": "ウォッチドッグ（停止検出）による再起動",
                         "PWRON_RESET": "電源投入 / RUN ピン"}.get(cause, cause)
    info = {"boots": info.get("boots", 0) + 1, "last_cause": cause, "last_reason": reason}
    try:
        with open(BOOTINFO_FILE, "w") as f:
            f.write(json.dumps(info))
    except OSError as e:
        print("boot: cannot write", BOOTINFO_FILE, e)
    st["boot"] = info
    print("boot: #%d cause=%s reason=%s" % (info["boots"], cause, reason))

def hard_reset(reason):
    """Intentional reboot: remember why (one extra small write, only right before a reset)."""
    print("reset:", reason)
    try:
        info = dict(st["boot"])
        info["pending"] = reason
        with open(BOOTINFO_FILE, "w") as f:
            f.write(json.dumps(info))
    except Exception:
        pass
    time.sleep(1)
    if machine:
        machine.reset()
    raise SystemExit("reset: " + reason)     # CPython / unix test

async def guarded(name, coro_fn):
    """Global exception guard: log, wait, then reboot."""
    try:
        await coro_fn()
    except Exception as e:
        st["fatal"] = "%s: %r" % (name, e)
        print("FATAL in", name)
        try:
            sys.print_exception(e)
        except AttributeError:
            import traceback
            traceback.print_exc()
        await asyncio.sleep(CRASH_REBOOT_DELAY_S)
        hard_reset("例外で再起動 (%s: %s)" % (name, e))

# ---------------- LED ----------------
def _led():
    if not USE_LED or machine is None:
        return None
    try:
        return machine.Pin(LED_PIN, machine.Pin.OUT)
    except Exception:
        return None

async def led_task():
    led = _led()
    if led is None:
        return
    n = 0
    while True:
        if st["resetting"]:
            pat = (1, 0, 1, 0, 0, 0, 0, 0)               # 2 回点滅: Key 削除後の再起動待ち
        elif net is None or not net.is_up():
            pat = (1, 0) * 4                             # 速い点滅: ネットワーク未接続
        elif ddns is None or ddns.last_error != 0:
            pat = (1, 1, 1, 1, 0, 0, 0, 0)               # ゆっくり点滅: DDNS 未登録 / エラー
        else:
            pat = (1,) * 8                               # 点灯: 正常
        led.value(pat[n % 8])
        n += 1
        await asyncio.sleep(0.25)

# ---------------- NTP ----------------
def ntp_sync():
    """Minimal SNTP client (instead of ntptime, whose getaddrinfo fails on Pico 2 W)."""
    if not USE_NTP or st["ntp"]:
        return
    for _ in range(2):
        s = None
        try:
            addr = dnsfix.getaddrinfo(NTP_HOST, 123, 0, socket.SOCK_DGRAM)[0][-1]
            feed()
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)
            q = bytearray(48)
            q[0] = 0x1B                               # LI=0, VN=3, Mode=3 (client)
            s.sendto(q, addr)
            msg = s.recv(48)
            t = struct.unpack(">I", msg[40:44])[0]    # transmit timestamp (seconds since 1900)
            t -= 3155673600 if time.gmtime(0)[0] == 2000 else 2208988800
            if machine:
                tm = time.gmtime(t)
                machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
            st["ntp"] = True
            print("ntp: synced via", addr[0] if isinstance(addr, tuple) else addr)
            return
        except Exception as e:
            print("ntp: failed", e)
        finally:
            if s:
                s.close()

# ---------------- DDNS task (normal mode) ----------------
def check_myip(now):
    """Upstream behaviour: getmyip every 10-20 min (1-5 min after failure); IP change -> register now."""
    changed = False
    try:
        ip = d.getmyip()
        st["myip_err"] = None
    except Exception as e:
        ip = None
        st["myip_err"] = str(e)
        print("getmyip: failed", e)
    if ip:
        if ip != st["myip"]:
            print("getmyip:", st["myip"], "->", ip)
            changed = st["myip"] is not None
        st["myip"] = ip
        st["myip_ticks"] = ticks_ms()
        st["myip_next"] = ticks_add(now, d._rand(*GETMYIP_OK) * 1000)
    else:
        st["myip_next"] = ticks_add(now, d._rand(*GETMYIP_NG) * 1000)
    return changed

def do_register():
    err, wait = ddns.register_once()
    want = st["wanted"]
    if err == 0 and want and (ddns.hostname or "").lower() != want:
        err, wait = ddns.register_once(want)
        if err == 0:
            save_wanted(want)
        elif err in NAME_ERRORS:
            print("ddns: cannot use hostname", want, "- keeping", ddns.hostname)
            st["name_note"] = "%s は使えませんでした（%s）。%s のまま動作中" % (want, ERR_JA[err], ddns.hostname)
            st["wanted"] = None          # 名前の問題は再試行しても直らない
            err, wait = 0, d._rand(3600, 7200)   # 1 回目の登録自体は成功しているので通常間隔
    return err, wait

async def ddns_task():
    global ddns
    ddns = d.DDNSClient(key_path=KEY_FILE, machine_name=MACHINE_NAME)
    next_reg = st["myip_next"] = ticks_ms()
    was_up = True
    while True:
        alive()
        if st["resetting"]:                  # Key を削除した -> 再起動まで何もしない
            await asyncio.sleep(1)
            continue
        now = ticks_ms()
        if NO_SUCCESS_REBOOT_S and ticks_diff(now, st["ok_ticks"] or BOOT) > NO_SUCCESS_REBOOT_S * 1000:
            hard_reset("%d 秒間 DDNS 登録に成功しなかったため再起動" % NO_SUCCESS_REBOOT_S)
        if not await net.ensure():
            if was_up:
                print("net: down, retrying")
            was_up = False
            await asyncio.sleep(2)
            continue
        if not was_up:                      # 経路が変わった可能性 -> すぐ確認・登録
            was_up = True
            next_reg = st["myip_next"] = ticks_ms()
        net.log_once()                      # IP を NTP・DDNS より先にログに出す
        ntp_sync()
        alive()
        now = ticks_ms()
        if ticks_diff(now, st["myip_next"]) >= 0:
            if check_myip(now):
                next_reg = now              # グローバル IP が変わった -> 即再登録
        alive()
        now = ticks_ms()
        if ticks_diff(now, next_reg) >= 0:
            async with lock:
                err, wait = do_register()
            st["last_ticks"] = ticks_ms()
            st["last_wall"] = wall()
            next_reg = st["next_ticks"] = ticks_add(ticks_ms(), wait * 1000)
            if err == 0:
                st["ok_ticks"] = ticks_ms()
                print("ddns: OK", ddns.fqdn, "->", ddns.ipv4)
            else:
                print("ddns: failed", err, ddns.last_exc or "")
            gc.collect()
        await asyncio.sleep(2)

# ---------------- status ----------------
def status():
    s = {"uptime_s": uptime(), "mem_free": None, "ntp_synced": st["ntp"], "now": wall()}
    s.update(net.info() if net else {})
    try:
        s["mem_free"] = gc.mem_free()
    except AttributeError:
        pass
    c = ddns
    err = c.last_error if c else None
    b = st["boot"]
    s.update({
        "hostname": c.hostname if c else None,
        "fqdn": c.fqdn if c else None,
        "registered_ipv4": c.ipv4 if c else None,
        "last_result": err,
        "last_result_ja": ERR_JA.get(err, "不明なエラー"),
        "last_exception": c.last_exc if c else None,
        "tls": d.last_tls,
        "wanted_hostname": st["wanted"],
        "hostname_note": st["name_note"],
        "last_register_ago_s": ticks_diff(ticks_ms(), st["last_ticks"]) // 1000 if st["last_ticks"] is not None else None,
        "last_register_time": st["last_wall"],
        "next_register_in_s": max(0, ticks_diff(st["next_ticks"], ticks_ms()) // 1000) if st["next_ticks"] is not None else None,
        "global_ip": st["myip"],
        "getmyip_ago_s": ticks_diff(ticks_ms(), st["myip_ticks"]) // 1000 if st["myip_ticks"] is not None else None,
        "getmyip_error": st["myip_err"],
        "boots": b.get("boots"), "reset_cause": b.get("last_cause"), "reset_reason": b.get("last_reason"),
        "wdt": ("有効 %d ms" % WDT_TIMEOUT_MS) if wdt else "無効",
    })
    if s["next_register_in_s"] is not None and st["ntp"]:
        s["next_register_time"] = wall(time.time() + s["next_register_in_s"])
    return s

def esc(v):
    if v is None:
        return "-"
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def dur(sec):
    if sec is None:
        return "-"
    h, m = sec // 3600, sec % 3600 // 60
    return ("%d時間" % h if h else "") + ("%d分" % m if h or m else "") + "%d秒" % (sec % 60)

def html(s):
    ok = s["last_result"] == 0
    rows = [
        ("接続方式", "Wi-Fi（接続中）" if s.get("connected") else "Wi-Fi（未接続・再接続中）"),
        ("MAC アドレス", esc(s.get("mac"))),
        ("本機の IP（DHCP）", esc(s.get("ip"))),
        ("ゲートウェイ / DNS", "%s / %s" % (esc(s.get("gateway")), esc(s.get("dns")))),
    ]
    rows += [("SSID", esc(s.get("ssid"))),
             ("電波強度 RSSI", esc(s.get("rssi")) + (" dBm" if s.get("rssi") is not None else ""))]
    rows += [
        ("グローバル IP（getmyip）", esc(s["global_ip"]) + ("（%s前に確認）" % dur(s["getmyip_ago_s"]) if s["getmyip_ago_s"] is not None else "")
                                    + ("　<span style=\"color:red\">失敗: %s</span>" % esc(s["getmyip_error"]) if s["getmyip_error"] else "")),
        ("ホスト名", esc(s["hostname"])),
        ("FQDN", esc(s["fqdn"])),
        ("登録された IPv4", esc(s["registered_ipv4"])),
        ("最後の結果", '<b style="color:%s">%s</b> %s' % ("green" if ok else "red", esc(s["last_result"]), esc(s["last_result_ja"]))),
        ("最後の登録", (dur(s["last_register_ago_s"]) + "前" if s["last_register_ago_s"] is not None else "-")
                       + (" (%s)" % s["last_register_time"] if s["last_register_time"] else "")),
        ("次回の登録", ("あと " + dur(s["next_register_in_s"]) if s["next_register_in_s"] is not None else "-")
                       + (" (%s)" % s["next_register_time"] if s.get("next_register_time") else "")),
        ("稼働時間", dur(s["uptime_s"])),
        ("空きメモリ", esc(s["mem_free"]) + (" bytes" if s["mem_free"] is not None else "")),
        ("現在時刻 (JST)", esc(s["now"]) if s["now"] else "未同期（NTP 失敗または無効）"),
        ("起動回数 / 前回の再起動理由", "%s 回目 / %s（%s）" % (esc(s["boots"]), esc(s["reset_reason"]), esc(s["reset_cause"]))),
        ("ウォッチドッグ", esc(s["wdt"])),
    ]
    if s["last_exception"]:
        rows.append(("エラー詳細", esc(s["last_exception"])))
    if s["tls"]:
        rows.append(("サーバー証明書", esc(s["tls"])))
    if s["hostname_note"]:
        rows.append(("ホスト名の指定", esc(s["hostname_note"])))
    body = "".join("<tr><th>%s</th><td>%s</td></tr>" % r for r in rows)
    form = ('<h2>ホスト名の変更</h2><form method="post" action="/hostname" '
            'onsubmit="return confirm(\'ホスト名を \' + this.hostname.value + \' に変更しますか？\')">'
            '<input id="h" name="hostname" maxlength="31" placeholder="例: myhome-pico" '
            'pattern="[A-Za-z0-9]([A-Za-z0-9-]{1,29})[A-Za-z0-9]" required> '
            '<button type="submit">OK</button></form>'
            '<p style="font-size:90%">3〜31 文字。英数字と - のみ（先頭・末尾に - は不可）。'
            '変更後は <i>新しい名前</i>.softether.net になります。</p>')
    return (PAGE_HEAD + '<h1>SoftEther DDNS 状態</h1><table>%s</table>%s'
            '<p>30 秒ごとに自動更新（入力中は止まります） / <a href="/status.json">status.json</a>'
            ' / <a href="/init">初期化（DDNS Key の削除）</a></p>'
            '<script>setInterval(function(){var i=document.getElementById("h");'
            'if(document.activeElement!==i&&!i.value)location.reload();},30000);</script>'
            '</body></html>') % (body, form)

PAGE_HEAD = ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>DDNS</title><style>body{font-family:sans-serif;margin:1em}'
             'table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}'
             'th{background:#f4f4f4}</style></head><body>')

def result_page(ok, msg):
    return (PAGE_HEAD.replace("<head>", '<head><meta http-equiv="refresh" content="8;url=/">')
            + '<h1>ホスト名の変更</h1><p style="color:%s;font-weight:bold">%s</p>'
            '<p><a href="/">状態ページに戻る</a>（8 秒後に自動で戻ります）</p></body></html>'
            % ("green" if ok else "red", msg))

# ---------------- hostname change (POST /hostname) ----------------
def url_decode(b):
    b = b.replace(b"+", b" ")
    out = bytearray()
    i = 0
    while i < len(b):
        if b[i] == 37 and i + 2 < len(b):   # '%'
            try:
                out.append(int(b[i + 1:i + 3].decode(), 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(b[i])
        i += 1
    try:
        return bytes(out).decode()
    except Exception:
        return ""

def parse_form(body):
    form = {}
    for part in body.split(b"&"):
        if part:
            i = part.find(b"=")
            k, v = (part, b"") if i < 0 else (part[:i], part[i + 1:])
            form[url_decode(k)] = url_decode(v)
    return form

async def change_hostname_web(name):
    """Returns (ok, Japanese message)."""
    name = name.strip().lower()
    err = d.check_hostname(name)
    if err:
        return False, "%s：%s" % (esc(name) or "(空)", ERR_JA[err])
    if st["resetting"]:
        return False, "Key を削除したため再起動待ちです。"
    if ddns is None:
        return False, "まだ起動処理中です。少し待ってからやり直してください。"
    if lock.locked():
        return False, "DDNS の登録処理中です。少し待ってからやり直してください。"
    if ddns.hostname and ddns.hostname.lower() == name:
        return True, "すでに %s です。" % esc(ddns.fqdn)
    async with lock:
        try:
            err = ddns.change_hostname(name).get("error", 0)
        except Exception as e:
            err = -1
            ddns.last_exc = str(e)
        ddns.last_error = err
    if err == 0:
        save_wanted(name)
        st["wanted"] = name
        st["name_note"] = None
        st["last_ticks"] = ticks_ms()
        st["last_wall"] = wall()
        print("ddns: hostname changed ->", ddns.fqdn)
        return True, "変更しました：%s" % esc(ddns.fqdn)
    print("ddns: hostname change failed", err, ddns.last_exc or "")
    msg = ERR_JA.get(err, "不明なエラー (%s)" % err)
    if err == -1 and ddns.last_exc:
        msg += "（%s）" % esc(ddns.last_exc)
    st["name_note"] = "%s への変更に失敗：%s（現在の名前 %s のまま）" % (name, ERR_JA.get(err, err), ddns.hostname)
    return False, "%s：%s" % (esc(name), msg)


# ---------------- init page (GET /init, POST /reset): delete the DDNS key ----------------
def init_info():
    i = net.info() if net else {}
    hn = None
    try:
        with open(HOSTNAME_FILE) as f:
            hn = f.read().strip() or None
    except OSError:
        pass
    cur = ddns.hostname if ddns and ddns.hostname else hn
    return {"mac": i.get("mac"), "ip": i.get("ip"), "hostname": cur, "key_present": _exists(KEY_FILE),
            "boots": st["boot"].get("boots"), "reset_reason": st["boot"].get("last_reason")}

def init_html(m):
    rows = [
        ("MAC アドレス", esc(m["mac"])),
        ("本機の IP", esc(m["ip"])),
        ("現在のホスト名", (esc(m["hostname"]) + ".softether.net") if m["hostname"]
                          else "不明（まだ登録されていません）"),
        ("DDNS Key (ddns_key.txt)", "あり" if m["key_present"] else "なし（次回起動時に新規作成）"),
        ("起動回数 / 前回の再起動理由", "%s 回目 / %s" % (esc(m["boots"]), esc(m["reset_reason"]))),
    ]
    body = "".join("<tr><th>%s</th><td>%s</td></tr>" % r for r in rows)
    return (PAGE_HEAD + '<h1>初期化（DDNS Key の削除）</h1>'
            '<p>本機を別のお客様に渡す・ホスト名を完全に作り直す、といった場合に使います。'
            '通常の運用では使う必要はありません。</p>'
            '<table>%s</table>'
            '<p style="color:red"><b>注意:</b> ddns_key.txt を削除すると、今のホスト名（%s）は'
            '<b>二度と取り戻せません</b>。再起動後に新しい Key と新しいホスト名（vpnNNNNNNNN）が割り当てられます。'
            '必要なら先に USB で ddns_key.txt をバックアップしてください（mpremote cp :ddns_key.txt .）。</p>'
            '<form method="post" action="/reset" onsubmit="return confirm(\'DDNS Key とホスト名の設定を削除します。'
            '元に戻せません。よろしいですか？\')">'
            '確認のため <b>DELETE</b> と入力: <input name="confirm" autocomplete="off" required> '
            '<button type="submit" style="color:#fff;background:#c00">Key を削除する</button></form>'
            '<p><a href="/">状態ページに戻る</a></p></body></html>') % (body, esc(m["hostname"]) if m["hostname"] else "不明")

def init_result(ok, msg):
    return (PAGE_HEAD + '<h1>初期化</h1><p style="color:%s;font-weight:bold">%s</p></body></html>'
            % ("green" if ok else "red", msg))

def init_reset(form):
    """POST /reset. Returns (ok, message, reboot)."""
    if form.get("confirm", "").strip() != "DELETE":
        return False, '確認の文字列が違います（大文字で DELETE と入力してください）。何も削除していません。<br><a href="/init">戻る</a>', False
    if lock.locked():
        return False, 'DDNS の登録処理中です。少し待ってからやり直してください。何も削除していません。<br><a href="/init">戻る</a>', False
    st["resetting"] = True               # DDNS タスクを止める（削除した Key を作り直さないように）
    done, errs = [], []
    for p in (KEY_FILE, HOSTNAME_FILE):
        if _exists(p):
            try:
                os.remove(p)
                done.append(p)
            except OSError as e:
                errs.append("%s (%s)" % (p, e))
    print("init: deleted", done, "errors", errs)
    if errs:
        return False, "削除に失敗しました: %s。5 秒後に再起動します。" % esc(", ".join(errs)), True
    return True, ("削除しました: %s。5 秒後に再起動し、新しい Key で新しいホスト名を登録します。"
                  "新しいホスト名は再起動後の状態ページで確認してください。" % (esc(", ".join(done)) or "（削除対象なし）")), True

async def reboot_later(reason, delay=5):
    await asyncio.sleep(delay)
    hard_reset(reason)

# ---------------- web server ----------------
async def route(method, path, body):
    """Returns (code, content-type, body)."""
    html_t = "text/html; charset=utf-8"
    if method == "POST" and path == "/reset":
        ok, msg, reboot = init_reset(parse_form(body))
        if reboot:
            asyncio.create_task(reboot_later("Web の初期化ページで Key を削除"))
        return "200 OK", html_t, init_result(ok, msg)
    if method == "GET" and path == "/init":
        return "200 OK", html_t, init_html(init_info())
    if method == "POST" and path == "/hostname":
        ok, msg = await change_hostname_web(parse_form(body).get("hostname", ""))
        return "200 OK", html_t, result_page(ok, msg)
    if method == "GET" and path == "/status.json":
        return "200 OK", "application/json", json.dumps(status())
    if method == "GET" and path == "/":
        return "200 OK", html_t, html(status())
    return "404 Not Found", "text/plain; charset=utf-8", "not found"

async def handle(reader, writer):
    try:
        line = await reader.readline()
        clen = 0
        for _ in range(50):
            h = await reader.readline()
            if not h or h == b"\r\n":
                break
            if h.lower().startswith(b"content-length:"):
                try:
                    clen = int(h.split(b":", 1)[1].strip().decode())
                except ValueError:
                    clen = 0
        parts = line.split()
        method = parts[0].decode() if parts else "GET"
        path = parts[1].decode().split("?")[0] if len(parts) > 1 else "/"
        body = await reader.readexactly(clen) if method == "POST" and 0 < clen <= 512 else b""
        code, ctype, body = await route(method, path, body)
        b = body.encode()
        writer.write(("HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                      "Cache-Control: no-cache\r\nConnection: close\r\n\r\n" % (code, ctype, len(b))).encode())
        writer.write(b)
        await writer.drain()
    except Exception as e:
        print("web: error", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        gc.collect()

# ---------------- startup ----------------
def safe_mode_requested():
    """'safemode' file, or BOOTSEL pressed during the first 3 s after start (rp2 only).
    Any failure of the BOOTSEL check (no rp2 module, other firmware) just skips it."""
    if _exists("safemode"):
        print("safe mode: 'safemode' file found -> main.py not started (delete it to run)")
        return True
    try:
        import rp2
        bootsel = rp2.bootsel_button
    except Exception:
        return False
    led = _led()
    print("boot: press BOOTSEL within 3 s for safe mode")
    try:
        for i in range(30):
            if led:
                led.value(i & 1)
            if bootsel():
                print("safe mode: BOOTSEL pressed -> main.py not started")
                return True
            time.sleep_ms(100)
    except Exception as e:
        print("boot: BOOTSEL check skipped", e)
    finally:
        if led:
            led.value(0)
    return False

async def main_async():
    global net
    asyncio.create_task(wdt_task())
    asyncio.create_task(led_task())
    try:
        from secrets import WIFI_SSID, WIFI_PASSWORD
    except ImportError:
        WIFI_SSID = WIFI_PASSWORD = None
        print("wifi: secrets.py not found (copy secrets_example.py to secrets.py)")
    net = netif.Net(WIFI_SSID, WIFI_PASSWORD, WIFI_TIMEOUT)
    dnsfix.dns_server_hook = net.dns         # DNS from DHCP
    d.MAC_HOOK = net.mac                     # machine hash for new_key(): Wi-Fi MAC
    feed()
    r = await net.start()
    print("net: start ->", r)
    server = await asyncio.start_server(handle, "0.0.0.0", WEB_PORT)
    print("web: listening on port", WEB_PORT)
    await guarded("ddns", ddns_task)
    server.close()

def run():
    global wdt
    if safe_mode_requested():
        return
    boot_record()
    no_wdt = _exists("nowdt")
    if USE_WDT and not no_wdt and machine is not None:
        wdt = machine.WDT(timeout=WDT_TIMEOUT_MS)   # 一度動かすと止められない (rp2)
        d.feed = dnsfix.feed = feed
        d.SOCK_TIMEOUT = 3                  # each blocking socket op < WDT timeout
        dnsfix.USE_BUILTIN = False          # lwIP getaddrinfo has no short timeout
        print("wdt: enabled", WDT_TIMEOUT_MS, "ms")
    else:
        print("wdt: disabled", "(nowdt file)" if no_wdt else "")
    try:
        asyncio.run(main_async())
    except Exception as e:                   # KeyboardInterrupt is not caught -> REPL
        try:
            sys.print_exception(e)
        except AttributeError:
            import traceback
            traceback.print_exc()
        time.sleep(CRASH_REBOOT_DELAY_S)
        hard_reset("例外で再起動 (main: %s)" % e)

if __name__ == "__main__":
    run()
