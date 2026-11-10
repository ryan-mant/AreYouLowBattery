# 📋 Changelog & Patch Notes

All notable changes to **AreYouLowBattery** from release to release are documented in this file.

---

## [v0.4.1] — 2026-11-10 — Windows Multi-Collection RX/TX Fix & Draggable Dashboard

### 🐛 Bug Fixes & UI Polish
- **Windows Simultaneous Vendor Collection Listening (`compx_v1` & `nordic_v1`):**
  - Fixed `Disconnected / Deep Sleep` on Windows for CompX 1K (`0x25a7`) and Nordic (`0x3554`) mice where Feature Report `0x08` (TX) lives on `UsagePage 0xFF02` while Input Report `0x09` (RX) arrives on `UsagePage 0xFF01`. All vendor sibling handles are now kept open simultaneously before transmitting `0x08` so `hid.dll` buffers the incoming `0x09` packet on `0xFF01`.
- **Draggable Mini-Dashboard & Pill-Rounded Battery Bars (`areyoulowbattery/popup.py`):**
  - Made the Mini-Dashboard flyout window draggable across the screen (`startSystemMove` + mouse drag fallback).
  - Replaced default Qt `QProgressBar` with a custom antialiased `RoundedBatteryBar` for smooth pill-shaped corners across all desktop themes.

---

## [v0.4.0] — 2026-11-10 — Mini-Dashboard Popup, Instant Hotplug & New Protocols

### ✨ New Features
- **Mini-Dashboard Flyout Popup (`areyoulowbattery/popup.py`):**
  - Left-clicking the System Tray icon now opens a sleek dark-mode flyout dashboard displaying cards for each connected peripheral, color-coded battery progress bars, connection protocol badges, and estimated charging time remaining (`ETA`).
  - Zero background CPU/GPU overhead: widgets are only built or updated while the popup is visible on screen.
  - Full Wayland (`kwin_wayland`), X11, and Windows compatibility (`Qt.Tool | Qt.FramelessWindowHint`).
- **Instant USB Hotplug Detection (`udev` & Topology Watcher):**
  - Listens passively to kernel `hidraw` and `power_supply` netlink events on Linux (`udevadm monitor`) and HID topology changes on Windows to update the tray icon within **~0.25s** whenever a charging cable or dongle is plugged in or unplugged.
- **New Peripheral Protocols (`nordic_v1` & `hidpp_v2`):**
  - **Nordic nRF52840 / Compx 4K & 8K (`0x3554`):** Added support for high-polling 4K/8K wireless mice (VXE R1 Pro / Mad R, ATK F1/X1, Scyrox V8, Lamzu 4K, Zaopin Z1 Pro / Z2, Ninjutso Sora V2, Darmoshark M3 4K).
  - **Logitech HID++ 2.0 (`0x046d`):** Added direct HID++ 2.0 (`0x1004` Unified Battery / `0x1000` Battery Status) querying for Logitech Lightspeed, Bolt, and Unifying devices (G Pro X Superlight 1 & 2, G502 X, G303, G703, G915), allowing Windows users to monitor battery without Logitech G HUB.

### ⚡ Performance, Security & Bug Fixes
- **Automated Unit Test Suite (`tests/`):**
  - Added automated unit tests with simulated HID transports covering YAML profile validation, CompX 8K (`0x03`), CompX 1K (`0x08`/`0x09` + charging interpolation), Nordic 4K/8K, Logitech HID++ 2.0, and cache key isolation, executed automatically in GitHub Actions CI.
- **Hardened `udev` Security (`MODE="0660", TAG+="uaccess"`):**
  - Replaced world-writable `MODE="0666"` in `rules/99-areyoulowbattery.rules` with `MODE="0660", TAG+="uaccess"` so `systemd-logind` grants dynamic ACL access exclusively to the active physical session user.
- **Collision-Free `VID:PID` Cache Keys & `--debug` Logging:**
  - Scoped device telemetry cache files by `(profile, vendor_id, product_id)` to prevent cache collisions across multiple generic devices while preserving shared `charge_base` state across wired/wireless PIDs of dual-mode mice.
  - Added structured diagnostic logging (`areyoulowbattery/logger.py`, `--debug` / `AREYOULOWBATTERY_DEBUG=1`).
- **HID Topology & Report Descriptor Caching:**
  - Cached `/dev/hidraw*` inode signatures and sysfs report descriptors in memory, reducing routine polling interval from `2s` to `10s` in both Tray and CLI `--daemon` modes (80% fewer background USB/RF queries).
- **CompX 1K (`0x25a7`) Smooth Charging Interpolation & Live Priority:**
  - Fixed voltage-under-charge jumps (`0x0a` / `0x5f`) on CompX 1K mice (e.g. Ajazz AJ199) when plugging in the USB-C cable by locking onto the pre-charge wireless reading (`charge_base`) and interpolating smoothly until full cutoff.
  - Prioritized live telemetry reports over cached readings when both the 2.4GHz dongle and USB-C cable are connected simultaneously.

---

## [v0.3.0] — 2026-11-08 — Smart Alerts, In-Game Mode & Autostart Control

