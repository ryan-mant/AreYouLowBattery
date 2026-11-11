# 🔋 AreYouLowBattery

> Lightweight battery monitor & System Tray indicator for wireless mice, keyboards, and headsets without native Linux drivers (Delux, Attack Shark, VXE, Baseus, etc.).

Works out-of-the-box with **KDE Plasma**, **GNOME**, **XFCE**, **Hyprland / Sway (Waybar)**, and **Polybar**.

---

## ✨ Features

- **Native System Tray Indicator & Flyout Dashboard:** Dynamic circular battery badge in your system tray; **left-click** opens a sleek dark-mode Mini-Dashboard with peripheral cards, color-coded progress bars, and charging ETA (`zero` background GPU/CPU overhead when closed), while **right-click** opens quick settings.
- **Smart Low (15%) & Critical (5%) Battery Alerts:** Audio and desktop alerts with hysteresis anti-spam so you never get caught off guard by a dead battery.
- **Competitive In-Game Protection (CS2, Dota 2, Steam, etc.):** Automatically detects running fullscreen games and suppresses visual pop-ups (zero focus stealing, zero compositor stutter) while playing a subtle background audio cue in your headset.
- **Instant USB Hotplug Detection (`udev`):** Detects cable or dongle plug/unplug events in ~0.25s via kernel netlink events and caches HID topology in memory to eliminate unnecessary USB bus polling.
- **"Start with system" Tray Toggle:** Enable or disable automatic startup on boot right from the System Tray menu on both Linux (`systemd`) and Windows (`Startup`).
- **One-Command Automated Installer (`install`):** Automatically configures `udev` permissions, installs the binary, and enables the background service.
- **Zero Input Lag (`O_RDONLY`):** Passive kernel buffer reads on the vendor endpoint without sending unnecessary USB interruptions or touching the mouse motion interface.
- **All Connection Modes Supported:** Handles 2.4GHz Wireless Dongle, Magnetic Charging Dock, and USB-C Wired charging modes.
- **Declarative Device Profiles:** Add support for new peripherals via simple YAML files in `profiles/` (or `~/.config/areyoulowbattery/profiles/`).
- **Multiple Output Formats (`text` / `json` / `full`):** Also works as a CLI backend for KDE *Command Output*, Waybar, or Polybar.

> 📋 **See [CHANGELOG.md](CHANGELOG.md) for full release-to-release Patch Notes.**

---

## 📦 Hardware Support Matrix

| Device | USB IDs (`VID:PID`) | Chipset / Protocol | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Delux M900 Pro** | `1d57:fa65` (2.4G Dongle)<br>`1d57:fa73` (USB-C Wired) | CompX 8K (`compx_v1`) | ✅ **Supported** | Live battery %, magnetic dock charging (`⚡`), USB-C wired charging (`⚡`), ETA to 100%, full charge detection |
| **Ajazz AJ199** *(+ AJ139 / AJ159)* | `25a7:fa7c` (2.4G Dongle)<br>`25a7:fa7b` (USB-C Wired) | Areson / CompX 1K (`compx_v1`) | ✅ **Supported** | Feature report `0x08` -> Input `0x09` telemetry, live wired & wireless battery %, charging status + ETA to 100% |
| **Attack Shark X11 / X3 / X6** | `1d57:fa60` / `25a7:fa7c` | CompX (`compx_v1`) | ✅ **Supported** | Automatic detection via CompX 8K (`0x03`) and CompX 1K (`0x08`/`0x09`) handlers |
| **Pulsar X2 / Lamzu / VXE R1** | `25a7:*` / `1d57:*` | CompX Generic Fallback | ✅ **Supported** | Auto-detected by vendor ID and HID report descriptor inspection |
| **VXE R1 Pro / Mad R / ATK F1 / Scyrox V8 / Lamzu 4K** | `3554:*` | Nordic nRF52840 4K/8K (`nordic_v1`) | ✅ **Supported** | Vendor telemetry query (`0x08`/`0x09`) without touching the 4K/8K motion endpoint |
| **Logitech G Pro X Superlight 1 & 2 / G502 X / Lightspeed** | `046d:*` | Logitech HID++ 2.0 (`hidpp_v2`) | ✅ **Supported** | Uses kernel `hidpp_battery` on Linux and direct HID++ `0x1004`/`0x1000` query on Windows (no G HUB needed!) |
| **Razer HyperSpeed Wireless (Viper, DeathAdder, Basilisk, BlackWidow)** | `1532:*` | Razer HyperSpeed (`razer_v1`) | ✅ **Supported** | Direct 90-byte vendor battery report query on HID interface (no Synapse needed!) |
| **SteelSeries Wireless (Aerox 3/5/9, Rival 3/650, Arctis 1/7/9, Nova 7)** | `1038:*` | SteelSeries (`steelseries_v1`) | ✅ **Supported** | Native mouse and headset telemetry probe |
| **Corsair Slipstream (Dark Core, Katar, Virtuoso, Void, HS80)** | `1b1c:*` | Corsair Slipstream (`corsair_v1`) | ✅ **Supported** | Direct Slipstream and feature report query |
| **HyperX Wireless (Cloud Flight/II/Alpha/III, Pulsefire)** | `0951:*` / `03f0:*` | HyperX Wireless (`hyperx_v1`) | ✅ **Supported** | Vendor command query for headsets and mice |
| **Royalaxe R68** | `25a7:2420` (2.4G) / Bluetooth | CompX / BlueZ Dual-Mode | ✅ **Supported** | Unifies 2.4G dongle with Bluetooth battery telemetry (80%/100%) |
| **Baseus AeQur GH02** | `10d6:4802` (2.4G Dongle) / Bluetooth | Actions Semi / BlueZ Dual-Mode | ✅ **Supported** | 2.4G audio dongle seamlessly paired with live Bluetooth battery telemetry |
| **Bluetooth Peripherals (All Brands)** | BlueZ D-Bus & UPower | `bluetooth` / `0x180F` | ✅ **Supported** | **100% universal** GATT Battery Service and HFP telemetry for any connected device |
| **Generic USB Battery Devices** | USB Power Device | `generic_hid` | ✅ **Supported** | Standard USB-IF HID Power Device (Usage Page `0x85`) |

