# ddns_softether.py - SoftEther VPN DDNS (*.softether.net) minimal client
# MicroPython (Raspberry Pi Pico 2 W) and CPython 3 compatible.
# Protocol reimplemented from SoftEtherVPN (Apache License 2.0):
#   src/Cedar/DDNS.c, src/Cedar/Wpc.c, src/Mayaqua/Pack.c
# Features (only): 1) new issuance  2) change hostname  3) keep-alive loop
try:
    import usocket as socket
except ImportError:
    import socket
try:
    import ssl
except ImportError:
    import ussl as ssl
try:
    import hashlib
except ImportError:
    import uhashlib as hashlib
try:
    import binascii
except ImportError:
    import ubinascii as binascii
import os, struct, time
try:
    from dnsfix import getaddrinfo as _getaddrinfo   # built-in DNS first, UDP DNS fallback
except ImportError:
    _getaddrinfo = socket.getaddrinfo

BUILD = 5187                 # CMakeLists.txt default BUILD_NUMBER
OSINFO = 3100                # OSTYPE_LINUX
SNI = "DDNS"                 # DDNS_SNI_VER_STRING (literal SNI value)
URL_HOST = "x%s.x%s.dev.open.servers.ddns.softether-network.net"  # ".servers" -> ".open.servers"
URL_PATH = "/ddns/ddns.aspx"
GETMYIP_HOST = "get-my-ip.ddns.softether-network.net"   # DDNS_URL2_V4_GLOBAL (plain HTTP)
GETMYIP_PATH = "/ddns/getmyip.ashx"
SOCK_TIMEOUT = 5     # seconds per blocking socket operation (keep well below the WDT timeout)
feed = None          # callable: feed the watchdog between blocking steps (set by main.py)

def _feed():
    if feed:
        feed()
UA = "Mozilla/5.0 (Windows NT 6.3; WOW64; rv:29.0) Gecko/20100101 Firefox/29.0"
CERT_HASHES = (  # DDNS_CERT_HASH: SHA-1 of server cert (DER), any match OK
    "78BF0499A99396907C9F49DD13571C81FE26E6F5", "439BAFA75A6EE5671FC9F9A02D34FF29881761A0",
    "EFAC5FA0CDD14E0F864EED58A73C35D7E33B62F3", "74DF99D4B1B5F0488A388B50D347D26013DC67A5",
    "6EBB39AFCA8C900635CFC11218CF293A612457E4", "05A9386C5E2B233F7BAB2479620EAAA2793709ED",
    "A811C64BB715351E36B6C1E022648D8BE0ACD128", "BD264DB3B0B1B3ABA0AF3074AA574ED1EF3B42D7",
    "9AB61D691536645DD55A8730FC6D2CDF33C8C73F")
ERR_DUPLICATE_DDNS_KEY = 132
ERRORS = {0: "OK", 132: "duplicate key", 133: "hostname exists", 134: "invalid char",
          135: "hostname too long", 136: "hostname empty", 137: "hostname too short"}

def _hex(b):
    return binascii.hexlify(b).decode().upper()

def _sha1(b):
    return hashlib.sha1(b).digest()

# ---------------- PACK (big-endian) ----------------
# PACK = u32 count, elements...
# element = u32 (len(name)+1), name bytes (no NUL), u32 type, u32 num_values, values
# element names are case-insensitive (server replies "Error"); decoded keys are lower-cased
# INT(0)=u32, DATA(1)=u32 len+bytes, STR(2)=u32 len+bytes, UNISTR(3)=u32 len+utf8 incl NUL, INT64(4)=u64
def pack_encode(items):
    out = [struct.pack(">I", len(items))]
    for name, val in items:
        n = name.encode()
        out.append(struct.pack(">I", len(n) + 1) + n)
        if isinstance(val, int):
            out.append(struct.pack(">III", 0, 1, val))
        else:
            v = val.encode() if isinstance(val, str) else val
            out.append(struct.pack(">III", 2 if isinstance(val, str) else 1, 1, len(v)) + v)
    return b"".join(out)

def pack_decode(b):
    p = 0
    def u32():
        nonlocal p
        v = struct.unpack(">I", b[p:p + 4])[0]; p += 4; return v
    res = {}
    for _ in range(u32()):
        nl = u32(); name = b[p:p + nl - 1].decode(); p += nl - 1
        t = u32(); vals = []
        for _ in range(u32()):
            if t == 0:
                vals.append(u32())
            elif t == 4:
                vals.append(struct.unpack(">Q", b[p:p + 8])[0]); p += 8
            else:
                ln = u32(); v = b[p:p + ln]; p += ln
                if t == 2:
                    v = v.decode()
                elif t == 3:
                    v = v.rstrip(b"\0").decode()
                vals.append(v)
        res[name.lower()] = vals[0] if len(vals) == 1 else vals
    return res

