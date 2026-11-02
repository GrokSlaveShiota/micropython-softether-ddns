# SoftEther DDNS Client — WIZnet W5100S-EVB-Pico2 (Wired LAN Only) Version

**Note:** This repository contains Japanese text in the source and documentation. 

The web UI (status page, hostname change, and initialization / device replacement page) is currently Japanese-only.


※ This project was developed by Grokbot with the goal of porting functionality from SoftEther VPN running on a Raspberry Pi.

- **Developed by:** Grokbot
- **Protocol source:** SoftEther VPN (`src/Cedar/DDNS.c`, `Wpc.c`, `Pack.c`, etc.)

### Special Thanks
* Deep thanks to **Grok (xAI)** for its excellent language model and advanced code analysis/generation capabilities that brought this project to life in just a few hours.
* Heartfelt thanks to the **University of Tsukuba SoftEther Project**, **Daiyuu Nobori**, and the other developers for maintaining and freely providing this high-quality DDNS service as an academic experiment.

This is a MicroPython reimplementation of only the following three features from the DDNS client built into SoftEther VPN Server (`*.softether.net`). It runs on the **wired LAN** of a WIZnet **W5100S-EVB-Pico2** (RP2350 + W5100S).

1. **New issuance**: Request a hostname (`vpnNNNNNNNN.softether.net`) with a new Key
2. **Hostname change**: Change to a desired name (3–31 characters) from the web interface
3. **Periodic update**: Re-register every 1–2 hours on success, or every 1–5 minutes on failure. Additionally, check the global IP every 10–20 minutes and re-register immediately if it has changed

See `PROTOCOL.md` for communication protocol details, and `THIRD_PARTY_LICENSES.txt` for license notices that should be bundled with the product.

## File Structure
```
| File                       | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| `main.py`                  | Startup, DDNS maintenance, status display / hostname change /|
|                            | init & device replacement web UI (port 80), watchdog         |
| `netif.py`                 | Wired LAN (W5100S) setup, DHCP, static IP fallback,          |
|                            | cable unplug / replug handling                               |
| `ddns_softether.py`        | Core DDNS client (register / getmyip / Key generation /      |
|                            | certificate hash verification)                               |
| `dnsfix.py`                | Simple short-timeout DNS (UDP) resolver                      |
| `keyxfer.py`               | DDNS Key export / import (device replacement)                |
| `config.py`                | Per-device settings (network, timeouts, watchdog, LED, etc.) |
| `PROTOCOL.md`              | DDNS protocol investigation notes                            |
| `THIRD_PARTY_LICENSES.txt` | License notices to include with the product                  |
```

Files automatically created on the device: `ddns_key.txt` (DDNS Key = proof of hostname ownership), `ddns_hostname.txt` (hostname selected via the web UI), and `bootinfo.json` (boot count and reboot reason).
No Wi-Fi is used, so no `secrets.py` is needed.

## 1. Install the Firmware (WIZnet MicroPython v1.29.0-preview)
- Download page: **https://github.com/WIZnet-ioNIC/WIZnet-EVB-Pico-micropython/releases**
- File to use: **`LWIP-W5100S_EVB_PICO2-v1.29.0-preview.uf2`** from release `v1.29.0-WIZnet-timeout`
  (release page: https://github.com/WIZnet-ioNIC/WIZnet-EVB-Pico-micropython/releases/tag/v1.29.0-WIZnet-timeout).
  Choose the file starting with `LWIP-` (lwIP build). The `TOE-` build and the official MicroPython Pico 2 firmware will not work.
- Flashing: Hold the **BOOTSEL button** while connecting USB → the `RP2350` drive appears on the PC → copy the `.uf2` file → the device reboots automatically.

## 2. Upload the Programs
1. Edit `config.py` if needed (the defaults are usually fine. If `HOSTNAME = None`, a `vpnNNNNNNNN` name is assigned automatically on first run).
2. Install `mpremote` on your PC (`pip install mpremote`), then from this folder run:
```
mpremote cp main.py netif.py ddns_softether.py dnsfix.py keyxfer.py config.py :
mpremote reset
```
**Do not delete `ddns_key.txt`** (you will lose the hostname).
3. Connect the LAN cable. View the logs: `mpremote repl` (exit with Ctrl+]).
Success is indicated by output like:
`lan: connected, IP (DHCP) = 192.168.x.x ...` → `ntp: synced via ...` → `ddns: OK vpnXXXX.softether.net -> global IP`

