# 📋 Changelog & Patch Notes

All notable changes to **AreYouLowBattery** from release to release are documented in this file.

---

## [v0.6.2] — 2026-11-25 — Vector Charging Tray Icon, Atomic Linux Updater & Python 3.10+ CI

### 🐛 Bug Fixes & Linux UX (PR #33)
- **Vector Charging Tray Icon (`areyoulowbattery/tray.py`)**:
  - Replaced Unicode emoji `⚡` text rendering (which failed to display inside the 64×64 tray icon on Linux/Nobara) with a crisp vector lightning polygon (`_draw_vector_lightning`) in both single-device and multi-device tray icons.
- **Reliable Linux Auto-Updater (`areyoulowbattery/updater.py`, `areyoulowbattery/i18n.py`)**:
  - `find_matching_asset()` now prefers the standalone Linux ELF binary over `.tar.gz` / `.sha256` assets.
  - Added `_atomic_replace_executable()` using a temporary file + `os.replace()` to prevent `ETXTBSY` on running binaries and avoid overwriting `--onedir` symlinks.
  - Updates writable standalone frozen executables directly, relaunches `--tray` automatically when `systemd --user` is not active, and provides exact `{path} install` / `{path} --tray` commands in manual fallback prompts (EN & PT-BR).

### 🧪 Packaging & CI Alignment
- Aligned `requires-python = ">=3.10"` in `pyproject.toml` with `README.md`.
- Expanded `.github/workflows/pr-check.yml` to run automated tests across **Python 3.10 and 3.12** on Linux (plus Python 3.12 on Windows), bringing total automated tests to **115/115 passing**.

---

## [v0.6.1] — 2026-11-22 — ATK A9 Air (Compx 8K), Restore Flow Fix, Linux Hardening & Udev Sync

### 🖱️ New Hardware & Protocol Fixes
- **ATK A9 Air / Compx 8K Wireless Mouse (`0x373b`, `373b:11d9` / `373b:120a`)**:
  - Added official profile ([`profiles/mice/atk_compx_8k.yaml`](profiles/mice/atk_compx_8k.yaml)), `VENDOR_PROTOCOL_MAP` entry in `discovery.py`, and hardened `udev` rule (`ATTRS{idVendor}=="373b"`) in `rules/99-areyoulowbattery.rules`.
  - Fixed `NordicHandler` (`nordic_v1`) to fall back to `write_output_report` when a dongle defines Report ID `0x08` as Output-only and silently ignores `send_feature_report` without raising an OS error.