# ---------------- WPC framing ----------------
# entry = 4-char name (upper, space padded) + "%010u" length + Safe64(data)
# Safe64 = base64 with '='->'(' '+'->')' '/'->'_'
def _safe64(b):
    s = binascii.b2a_base64(b).decode().strip()
    return s.replace("=", "(").replace("+", ")").replace("/", "_")

def _unsafe64(s):
    return binascii.a2b_base64(s.replace("(", "=").replace(")", "+").replace("_", "/"))

def wpc_encode(pack_bytes):
    out = ""
    for name, data in (("PACK", pack_bytes), ("HASH", _sha1(pack_bytes))):
        e = _safe64(data)
        out += name + "%010d" % len(e) + e
    return out.encode()

def wpc_decode(body):
    ent, p = {}, 0
    while p + 14 <= len(body):
        name = body[p:p + 4].decode().strip(); size = int(body[p + 4:p + 14].decode()); p += 14
        ent[name] = body[p:p + size].decode(); p += size
    pk = _unsafe64(ent["PACK"])
    if "HASH" in ent and _unsafe64(ent["HASH"]) != _sha1(pk):
        raise ValueError("WPC HASH mismatch")
    return pack_decode(pk)

# ---------------- TLS + certificate pinning ----------------
# The DDNS server cert is self-signed (CN=ddns-register-1.sehosts.com, X.509 v1,
# sha1WithRSA, valid to 2037-01-19). mbedTLS CERT_REQUIRED + cadata cannot accept it
# (SHA-1 signature rejected by the default profile, CN != SNI "DDNS"), so - like
# SoftEther itself - we pin the SHA-1 of the DER server certificate instead:
#  * MicroPython (tls module): CERT_OPTIONAL + verify_callback checks the hash during
#    the handshake and aborts it on mismatch (works without getpeercert()).
#  * CPython / firmware with getpeercert(True): hash checked after the handshake.
# Nothing is sent before the check passes. ALLOW_INSECURE=True disables fail-closed.
ALLOW_INSECURE = False

def _tls_wrap(sock, host, sni):
    """Returns (ssl_socket, how_verified). Raises OSError if not verified (fail closed)."""
    pins = CERT_HASHES
    seen = []
    tlsmod = None
    try:
        import tls as tlsmod                 # MicroPython >= 1.23
    except ImportError:
        pass
    if tlsmod is not None and hasattr(tlsmod, "SSLContext"):
        ctx = tlsmod.SSLContext(tlsmod.PROTOCOL_TLS_CLIENT)
        if hasattr(ctx, "verify_callback"):
            def _cb(cert, depth):
                _feed()
                if depth == 0:
                    seen.append(_hex(_sha1(bytes(cert))))
                    return 0 if seen[-1] in pins else -1
                return 0
            ctx.verify_mode = tlsmod.CERT_OPTIONAL   # run verification so the callback is called
            ctx.verify_callback = _cb
        else:
            ctx.verify_mode = tlsmod.CERT_NONE
        try:
            s = ctx.wrap_socket(sock, server_hostname=sni or host)
        except Exception as e:
            if seen and seen[-1] not in pins:
                raise OSError("server certificate not trusted: " + seen[-1])
            raise
        if seen and seen[-1] in pins:
            return s, "pinned via verify_callback " + seen[-1][:8]
    elif hasattr(ssl, "SSLContext"):         # CPython (or old MicroPython ssl)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            ctx.check_hostname = False
        except AttributeError:
            pass
        ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(sock, server_hostname=sni or host)
    else:
        s = ssl.wrap_socket(sock, server_hostname=sni or host)
    der = None
    try:
        der = s.getpeercert(True)
    except Exception:
        pass
    if der:
        h = _hex(_sha1(der))
        if h in pins:
            return s, "pinned via getpeercert " + h[:8]
        s.close()
        raise OSError("server certificate not trusted: " + h)
    if ALLOW_INSECURE:
        print("ddns: WARNING: server certificate NOT verified (ALLOW_INSECURE=True)")
        return s, "NOT verified (insecure)"
    s.close()
    raise OSError("cannot verify server certificate (no verify_callback/getpeercert); "
                  "key not sent. Set ALLOW_INSECURE=True to override")

# ---------------- HTTP(S) ----------------
last_tls = None

