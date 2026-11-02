# dnsfix.py - minimal UDP DNS (A record) resolver for MicroPython / CPython.
# Fallback for firmware whose built-in resolver fails (e.g. getaddrinfo -> OSError -2
# seen on Raspberry Pi Pico 2 W) while plain UDP to a DNS server works.
try:
    import usocket as socket
except ImportError:
    import socket
import os, struct

FALLBACK_SERVERS = ("8.8.8.8", "1.1.1.1")
debug = False
dns_server_hook = None   # callable -> DNS server of the active interface (set by main.py)
feed = None              # callable to feed the watchdog between blocking steps
USE_BUILTIN = True       # try socket.getaddrinfo first (its timeout is not bounded!)

def _is_ipv4(s):
    p = s.split(".")
    if len(p) != 4:
        return False
    for x in p:
        if not x.isdigit() or int(x) > 255:
            return False
    return True

def _servers():
    out = []
    try:
        if dns_server_hook:
            dns = dns_server_hook()                        # DNS of the active interface (from DHCP)
        else:
            import network
            dns = network.WLAN(network.STA_IF).ifconfig()[3] if hasattr(network, "WLAN") else None
        if dns and dns != "0.0.0.0":
            out.append(dns)
    except Exception:
        pass
    for s in FALLBACK_SERVERS:
        if s not in out:
            out.append(s)
    return out

def build_query(host, qid):
    q = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)       # RD=1, QDCOUNT=1
    for label in host.rstrip(".").split("."):
        b = label.encode()
        q += bytes([len(b)]) + b
    return q + b"\x00" + struct.pack(">HH", 1, 1)              # QTYPE=A, QCLASS=IN

def _read_name(msg, p):
    """Returns (lower-case name, offset after the name). Handles compression pointers."""
    labels, end, jumps = [], None, 0
    while True:
        n = msg[p]
        if n & 0xC0 == 0xC0:
            if end is None:
                end = p + 2
            p = ((n & 0x3F) << 8) | msg[p + 1]
            jumps += 1
            if jumps > 20:
                raise ValueError("DNS pointer loop")
            continue
        if n == 0:
            p += 1
            break
        labels.append(bytes(msg[p + 1:p + 1 + n]).decode().lower())
        p += 1 + n
    return ".".join(labels), (end if end is not None else p)

def parse_response(msg, host=None, qid=None):
    """Returns list of IPv4 strings for host (following CNAME chain). Raises on error."""
    rid, flags, qd, an = struct.unpack(">HHHH", msg[:8])
    if qid is not None and rid != qid:
        raise ValueError("DNS id mismatch")
    if not flags & 0x8000:
        raise ValueError("not a DNS response")
    rcode = flags & 0x0F
    if rcode:
        raise OSError("DNS rcode %d" % rcode)
    p = 12
    for _ in range(qd):
        qname, p = _read_name(msg, p)
        p += 4
        if host is None:
            host = qname
    names = {host.rstrip(".").lower()}
    recs = []
    for _ in range(an):
        name, p = _read_name(msg, p)
        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", msg[p:p + 10])
        p += 10
        rdata_off = p
        p += rdlen
        recs.append((name, rtype, rdata_off, rdlen))
    for _ in range(len(recs)):                  # CNAME chain (any order)
        for name, rtype, off, ln in recs:
            if rtype == 5 and name in names:
                names.add(_read_name(msg, off)[0])
    ips = []
    for name, rtype, off, ln in recs:
        if rtype == 1 and ln == 4 and name in names:
            ips.append("%d.%d.%d.%d" % tuple(msg[off:off + 4]))
    return ips

def resolve(host, timeout=2, retries=2, servers=None):
    """host -> 'a.b.c.d' (first A record). Raises OSError if all servers fail."""
    if _is_ipv4(host):
        return host
    last = None
    for _ in range(retries):
        for srv in (servers or _servers()):
            if feed:
                feed()
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.settimeout(timeout)
                qid = struct.unpack(">H", os.urandom(2))[0]
                s.sendto(build_query(host, qid), (srv, 53))
                for _ in range(3):                 # ignore stray packets
                    msg = s.recv(512)
                    try:
                        ips = parse_response(msg, host, qid)
                    except ValueError as e:
                        last = e
                        continue
                    if ips:
                        return ips[0]
                    last = OSError("no A record for " + host)
                    break
            except Exception as e:
                last = e
                if debug:
                    print("dnsfix:", srv, e)
            finally:
                s.close()
    raise OSError("dnsfix: cannot resolve %s (%s)" % (host, last))

def getaddrinfo(host, port, af=0, type=0, proto=0, flags=0):
    """socket.getaddrinfo first (if USE_BUILTIN); on OSError use the UDP resolver (IPv4 only).
    With a watchdog, set USE_BUILTIN=False: the UDP resolver has bounded timeouts."""
    if USE_BUILTIN or _is_ipv4(host):
        try:
            return socket.getaddrinfo(host, port, af, type, proto, flags)
        except OSError as e:
            if debug:
                print("dnsfix: built-in getaddrinfo failed (%s), using UDP DNS" % e)
    ip = resolve(host)
    return [(socket.AF_INET, type or socket.SOCK_STREAM, proto, "", (ip, port))]