---

## 🚀 Quick Start

### Option A: Standalone Executable (from GitHub Releases)

#### Linux (Ubuntu 22.04+, Debian 12+, Fedora, Arch, Mint, Pop!_OS):
Download `areyoulowbattery-linux-x86_64` (or `areyoulowbattery`) from the **[Releases](../../releases)** page and run:

```bash
chmod +x areyoulowbattery
./areyoulowbattery install
```
That's it! It configures `udev` rules, installs the binary to `~/.local/bin/areyoulowbattery`, starts the `systemd --user` service, and shows the battery icon in your System Tray (no Python installation required).

#### Windows 10 & 11 (x64):
Download **`AreYouLowBattery-Windows-Setup.exe`** (recommended installer) or `areyoulowbattery-windows-x64.zip` (portable folder) from the **[Releases](../../releases)** page:
1. Run **`AreYouLowBattery-Windows-Setup.exe`** (or extract the `.zip` and double-click `areyoulowbattery.exe`).
2. The battery icon will appear right next to the Windows clock in your Taskbar Tray, and you can toggle **"Start with system"** or **"Export diagnostic log..."** directly from the right-click menu!

### 🗑️ Clean Uninstallation

Want to completely remove AreYouLowBattery? You can do it in two easy ways:

* **Via System Tray (GUI):** Right-click the battery icon in your system tray and select **"Uninstall..."** — confirm with Yes, and the app will stop, remove the service, delete configurations, and close cleanly.
* **Via Terminal (CLI):**
  ```bash
  areyoulowbattery uninstall
  # Or from source: python3 cli.py uninstall
  ```

This cleanly stops and disables the `systemd` service, removes `~/.local/bin/areyoulowbattery`, cleans `~/.config/areyoulowbattery`, removes `/dev/shm` caches, and offers to remove `/etc/udev/rules.d/99-areyoulowbattery.rules`. **Zero background bloat or leftover services remain.**

### Option B: From Source

```bash
git clone https://github.com/ryan-mant/AreYouLowBattery.git
cd AreYouLowBattery
python3 cli.py install
```

---

## 🖥️ CLI Usage (Waybar / Polybar / KDE Command Output)

Even with the System Tray running, the CLI reads instantly (< 10ms) from the shared memory cache (`/dev/shm/areyoulowbattery_status.json`):

```bash
# Formatted text (e.g. 🖱️ 98% or 🖱️ 68%⚡)
python3 cli.py

# JSON output for Waybar / scripts
python3 cli.py --format json

# Verbose debug output
python3 cli.py --format full
```

---

## 🔬 Reverse-Engineering a New Device

Use the interactive capture tool to record labeled HID traffic across physical states (idle, moving, on dock, wired):

```bash
python3 tools/capture.py --vid 1d57 --pid fa65
```