def _https_post(host, path, body, timeout=None, sni=SNI):
    global last_tls
    # connect to the resolved IP; TLS SNI / Host header stay as before
    ai = _getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM)
    s.settimeout(timeout or SOCK_TIMEOUT)
    _feed()
    s.connect(ai[-1])
    _feed()
    try:
        s, last_tls = _tls_wrap(s, host, sni)
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        raise
    req = ("POST %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\n"
           "Content-Type: application/x-www-form-urlencoded\r\nContent-Length: %d\r\n"
           "Connection: close\r\n\r\n" % (path, host, UA, len(body))).encode() + body
    s.write(req) if hasattr(s, "write") else s.sendall(req)
    data = b""
    while True:
        _feed()
        c = s.read(2048) if hasattr(s, "read") else s.recv(2048)
        if not c:
            break
        data += c
    s.close()
    i = data.find(b"\r\n\r\n")
    head, payload = data[:i], data[i + 4:]
    status = int(head.split(b" ", 2)[1].decode())
    if status != 200:
        raise OSError("HTTP %d" % status)
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            payload = payload[:int(line.split(b":")[1].decode().strip())]
    return payload

def getmyip(timeout=None):
    """Upstream DCGetMyIp: GET http://get-my-ip.../getmyip.ashx?v=<rand>, body 'IP=a.b.c.d'.
    Returns the global IPv4 seen by the server. Raises OSError on failure."""
    ai = _getaddrinfo(GETMYIP_HOST, 80, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM)
    try:
        s.settimeout(timeout or SOCK_TIMEOUT)
        _feed()
        s.connect(ai[-1])
        req = ("GET %s?v=%d HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\nPragma: no-cache\r\n"
               "Cache-Control: no-cache\r\nConnection: close\r\n\r\n"
               % (GETMYIP_PATH, struct.unpack(">Q", os.urandom(8))[0], GETMYIP_HOST, UA)).encode()
        s.send(req)
        data = b""
        while len(data) < 4096:
            _feed()
            c = s.recv(512)
            if not c:
                break
            data += c
    finally:
        s.close()
    i = data.find(b"\r\n\r\n")
    if i < 0 or b" 200" not in data[:i].split(b"\r\n")[0]:
        raise OSError("getmyip: bad HTTP response")
    body = data[i + 4:].strip()
    if not body.startswith(b"IP="):
        raise OSError("getmyip: protocol error")
    return body[3:].split(b"\r")[0].split(b"\n")[0].decode().strip()

# ---------------- key ----------------
def _ticks64(name, fallback):
    f = getattr(time, name, None)
    try:
        return (f() if f else fallback()) & 0xFFFFFFFFFFFFFFFF
    except Exception:
        return 0

MAC_HOOK = None      # callable -> MAC address (bytes) of the active NIC (set by main.py)

def _machine_hash():
    """Device-specific info (like GetCurrentMachineIpProcessHash): chip unique ID + MAC address.
    MAC comes from MAC_HOOK (the NIC object main.py already created: WLAN on Pico 2 W,
    WIZNET6K on W6300-EVB-Pico2). Without a hook only network.WLAN is tried (never a
    wired-NIC constructor, which may need pins). Every source is optional."""
    b = b""
    try:
        import machine
        b += machine.unique_id()
    except Exception:
        pass
    mac = None
    if MAC_HOOK:
        try:
            mac = MAC_HOOK()
        except Exception:
            mac = None
    if not mac:
        try:
            import network
            if hasattr(network, "WLAN"):
                mac = network.WLAN(network.STA_IF).config("mac")
        except Exception:
            mac = None
    if mac:
        try:
            b += bytes(mac)
        except Exception:
            pass
    try:
        import uuid  # CPython
        b += struct.pack(">Q", uuid.getnode())
    except Exception:
        pass
    return _sha1(b)

def new_key():
    """Same as upstream DCGenNewKey:
    SHA1(rand20 + highres_tick64 + tick64 + systemtime64 + machine_hash) XOR rand20."""
    b = os.urandom(20)
    b += struct.pack(">Q", _ticks64("ticks_us", lambda: int(time.time() * 1000000)))
    b += struct.pack(">Q", _ticks64("ticks_ms", lambda: int(time.time() * 1000)))
    b += struct.pack(">Q", _ticks64("time_ns", lambda: int(time.time() * 1000000000)))
    b += _machine_hash()
    h = _sha1(b)
    r = os.urandom(20)
    return bytes(h[i] ^ r[i] for i in range(20))

def load_key(path="ddns_key.txt"):
    try:
        with open(path) as f:
            k = binascii.unhexlify(f.read().strip())
            if len(k) == 20:
                return k
    except OSError:
        pass
    k = new_key()
    save_key(k, path)
    return k

def save_key(k, path="ddns_key.txt"):
    with open(path, "w") as f:
        f.write(_hex(k))

