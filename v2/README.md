# SoftEther DDNS Client — Raspberry Pi Pico 2 W (Wi-Fi Only) Version

**Note:** This repository contains Japanese text in the source and documentation. 

The web UI (status page, hostname change, and initialization page) is currently Japanese-only.


※ This project was developed by Grokbot with the goal of porting functionality from SoftEther VPN running on a Raspberry Pi.

- **Developed by:** Grokbot
- **Protocol source:** SoftEther VPN (`src/Cedar/DDNS.c`, `Wpc.c`, `Pack.c`, etc.)

### Special Thanks
* Deep thanks to **Grok (xAI)** for its excellent language model and advanced code analysis/generation capabilities that brought this project to life in just a few hours.
* Heartfelt thanks to the **University of Tsukuba SoftEther Project**, **Daiyuu Nobori**, and the other developers for maintaining and freely providing this high-quality DDNS service as an academic experiment.

This is a MicroPython reimplementation of only the following three features from the DDNS client built into SoftEther VPN Server (`*.softether.net`). It runs on the **Wi-Fi** of a Raspberry Pi **Pico 2 W**.

1. **New issuance**: Request a hostname (`vpnNNNNNNNN.softether.net`) with a new Key
2. **Hostname change**: Change to a desired name (3–31 characters) from the web interface
3. **Periodic update**: Re-register every 1–2 hours on success, or every 1–5 minutes on failure. Additionally, check the global IP every 10–20 minutes and re-register immediately if it has changed

See `PROTOCOL.md` for communication protocol details, and `THIRD_PARTY_LICENSES.txt` for license notices that should be bundled with the product.

## File Structure
```
| File                       | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| `main.py`                  | Startup, DDNS maintenance, status display / hostname change /|
|                            | init web UI (port 80), watchdog                              |
| `keyxfer.py`               | Key export / import / delete on the init page                |
|                            | (buttons with confirmation dialogs)                          |
| `netif.py`                 | Wi-Fi connection (DHCP) and reconnection                     |
| `ddns_softether.py`        | Core DDNS client (register / getmyip / Key generation /      |
|                            | certificate hash verification)                               |
| `dnsfix.py`                | Simple short-timeout DNS (UDP) resolver                      |
|                            | (workaround for Pico 2 W name resolution issues)             |
| `config.py`                | Per-device settings (timeouts, watchdog, LED, etc.)          |
| `secrets_example.py`       | Template for `secrets.py` (Wi-Fi SSID / password)            |
| `PROTOCOL.md`              | DDNS protocol investigation notes                            |
| `THIRD_PARTY_LICENSES.txt` | License notices to include with the product                  |
```

Files automatically created on the device: `ddns_key.txt` (DDNS Key = proof of hostname ownership), `ddns_hostname.txt` (hostname selected via the web UI), and `bootinfo.json` (boot count and reboot reason).

## 1. Install the Firmware (Official MicroPython v1.29.x)
- Official page: **https://micropython.org/download/RPI_PICO2_W/**
- Tested version: `RPI_PICO2_W-20260824-v1.29.0.uf2`
  (Direct link: https://micropython.org/resources/firmware/RPI_PICO2_W-20260824-v1.29.0.uf2).
  Newer patch versions of v1.29.x are fine. No custom firmware is required.
- Flashing: Hold the **BOOTSEL button** while connecting USB → the `RP2350` drive appears on the PC → copy the `.uf2` file → the device reboots automatically.

## 2. Upload the Programs
1. Copy `secrets_example.py` to `secrets.py` and set `WIFI_SSID` and `WIFI_PASSWORD`.
   **Do not share or publish `secrets.py`** (the password is never shown in the web UI, status.json, or logs).
2. Edit `config.py` if needed (the defaults are usually fine. If `HOSTNAME = None`, a `vpnNNNNNNNN` name is assigned automatically on first run).
3. Install `mpremote` on your PC (`pip install mpremote`), then from this folder run:
```
mpremote cp main.py keyxfer.py netif.py ddns_softether.py dnsfix.py config.py secrets.py :
mpremote reset
```
**Do not delete `ddns_key.txt`** (you will lose the hostname).
4. View the logs: `mpremote repl` (exit with Ctrl+]).
Success is indicated by output like:
`wifi: connected, IP (DHCP) = 192.168.x.x ...` → `ntp: synced via ...` → `ddns: OK vpnXXXX.softether.net -> global IP`