### Main settings in config.py
```
| Setting                       | Default                       | Description                                         |
| ----------------------------- | ----------------------------- | --------------------------------------------------- |
| `LAN_PINS`                    | `None`                        | W5100S wiring (SPI0: MISO=GP16, CS=GP17, SCK=GP18,  |
|                               |                               | MOSI=GP19, RSTn=GP20, INTn=GP21). `None` = board    |
|                               |                               | default; write only the differences to change it    |
|                               |                               | (e.g. `{"baudrate": 10_000_000}`)                   |
| `LAN_DHCP_TIMEOUT`            | `12`                          | Seconds to wait for DHCP after link-up, then static |
| `LAN_LINK_WAIT`               | `4`                           | Seconds without link = "cable not connected" ->     |
|                               |                               | static IP                                           |
| `LAN_DHCP_RETRY`              | `60`                          | DHCP retry interval while on static IP (0 = never)  |
| `LAN_FALLBACK_IP`             | `("192.168.14.199",           | Static IP (IP, netmask, gateway, DNS)               |
|                               |  "255.255.255.0",             |                                                     |
|                               |  "192.168.14.1",              |                                                     |
|                               |  "192.168.14.1")`             |                                                     |
| `NET_HOSTNAME`                | `"Pico2W"`                    | Device name sent to the DHCP server                 |
| `HOSTNAME`                    | `None`                        | DDNS hostname; a name set in the web UI takes       |
|                               |                               | priority                                            |
| `MACHINE_NAME`                | `"micropython"`               | Machine name sent to the DDNS server                |
| `WEB_PORT`                    | `80`                          | Web UI port                                         |
| `TZ_OFFSET`                   | `9 * 3600`                    | Time zone for display (JST)                         |
| `USE_NTP` / `NTP_HOST`        | `True` / `"pool.ntp.org"`     | Time sync                                           |
| `USE_WDT` / `WDT_TIMEOUT_MS`  | `True` / `8000`               | Watchdog                                            |
| `NO_SUCCESS_REBOOT_S`         | `6 * 3600`                    | Reboot if no DDNS registration succeeds for this    |
|                               |                               | many seconds (0 = off; not while on static IP)      |
| `CRASH_REBOOT_DELAY_S`        | `10`                          | Seconds before reboot after an unexpected exception |
| `USE_LED` / `LED_PIN`         | `True` / `25`                 | Status display on the onboard LED (GP25)            |
```

## 3. Operation
- On boot: Initialize the W5100S → check the link → DHCP → sync time via NTP → check global IP via getmyip → register with DDNS.
  On the first run, a Key is generated and saved to `ddns_key.txt` (a 20-byte random value created on the device. Same method as the original: mixes randomness, time, and the device’s ID/MAC via SHA-1; the MAC is that of the W5100S).
- **If DHCP fails or the cable is not connected**, the device starts with the static IP `192.168.14.199/24` (gateway and DNS `192.168.14.1`).
  While on the static IP, DHCP is retried every 60 seconds; once a lease is obtained, it switches to DHCP automatically.
- When the cable is unplugged, the status shows "disconnected"; when it is plugged back in, the network starts over (DHCP → static IP if DHCP fails).
  If the DHCP address is lost for more than 60 seconds, the LAN is re-initialized. Whenever the route changes, the global IP check and registration run immediately.
- NTP time sync runs after boot and then every 24 hours (retried after 60 seconds on failure). The time is for display only and is not used for registration intervals.
- The registered IP is the source address seen by the server = **the router’s global IP**. Separate router port forwarding is required to reach services from outside.