def key_from_vpn_server_config(b64):
    """'byte Key <base64>' in DDnsClient of vpn_server.config -> 20-byte key"""
    return binascii.a2b_base64(b64)

# ---------------- DDNS ----------------
HOSTNAME_MIN, HOSTNAME_MAX = 3, 31          # strtable ERR_137 / ERR_135
_HN_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"

def check_hostname(name):
    """Local pre-check. Returns 0 if OK, else SoftEther error code (134-137).
    Allowed chars are not documented in the client source (server decides);
    we allow letters, digits and '-' (not at the start/end) like a DNS label."""
    if not name:
        return 136
    if len(name) < HOSTNAME_MIN:
        return 137
    if len(name) > HOSTNAME_MAX:
        return 135
    for ch in name:
        if ch not in _HN_CHARS:
            return 134
    if name[0] == "-" or name[-1] == "-":
        return 134
    return 0

class DDNSClient:
    def __init__(self, key_path="ddns_key.txt", machine_name="micropython", sni=SNI):
        # sni: "DDNS" like the original. None -> real hostname (needed behind SNI-routing proxies)
        self.sni = sni
        self.key_path = key_path
        self.key = load_key(key_path)
        self.machine_name = machine_name.lower()
        self.fqdn = self.hostname = self.ipv4 = None
        self.last_error = None
        self.last_exc = None

    def register(self, new_hostname=None):
        """Features 1/3 (new_hostname=None) and 2 (new_hostname='name'). Returns response dict."""
        key_str = _hex(self.key)
        kh = binascii.hexlify(_sha1(key_str.encode())).decode()   # lower-case
        host = URL_HOST % (kh[2], kh[3])
        items = [("key", key_str), ("build", BUILD), ("osinfo", OSINFO), ("is_64bit", 0),
                 ("is_softether", 1), ("is_packetix", 0),
                 ("machine_key", _hex(_sha1(self.key + b"machine"))),
                 ("machine_name", self.machine_name),
                 ("lasterror_ipv4", 0), ("lasterror_ipv6", 0), ("use_azure", 0),
                 ("product_str", "SoftEther OSS"), ("ddns_protocol_version", 1), ("ddns_oss", 1)]
        if new_hostname:
            items.append(("new_hostname", new_hostname))
        items.append(("function", "register"))
        path = URL_PATH + "?v=%d" % struct.unpack(">Q", os.urandom(8))[0]
        res = wpc_decode(_https_post(host, path, wpc_encode(pack_encode(items)), sni=self.sni))
        err = res.get("error", 0)
        self.last_error = err
        if err == 0:
            self.hostname = res.get("current_hostname")
            self.fqdn = res.get("current_fqdn")
            self.ipv4 = res.get("current_ipv4")
        elif err == ERR_DUPLICATE_DDNS_KEY:
            self.key = new_key()         # same behaviour as DCRegister
            save_key(self.key, self.key_path)
        return res

    def change_hostname(self, name):
        err = check_hostname(name)
        if err:
            return {"error": err}             # same codes as the server, nothing sent
        return self.register(name)

    def register_once(self, new_hostname=None):
        """One attempt, never raises. Returns (error_code, seconds_until_next).
        error_code -1 = network/TLS/protocol exception (text in self.last_exc)."""
        self.last_exc = None
        try:
            err = self.register(new_hostname).get("error", 0)
        except Exception as e:
            err = -1
            self.last_exc = str(e)
        self.last_error = err
        if err == 0:
            wait = _rand(3600, 7200)        # OK: 1-2 h
        elif err == ERR_DUPLICATE_DDNS_KEY:
            wait = 0                        # new key already generated -> retry now
        else:
            wait = _rand(60, 300)           # NG: 1-5 min
        return err, wait

    def run_forever(self):
        """Keep-alive: success -> next in 1-2h, failure -> 1-5min (random), dup key -> immediately."""
        while True:
            try:
                r = self.register()
                err = r.get("error", 0)
            except Exception as e:
                print("ddns: error", e)
                err = -1
            if err == 0:
                print("ddns: OK", self.fqdn, self.ipv4)
                wait = _rand(3600, 7200)
            elif err == ERR_DUPLICATE_DDNS_KEY:
                wait = 0
            else:
                print("ddns: failed", err, ERRORS.get(err, ""))
                wait = _rand(60, 300)
            time.sleep(wait)

def _rand(a, b):
    return a + struct.unpack(">I", os.urandom(4))[0] % (b - a + 1)

if __name__ == "__main__":
    import sys
    c = DDNSClient()
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        c.run_forever()
    r = c.change_hostname(sys.argv[1]) if len(sys.argv) > 1 else c.register()
    print(r)