### ✨ New Features
- **Smart Low (15%) & Critical (5%) Battery Alerts:**
  - Automatically triggers a desktop warning at **15%** and a critical alert at **5%** battery remaining.
  - Built-in hysteresis anti-spam: each threshold fires only once per discharge cycle and resets automatically when charging starts or battery exceeds 20%.
- **Competitive In-Game Protection (`cs2`, `dota2`, `steam_app_*`, `valorant.exe`, etc.):**
  - Detects running fullscreen games and **suppresses visual pop-up notifications** so the OS compositor never unredirects fullscreen windows, steals focus, or causes frame-time stutter.
  - Plays a non-blocking **background audio cue** (`pw-play` / PipeWire on Linux, `winsound` on Windows) directly to your headset so you still know when your mouse hits 15% or 5% mid-match.
- **"Start with system" Tray Toggle:**
  - Added a checkable **Start with system** option directly in the System Tray context menu.
  - Toggles `systemctl --user enable/disable areyoulowbattery.service` on Linux and `%APPDATA%\...\Startup\AreYouLowBattery.bat` on Windows.
- **Official Application Icon:**
  - Added high-resolution vector icons (`assets/icon.png` and `assets/icon.ico`) embedded into the Linux and Windows standalone executables.

---

## [v0.2.7] — 2026-11-08

### 🐛 Bug Fixes
- **Windows Composite USB Mice (`0x25a7` / Ajazz AJ199, Attack Shark, etc.):**
  - Fixed an issue on Windows where `HidD_SetFeature` (Report ID `0x08`) is accepted on one top-level HID collection while the `0x09` battery input report arrives on a sibling vendor collection (`UsagePage 0xFF00` / `0xFF01` / `0xFF02`). The CompX handler now opens all sibling collections simultaneously on Windows.

---

## [v0.2.6] — 2026-11-08

### 🐛 Bug Fixes
- **Windows RF Handshake & Sleep Detection:**
  - Improved CompX 1K feature report handshake (`0x08` + `0x00` report ID prefix fallback) on Windows.
  - Added clear diagnostic messaging when a wireless mouse is in deep RF sleep (`00 00`) on Windows (`Move or click the mouse to wake it up`).

---

## [v0.2.5] — 2026-11-08

### 📦 Packaging & CI
- **Windows `.zip` Release & Version Resource Metadata:**
  - Added `areyoulowbattery-windows-x64.zip` to GitHub Releases and embedded `windows_version_info.txt` into the PyInstaller `.exe` to prevent Windows Defender / SmartScreen false-positive blocks (`Trojan:Win32/Wacatac.B!ml`) common to unsigned PyInstaller onefile binaries.

---

## [v0.2.4] — 2026-11-08

### 🐛 Bug Fixes
- **Windows `hidapi` Timeout & Console Output:**
  - Removed `dev.set_nonblocking(True)` before `dev.read(64, timeout_ms=...)` on Windows, which was causing `hidapi` to return `[]` immediately in 0ms before the 2.4GHz dongle could reply over RF.
  - Grouped multi-collection HID candidates by `(vid, pid)` in `engine.py` so fallback interfaces are tested if the primary collection returns no telemetry.
  - Redirected `sys.stdout` and `sys.stderr` to `CONOUT$` when `AttachConsole(-1)` succeeds on Windows so `areyoulowbattery.exe --format full` prints to PowerShell/CMD.

---

## [v0.2.1 – v0.2.3] — 2026-11-08

### ✨ Enhancements & Fixes
- Defaulted double-clicking `areyoulowbattery.exe` on Windows to launch the System Tray indicator (`--tray`).
- Added neutral naming (`CompX 1K Wireless Peripheral (25a7:fa7c)`) plus right-click **Rename device...** and **Change device type...** options in the System Tray.
- Added `requirements.txt` for running from source on Windows and Linux.

---

## [v0.2.0] — 2026-11-08

### ✨ New Features
- **Cross-Platform Windows Support:**
  - Added `hidapi` backend for Windows alongside native Linux `/dev/hidraw` support.
  - Added automated GitHub Actions CI workflow building both `areyoulowbattery-linux-x86_64` and `areyoulowbattery-windows-x64.exe`.

---

## [v0.1.1] — 2026-11-07

### ✨ New Features
- **One-Click Uninstaller:**
  - Added `areyoulowbattery uninstall` in CLI and **Uninstall...** in the System Tray menu to cleanly stop services, remove binaries, and delete configuration/cache files.

---

## [v0.1.0] — 2026-11-07

### 🎉 Initial Release
- **Qt6 System Tray Indicator** with dynamic battery percentage ring and charging bolt (`⚡`).
- **CompX 8K (`1d57:fa65` / `1d57:fa73`)** support for Delux M900 Pro (wireless dongle, magnetic dock charging, and USB-C wired charging with ETA estimation).
- **CompX 1K (`25a7:fa7c` / `25a7:fa7b`)** support for Ajazz AJ199 / Attack Shark mice.
- **Linux `sysfs_power_supply`** fallback for standard Bluetooth & kernel-supported peripherals.
- **One-Command Installer (`install`)** configuring `udev` rules and `systemd --user` service.
