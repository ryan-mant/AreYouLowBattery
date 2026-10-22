# 🔋 AreYouLowBattery

> Lightweight battery monitor & System Tray indicator for wireless mice, keyboards, and headsets without native Linux drivers (Delux, Attack Shark, VXE, Baseus, etc.).

Works out-of-the-box with **KDE Plasma**, **GNOME**, **XFCE**, **Hyprland / Sway (Waybar)**, and **Polybar**.

---

## ✨ Features

- **Native System Tray Indicator:** Dynamic circular battery badge in your system tray (color-coded by level + charging bolt `⚡`, tooltip, and right-click menu).
- **One-Command Automated Installer (`install`):** Automatically configures `udev` permissions, installs the binary, and enables the `systemd --user` background service.
- **Zero Input Lag (`O_RDONLY`):** Passive kernel buffer reads on the vendor endpoint without sending unnecessary USB interruptions or touching the mouse motion interface.
- **All Connection Modes Supported:** Handles 2.4GHz Wireless Dongle, Magnetic Charging Dock, and USB-C Wired charging modes.
- **Declarative Device Profiles:** Add support for new peripherals via simple YAML files in `profiles/` (or `~/.config/areyoulowbattery/profiles/`).
- **Multiple Output Formats (`text` / `json` / `full`):** Also works as a CLI backend for KDE *Command Output*, Waybar, or Polybar.

---

## 📦 Hardware Support Matrix

| Device | USB IDs (`VID:PID`) | Chipset / Protocol | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Delux M900 Pro** | `1d57:fa65` (2.4G Dongle)<br>`1d57:fa73` (USB-C Wired) | CompX 8K (`compx_v1`) | ✅ **Supported** | Live battery %, magnetic dock charging (`⚡`), USB-C wired charging (`⚡`), ETA to 100%, full charge detection |
| **Ajazz AJ199** *(+ AJ139 / AJ159)* | `25a7:fa7c` (2.4G Dongle)<br>`25a7:fa7b` (USB-C Wired) | Areson / CompX 1K (`compx_v1`) | ✅ **Supported** | Feature report `0x08` -> Input `0x09` telemetry, live wired & wireless battery %, charging status + ETA to 100% |
| **Attack Shark X11 / X3 / X6** | `1d57:fa60` / `25a7:fa7c` | CompX (`compx_v1`) | ✅ **Supported** | Automatic detection via CompX 8K (`0x03`) and CompX 1K (`0x08`/`0x09`) handlers |
| **Pulsar X2 / Lamzu / VXE R1** | `25a7:*` / `1d57:*` | CompX Generic Fallback | ✅ **Supported** | Auto-detected by vendor ID and HID report descriptor inspection |
| **Logitech / Bluetooth Peripherals** | Kernel `power_supply` | `sysfs_power_supply` | ✅ **Supported** | Automatically reads any peripheral exposed under `/sys/class/power_supply/` (`scope=Device`) |
| **Baseus AeQur GH02** | `10d6:4802` (2.4G Dongle) | Actions Semi (`actions_v1`) | ⚠️ **BT Only** | 2.4GHz dongle only exposes audio + media keys + ADFU bootloader triggers (`0x55`/`0x41`); battery is only transmitted over Bluetooth (`sysfs_power_supply`) |

---

## 🚀 Quick Start

### Option A: Standalone Executable (from GitHub Releases)

Download `areyoulowbattery` from the **[Releases](../../releases)** page and run:

```bash
chmod +x areyoulowbattery
./areyoulowbattery install
```

That's it! It configures `udev` rules, installs the binary to `~/.local/bin/areyoulowbattery`, starts the `systemd --user` service, and shows the battery icon in your System Tray.

To remove the service later:
```bash
areyoulowbattery uninstall
```

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
