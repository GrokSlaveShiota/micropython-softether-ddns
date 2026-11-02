# keyxfer.py - DDNS key export / import for the initialization page (device replacement).
# Shared by the Pico 2 W (/init) and W6300-EVB-Pico2 (maintenance page) versions.
# Plain HTTP, no login: every action is a POST with a hidden confirm=1 field, sent only after a
# JavaScript confirm() dialog. The key is never printed, logged or shown in status/status.json.
import os

MAX_BODY = 2048          # bytes accepted for POST bodies (a key file is ~40 bytes)
TMP_SUFFIX = ".tmp"
HEX = "0123456789ABCDEF"

def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False

# ---------------- key text ----------------
def normalize_key(raw):
    """bytes/str -> (KEY40 or None, Japanese error). Strips BOM / whitespace / CRLF, any case."""
    if raw is None:
        return None, "Key が入力されていません。"
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
        if raw[:3] == b"\xef\xbb\xbf":                 # UTF-8 BOM
            raw = raw[3:]
        try:
            raw = raw.decode()
        except Exception:
            return None, "Key ファイルの文字コードが不正です（ddns_key.txt をそのまま選んでください）。"
    s = "".join(c for c in raw.replace("\ufeff", "") if c not in " \t\r\n\x0b\x0c").upper()
    if not s:
        return None, "Key が入力されていません。"
    if len(s) != 40:
        return None, "Key は 16 進数 40 文字（20 バイト）です。入力は %d 文字でした。" % len(s)
    for c in s:
        if c not in HEX:
            return None, "Key に 16 進数（0〜9, A〜F）以外の文字が含まれています。"
    return s, None

def read_key(path):
    """Current key as 40 uppercase hex chars, or None."""
    try:
        with open(path) as f:
            k, err = normalize_key(f.read())
        return k
    except OSError:
        return None

def write_key_atomic(path, key40):
    """Write tmp, verify, then rename over the key file (littlefs: rename replaces)."""
    tmp = path + TMP_SUFFIX
    with open(tmp, "w") as f:
        f.write(key40)
    with open(tmp) as f:
        if f.read() != key40:
            raise OSError("verify failed")
    try:
        os.rename(tmp, path)
    except OSError:                  # filesystems where rename does not overwrite
        try:
            os.remove(path)
        except OSError:
            pass
        os.rename(tmp, path)

# ---------------- forms ----------------
def ctype_boundary(ctype):
    """multipart boundary from a Content-Type header value (bytes or str), or None."""
    if isinstance(ctype, (bytes, bytearray)):
        ctype = bytes(ctype).decode()
    if not ctype or not ctype.lower().startswith("multipart/form-data"):
        return None
    for part in ctype.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            b = part[9:].strip()
            if len(b) > 1 and b[0] == '"' and b[-1] == '"':
                b = b[1:-1]
            return b.encode() if b else None
    return None

def parse_multipart(body, boundary):
    """Simple multipart/form-data parser -> {name: bytes}. Works with Chrome/Edge/Firefox/curl."""
    out = {}
    if not boundary:
        return out
    delim = b"--" + boundary
    for chunk in body.split(delim):
        if chunk[:2] == b"\r\n":
            chunk = chunk[2:]
        elif chunk[:1] == b"\n":
            chunk = chunk[1:]
        if not chunk or chunk[:2] == b"--":          # preamble / closing delimiter
            continue
        i = chunk.find(b"\r\n\r\n")
        sep = 4
        if i < 0:
            i = chunk.find(b"\n\n")
            sep = 2
        if i < 0:
            continue
        head, data = chunk[:i], chunk[i + sep:]
        if data[-2:] == b"\r\n":
            data = data[:-2]
        elif data[-1:] == b"\n":
            data = data[:-1]
        name = None
        for line in head.split(b"\n"):
            l = line.strip()
            if l.lower().startswith(b"content-disposition:"):
                j = l.find(b'name="')
                if j >= 0:
                    k = l.find(b'"', j + 6)
                    name = l[j + 6:k].decode() if k > j else None
        if name is not None and name not in out:
            out[name] = data
    return out

def import_key_from(fields):
    """fields: {"keyfile": bytes} -> (KEY40 or None, Japanese error). File upload only."""
    f = fields.get("keyfile") or b""
    has_f = bool(bytes(f).strip()) if isinstance(f, (bytes, bytearray)) else bool(f.strip())
    if has_f:
        return normalize_key(f)
    return None, "Key ファイル（ddns_key.txt）を選んでください。"

