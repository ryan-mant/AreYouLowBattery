# 🔋 AreYouLowBattery

> Lightweight battery monitor for wireless mice, keyboards, and headsets without native Linux drivers (Delux, Attack Shark, VXE, Baseus, etc.).

Designed to work out-of-the-box with **KDE Plasma** (*Command Output* widget), **Waybar** (Hyprland / Sway), **Polybar**, and other Linux status bars.

---

## ✨ Features

- **Driverless in Userspace:** Uses native Linux `/dev/hidraw` without requiring kernel modules or interfering with mouse tracking / audio streams.
- **Declarative Device Profiles:** Add support for new peripherals via simple YAML files in `profiles/`.
- **All Connection Modes Supported:** Handles 2.4GHz Wireless Dongle, Magnetic Charging Dock, and USB-C Wired charging modes.
- **Automatic Kernel/BlueZ Fallback:** Also reads peripheral batteries exposed under `/sys/class/power_supply/` (`scope=Device`, such as Bluetooth headsets and controllers).
- **Interactive Capture Tool (`tools/capture.py`):** Built-in labeled HID sniffer with automatic USB re-enumeration handling for reverse-engineering new peripherals.

---

## 📦 Hardware Support Matrix

| Device | USB IDs (`VID:PID`) | Chipset / Protocol | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Delux M900 Pro** | `1d57:fa65` (2.4G Dongle)<br>`1d57:fa73` (USB-C Wired) | CompX / Beken (`compx_v1`) | ✅ **Supported** | Live battery %, magnetic dock charging (`⚡`), USB-C wired charging (`⚡`), 100% full charge detection |
| **Baseus AeQur GH02** | `10d6:4802` (2.4G Dongle) | Actions Semi (`actions_v1`) | ⚠️ **BT Only** | 2.4GHz dongle only exposes audio + media keys + ADFU bootloader triggers (`0x55`/`0x41`); battery is only transmitted over Bluetooth (`sysfs_power_supply`) |

---

## 🚀 Quick Start

### 1. Configure UDev Permissions
To allow non-root users to read battery metrics from `/dev/hidraw`:

```bash
sudo cp rules/99-areyoulowbattery.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2. Run the Tool

```bash
# Formatted for KDE Command Output / status bars (e.g. 🖱️ 98% or 🖱️ 68%⚡)
python3 cli.py

# JSON output for Waybar / scripts
python3 cli.py --format json

# Verbose debug output
python3 cli.py --format full
```

---

## 🖥️ KDE Plasma Setup

1. Right-click your panel and select **Add Widgets...**
2. Search for and add **Command Output**.
3. Configure the widget:
   - **Command:** `python3 /path/to/AreYouLowBattery/cli.py`
   - **Run every:** `30` or `60` seconds

---

## 🔬 Reverse-Engineering a New Device

Use the interactive capture tool to record labeled HID traffic across physical states (idle, moving, on dock, wired):

```bash
python3 tools/capture.py --vid 1d57 --pid fa65
```
