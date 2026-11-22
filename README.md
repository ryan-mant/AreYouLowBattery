# 🔋 AreYouLowBattery

> **Ultra-lightweight, cross-platform peripheral battery telemetry monitor & System Tray indicator for Linux & Windows.**  
> Monitor your wireless gaming mice, keyboards, and headsets with **low-latency Game Mode**, **~0.1% idle CPU overhead**, and **sleep-aware polling**.

Works out-of-the-box on **Linux** (KDE Plasma, GNOME, XFCE, Hyprland, Sway, Waybar, Polybar) and **Windows 10 & 11**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)](https://python.org)
[![Platform: Linux & Windows](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-informational.svg)](#-quick-start)

---

## 📸 Interface Preview

<p align="center">
  <img src="assets/preview_dashboard.png" alt="AreYouLowBattery System Tray Dashboard" width="320" />
  &nbsp;&nbsp;&nbsp;
  <img src="assets/preview_discovery.png" alt="AreYouLowBattery Device Discovery Dialog" width="480" />
</p>

---

## 📖 About the Project

Most wireless gaming peripherals (especially popular enthusiast brands like Delux, Attack Shark, Ajazz, VXE, ATK, Lamzu, Scyrox, as well as major brands like Logitech, Razer, SteelSeries, Corsair, and HyperX) rely on heavy, bloated proprietary companion suites (like G HUB, Razer Synapse, or iCUE) or offer **no native Linux software at all**.

**AreYouLowBattery** bridges this gap:
- **Game Mode & Sensor Isolation:** Reads secondary vendor telemetry endpoints (`Interface 1/2`) without touching the primary motion stream (`Interface 0`). During detected competitive games, forced refreshes are blocked and polling relaxes to 180s. The tray menu shows when Game Mode is active and lets you turn it on manually with **Pause Polling (Game Mode)**.
- **Passive Sleep Guard:** When a peripheral is confirmed asleep or powered off, active RF polling pauses for 300s to avoid unnecessary transceiver wake-ups.
- **Low Overhead:** Uses **~0.0% - 0.3% CPU** in idle (~36 MB RAM from source; ~33 MB systemd cgroup / ~104 MB RSS in Linux `--onedir` bundle). Telemetry cache resides in shared memory (`/dev/shm`), causing **0 disk writes/sec** to preserve SSD lifespan.
- **Cross-Platform Architecture:** Unified PySide6 UI and protocol engine running on Linux (`hidraw`, `udev`, BlueZ/UPower) and Windows (`hidapi`, Win32 `SetupAPI`), tailored to each OS's native APIs.

> 📋 **For full version history and release patch notes, see [CHANGELOG.md](CHANGELOG.md).**

---

## 🎮 Supported Hardware Matrix

> **Legend:** **✅ Verified** = confirmed on physical hardware · **🧪 Experimental** = protocol implemented, awaiting community hardware validation

| Brand / Device | USB IDs (`VID:PID`) | Protocol / Chipset | Status | Features |
| :--- | :--- | :--- | :--- | :--- |
| **CompX 1K / 8K Mice (Delux M900 Pro, Ajazz AJ199/AJ139/AJ159, Attack Shark)** | `1d57:*` / `25a7:fa7b` / `25a7:fa7c` | CompX (`compx_v1`) | ✅ Verified | Live %, Magnetic Dock / USB-C charging (`⚡`), ETA to 100% |
| **ATK A9 Air / Compx 8K Wireless Mice** | `373b:11d9` / `373b:120a` | Nordic / Compx 8K (`nordic_v1`) | ✅ Verified | Live % over 8K dongle via Output Report `0x08` + hardened `udev` rules |
| **Smailwolf RS7 / EWEADN G5 / MCHOSE G7** | `a8a5:2255` / `a8a4:2255` | YJX-CHIP (`yjx_v1`) | ✅ Verified | Live battery %, USB cable & RF charging status, sleep cache (by [@EdevandoAlves](https://github.com/EdevandoAlves)) |
| **GameSir Cyclone 2 (XInput Dongle)** | `3537:100b` | GameSir (`gamesir_v1`) | ✅ Verified | Live battery % and charging telemetry over 2.4G dongle (by [@EdevandoAlves](https://github.com/EdevandoAlves)) |
| **Royalaxe R68** | `25a7:2420` / Bluetooth | CompX / BLE Dual-Mode | ✅ Verified | Unifies 2.4G dongle with Bluetooth battery telemetry |
| **Baseus AeQur GH02** | `10d6:4802` / Bluetooth | Actions Semi / BLE Dual-Mode | ✅ Verified | Dual-mode Bluetooth BLE telemetry |
| **Bluetooth Peripherals (All Brands)** | Bluetooth GATT / UPower / Win32 SetupAPI | `bluetooth` / `0x180F` | ✅ Verified | Universal BLE Battery Service and HFP telemetry (Linux & Windows) |
| **Logitech Lightspeed, Unifying & Nano Receivers** | `046d:*` / `046d:c534` | Logitech HID++ 1.0/2.0 (`hidpp_v1` / `hidpp_v2`) | 🧪 Experimental | Works via Linux `sysfs`; Windows `hidapi` & legacy Nano receivers (`046d:c534`) under validation |
| **VXE R1 Pro / Mad R / ATK F1 / Scyrox V8 / Lamzu 4K** | `3554:*` | Nordic nRF52840 4K/8K (`nordic_v1`) | 🧪 Experimental | Protocol implemented; needs real hardware confirmation |
| **Razer HyperSpeed Wireless** | `1532:*` | Razer HyperSpeed (`razer_v1`) | 🧪 Experimental | Protocol implemented; requires *Find Devices* / auto-detect & hardware testing |
| **SteelSeries Wireless** | `1038:*` | SteelSeries (`steelseries_v1`) | 🧪 Experimental | Protocol implemented; requires *Find Devices* / auto-detect & hardware testing |
| **Corsair Slipstream** | `1b1c:*` | Corsair Slipstream (`corsair_v1`) | 🧪 Experimental | Protocol implemented; requires *Find Devices* / auto-detect & hardware testing |
| **HyperX Wireless** | `0951:*` / `03f0:*` | HyperX Wireless (`hyperx_v1`) | 🧪 Experimental | Protocol implemented; requires *Find Devices* / auto-detect & hardware testing |
| **Generic USB Battery Devices** | USB Power Device | `generic_hid` | 🧪 Experimental | Standard USB-IF HID Power Device (Usage Page `0x85`) |

> 🛠️ **Device not detected or listed as Experimental?** Run **Export diagnostics** from the tray menu (or `areyoulowbattery --diag`) and open an Issue with the generated `.txt` file — community captures make new devices work fast!

---

## 🚀 How to Run & Install

### Option A: Standalone Binary (Recommended)

#### Linux (Ubuntu, Debian, Fedora, Arch, Nobara, Mint, Pop!_OS)
1. Download **`areyoulowbattery-linux-x86_64.tar.gz`** (recommended `--onedir` bundle, much lower memory footprint) or `areyoulowbattery-linux-x86_64` from the **[Releases](../../releases)** page.
2. Open a terminal in your download folder and run the automated one-step installer:
   ```bash
   tar -xzf areyoulowbattery-linux-x86_64.tar.gz
   ./areyoulowbattery/areyoulowbattery install
   ```
   *(Or for the single-file binary: `chmod +x areyoulowbattery-linux-x86_64 && ./areyoulowbattery-linux-x86_64 install`.)*
   *This automatically sets up secure udev rules (`/etc/udev/rules.d/`), installs to `~/.local/share/areyoulowbattery/` with a `~/.local/bin/areyoulowbattery` symlink, enables the `systemd --user` background service, and displays the battery badge in your system tray.*

#### Windows 10 & 11 (x64)
1. Download **`AreYouLowBattery-Windows-Setup.exe`** from the **[Releases](../../releases)** page.
2. Run the installer. The telemetry dashboard will automatically launch upon completion (`--tray --show`), and the battery indicator will dock next to your system clock in the Taskbar.

> **Note on Windows SmartScreen:** Because this is a free open-source project without a paid Authenticode certificate, Windows Defender SmartScreen may display *"Windows protected your PC"* on first launch. Every release binary is compiled directly from this public repository via [GitHub Actions](.github/workflows/release.yml) — click **More info → Run anyway** if you want to proceed, or run directly from source below.

---

### Option B: Run from Source

**Requirements:** Python 3.10+ and Git.

```bash
git clone https://github.com/ryan-mant/AreYouLowBattery.git
cd AreYouLowBattery

# Install dependencies
pip install -r requirements.txt

# Run directly
python3 cli.py --tray --show

# Or install as a system service
python3 cli.py install
```

---

### 🗑️ Uninstallation

You can cleanly remove the application at any time:
- **Via GUI:** Right-click the tray icon and select **"Uninstall..."**. Confirm the prompt, and the app will stop, remove services, clean configuration files, and exit.
- **Via Terminal:**
  ```bash
  areyoulowbattery uninstall
  # Or: python3 cli.py uninstall
  ```

---

## 🎯 User Guide & Tutorial

### 1. The System Tray Icon
- **Dynamic Battery Badge:** Displays the battery percentage of your active peripheral right on the tray icon. If charging, a `⚡` symbol is shown.
- **Dual-Device Indicator:** If you have multiple devices connected (e.g., a wireless mouse and keyboard), the tray icon dynamically splits into a multi-device indicator.
- **Left-Click:** Opens or hides the **Flyout Dashboard**.
- **Right-Click:** Opens the **Quick Settings Menu** (*Rename*, *Change protocol*, *Pause Polling (Game Mode)*, *Language: English / Português (Brasil)*, *Refresh now*, *Start with system*, *Quit*).

### 2. The Flyout Dashboard
Clicking the tray icon opens a sleek, frameless dark-mode dashboard:
- **Peripheral Cards:** Each connected device displays its category icon (🖱️ Mouse, ⌨️ Keyboard, 🎧 Headset, 🎮 Gamepad), custom name, percentage bar, and connection status.
- **Charging ETA:** When plugged in or placed on a magnetic dock, the card calculates the estimated time remaining until 100% battery.
- **Zero Background Resource Usage:** When closed, the dashboard consumes 0% GPU/CPU.

### 3. Card Action Menu (`•••`)
Click the three dots (`•••`) on any card (or right-click it) to manage that specific device:
- **Change protocol...:** Switch protocols on the fly (e.g. CompX, Nordic, Logitech HID++ 1.0/2.0, Razer, SteelSeries, Corsair, HyperX, Generic HID, Requires Bluetooth, Wired USB) with instant recalculation.
- **Rename device...:** Set a custom friendly display name.
- **Change device type...:** Switch category icon between Mouse, Keyboard, Headset, Gamepad, or Other.
- **Remove device...:** Hide unwanted devices or dongles. Hidden devices are stored in `ignored_devices.json` and can be restored at any time.

### 4. Zero-Config Hotplug Auto-Detection
You don't need to manually configure your peripherals:
- Plug in your 2.4GHz USB dongle or connect via USB cable.
- The app automatically detects the new hardware event in **< 0.25s**.
- If the peripheral belongs to a supported vendor, it safely validates the connection with live confirmation reads and creates the profile automatically, notifying you via a tray balloon.
- If the hardware is unrecognized, the app **never writes random packets**; it simply notifies you once: *"Unrecognized device — click to identify"*.

### 5. Competitive In-Game Protection (CS2, Valorant, Fullscreen)
- When a low battery state is reached (15% or 5%), AreYouLowBattery detects whether a fullscreen game is running.
- If in a fullscreen game, visual popup alerts are automatically suppressed to avoid focus stealing or frame drops, and a subtle audio cue is played instead.

### 6. CLI & Status Bar Usage (Waybar / Polybar / KDE Command Output)
You can query the telemetry engine directly from the command line or embed it into your custom desktop bar:

```bash
# Formatted text output (e.g., 🖱️ 95% | ⌨️ 80%)
areyoulowbattery

# JSON output (list of devices) for custom scripts
areyoulowbattery --format json

# Native Waybar module output: one JSON object (text, tooltip, class, percentage, alt)
areyoulowbattery --format waybar

# Verbose hardware diagnostic output
areyoulowbattery --format full

# Open the dashboard flyout directly from terminal or shortcut
areyoulowbattery --show
```

#### Native Waybar module (`--format waybar`)

Waybar custom modules configured with `return-type: json` expect a **single JSON object**, not the
list emitted by `--format json`. `--format waybar` prints exactly that object:

```json
{"text": "🎮 75% | 🖱️ 42%", "tooltip": "🎮 Pro Controller: 75%\n🖱️ Mouse: 42%", "class": "warning", "percentage": 42, "alt": "warning"}
```

- `text` — same compact string as the text format (icons + percentages).
- `tooltip` — one line per device (offline, Bluetooth required, wired USB or live percentage).
- `percentage` — lowest connected battery level, used for sorting/conditional styling.
- `class` — `charging`, `critical` (≤ 15%), `warning` (≤ 50%), `good`, or `disconnected`.
- `alt` — mirrors `class` so icon/alt-based styling works too.

Example Waybar config:

```jsonc
"custom/battery-peripherals": {
    "exec": "areyoulowbattery --format waybar",
    "return-type": "json",
    "interval": 30,
    "tooltip": true
}
```

> On Linux, peripherals that only expose a discrete `capacity_level`
> (`Full`, `High`, `Normal`, `Low`, `Critical`) under `/sys/class/power_supply/<device>/`
> — for example `hid-nintendo` controllers and some BLE devices — are now supported
> even when no numeric `capacity` file exists.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