### 🐛 Bug Fixes & Linux Hardening
- **Remove → Find Devices → Restore Flow**: Fixed `restore_device()` in `areyoulowbattery/engine.py` to also un-ignore custom renamed device names stored under `profile_name` in `device_overrides.json` (previously only `vid:pid` / `vid` keys were checked, leaving renamed devices hidden from the dashboard after restoring).
- **Outdated `udev` Rules Detection** — contributed by **[@emreocell](https://github.com/emreocell)** in PR #32 (#30):
  - `are_udev_rules_installed()` now compares installed rules against the bundled `rules/99-areyoulowbattery.rules` so newly added vendor IDs (`a8a5`, `3537`, `373b`, etc.) trigger the installer prompt on upgrades.
- **Security & Linux Packaging Hardening** (PR #29):
  - Hardened temporary cache paths, `systemd` `ExecStart` quoting, `sysfs` file-handle cleanup, and pinned GitHub Actions release SHAs.

### 🧪 Automated QA & Frontend Tests
- Added **`tests/test_ui_flows.py`** (PySide6 offscreen UI tests) covering dashboard header & empty-state buttons, `DeviceCard` menu actions (`Change Protocol`, `Rename`, `Change Type`, `Remove`), *Find Devices* (`Test Protocol`, `Save`, `Rescan`, `Done`), and the end-to-end **Remove → Find Devices → Test Protocol → Restore** regression with custom renames.

---

## [v0.6.0] — 2026-11-18 — GameSir Cyclone 2, Bilingual UI (EN/PT-BR), Game Mode Controls, Waybar & Linux Footprint

### 🎮 New Hardware & Protocol Improvements
- **New `gamesir_v1` Protocol Handler (`3537:100b`)** — contributed by **[@EdevandoAlves](https://github.com/EdevandoAlves)** in PR #22!
  - Adds battery % and charging telemetry for the **GameSir Cyclone 2** XInput 2.4G dongle, with YAML profile, hardened `udev` rules, and reverse-engineering notes (`docs/protocol-gamesir-cyclone2.md`).
- **YJX Wired Charging Telemetry (`a8a4:2255`)** — by **[@EdevandoAlves](https://github.com/EdevandoAlves)**: reads live USB cable charging state and accepts post-charge battery levels.

### 🌐 Multi-Language UI (`i18n`)
- **English (`en_US`) & Brazilian Portuguese (`pt_BR`)** — contributed by **[@EdevandoAlves](https://github.com/EdevandoAlves)** in PR #24 (#17):
  - Added lightweight `areyoulowbattery/i18n.py` translation layer persisted in `settings.json`, with live language switcher in the tray context menu across popup cards, discovery dialogs, tray menus, and Linux `udev` installer prompts.

### 🕹️ Game Mode Tray Indicator & Manual Pause
- Contributed by **[@Golden007-prog](https://github.com/Golden007-prog)** in PR #21 (#18):
  - Displays active **Game Mode** status in the tray menu and adds a **Pause Polling (Game Mode)** toggle, backed by shared detection in `areyoulowbattery/gamemode.py`.

### 🐧 Linux Desktop, Waybar & Memory Footprint
- **Waybar `capacity_level` Fallback** — contributed by **[@EdevandoAlves](https://github.com/EdevandoAlves)** in PR #23:
  - Supports Linux `sysfs` `power_supply` devices that only expose discrete `capacity_level` (`Full` / `High` / `Normal` / `Low` / `Critical`) when numeric `capacity` is absent.
- **Linux `--onedir` Bundle & Qt Module Exclusions** (#15, PR #25):
  - Added `--exclude-module` flags in PyInstaller builds for unused Qt6/stdlib modules and shipped `areyoulowbattery-linux-x86_64.tar.gz` (`--onedir`), reducing systemd cgroup footprint on Linux from `256.2 MB` (`--onefile`) to `33.4 MB` (`-87%`), plus idle tray UI signature caching (`last_ui_sig`).

---

## [v0.5.5] — 2026-11-17 — YJX-CHIP Protocol (`@EdevandoAlves`), Windows UX & PR Security CI

### 🤝 Community Contributions
- **New `yjx_v1` Protocol Handler (`a8a5:2255`)** — contributed by **[@EdevandoAlves](https://github.com/EdevandoAlves)** in PR #12!
  - Adds full battery % and charging telemetry support for **Smailwolf RS7**, **EWEADN G5**, and **MCHOSE G7** wireless gaming mice on YJX-CHIP 2.4G receivers.
  - Includes YAML profile (`profiles/mice/yjx_smailwolf_rs7.yaml`), `VENDOR_PROTOCOL_MAP` auto-detection, hardened `udev` rule, reverse-engineering documentation (`docs/protocol-yjx-a8a5.md`), and 6 unit tests using captured hardware frames.

### 🎨 Windows & Desktop UX Fixes
- **Modals Always Appear Above Dashboard**: The dashboard flyout (`WindowStaysOnTopHint`) now hides cleanly before opening *Find Devices*, *Rename*, *Change Type*, *Change Protocol*, or *Export Diagnostics* and restores automatically when closed, while key dialogs enforce top-most focus so modals never open hidden behind the popup on Windows.
- **Cleaner Find Devices List**: Active Bluetooth peripherals already monitored natively in the dashboard (e.g., `R68 BT5.0`, `Ba-FON240`) no longer clutter *Find Devices* unless previously hidden/removed by the user.

### 🛡️ Repository Security & Governance
- Added **`.github/workflows/pr-check.yml`** (read-only PR CI running Linux + Windows unit tests, `tools/sim_lab.py --chaos`, `bandit` security scan, and `udev` rules safety validation).
- Added **`CONTRIBUTING.md`** and **`.github/pull_request_template.md`**.

### 📖 Documentation
- Added UI preview screenshots (`assets/preview_dashboard.png`, `assets/preview_discovery.png`), hardware support for `yjx_v1`, honest resource-usage figures, and a transparent Windows SmartScreen note to `README.md`.

---

## [v0.5.4.2] — 2026-11-17 — Windows HID Resilience, Native SetupAPI Bluetooth & Chaos Simulator

### 🪟 Windows Hardware & Bluetooth Fixes
- **Native Win32 `setupapi.dll` Bluetooth Battery Reader**: Queries `DEVPKEY_Device_BatteryPercentage` directly in-process via `ctypes` (<10ms, works without administrator privileges and without PowerShell PnP timeouts).
- **Resilient HID Multi-Collection Handling**: `HidrawTransport.read_input_report()` now catches `OSError`/`ValueError` (`had_read_error`), protecting all 10 protocol handlers against Windows `hidapi` `read error` crashes on locked/incompatible collections.
- **Logitech HID++ Collection Isolation**: Skips Windows-locked `\KBD` collections and handles read errors cleanly across `Col01`..`Col05` so vendor `0xFF00` endpoints and HID++ 1.0 fallbacks are always reached.

### 🧰 QA & Diagnostics Tooling
- **New `tools/sim_lab.py`**: Chaos fault-injection simulator across all 10 protocol handlers + diagnostic report (`--diag`) replay harness.
- **59/59 unit tests passing** (including Windows `read error` and `SetupAPI` Bluetooth coverage).

---

## [v0.5.4.1] — 2026-11-16 — UI Polish, Visual Audit Tooling & udev Installer Feedback

### 🎨 Interface Fixes
- **Find Devices**: vector lightning icon on *Test Protocol* (no more empty emoji box), removed the square Breeze frame behind device cards, themed slim dark scrollbar.
- **Dashboard**: redesigned settings gear icon, long device names are elided with a full-name tooltip, fixed clipped text in the empty state.

### 🎮 Game Mode Coverage
- **Daemon and CLI now respect Game Mode**: `--daemon` and `--poll` previously ignored it, so running them next to the tray could still query the hardware during matches. Detection moved to the shared `areyoulowbattery/gamemode.py`; while a game runs, `--poll` serves cached data only without touching hardware, and `--daemon` / tray block forced refreshes while extending the telemetry refresh interval to 180s (planned low-frequency refresh rather than zero-read forever).
- **No more false positives on Windows**: fullscreen browsers and media/communication apps (Chrome, Firefox, Edge, VLC, mpv, Discord, Teams, OBS...) no longer trigger Game Mode.

### 🛡️ udev Installer
- Authorization failures (`pkexec` exit 127) now show an explanatory dialog with manual commands instead of looking like a silent cancel. Dismissing the prompt (exit 126) stays silent.

### 🧰 Developer Tooling
- New `tools/visual_audit.py`: renders every UI state offscreen and saves PNG captures to `captures/visual_audit/` for visual regression review.

### 🔧 Housekeeping
- Version strings synchronized across `pyproject.toml`, `__init__.py`, `installer.iss` and `windows_version_info.txt`.

---

## [v0.5.4] — 2026-11-15 — Smart Game Mode Hardening, Native Windows Game Detection, Automated udev Installer & Vector Dialogs

### 🚀 Smart Game Mode Hardening (Anti-Stutter & Zero USB Contention)
- **Strict Hardware Write Suppression in Competitive Matches**:
  - `in_game=True` now strictly suppresses `force=True` hardware cache bypasses.
  - If a user opens the dashboard, clicks the tray icon, or a hotplug event fires during a match (CS2, Valorant, Apex Legends, Deadlock, Dota 2), the 180s battery telemetry cache is strictly enforced, preventing any USB write commands (`write_output_report`) from being injected into mouse endpoints and guaranteeing zero packet collision with high-polling sensors (1000Hz/4000Hz/8000Hz).
  - Background polling thread automatically drops `is_force` while in-game.

### 🪟 Native Windows Game & Fullscreen Detection
- **Win32 API Native Integration via `ctypes`**:
  - Replaced the platform placeholder on Windows with real-time foreground process inspection and screen boundary verification using standard library `ctypes` (zero third-party dependencies).
  - Automatically identifies competitive games (`cs2.exe`, `valorant.exe`, `r5apex.exe`, `overwatch.exe`, `pubg.exe`, `fortnite.exe`, `deadlock.exe`, etc.) and exclusive/borderless fullscreen windows.
  - Windows players now benefit from the exact same latency-protective Game Mode as Linux users.

### 🛡️ Automated udev Rules Installer & Composite Dongle Access (Linux)
- **Graphical Administrator Authorization via `pkexec`**:
  - Integrated one-click udev rules installation into the *Find Devices* assistant and settings menu.
  - Elevates privileges cleanly via system Polkit (`pkexec`) using a dedicated atomic script (`rules/install_udev.sh`), eliminating manual terminal commands (`sudo cp`, `sudo udevadm`) and shell string interpolation risks.
  - **100% Platform Isolated**: The udev installer and permissions banners are strictly guarded on Linux and completely omitted on Windows.
- **Restored Multi-Interface Composite Dongle Compatibility**:
  - Removed restrictive `bInterfaceProtocol!='01'` filter from `rules/99-areyoulowbattery.rules`. Composite 2.4G wireless dongles (such as Royalaxe `0x25a7:0x2420`) that declare protocol 01 on all endpoints now properly receive user-space `uaccess`.

### 🎨 Native Vector Icons & Dialog Overhaul
- **End of Broken Emojis in Dialogs**:
  - Added `render_category_icon` to `vector_icons.py`.
  - Replaced system `QInputDialog` (which caused blank square glyphs/tofu on Linux) with a modern dark-themed *Change Device Type / Icon* dialog featuring crisp sky-blue (`#38bdf8`) vector icons for Mouse, Keyboard, Headset, Gamepad, and Other.
  - Updated *Find Devices* category dropdown to render native vector icons alongside text labels.
- **Strict Hardware Blacklist in Device Discovery**:
  - Enforced unconditional filtering of internal host hardware (Root Hubs, USB 2.0/3.0 Hubs, webcams, USB microphones, and motherboard RGB controllers like MSI Mystic Light) in the *Find Devices* scanner.
  - Prevented USB Host Controllers from erroneously matching as Gamepads (`🎮`).

---

## [v0.5.3.2] — 2026-11-14 — Anti-Stutter Gaming Mode, Native Bluetooth D-Bus & Wayland Integration

### 🚀 Performance & Gaming Optimization (Anti-Stutter)
- **Competitive Game Mode (CS2, Deadlock, Dota 2, Apex Legends)**:
  - Automatically identifies active competitive fullscreen games and enters low-latency Game Mode.
  - **Zero USB Contention on Mice**: Suspends USB write commands (`write_output_report`) on 2.4G wireless mouse dongles (CompX, Nordic, Areson) and extends telemetry cache to 180s, preventing any packet collision with 1000Hz/4000Hz/8000Hz mouse sensor reporting.
  - **Relaxed Background Threading**: Extends routine background polling cadence from 10s to 120s while games are active.
  - **Auto-Detection & Hotplug Pausing**: Suppresses device probing and debounces udev events during gaming sessions.
  - **Cached Game Check**: Caches `/proc` process detection for 15s to avoid repetitive kernel context switches.

### 🐛 Bug Fixes & Stability
- **Elimination of `bluetoothctl` Coredumps on Linux (`SIGABRT` / Exit Code 134)**:
  - Completely removed external `bluetoothctl` CLI subprocess execution.
  - Bluetooth battery querying on Linux now operates exclusively in-memory via D-Bus (`org.bluez` / `org.freedesktop.UPower`) and `/sys/class/power_supply`.
  - Eliminates all recurring `systemd-coredump` I/O spikes and crashes on modern BlueZ 5.86 / Fedora / Nobara systems.
- **Wayland Window Identity & Desktop Integration (Resolved Wayland "W" Icon)**:
  - Implemented `get_app_icon()` with automatic fallback to high-DPI vector graphics.
  - Sets `app.setDesktopFileName("areyoulowbattery")` and `setWindowIcon(...)` across the tray, dashboard flyout, and discovery dialogs.
  - Automatically provisions `~/.local/share/applications/areyoulowbattery.desktop` and installs high-res icons in `~/.local/share/icons/hicolor/256x256/apps/` on startup so KDE Plasma and GNOME Wayland compositors display the official application icon instead of the generic Wayland "W" logo.

### 🛡️ Security Hardening
- **Anti-Keylogger udev Rule Hardening (`ATTRS{bInterfaceProtocol}!="01"`)**:
  - Excluded standard Boot Keyboard text-typing interfaces from receiving user ACL permissions.
  - Keystroke endpoints remain strictly locked to `root:root` (`0600`), ensuring malicious user-space processes cannot intercept typed passwords via `/dev/hidraw`, while vendor battery telemetry endpoints remain accessible to the app.

---

## [v0.5.3.1] — 2026-11-13 — Bluetooth GATT Authority, Logitech Nano Receiver & Linux Subprocess Isolation

### 🐛 Bug Fixes & Hardware Stability
- **Bluetooth GATT Telemetry Authority (Resolved 15% vs 95% Bug):**
  - Enforced operating system Bluetooth GATT battery telemetry as authoritative over unverified HID probes.
  - On Windows, Bluetooth LE HID nodes are no longer claimed by 2.4GHz Lightspeed profiles (`logitech_hidpp.yaml`), preventing erroneous byte interpretations from overriding real battery percentages.
  - Automatically merges and upgrades placeholder devices (such as `requires_bluetooth` Pebble Keys 2 K380s) to active keyboard telemetry with live battery levels.
- **Logitech HID++ 1.0 Nano Receiver Fix for Windows (Resolved M170 "Disconnected"):**
  - Removed blind `usage_page < 0xFF00` restriction on Windows for legacy Logitech Nano Receivers (`046d:c534`, M170, M185, M220, MK270).
  - Telemetry is now queried via short report `0x10` registers `0x0D` and `0x07` on standard mouse collections without false "Disconnected / Deep Sleep" states.
- **Device Removal & "Find Devices" Restoration Fixes:**
  - Fixed unconditional filtering in `scan_unmapped_devices` so previously ignored/removed peripherals properly appear in the Find Devices assistant with a functional one-click "Restore Device" button.
  - Integrated connected Bluetooth devices into the Find Devices scanner.
  - Synchronized peripheral removal across profile names, Bluetooth friendly names, and hardware IDs to prevent removed devices from immediately respawning in the system tray menu.
- **Linux Subprocess Environment Sanitization (`clean_env`):**
  - Sanitized `LD_LIBRARY_PATH` across all system subprocess invocations (`systemctl`, `udevadm`, `sudo`, `paplay`, `bluetoothctl`).
  - Resolves `systemctl: ... version OPENSSL_3.4.0 not found` and `bluetoothctl` SIGABRT dynamic linker conflicts when running PyInstaller standalone binaries on modern Linux distributions (Fedora, Nobara, Arch, openSUSE).
- **Native Vector Icons & Wayland Stability (Resolved Empty Box & Segfaults):**
  - Introduced resolution-independent vector icons rendered via `QPainter` for peripheral categories and dashboard buttons (Find Devices, Refresh, Settings, Close), eliminating missing glyphs and empty boxes (tofu □) caused by COLRv1 color emoji incompatibility in Qt on modern Linux.
  - Hardened Wayland window dragging and dynamic card rebuilding to prevent PySide6 SIGSEGV crashes while interacting with popup menus.

---

## [v0.5.3] — 2026-11-13 — Dashboard Auto-Launch, Device Removal, Dynamic Protocols & Windows Diagnostic Fixes

### ✨ Major New Features
- **Dashboard Auto-Launch Post-Installation & Double-Click:**
  - Added `--show` / `--open` CLI flags allowing direct activation of the dashboard flyout.
  - Windows installer now launches with `--tray --show` upon completion, opening the telemetry dashboard immediately for instant visual feedback.
  - Added optional Windows desktop icon shortcut configured with `--tray --show`.
  - Windows autostart at system boot (`{userstartup}`) remains strictly silent in the background with `--tray`.
- **Remove / Hide Devices:**
  - Added "Remove device..." option available directly from individual peripheral cards (••• menu) and the System Tray context menu.
  - Automatically registers unwanted hardware in `ignored_devices.json` and deletes any corresponding user-generated custom YAML profile in `profiles/`.
- **Zero-Config Device Auto-Detection:**
  - Plug in a new peripheral and it is identified automatically on hotplug / app start — no menus required.
  - Known vendor families (Logitech, Razer, SteelSeries, Corsair, HyperX, CompX, Nordic, Actions) are probed with their own protocols only; a profile is created automatically only after **one live probe plus one confirmation re-read** on the same HID node (cached/asleep values are rejected), and a tray notification explains what was set up.
  - Unknown vendors are **never written to**: if the device looks wireless, a single "Unrecognized device — click to identify" notification opens the Find Device assistant.
  - Each model (VID:PID) is remembered in `auto_detect_state.json`, so it is never probed or announced twice; failed probes (one probe each, never re-probed within an attempt) retry at most 3 times (5 min apart) in case the mouse was asleep.
  - Probes now try every HID interface of the dongle instead of only the first node.
- **Refined Dashboard & Dialog UX:**
  - Separated Dashboard settings from tray menu: the gear icon (⚙) now cleanly displays global application actions only (*Start with system*, *Export log*, *Check updates*, *Quit*), removing redundant per-card actions.
  - Per-device actions (*Rename*, *Change protocol*, *Change type*, *Remove*) live strictly on each device card's `•••` menu.
  - Dashboard now smoothly remains active or reopens automatically after interacting with modal dialogs (*Rename*, *Protocol*, *Find Devices*, *Remove*), so users never need to re-click the tray icon.
- **Dynamic Protocol & Connection Switching:**
  - Users can now change a peripheral's protocol directly from the card action menu (•••) or tray menu (e.g., switch between CompX, Nordic 4K/8K, Logitech HID++ 1.0/2.0, Razer, SteelSeries, Corsair, HyperX, Generic HID, Requires Bluetooth, or Wired USB) with immediate live recalculation of telemetry.
  - Protocol changes are persisted in `device_overrides.json` or custom YAML without manual text editing.

### 🐛 Bug Fixes & Hardware Compatibility
- **Zero-Energy Passive Hardware Sleep Guard:**
  - Implemented an intelligent sleep guard that completely stops background 2.4GHz RF polling when a peripheral enters deep sleep or is turned off, preventing transceiver wake-ups and eliminating unnecessary battery drain.
  - Telemetry is queried purely on-demand when opening the dashboard flyout, clicking tray refresh, or on physical USB connection changes.
- **Updater Security Hardening & SHA-256 Verification:**
  - Removed insecure unverified TLS fallbacks. Enforced strict certificate validation using system Root CA stores (`ssl.enum_certificates`) and `certifi`.
  - Added cryptographic SHA-256 checksum verification during binary update downloads to guarantee file integrity before execution.
- **Vendor Protocol Isolation in Device Discovery:**
  - Restricted protocol probes strictly by USB Vendor ID (`0x046D` only tests Logitech, `0x1532` only tests Razer, etc.), guaranteeing that foreign vendor-specific frames are never sent to incompatible peripherals.
- **Logitech HID++ 1.0 Support for Legacy Nano Receivers (`046d:c534`):**
  - Added support for legacy Logitech Nano Receivers (M185, M220, M330, MK270) that do not implement HID++ 2.0 IRoot feature discovery.
  - Implemented Short Report `0x10` queries using register `0x0D` (Battery Mileage percentage) and register `0x07` (Battery Status levels) across receiver slots 0x01 and 0x02.
- **Pebble K380s BLE & HID++ Deduplication:**
  - Unified Windows Bluetooth BLE (`BTHLEDevice`) and Logitech HID++ dual endpoints of the same peripheral into a single clean card, preventing bouncing battery percentages and duplicate cards.
  - Direct hardware register telemetry (e.g. 15% SoC) takes precedence over stale Windows GATT battery cache (95%).
- **Discovery Assistant Hardware Filters:**
  - Internal laptop hardware without batteries is now automatically filtered out of discovery: ignored Goodix touchpads (`0x27C6`), Dell I2C touchpads (`HIDI2C Device`), and Microsoft virtual devices (`ConvertedDevice` PID `0x0000`).
  - Fallback suggested category for unidentified peripherals changed from `🎮 Gamepad` to `🔋 Other`.
- **System Service & Cache Hardening:**
  - Updated `systemd/areyoulowbattery.service` template to use standard `%h/.local/bin/areyoulowbattery --tray` instead of development folder paths.
  - Restricted shared memory telemetry cache files (`/dev/shm/areyoulowbattery*`) to `0600` permissions (owner read/write only).
- **Second Security Review Hardening:**
  - **Mandatory update checksum:** the updater now refuses to download/run any installer unless a trusted SHA-256 is published (GitHub `assets[].digest` first, release notes as fallback). Releases without a checksum open the release page for manual download instead.
  - **Safer download location:** updates are saved in a private `0700` temporary directory with a sanitized filename (no path traversal or predictable `/tmp` collisions).
  - **Passive discovery for unknown vendors:** unidentified hardware is now probed only with the read-only standard HID handler; vendor-specific write protocols (CompX/Nordic) are never guessed (use "Change protocol..." manually).
  - **Read-only Generic HID:** the generic handler opens devices with `O_RDONLY`.
  - **Per-device query rate limit:** the same device's hardware is queried at most once every 5 seconds unless the user explicitly refreshes.
  - **systemd:** `Restart=on-failure` (a clean Quit no longer respawns the app) with `StartLimitBurst=5` per 120s to stop crash loops.
  - **Tests:** added `tests/__init__.py` so `python -m unittest` discovers the suite; added a `dev` extra with `pytest`.

---

## [v0.5.2] — 2026-11-12 — Windows Updater GC Stability & Native Autostart Shortcut

### 🐛 Bug Fixes & Stability Improvements
- **Resolved Windows Silent Crash on Check for Updates:**
  - Fixed a race condition where the asynchronous `CheckUpdateThread` was garbage-collected by Python while the underlying C++ network thread was executing, triggering an unhandled abort on Windows.
  - Implemented persistent thread lifecycle registry `_ACTIVE_WORKERS` to guarantee memory safety during background update checks and downloads.
  - Hardened `QApplication.quitOnLastWindowClosed(False)` to ensure closing informational update dialogs never inadvertently closes the System Tray application.
- **Fixed Windows Autostart Shortcut Persistence:**
  - Migrated Windows startup shortcut from legacy `.bat` command execution to native Inno Setup `.lnk` integration (`[Icons]` with `Tasks: autostart; Flags: unchecked`).
  - The "Start with Windows" installer checkbox now defaults to unchecked and, when left unselected or unchecked during an upgrade, cleanly removes any prior startup shortcut.
  - Added cleanup logic to purge legacy `AreYouLowBattery.bat` files.
- **Linux CI Headless Compatibility:**
  - Handled headless environments where `libEGL.so.1` is absent by isolating Qt GUI imports, allowing CLI execution and unit tests to run cleanly in pure server environments.

---

## [v0.5.1] — 2026-11-12 — Windows Bluetooth Telemetry, In-App Self-Update & UI Polish

### ✨ Major New Features
- **Native Windows Bluetooth Peripheral Battery Telemetry:**
  - Added native PnP device property monitoring (`DEVPKEY_Device_BatteryLevel` `{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2`) via in-process Windows Registry (`HKLM\SYSTEM\CurrentControlSet\Enum\BTHENUM` & `BTHLE`) with zero subprocess overhead.
  - Added non-blocking PowerShell PnP query fallback and 15s telemetry cache to guarantee 0.0% CPU overhead.
  - Automatically identifies Bluetooth keyboards, mice, headsets, and controllers without hardcoding any specific model or brand.
- **In-App Self-Update (1-Click Update):**
  - Added manual **"Check for updates..."** action in both the System Tray context menu and the Dashboard settings menu (⚙).
  - Strictly on-demand: zero background network requests and 0.0% CPU impact during normal monitoring.
  - **Windows 1-Click Update**: Automatically checks GitHub Releases API, displays version diff and release patch notes, downloads `AreYouLowBattery-Windows-Setup.exe` to `%TEMP%` with real-time download progress, and launches the Inno Setup installer while cleanly releasing file locks.
  - **Linux Support**: Automatically updates the standalone binary (`~/.local/bin/areyoulowbattery`) and restarts the systemd user service (`areyoulowbattery.service`), or guides the user when running from source.
- **UI & Menu Alignment Polish:**
  - Removed disparate emoji icons from menu action labels (`Find devices...`, `Check for updates...`), keeping clean text-only action items.
  - Enhanced `QMenu` stylesheet for pixel-perfect vertical alignment and uniform spacing.

---

## [v0.5.0] — 2026-11-11 — Bluetooth Telemetry, Device Discovery Assistant, Anti-Jitter Filter & Protocol Expansion

### ✨ Major New Features
- **Native Bluetooth Peripheral Battery Telemetry (BlueZ D-Bus & UPower):**
  - Integrated in-process D-Bus monitoring for Bluetooth peripherals on Linux (`org.bluez` and `org.freedesktop.UPower`).
  - Automatically queries GATT Battery Service (`0x180F`) and Handsfree profile batteries for connected wireless headsets, keyboards, mice, and gamepads with zero external CLI overhead.
- **Smart Dual-Mode Unification:**
  - Automatically identifies when a connected Bluetooth peripheral corresponds to a 2.4G dongle without native telemetry (e.g. Baseus GH02, Royalaxe R68) by matching hardware Modalias VID:PID or unique model identifiers. Unifies them into a single live card without duplicate entries.
  - Implemented **Category Guard** to prevent cross-category device merging.
- **Interactive "Find Devices" Assistant (`discovery_dialog.py`):**
  - Added a built-in GUI discovery tool accessible from the Dashboard header (`🔍`) and Tray context menu (`Find & add new device...`).
  - Scans USB ports and HID nodes for unmapped peripherals, ignoring motherboard chips, root hubs, webcams, and Bluetooth host adapters.
  - Features a live **"⚡ Test Protocol"** probe that tests CompX, Nordic, Logitech, Razer, SteelSeries, Corsair, HyperX, and Generic HID channels with animated loading feedback and automatic protocol selection.
  - Generates custom YAML profiles in 1 click saved to `~/.config/areyoulowbattery/profiles/`.
- **Anti-Jitter Monotonic Filter:**
  - Prevents voltage sag bounce (e.g., RGB LEDs turning off causing a resting voltage jump from 80% to 90%).
  - Smooths battery readings by clamping upward spikes during discharging while allowing immediate downward discharge, charging increases, and sustained external charging updates.
- **Wired Peripheral Filter (`is_wired`):**
  - Distinguishes continuous USB power devices (e.g. Logitech G403 HERO, G203) from wireless devices, displaying `🔌 Wired USB` and suppressing false low-battery notifications.
- **Expanded Protocol Ecosystem:**
  - Added native protocol handlers for:
    - **Razer HyperSpeed** (`razer_v1`): Viper, DeathAdder, Basilisk, Naga, BlackWidow.
    - **SteelSeries Wireless** (`steelseries_v1`): Aerox, Rival, Arctis 1/7/9, Arctis Nova 7.
    - **Corsair Slipstream** (`corsair_v1`): Dark Core, Katar, Ironclaw, Virtuoso, Void, HS80.
    - **HyperX Wireless** (`hyperx_v1`): Cloud Flight, Cloud II, Cloud Alpha, Cloud III, Pulsefire.
    - **Standard USB HID Battery** (`generic_hid`): Generic Power Device (Usage Page 0x85).

### 🎨 UI Polish & Test Coverage
- Redesigned `DeviceCard` to ensure uniform card height and layout across all devices, eliminating text wrapping glitches on Bluetooth-required peripherals.
- Standardized all user-facing strings and badges in clean English.
- Expanded automated unit test suite from 6 to **17 unit tests**, validating all new handlers, filters, and profile generation logic.

---

## [v0.4.2] — 2026-11-10 — Windows Inno Setup Installer, Universal Linux Build & Diagnostic Exporter

### ✨ New Features & Packaging
- **Windows Inno Setup Installer (`AreYouLowBattery-Windows-Setup.exe`) & `--onedir` Build:**
  - Switched Windows packaging from `--onefile` to `--onedir` + native **Inno Setup** installer (`installer.iss`). Eliminates `%TEMP%` self-extraction on launch (preventing Windows Defender `Wacatac.B!ml` false positives and speeding up startup by 5x).
- **Universal Linux Binary Compatibility (`ubuntu-22.04` / `glibc 2.35`):**
  - Built Linux standalone binaries on `ubuntu-22.04` so `areyoulowbattery-linux-x86_64` runs out-of-the-box across Debian 12+, Ubuntu 22.04+, Linux Mint 21+, Pop!_OS, Fedora, Arch, and Manjaro.
- **1-Click Diagnostic Log Exporter (`Export diagnostic log...` & `--diag`):**
  - Added **"Export diagnostic log..."** in the System Tray menu (and `areyoulowbattery --diag` in CLI) to export a full USB HID enumeration and protocol trace to `Desktop/areyoulowbattery_diag.txt` for easy troubleshooting.
- **Enhanced Logitech HID++ 2.0 Support (G Pro X Superlight 2):**
  - Added support for 20-byte Long HID++ (`0x11`) reports, `0x1001` millivolt battery curve fallback, and multi-collection `0xFF00`/`0xFF43` scanning for Logitech Lightspeed 2K/4K/8K receivers.

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
