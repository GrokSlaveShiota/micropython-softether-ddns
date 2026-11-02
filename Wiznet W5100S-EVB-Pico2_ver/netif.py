# netif.py - wired LAN manager for WIZnet W5100S-EVB-Pico2 (RP2350 + W5100S over SPI0).
# Needs a MicroPython firmware with the WIZnet NIC driver for this board (class network.WIZNET6K
# in WIZnet's LWIP build; network.WIZNET5K in other builds - both names are tried).
# Boot: DHCP. If there is no DHCP answer (or no cable) -> static fallback address (FALLBACK_IP).
# While in fallback the DHCP is retried (DHCP_RETRY_S); cable out / back in is handled in ensure().
# Never blocks for long: everything is awaited by polling so the watchdog keeps running.
try:
    import asyncio
except ImportError:
    import uasyncio as asyncio
import time
import network

try:
    ticks_ms, ticks_diff, ticks_add = time.ticks_ms, time.ticks_diff, time.ticks_add
except AttributeError:
    ticks_ms = lambda: int(time.monotonic() * 1000)
    ticks_diff = lambda a, b: a - b
    ticks_add = lambda a, b: a + b

# ---- settings (override from config.py if you like; see main.py) ----
# W5100S-EVB-Pico2 wiring is fixed on the board (WIZnet docs / pico-sdk board header):
#   SPI0: MISO=GP16, CS=GP17, SCK=GP18, MOSI=GP19, RSTn=GP20, INTn=GP21
LAN_PINS = {"spi": 0, "sck": 18, "mosi": 19, "miso": 16, "cs": 17, "rst": 20, "int": 21,
            "baudrate": 20_000_000}
DHCP_TIMEOUT_S = 12          # boot / re-init: seconds to wait for a DHCP lease
LINK_WAIT_S = 4              # boot / re-init: seconds to wait for the cable link (PHY auto-negotiation)
DHCP_RETRY_S = 60            # in fallback: try DHCP again this often (0 = never)
# Fallback (static) configuration: IP, netmask, gateway, DNS
FALLBACK_IP = ("192.168.14.199", "255.255.255.0", "192.168.14.1", "192.168.14.1")
NET_HOSTNAME = "Pico2W"      # name sent to the DHCP server (None = leave the firmware default)

def _mac_str(b):
    try:
        return ":".join("%02x" % x for x in bytes(b))
    except Exception:
        return None

ZERO = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")

def _nic_class():
    return getattr(network, "WIZNET6K", None) or getattr(network, "WIZNET5K", None)

