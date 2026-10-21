# 🔋 AreYouLowBattery

> Lightweight battery monitor for wireless mice, keyboards, and headsets without native Linux drivers (Delux, Baseus, Attack Shark, VXE, etc.).

Designed to work out-of-the-box with **KDE Plasma** (*Command Output* widget), **Waybar** (Hyprland / Sway), **Polybar**, and other Linux status bars.

---

## ✨ Features

- **Driverless in Userspace:** Uses native Linux `/dev/hidraw` without requiring kernel modules or interfering with mouse tracking / audio streams.
- **Declarative Device Profiles:** Add support for new peripherals via simple YAML files in `profiles/`.
- **Multiple Output Formats:**
  - Plain text (e.g., `🖱️ 85% | 🎧 50%`) for KDE Command Output.
  - JSON for Waybar / Polybar.
  - Detailed debug view for testing and sniffing.
- **Broad Hardware Architecture Support:** Focuses on popular OEM chipsets used by Chinese peripherals (CompX/Beken, Actions Semiconductor, SinoWealth, Telink).

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
# Formatted for KDE / status bars
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
   - **Run every:** `60 seconds`
