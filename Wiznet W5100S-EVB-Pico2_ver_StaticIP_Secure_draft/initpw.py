# initpw.py - 初期化ページ（/init）のパスワード（HTTP Basic 認証）
# 目的は「お客様の誤操作防止」で、強いセキュリティではありません（HTTP は暗号化されません）。
# 既定のパスワードは本機の MAC アドレス（大文字小文字と ':' '-' の区切りは無視）。
# 変更したパスワードは initpw.json に「ランダムな salt + SHA-256」だけを保存（パスワード本体は保存・表示しない）。
# initpw.json を消す（mpremote rm :initpw.json）と既定（MAC）に戻ります。
import os, json, hashlib, binascii

FILE = "initpw.json"
TMP = FILE + ".tmp"
REALM = "Pico DDNS init"        # WWW-Authenticate の realm（ASCII）
MIN_LEN, MAX_LEN = 4, 64

def _hex(b):
    return binascii.hexlify(b).decode()

def _hash(salt, pw):
    h = hashlib.sha256(salt)
    h.update(pw.encode())
    return h.digest()

def norm_mac(s):
    """MAC 比較用: 小文字化し ':' '-' と空白を除く"""
    return "".join(c for c in str(s).strip().lower() if c not in ":- ")

def mac_hex(mac):
    """bytes（6 バイト）または文字列の MAC -> '0200000000aa' 形式。不明なら None"""
    if mac is None:
        return None
    if isinstance(mac, (bytes, bytearray)):
        return _hex(bytes(mac)) if len(mac) else None
    return norm_mac(mac) or None

def consteq(a, b):
    """長さ以外は内容に依存しない時間で比較"""
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= x ^ y
    return r == 0

def load():
    """-> (salt bytes, hash bytes) または None（ファイルなし・壊れている -> 既定の MAC）"""
    try:
        with open(FILE) as f:
            d = json.loads(f.read())
        salt = binascii.unhexlify(d["salt"])
        h = binascii.unhexlify(d["hash"])
        if len(salt) < 8 or len(h) != 32:
            raise ValueError("bad length")
        return salt, h
    except OSError:
        return None
    except Exception as e:
        print("initpw: %s が壊れているため既定（MAC）を使います: %s" % (FILE, type(e).__name__))
        return None

def is_default():
    return load() is None

def check(pw, mac):
    """パスワードが正しいか。設定ファイルがあればそのハッシュ、無ければ MAC と比較"""
    if pw is None:
        return False
    rec = load()
    if rec is None:
        m = mac_hex(mac)
        if not m:
            return False
        return consteq(norm_mac(pw).encode(), m.encode())
    salt, h = rec
    return consteq(_hash(salt, pw), h)

def validate_new(pw, pw2):
    """-> None（OK）または日本語エラー"""
    if pw != pw2:
        return "新しいパスワードと確認が一致しません。"
    if not (MIN_LEN <= len(pw) <= MAX_LEN):
        return "新しいパスワードは %d〜%d 文字にしてください。" % (MIN_LEN, MAX_LEN)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in pw):
        return "新しいパスワードに使えない文字が含まれています。"
    return None

def save(pw):
    """salt + SHA-256 を原子的に保存（tmp -> 読み直して確認 -> rename）"""
    salt = os.urandom(16)
    data = json.dumps({"v": 1, "salt": _hex(salt), "hash": _hex(_hash(salt, pw))})
    with open(TMP, "w") as f:
        f.write(data)
    with open(TMP) as f:
        if f.read() != data:
            raise OSError("verify failed")
    try:
        os.rename(TMP, FILE)
    except OSError:
        try:
            os.remove(FILE)
        except OSError:
            pass
        os.rename(TMP, FILE)

def parse_basic(value):
    """Authorization ヘッダーの値（bytes / str）-> パスワード（ユーザー名は何でもよい）or None"""
    try:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode()
        value = value.strip()
        if value[:6].lower() != "basic ":
            return None
        raw = binascii.a2b_base64(value[6:].strip()).decode()
        i = raw.find(":")
        return None if i < 0 else raw[i + 1:]
    except Exception:
        return None

def challenge_header():
    return 'WWW-Authenticate: Basic realm="%s", charset="UTF-8"\r\n' % REALM
