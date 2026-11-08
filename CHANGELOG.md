# 📋 Changelog & Patch Notes

All notable changes to **AreYouLowBattery** from release to release are documented in this file.

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