# ---------------- HTML (Japanese) ----------------
# Buttons are type="button": nothing is sent unless confirm() returns OK. The hidden field starts
# at 0 and is set to 1 by the script only after OK, so if JavaScript or the dialog is blocked the
# server refuses the request (fail closed).
_JS = ('<script>function ddnsAsk(b){var f=b.form;'
       'if(f.keyfile&&!f.keyfile.value){alert("Key ファイル（ddns_key.txt）を選んでください。");return;}'
       'if(window.confirm(b.getAttribute("data-m"))){f.confirm.value="1";f.submit();}}</script>')

def _form(action, msg, label, style="", multipart=False, extra=""):
    return ('<form method="post" action="%s"%s>'
            '<input type="hidden" name="confirm" value="0">%s'
            '<button type="button" onclick="ddnsAsk(this)" data-m="%s"%s>%s</button></form>'
            % (action, ' enctype="multipart/form-data"' if multipart else "", extra,
               msg.replace("\n", "&#10;"), (' style="%s"' % style) if style else "", label))

def forms_html(key_present, hostname, back="/"):
    """Export / import / delete sections. Each is a button + JS confirm() final dialog."""
    hn = (hostname + ".softether.net") if hostname else "（不明）"
    exp = ('<h2>DDNS Key の書き出し（機器入れ替え用）</h2>'
           '<p>この機器の ddns_key.txt をダウンロードします。<br>新しい機器に読み込むと、同じホスト名 %s を引き継げます。</p>'
           '<p style="color:red"><b>書き出したファイルは秘密にしてください。<br></b>このファイルを持っている人は誰でも'
           'このホスト名の持ち主になれます<br>（メールやチャットで送らない・共有フォルダに置かない）。</p>' % hn)
    if key_present:
        exp += _form("/export", "DDNS Key（ddns_key.txt）をダウンロードします。\n"
                     "このファイルはホスト名の持ち主の証明です。\n他人に渡さず安全に保管してください。\nよろしいですか？",
                     "Key を書き出す（ddns_key.txt）")
    else:
        exp += '<p>Key がまだありません（書き出せません）。</p>'
    imp = ('<h2>DDNS Key の読み込み（機器入れ替え用）</h2>'
           '<p>古い機器から書き出した ddns_key.txt を読み込みます。<br>読み込むと今の Key は上書きされ、'
           'ホスト名の設定（ddns_hostname.txt）を消して再起動し、<br>その Key に結びついたホスト名をそのまま使います。</p>'
           '<p style="color:red"><b>必ず古い機器の電源を切って（または LAN から外して）から</b>新しい機器を動かしてください。<br>'
           '同じ Key の機器が 2 台動くと、同じホスト名を交互に書き換えてしまいます。</p>'
           + _form("/import", "Key を読み込み、今の Key を上書きして再起動します。\n"
                   "今の Key は書き出していなければ失われます。\n古い機器の電源は切りましたか？よろしいですか？",
                   "Key を読み込む", multipart=True,
                   extra='ファイル: <input type="file" name="keyfile" accept=".txt,text/plain"><br>'))
    dele = ('<h2>DDNS Key の削除（初期化）</h2>'
            '<p style="color:red"><b>注意:</b> ddns_key.txt を削除すると、今のホスト名（%s）は<br>'
            'Key を書き出していなければ<b>二度と取り戻せません</b><br>（書き出した Key を読み込めば元のホスト名に戻せます）。<br>'
            '再起動後に新しい Key と新しいホスト名（vpnNNNNNNNN）が割り当てられます。</p>' % hn
            + _form("/reset", "【最終確認】DDNS Key とホスト名の設定を削除して再起動します。\n"
                    "この操作は元に戻せません。Key を書き出していない場合、\n今のホスト名 %s は二度と取り戻せません。\n"
                    "本当に削除しますか？" % hn, "Key を削除する", style="color:#fff;background:#c00"))
    return _JS + exp + imp + dele

CONFIRM_MSG = '確認が取れませんでした（ページの確認ダイアログで OK を押してください）。何も変更していません。'

def confirmed(form):
    v = form.get("confirm", "")
    if isinstance(v, (bytes, bytearray)):
        try:
            v = bytes(v).decode()
        except Exception:
            v = ""
    return v.strip() == "1"