### Web Interface (http://<device IP>/)
Check the router’s DHCP lease list for the IP. **There is no authentication. Use only on the LAN** and do not expose port 80 externally.
If you cannot check the DHCP assignment on the router, you can find the assigned IPv4 address with `ping Pico2W -4` (on Windows).
When running on the static IP, open `http://192.168.14.199/` (set your PC to an address in the same 192.168.14.x range).
- **Status page `/`** (auto-refreshes every 30 seconds; paused while typing): connection type / link (cable) / IP method (DHCP or static, time until the next DHCP retry) /
  MAC / IP·netmask·gateway·DNS / global IP / hostname·FQDN / registered IPv4 / last result (0 = success, 132–137, -1 = communication error) /
  last and next registration / uptime / free memory / time / boot count and last reboot reason / watchdog / certificate verification result.
  A notice is shown at the top of the page while running on the static IP. The same data is available as JSON at `/status.json`.
- **Hostname change**: Enter a new name in the field at the bottom of the status page and press **OK** (confirmation dialog). 3–31 characters, alphanumeric and `-` (cannot start or end with `-`).
  The result (success / 133 = already in use, etc.) is shown in Japanese. The chosen name is saved to `ddns_hostname.txt` and persists across reboots. The old name is released.
- **Initialization / device replacement page `/init`** (link at the bottom of the status page): See the “Initialization / Device Replacement” section below.

## 4. Initialization / Device Replacement (DDNS Key)
Open `http://<device IP>/init`. It shows the MAC, IP, current hostname, whether a Key exists, and the boot count.
There are three actions. Each runs only after you press the button **and then OK in the confirmation dialog** (if JavaScript or the dialog is blocked, nothing is changed).
- **Export Key**: Downloads this device’s `ddns_key.txt`. Importing it on a new device keeps the same hostname.
- **Import Key**: Select a `ddns_key.txt` exported from the old device and press the import button. The current Key is overwritten,
  `ddns_hostname.txt` is deleted, and the device reboots after 5 seconds, then keeps registering with the hostname tied to that Key.
  The Key is 40 hex characters (upper or lower case; surrounding spaces / line breaks are allowed).
- **Delete Key**: Deletes `ddns_key.txt` and `ddns_hostname.txt` and reboots automatically after 5 seconds.
  After reboot, a new Key is generated and a new hostname (`vpnNNNNNNNN`) is assigned.
- After an action that reboots, the page waits for the reboot and returns to the top page automatically. DDNS registration is paused from deletion / import until reboot.
- During an active registration, the request is rejected with a “please wait a moment” message. `GET /reset` and similar do not exist (404).
- **If you cannot reach the web UI**, use USB:
  - Delete the Key: `mpremote rm :ddns_key.txt` and `mpremote rm :ddns_hostname.txt` → `mpremote reset`
  - Because the WDT may reset the device during file operations, enter “Safe Mode” first (see below).

> ⚠ **Keep the exported `ddns_key.txt` secret.** Anyone who has this file can take over the hostname
> (do not send it by e-mail or chat, and do not put it in shared folders). The Key is never shown in logs, the status page, or status.json.
> ⚠ **Deleting the Key without exporting it permanently loses the current hostname.** To back it up over USB:
> `mpremote cp :ddns_key.txt ddns_key_backup.txt` (restore with `mpremote cp ddns_key_backup.txt :ddns_key.txt`).
> Do not run the same Key on two devices at the same time (the IP will be overwritten alternately). When replacing a device, power off the old one first.
> Anyone on the same LAN can open this page (no authentication, same as hostname change). Use only on the LAN.

## 5. LED (Onboard LED, GP25)
```
| Display                          | Meaning                                         |
| -------------------------------- | ----------------------------------------------- |
| Solid on                         | Normal (DDNS registration successful)           |
| Slow blink (1 s on / 1 s off)    | Network up but DDNS not registered / error      |
| Short flash once every 2 s       | Running on static IP (no DHCP)                  |
| Fast blink                       | Network not connected (cable unplugged /        |
|                                  | initialization failed)                          |
| Double blink                     | Waiting for reboot after Key deletion / import  |
| Fast blink for first 3 seconds   | Safe mode window (press BOOTSEL during this to  |
|  after boot                      | enter safe mode)                                |
```
Disable with `USE_LED = False` in `config.py`.