class Net:
    def __init__(self, lan_pins=None, dhcp_timeout=None, fallback_ip=None, link_wait=None,
                 dhcp_retry=None, hostname=NET_HOSTNAME):
        p = dict(LAN_PINS)
        p.update(lan_pins or {})
        self.lan_pins = p
        self.explicit_pins = bool(lan_pins)          # True: skip the board's built-in default config
        self.dhcp_timeout = DHCP_TIMEOUT_S if dhcp_timeout is None else dhcp_timeout
        self.link_wait = LINK_WAIT_S if link_wait is None else link_wait
        self.dhcp_retry = DHCP_RETRY_S if dhcp_retry is None else dhcp_retry
        self.fallback_ip = tuple(fallback_ip or FALLBACK_IP)
        self.hostname = hostname
        self.lan = None
        self.kind = None                    # "lan" | None
        self.mode = None                    # "dhcp" | "static" | None
        self.lan_error = None
        self.mode_ticks = ticks_ms()        # when mode last changed
        self._logged = False
        self._lost = False                  # cable was seen unplugged
        self._next_retry = None             # fallback: next DHCP retry
        self._next_init = None              # after a failed init: do not retry too fast
        self._noip_since = None             # DHCP mode: link up but no address since

    # ---- helpers ----
    @property
    def fallback(self):
        return self.mode == "static"

    def available(self):
        return _nic_class() is not None

    def _lan_obj(self):
        """Create the NIC object once. Default: the board's own configuration (no arguments);
        if that is not available (or lan_pins was given) the pins of LAN_PINS are passed explicitly."""
        if self.lan is None:
            cls = _nic_class()
            if self.hostname:
                try:
                    network.hostname(self.hostname)
                except Exception as e:
                    print("lan: hostname not set", e)
            nic = None
            if not self.explicit_pins:
                try:
                    nic = cls()
                except Exception as e:
                    print("lan: board default config unavailable (%s), using explicit pins" % (e,))
            if nic is None:
                from machine import Pin, SPI
                p = self.lan_pins
                spi = SPI(p["spi"], baudrate=p["baudrate"], sck=Pin(p["sck"]),
                          mosi=Pin(p["mosi"]), miso=Pin(p["miso"]))
                if p.get("int") is not None:     # INTn -> interrupt-driven receive
                    nic = cls(spi, Pin(p["cs"]), Pin(p["rst"]), Pin(p["int"]))
                else:
                    nic = cls(spi, Pin(p["cs"]), Pin(p["rst"]))
            self.lan = nic
        return self.lan

    def link(self):
        """Cable / PHY link: True, False, or None if unknown (not initialised yet).
        Only read once the chip has been activated (before that the driver cannot talk to it)."""
        try:
            nic = self.lan
            if nic is None or not nic.active():
                return None
            return nic.status() != 0
        except Exception:
            return None

    def _activate(self):
        """(Re)initialise the W5100S. active(True) resets the chip (~0.5 s, blocking) and lwIP then
        starts DHCP by itself."""
        nic = self._lan_obj()
        if nic.active():
            nic.active(False)
        nic.active(True)
        return nic

    def _set_mode(self, mode):
        if mode != self.mode:
            self.mode_ticks = ticks_ms()
        self.mode = mode
        self.kind = "lan" if mode else None
        self._logged = False
        self._noip_since = None
        self._next_retry = None
        if mode == "static" and self.dhcp_retry:
            self._next_retry = ticks_add(ticks_ms(), self.dhcp_retry * 1000)

    def _to_static(self, nic):
        nic.ifconfig(self.fallback_ip)              # stops DHCP, sets the static address
        self._set_mode("static")

    async def start_lan(self):
        """Activate the W5100S, wait for link and DHCP (polling). Returns "dhcp", "static" or None.
        No link, or no DHCP lease in dhcp_timeout seconds -> static FALLBACK_IP."""
        if not self.available():
            self.lan_error = "network.WIZNET6K / WIZNET5K not in firmware"
            print("lan:", self.lan_error, "- flash the W5100S-EVB-Pico2 firmware")
            return None
        try:
            nic = self._activate()
        except Exception as e:
            self.lan_error = "%s" % (e,)
            self._set_mode(None)
            self._next_init = ticks_add(ticks_ms(), 10000)
            print("lan: init failed", e)
            return None
        self.lan_error = None
        self._lost = False
        t0 = ticks_ms()
        while self.link() is False:                      # PHY auto-negotiation takes ~1-3 s (None = unknown: go on)
            if ticks_diff(ticks_ms(), t0) >= self.link_wait * 1000:
                self._to_static(nic)
                print("lan: no link (cable not connected) -> static IP", self.fallback_ip[0])
                self._lost = True                        # report as link-down until the cable shows up
                return "static"
            await asyncio.sleep(0.2)
        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < self.dhcp_timeout * 1000:
            if nic.isconnected():
                self._set_mode("dhcp")
                return "dhcp"
            await asyncio.sleep(0.25)
        self._to_static(nic)
        print("lan: DHCP failed (%d s) -> static IP %s" % (self.dhcp_timeout, self.fallback_ip[0]))
        return "static"

    async def start(self):
        """Boot-time bring-up. Returns "dhcp", "static" (fallback) or None."""
        return await self.start_lan()

    def is_up(self):
        try:
            return self.kind == "lan" and self.link() is not False and bool(self.lan.isconnected())
        except Exception:
            return False

    def _has_dhcp(self):
        """True when the current address came from DHCP."""
        try:
            return bool(self.lan.ipconfig("has_dhcp4"))
        except Exception:
            return False

    async def _retry_dhcp(self):
        """Fallback only: ask DHCP again while keeping the static address (lwIP keeps it until a
        lease arrives). Returns True when switched to DHCP."""
        nic = self.lan
        print("lan: fallback -> retrying DHCP")
        try:
            nic.ipconfig(dhcp4=True)
        except Exception:                                # driver without ipconfig(): re-init instead
            return await self.start_lan() == "dhcp"
        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < self.dhcp_timeout * 1000:
            if self._has_dhcp():
                self._set_mode("dhcp")
                print("lan: DHCP obtained -> leaving fallback")
                return True
            if self.link() is False:
                return False
            await asyncio.sleep(0.5)
        return False

    async def ensure(self):
        """Called periodically. Returns True when the network is usable (dhcp or static with link)."""
        if self.mode is None:                            # init failed earlier / not started
            if self._next_init is not None and ticks_diff(ticks_ms(), self._next_init) < 0:
                return False
            return await self.start_lan() is not None and self.is_up()
        link = self.link()
        if link is False:
            if not self._lost:
                print("lan: link down")
            self._lost = True
            return False
        if link is True and self._lost:                  # cable (re)connected -> start over: DHCP, else static
            print("lan: link up -> re-init / DHCP")
            await asyncio.sleep(1)                       # let the switch port settle
            await self.start_lan()
            return self.is_up()
        if self.mode == "static":
            if self._has_dhcp():                         # a lease arrived in the background
                self._set_mode("dhcp")
                print("lan: DHCP obtained -> leaving fallback")
            elif self._next_retry is not None and ticks_diff(ticks_ms(), self._next_retry) >= 0:
                self._next_retry = ticks_add(ticks_ms(), self.dhcp_retry * 1000)
                await self._retry_dhcp()
            return self.is_up()
        # DHCP mode: link is up. If the address disappears for a long time, re-init.
        if self.lan.isconnected():
            self._noip_since = None
            return True
        if self._noip_since is None:
            self._noip_since = ticks_ms()
        elif ticks_diff(ticks_ms(), self._noip_since) > 60000:
            print("lan: no address for 60 s -> re-init")
            await self.start_lan()
            return self.is_up()
        return False

    def nic(self):
        return self.lan

    def mac(self):
        try:
            return bytes(self.lan.config("mac")) if self.lan is not None else None
        except Exception:
            return None

    def ifconfig(self):
        try:
            return self.lan.ifconfig()
        except Exception:
            return ZERO

    def dns(self):
        return self.ifconfig()[3]

    def log_once(self):
        if not self._logged:
            c = self.ifconfig()
            print("lan: connected, IP (%s) = %s  mask %s  gw %s  dns %s"
                  % ((("static fallback" if self.fallback else "DHCP"),) + tuple(c)))
            self._logged = True

    def info(self):
        up = self.is_up()
        i = {"iface": self.kind, "mode": self.mode, "fallback": self.fallback, "link": None,
             "connected": up, "mac": None, "ip": None, "netmask": None, "gateway": None, "dns": None,
             "lan_error": self.lan_error, "dhcp_retry_in_s": None, "fallback_ip": self.fallback_ip[0]}
        if self.lan is None:
            return i
        i["ip"], i["netmask"], i["gateway"], i["dns"] = self.ifconfig()
        i["mac"] = _mac_str(self.mac())
        i["link"] = self.link()
        if self.fallback and self._next_retry is not None:
            i["dhcp_retry_in_s"] = max(0, ticks_diff(self._next_retry, ticks_ms()) // 1000)
        return i
