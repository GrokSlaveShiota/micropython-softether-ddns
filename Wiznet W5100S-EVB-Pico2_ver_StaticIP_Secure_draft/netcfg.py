# netcfg.py - 固定 IP 設定（netcfg.json）の検証・読み書きと、初期化ページ用のフォーム
# W5100S-EVB-Pico2 有線 LAN 版。ファイルがあれば起動時にその固定 IP を使い、無ければ DHCP。
# 書き込みは一時ファイル -> 読み直して確認 -> rename（途中で電源が切れても壊れたファイルを残さない）。
import os, json
import keyxfer

FILE = "netcfg.json"
TMP = FILE + ".tmp"
FIELDS = (("ip", "IP アドレス"), ("mask", "サブネットマスク"), ("gw", "デフォルトゲートウェイ"), ("dns", "DNS サーバー"))

def ip2int(s):
    """'192.168.1.10' -> int、形式が不正なら None（先頭 0 付き・空・範囲外も不可）"""
    if not isinstance(s, str):
        return None
    p = s.strip().split(".")
    if len(p) != 4:
        return None
    v = 0
    for x in p:
        if not x or len(x) > 3 or not all("0" <= c <= "9" for c in x) or (len(x) > 1 and x[0] == "0"):
            return None
        n = int(x)
        if n > 255:
            return None
        v = (v << 8) | n
    return v

def int2ip(v):
    return "%d.%d.%d.%d" % ((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255)

def _unicast(v):
    """機器・ゲートウェイ・DNS に使えるアドレスか（0.x / 127.x / 224 以上は不可）"""
    a = v >> 24
    return a != 0 and a != 127 and a < 224

def validate(ip, mask, gw, dns):
    """入力文字列 4 つ -> ((ip, mask, gw, dns) 正規化済み, None) または (None, 日本語エラー)"""
    vals = {}
    for (k, label), s in zip(FIELDS, (ip, mask, gw, dns)):
        v = ip2int(s)
        if v is None:
            return None, "%s の形式が正しくありません（例: 192.168.1.10）。" % label
        vals[k] = v
    m = vals["mask"]
    inv = (~m) & 0xFFFFFFFF
    if inv & (inv + 1):                        # 1 が左詰めで連続していない
        return None, "サブネットマスクが正しくありません（例: 255.255.255.0）。"
    if inv < 3:                                # /31, /32 はネットワーク・ブロードキャストと両立しない
        return None, "サブネットマスクが小さすぎます（/30 = 255.255.255.252 まで）。"
    if m == 0:
        return None, "サブネットマスクが正しくありません（0.0.0.0 は不可）。"
    for k in ("ip", "gw", "dns"):
        if not _unicast(vals[k]):
            return None, "%s に使えないアドレスです（0.x / 127.x / 224 以上は不可）。" % dict(FIELDS)[k]
    net = vals["ip"] & m
    for k in ("ip", "gw"):
        v = vals[k]
        if k == "gw" and (v & m) != net:
            return None, "IP アドレスとゲートウェイが同じサブネットにありません。"
        if v == net:
            return None, "%s がネットワークアドレス（%s）です。" % (dict(FIELDS)[k], int2ip(net))
        if v == net | inv:
            return None, "%s がブロードキャストアドレス（%s）です。" % (dict(FIELDS)[k], int2ip(net | inv))
    if vals["ip"] == vals["gw"]:
        return None, "IP アドレスとゲートウェイが同じです。"
    return tuple(int2ip(vals[k]) for k, _ in FIELDS), None

def load():
    """-> (cfg タプル or None, 警告文 or None)。ファイルが無ければ (None, None)。
    壊れている・値が不正なら無視して DHCP で起動する（ファイルは消さない）。"""
    try:
        with open(FILE) as f:
            raw = f.read()
    except OSError:
        return None, None
    try:
        d = json.loads(raw)
        cfg, err = validate(d["ip"], d["mask"], d["gw"], d["dns"])
    except Exception as e:
        cfg, err = None, "読み込めません（%s）" % e
    if cfg is None:
        msg = "固定 IP 設定（%s）が不正なため無視し、DHCP で起動しました: %s" % (FILE, err)
        print("netcfg:", msg)
        return None, msg
    return cfg, None

def save(cfg):
    """原子的に保存（tmp に書く -> 読み直して確認 -> rename）。失敗時は OSError。"""
    data = json.dumps({"ip": cfg[0], "mask": cfg[1], "gw": cfg[2], "dns": cfg[3]})
    with open(TMP, "w") as f:
        f.write(data)
    with open(TMP) as f:
        if f.read() != data:
            raise OSError("verify failed")
    try:
        os.rename(TMP, FILE)                   # littlefs: 既存ファイルを置き換える
    except OSError:
        try:
            os.remove(FILE)
        except OSError:
            pass
        os.rename(TMP, FILE)

def delete():
    """設定ファイルを削除。-> 削除したら True、元から無ければ False"""
    try:
        os.remove(TMP)
    except OSError:
        pass
    try:
        os.remove(FILE)
        return True
    except OSError:
        return False

def _esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def forms_html(mode, saved, cur):
    """初期化ページの「ネットワーク設定（固定 IP）」欄。saved: 保存済み設定 or None、cur: 今の ifconfig"""
    now = {"config": "固定（設定）", "dhcp": "DHCP", "static": "固定（フォールバック）"}.get(mode, "-")
    pre = saved or (cur if cur and cur[0] != "0.0.0.0" else ("", "255.255.255.0", "", ""))
    inputs = "".join('%s: <input name="%s" value="%s" maxlength="15" size="15" inputmode="decimal"><br>'
                     % (label, k, _esc(v)) for (k, label), v in zip(FIELDS, pre))
    h = ('<p>今の IP の取得方法: <b>%s</b>　保存済みの固定 IP 設定: <b>%s</b></p>'
         '<p>保存すると再起動後はこの固定 IP で動きます（DHCP は使いません）。<br>'
         '<b>再起動後は新しい IP アドレスで開き直してください。</b></p>'
         % (now, _esc(saved[0]) if saved else "なし（DHCP）"))
    h += keyxfer._form("/netcfg", "この固定 IP 設定を保存して再起動します。\n"
                       "再起動後は新しい IP アドレスで開き直す必要があります。\nよろしいですか？",
                       "保存して再起動", extra=inputs)
    if saved:
        h += keyxfer._form("/netcfg_delete", "固定 IP 設定を削除し、DHCP に戻して再起動します。\n"
                           "再起動後の IP アドレスはルーターの DHCP で決まります。\nよろしいですか？",
                           "削除して DHCP に戻す", style="color:#fff;background:#c00")
    return h