## 6. Recovery Mechanisms (Auto-Recovery)
- **Watchdog** (`USE_WDT = True`, 8 seconds): A dedicated task feeds it every second. If the main loop stops for more than 2 minutes, feeding stops and the device resets.
  Socket operations timeout at 3 seconds, DNS at 2 seconds per attempt, and the watchdog is fed between TLS and DNS steps.
- **Exception guard**: Unexpected exceptions are logged, then the device reboots after 10 seconds.
- **Reboot on prolonged failure**: If DDNS registration has not succeeded even once for 6 hours (`NO_SUCCESS_REBOOT_S`), the device reboots (not while running on the static IP).
- **Boot count and reboot reason**: Recorded in `bootinfo.json` and shown on the status page (written only at boot and immediately before an intentional reboot).

## 7. Recovery / Development Operations (Safe Mode)
Once the rp2 watchdog starts, it cannot be stopped (even entering the REPL with Ctrl+C will reset after about 8 seconds). Do one of the following before file operations:
- **Safe mode** (does not start main.py processing and does not run the WDT):
  - After power-on or reset, **press BOOTSEL during the first 3 seconds while the LED is blinking fast**
    (if you hold it before power-on, it enters USB flashing mode, so press it after boot starts).
  - Or: `mpremote touch :safemode` → `mpremote reset`. To exit: `mpremote rm :safemode` → `mpremote reset`.
- **Disable only the WDT**: `mpremote touch :nowdt` (to re-enable: `mpremote rm :nowdt`), or set `USE_WDT = False` in `config.py`.
- If it still does not work: Reflash the firmware (hold BOOTSEL while connecting USB → copy the `.uf2`).
  Files are preserved, but back up `ddns_key.txt` just in case.

## 8. Name Resolution (DNS)
`dnsfix.py` queries, in order: the DNS server received via DHCP (the `LAN_FALLBACK_IP` DNS while on the static IP) → 8.8.8.8 → 1.1.1.1 (2 seconds per server, up to 2 attempts).
While the watchdog is enabled, the built-in `getaddrinfo` (whose timeout cannot be kept short) is not used.
NTP also uses a small SNTP implementation inside `main.py` instead of `ntptime`.

## 9. Certificate Verification (Anti-Impersonation)
Before sending the Key, the SHA-1 hash of the DDNS server certificate is checked against the same 9 built-in hashes (`DDNS_CERT_HASH`) as the original.
If it does not match, the client **fails without sending the Key** (`tls` module `CERT_OPTIONAL` + `verify_callback`). No certificate file is required.
The status page’s “Server Certificate” field shows something like `pinned via verify_callback EFAC5FA0`.

## 10. Terms of Use
- The softether.net DDNS service is provided **free of charge as an academic experiment** by the University of Tsukuba SoftEther Project. It is provided as-is, without warranty, and may be discontinued without notice.
  It is originally a feature for SoftEther VPN Server. If incorporating this into a product for delivery, explain this to your customers.
- The client identifies itself with values such as `product_str="SoftEther OSS"` (same as the original). Registration intervals are also the same as the original.

## 11. License
- The Python files in this package (`main.py`, `netif.py`, `ddns_softether.py`, `dnsfix.py`, `keyxfer.py`, `config.py`) were newly written
  by analyzing the SoftEther VPN protocol; no SoftEther code was copied.
  However, constants (URLs, the certificate hashes `DDNS_CERT_HASH`, etc.) come from the SoftEther VPN source (Apache License 2.0).
- The firmware (WIZnet MicroPython; not bundled with this package) contains:
  MicroPython (MIT), micropython-lib (MIT), Raspberry Pi pico-sdk (BSD-3-Clause), TinyUSB (MIT), lwIP (BSD-3-Clause),
  Mbed TLS (Apache-2.0), and WIZnet ioLibrary_Driver (MIT).
- When delivering this as a product, give `THIRD_PARTY_LICENSES.txt` to your customers (printed, as a PDF, or as a file).
