# netif.py - Wi-Fi (CYW43, network.WLAN) interface manager for Raspberry Pi Pico 2 W.
# DHCP only. Never blocks: connection is awaited by polling so the watchdog keeps running.
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio
import time
import network

try:
    ticks_ms, ticks_diff = time.ticks_ms, time.ticks_diff
except AttributeError:
    ticks_ms = lambda: int(time.monotonic() * 1000)
    ticks_diff = lambda a, b: a - b

def _mac_str(b):
    try:
        return ":".join("%02x" % x for x in bytes(b))
    except Exception:
        return None

ZERO = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")

class Net:
    def __init__(self, wifi_ssid=None, wifi_password=None, wifi_timeout=30):
        self.ssid = wifi_ssid
        self._pw = wifi_password            # never printed / never put into status
        self.wifi_timeout = wifi_timeout
        self.wlan = None
        self.kind = None                    # "wifi" | None
        self.fallback = False               # no static fallback on Wi-Fi
        self._logged = False

    def _obj(self):
        if self.wlan is None:
            self.wlan = network.WLAN(network.STA_IF)
        return self.wlan

    async def start_wifi(self):
        w = self._obj()
        if w.isconnected():
            self.kind = "wifi"
            return True
        if not self.ssid:
            print("wifi: WIFI_SSID not set (create secrets.py)")
            return False
        w.active(False)                      # clean re-init after a failure
        w.active(True)
        print("wifi: connecting to", self.ssid)
        w.connect(self.ssid, self._pw)       # DHCP
        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < self.wifi_timeout * 1000:
            if w.isconnected():
                self.kind, self._logged = "wifi", False
                return True
            await asyncio.sleep(1)
        print("wifi: connect timeout")
        w.active(False)
        return False

    async def start(self):
        """Boot-time bring-up. Returns "wifi" or None (keeps retrying in ensure())."""
        return "wifi" if await self.start_wifi() else None

    def is_up(self):
        try:
            return self.kind == "wifi" and bool(self.wlan.isconnected())
        except Exception:
            return False

    async def ensure(self):
        """Called periodically. Returns True when the network is usable; reconnects otherwise."""
        if self.is_up():
            return True
        if self.kind == "wifi":
            print("wifi: disconnected, reconnecting")
        self.kind = None
        return await self.start_wifi()

    def nic(self):
        return self.wlan

    def mac(self):
        try:
            return bytes(self._obj().config("mac"))
        except Exception:
            return None

    def ifconfig(self):
        try:
            return self.wlan.ifconfig()
        except Exception:
            return ZERO

    def dns(self):
        return self.ifconfig()[3]

    def log_once(self):
        if not self._logged:
            c = self.ifconfig()
            print("wifi: connected, IP (DHCP) = %s  mask %s  gw %s  dns %s" % c)
            self._logged = True

    def info(self):
        up = self.is_up()
        i = {"iface": self.kind, "fallback": False, "link": up, "connected": up,
             "mac": None, "ip": None, "netmask": None, "gateway": None, "dns": None,
             "ssid": self.ssid, "rssi": None}
        if self.wlan is None:
            return i
        i["ip"], i["netmask"], i["gateway"], i["dns"] = self.ifconfig()
        i["mac"] = _mac_str(self.mac())
        if up:
            try:
                i["rssi"] = self.wlan.status("rssi")
            except Exception:
                pass
        return i