## 3. Operation
- On boot: Connect to Wi-Fi (DHCP) → sync time via NTP → check global IP via getmyip → register with DDNS.
  On the first run, a Key is generated and saved to `ddns_key.txt` (a 20-byte random value created on the device. Same method as the original: mixes randomness, time, and the device’s ID/MAC via SHA-1).
- If Wi-Fi drops, it automatically reconnects. It keeps retrying while disconnected (it never falls back to a static IP).
- The registered IP is the source address seen by the server = **the router’s global IP**. Separate router port forwarding is required to reach services from outside.

### Web Interface (http://<device IP>/)
Check the router’s DHCP lease list for the IP. **There is no authentication. Use only on the LAN** and do not expose port 80 externally.
If you cannot check the DHCP assignment on the router, you can find the assigned IPv4 address with `ping Pico2W -4` (on Windows).
- **Status page `/`** (auto-refreshes every 30 seconds): Wi-Fi status / SSID / signal strength / MAC / IP·gateway·DNS / global IP / hostname·FQDN / last result (0 = success, 132–137, -1 = communication error) / last and next registration / uptime / free memory / time / boot count and last reboot reason / watchdog / certificate verification result. The same data is available as JSON at `/status.json`.
- **Hostname change**: Enter a new name in the field at the bottom of the status page and press **OK** (confirmation dialog). 3–31 characters, alphanumeric and `-` (cannot start or end with `-`).
  The result (success / 133 = already in use, etc.) is shown in Japanese. The chosen name is saved to `ddns_hostname.txt` and persists across reboots. The old name is released.
- **Initialization page `/init`** (link at the bottom of the status page: “初期化・機器入れ替え（DDNS Key）”): See the “Initialization / Device Replacement” section below.

## 4. Initialization / Device Replacement (DDNS Key)
The initialization page is **part of the normal web UI**. Open `http://<device IP>/init` (also linked from the bottom of the status page).
It shows the MAC, IP, current hostname, and whether a Key exists, and has three buttons. Each button shows a **final confirmation dialog**,
and the action runs only when you press OK (Cancel, or a browser that blocks JavaScript or dialogs, changes nothing).

| Button | Action |
|---|---|
| **Export Key** | Downloads the device’s `ddns_key.txt` (for device replacement / backup) |
| **Import Key** | Overwrites the current Key with the selected `ddns_key.txt`, deletes `ddns_hostname.txt`, and reboots after 5 seconds |
| **Delete Key** | Deletes `ddns_key.txt` and `ddns_hostname.txt`, and reboots after 5 seconds |

- After import or delete, the result page waits for the reboot to finish and **automatically returns to the top page**
  (if it cannot return within 2 minutes, the IP may have changed; reopen the page at the new IP). DDNS registration is paused until the reboot.
- Only a file (40 hexadecimal characters) can be imported. A wrong length, invalid characters, or a file that is too large (over 2 KB) is rejected with a Japanese error and nothing is changed.
- During an active registration, the request is rejected with a “please wait a moment” message. `GET /export`, `/import` and `/reset` do not exist (404).
- After deletion, a new Key is generated and a new hostname (`vpnNNNNNNNN`) is assigned. Check the status page.

### Device Replacement Procedure
1. On the old device’s `/init`, click **Export Key** and save `ddns_key.txt`.
2. **Power off the old device** (or disconnect it from the LAN).
3. Start the new device (leave `HOSTNAME = None` in `config.py`), open its `/init`, select the file from step 1, and click **Import Key**.
4. After the reboot, confirm on the status page that the hostname is the same as on the old device.

