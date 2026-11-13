# 🔋 AreYouLowBattery

> **Ultra-lightweight, cross-platform peripheral battery telemetry monitor & System Tray indicator for Linux & Windows.**  
> Monitor your wireless gaming mice, keyboards, and headsets with **zero input lag**, **~0.1% CPU overhead**, and **zero battery drain**.

Works out-of-the-box on **Linux** (KDE Plasma, GNOME, XFCE, Hyprland, Sway, Waybar, Polybar) and **Windows 10 & 11**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)](https://python.org)
[![Platform: Linux & Windows](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-informational.svg)](#-quick-start)

---

## 📖 About the Project

Most wireless gaming peripherals (especially popular enthusiast brands like Delux, Attack Shark, Ajazz, VXE, ATK, Lamzu, Scyrox, as well as major brands like Logitech, Razer, SteelSeries, Corsair, and HyperX) rely on heavy, bloated proprietary companion suites (like G HUB, Razer Synapse, or iCUE) or offer **no native Linux software at all**.

**AreYouLowBattery** bridges this gap:
- **Zero Input Lag:** Directly reads secondary vendor telemetry endpoints (`Interface 1/2`) without ever touching or interrupting the mouse sensor motion stream (`Interface 0`). Tested and validated for competitive gaming (CS2, Valorant, Apex Legends).
- **Zero-Energy Passive Sleep Guard:** When your peripheral enters deep sleep or is switched off, the monitor completely ceases 2.4GHz RF packet transmission, eliminating RF transceiver wake-ups and saving 100% of your mouse's battery.
- **Ultra-Lightweight:** Consumes **< 40 MB RAM** and **~0.0% - 0.1% CPU**. Telemetry cache resides in shared memory (`/dev/shm`), causing **0 disk writes/sec** to preserve SSD lifespan.
- **100% Cross-Platform Parity:** Identical features, protocols, and interface on both Linux and Windows.

> 📋 **For full version history and release patch notes, see [CHANGELOG.md](CHANGELOG.md).**

---

## 🎮 Supported Hardware Matrix

| Brand / Device | USB IDs (`VID:PID`) | Protocol / Chipset | Status | Features |
| :--- | :--- | :--- | :--- | :--- |
| **Delux M900 Pro** | `1d57:fa65` / `1d57:fa73` | CompX 8K (`compx_v1`) | ✅ Supported | Live %, Magnetic Dock charging (`⚡`), USB-C wired charging, ETA to 100% |
| **Ajazz AJ199 / AJ139 / AJ159** | `25a7:fa7c` / `25a7:fa7b` | Areson / CompX 1K (`compx_v1`) | ✅ Supported | Feature report `0x08` / `0x09` telemetry, live wired/wireless %, charging ETA |
| **Attack Shark X11 / X3 / X6** | `1d57:fa60` / `25a7:fa7c` | CompX (`compx_v1`) | ✅ Supported | Automatic detection via CompX 8K (`0x03`) and CompX 1K (`0x08`/`0x09`) |
| **VXE R1 Pro / Mad R / ATK F1 / Scyrox V8 / Lamzu 4K** | `3554:*` | Nordic nRF52840 4K/8K (`nordic_v1`) | ✅ Supported | Vendor telemetry query without touching the 4K/8K motion endpoint |
| **Logitech Lightspeed & PRO Series (G Pro X Superlight 1 & 2, G502 X, G303, G703, G915, Bolt)** | `046d:*` | Logitech HID++ 2.0 (`hidpp_v2`) | ✅ Supported | Direct hardware HID++ register query (no G HUB needed!) |
| **Logitech Nano Receivers (M185, M220, M330, MK270)** | `046d:c534` | Logitech HID++ 1.0 (`hidpp_v1`) | ✅ Supported | Registers `0x0D` (mileage) and `0x07` (status) for popular AA/AAA mice |
| **Razer HyperSpeed Wireless (Viper, DeathAdder, Basilisk, BlackWidow, Cobra)** | `1532:*` | Razer HyperSpeed (`razer_v1`) | ✅ Supported | Direct 90-byte vendor battery report query (no Synapse needed!) |
| **SteelSeries Wireless (Aerox 3/5/9, Rival 3/650, Arctis 1/7/9, Nova 7)** | `1038:*` | SteelSeries (`steelseries_v1`) | ✅ Supported | Native mouse and headset telemetry probe |
| **Corsair Slipstream (Dark Core, Katar, Virtuoso, Void, HS80)** | `1b1c:*` | Corsair Slipstream (`corsair_v1`) | ✅ Supported | Direct Slipstream and feature report query |
| **HyperX Wireless (Cloud Flight/II/Alpha/III, Pulsefire)** | `0951:*` / `03f0:*` | HyperX Wireless (`hyperx_v1`) | ✅ Supported | Vendor command query for headsets and mice |
| **Royalaxe R68** | `25a7:2420` / Bluetooth | CompX / BlueZ Dual-Mode | ✅ Supported | Unifies 2.4G dongle with Bluetooth battery telemetry |
| **Baseus AeQur GH02** | `10d6:4802` / Bluetooth | Actions Semi / BlueZ Dual-Mode | ✅ Supported | Dual-mode Bluetooth BLE telemetry |
| **Bluetooth Peripherals (All Brands)** | Bluetooth GATT / UPower | `bluetooth` / `0x180F` | ✅ Supported | Universal BLE Battery Service and HFP telemetry |
| **Generic USB Battery Devices** | USB Power Device | `generic_hid` | ✅ Supported | Standard USB-IF HID Power Device (Usage Page `0x85`) |

---

## 🚀 How to Run & Install

### Option A: Standalone Binary (Recommended)

#### Linux (Ubuntu, Debian, Fedora, Arch, Nobara, Mint, Pop!_OS)
1. Download `areyoulowbattery-linux-x86_64` (or `areyoulowbattery`) from the **[Releases](../../releases)** page.
2. Open a terminal in your download folder and run the automated one-step installer:
   ```bash
   chmod +x areyoulowbattery
   ./areyoulowbattery install
   ```
   *This automatically sets up secure udev rules (`/etc/udev/rules.d/`), installs the binary to `~/.local/bin/areyoulowbattery`, enables the `systemd --user` background service, and displays the battery badge in your system tray.*

#### Windows 10 & 11 (x64)
1. Download **`AreYouLowBattery-Windows-Setup.exe`** from the **[Releases](../../releases)** page.
2. Run the installer. The telemetry dashboard will automatically launch upon completion (`--tray --show`), and the battery indicator will dock next to your system clock in the Taskbar.

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
- **Right-Click:** Opens the **Quick Settings Menu** (*Rename*, *Change protocol*, *Refresh now*, *Start with system*, *Quit*).

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

# JSON output for Waybar / custom scripts
areyoulowbattery --format json

# Verbose hardware diagnostic output
areyoulowbattery --format full

# Open the dashboard flyout directly from terminal or shortcut
areyoulowbattery --show
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