### If Wi-Fi Cannot Connect
If you cannot reach the web UI (e.g., after an SSID/password change), use USB:
- Fix Wi-Fi settings: Rewrite `secrets.py`, then `mpremote cp secrets.py :` → `mpremote reset`
- Delete the Key: `mpremote rm :ddns_key.txt` and `mpremote rm :ddns_hostname.txt` → `mpremote reset`
- Because the WDT may reset the device during file operations, enter “Safe Mode” first (see below).

> ⚠ **Deleting the Key permanently loses the current hostname.** If you want to keep it, back it up first with
> `mpremote cp :ddns_key.txt ddns_key_backup.txt` (restore with `mpremote cp ddns_key_backup.txt :ddns_key.txt`).
> Do not run the same Key on two devices at the same time (the IP will be overwritten alternately).
> Keep an exported `ddns_key.txt` secret (anyone who has it can take over this hostname).
> Anyone on the same LAN can open the initialization page (no authentication, same as hostname change). Use only on the LAN.

## 5. LED (Onboard LED)
```
| Display                          | Meaning                                         |
| -------------------------------- | ----------------------------------------------- |
| Solid on                         | Normal (DDNS registration successful)           |
| Slow blink (1 s on / 1 s off)    | Wi-Fi connected but DDNS not registered / error |
| Fast blink                       | Wi-Fi not connected (connecting / retrying)     |
| Double blink                     | Waiting for reboot after Key delete / import    |
| Fast blink for first 3 seconds   |Safe mode window (press BOOTSEL during this to   |
|  after boot                      | enter safe mode)                                |
```
Disable with `USE_LED = False` in `config.py`.

## 6. Recovery Mechanisms (Auto-Recovery)
- **Watchdog** (`USE_WDT = True`, 8 seconds): A dedicated task feeds it every second. If the main loop stops for more than 2 minutes, feeding stops and the device resets.
  Socket operations timeout at 3 seconds, DNS at 2 seconds per attempt, and the watchdog is fed between TLS and DNS steps.
- **Exception guard**: Unexpected exceptions are logged, then the device reboots after 10 seconds.
- **Reboot on prolonged failure**: If DDNS registration has not succeeded even once for 6 hours (`NO_SUCCESS_REBOOT_S`), the device reboots.
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

## 8. Name Resolution (DNS) on Pico 2 W
On Pico 2 W MicroPython, `socket.getaddrinfo()` has been observed to raise `OSError -2` (while plain UDP communication works).
`dnsfix.py` queries, in order: the DNS server received via DHCP → 8.8.8.8 → 1.1.1.1 (2 seconds per server, up to 2 attempts).
NTP also uses a small SNTP implementation inside `main.py` instead of `ntptime`.

## 9. Certificate Verification (Anti-Impersonation)
Before sending the Key, the SHA-1 hash of the DDNS server certificate is checked against the same 9 built-in hashes (`DDNS_CERT_HASH`) as the original.
If it does not match, the client **fails without sending the Key** (`tls` module `CERT_OPTIONAL` + `verify_callback`). No certificate file is required.
The status page’s “Server Certificate” field shows something like `pinned via verify_callback EFAC5FA0`.

## 10. Real Device Verification Status
- On Pico 2 W (official v1.29 series firmware) + Wi-Fi: DDNS registration, certificate verification (`verify_callback`), and hostname change via the web UI have been confirmed.

## 11. Terms of Use
- The softether.net DDNS service is provided **free of charge as an academic experiment** by the University of Tsukuba SoftEther Project. It is provided as-is, without warranty, and may be discontinued without notice.
  It is originally a feature for SoftEther VPN Server. If incorporating this into a product for delivery, explain this to your customers.
- The client identifies itself with values such as `product_str="SoftEther OSS"` (same as the original). Registration intervals are also the same as the original.
