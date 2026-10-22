#!/usr/bin/env python3
import os
import sys
import glob
import json
import time
import shutil
import tempfile
import argparse
import subprocess
from typing import List, Tuple

# Ensure package is discoverable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from areyoulowbattery.engine import BatteryEngine
from areyoulowbattery.transport import enumerate_hidraw
from areyoulowbattery.profile_loader import get_resource_dir
from areyoulowbattery.models import DeviceProfile, BatteryStatus, DeviceCategory, DeviceMatch

CACHE_DIR = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
CACHE_FILE = os.path.join(CACHE_DIR, "areyoulowbattery_status.json")

def format_text_output(results: List[Tuple[DeviceProfile, BatteryStatus]], show_all: bool = False) -> str:
    if not results:
        return "No supported devices detected"

    parts = []
    for profile, status in results:
        # Devices whose protocol is not mapped yet are hidden unless --all is used
        if not show_all and not status.supported:
            continue

        if not status.is_connected:
            parts.append(f"{profile.icon} OFF")
            continue

        charging_symbol = "⚡" if status.is_charging else ""
        if status.percentage is None:
            parts.append(f"{profile.icon} {charging_symbol or '?'}")
        else:
            parts.append(f"{profile.icon} {status.percentage}%{charging_symbol}")

    if not parts:
        # Fallback if no device has > 0%
        for profile, status in results:
            parts.append(f"{profile.icon} OFF" if not status.is_connected else f"{profile.icon} {status.percentage}%")

    return " | ".join(parts)

def format_json_output(results: List[Tuple[DeviceProfile, BatteryStatus]]) -> str:
    data = []
    for profile, status in results:
        data.append({
            "name": profile.name,
            "category": profile.category.value,
            "icon": profile.icon,
            "percentage": status.percentage,
            "is_charging": status.is_charging,
            "is_connected": status.is_connected,
            "details": status.details
        })
    return json.dumps(data, indent=2)

def format_full_output(results: List[Tuple[DeviceProfile, BatteryStatus]]) -> str:
    lines = []
    lines.append("=== AreYouLowBattery Status ===")
    if not results:
        lines.append("No matching devices found.")
        return "\n".join(lines)

    for profile, status in results:
        state = "ONLINE" if status.is_connected else "OFFLINE"
        chg = " ⚡ (Charging)" if status.is_charging else ""
        eta_str = status.format_eta()
        eta_part = f" [{eta_str}]" if eta_str else ""
        pct_str = f" {status.percentage}%" if status.percentage is not None else ""
        lines.append(f"Device: {profile.name} [{profile.category.value.upper()}]")
        lines.append(f"  Status: {state}{pct_str}{chg}{eta_part}")
        if status.details:
            lines.append(f"  Details: {status.details}")
        lines.append("-" * 32)
    return "\n".join(lines)

def run_daemon_loop():
    """Lightweight background daemon that monitors events and keeps /dev/shm cache fresh."""
    print("Starting AreYouLowBattery daemon (caching to /dev/shm)...", flush=True)
    engine = BatteryEngine()
    tmp_file = CACHE_FILE + ".tmp"

    while True:
        try:
            results = engine.poll_all_devices()
            cached_data = []
            for profile, status in results:
                cached_data.append({
                    "name": profile.name,
                    "category": profile.category.value,
                    "icon": profile.icon,
                    "protocol": profile.protocol,
                    "percentage": status.percentage,
                    "is_charging": status.is_charging,
                    "is_connected": status.is_connected,
                    "supported": status.supported,
                    "details": status.details,
                    "timestamp": time.time()
                })
            with open(tmp_file, "w") as f:
                json.dump(cached_data, f)
            os.replace(tmp_file, CACHE_FILE)
        except Exception as e:
            print(f"Daemon error: {e}", file=sys.stderr, flush=True)

        time.sleep(1)

def read_from_cache_or_poll(force_poll: bool = False) -> List[Tuple[DeviceProfile, BatteryStatus]]:
    # Only trust the daemon cache if it was refreshed recently (daemon is alive)
    cache_fresh = os.path.exists(CACHE_FILE) and time.time() - os.path.getmtime(CACHE_FILE) < 15
    if not force_poll and cache_fresh:
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            results = []
            for item in data:
                profile = DeviceProfile(
                    name=item["name"],
                    category=DeviceCategory(item.get("category", "other")),
                    icon=item.get("icon", "🔋"),
                    match=DeviceMatch(vendor_id=0),
                    protocol=item.get("protocol", "cached"),
                )
                status = BatteryStatus(
                    percentage=item["percentage"],
                    is_charging=item.get("is_charging", False),
                    is_connected=item.get("is_connected", False),
                    details=item.get("details"),
                    supported=item.get("supported", True),
                    eta_seconds=item.get("eta_seconds"),
                )
                results.append((profile, status))
            if results:
                return results
        except Exception:
            pass
    engine = BatteryEngine()
    return engine.poll_all_devices()

def cmd_install_rules():
    rules_src = os.path.join(get_resource_dir(), "rules", "99-areyoulowbattery.rules")
    rules_dst = "/etc/udev/rules.d/99-areyoulowbattery.rules"

    if not os.path.exists(rules_src):
        print(f"Error: Rules file not found at {rules_src}", file=sys.stderr)
        sys.exit(1)

    print(f"To install udev rules, run the following command:")
    print(f"\n  sudo cp \"{rules_src}\" \"{rules_dst}\" && sudo udevadm control --reload-rules && sudo udevadm trigger\n")


def cmd_install():
    """Automated one-step installer: udev rules + systemd user service on Linux, Startup on Windows."""
    if sys.platform == "win32":
        print("=== Installing AreYouLowBattery for Windows ===")
        startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        if os.path.exists(startup_dir):
            bat_path = os.path.join(startup_dir, "AreYouLowBattery.bat")
            with open(bat_path, "w") as f:
                if getattr(sys, "frozen", False):
                    exe_path = os.path.realpath(sys.executable)
                    f.write(f'@start "" "{exe_path}" --tray\n')
                else:
                    script = os.path.abspath(__file__)
                    f.write(f'@start "" "{sys.executable}" "{script}" --tray\n')
            print(f"[1/2] Created startup shortcut in {bat_path}")

        print("[2/2] Starting AreYouLowBattery in System Tray...")
        if getattr(sys, "frozen", False):
            subprocess.Popen([os.path.realpath(sys.executable), "--tray"])
        else:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--tray"])
        print("\n✅ Done! The battery icon is now active in your Windows System Tray.")
        return

    print("=== Installing AreYouLowBattery ===")
    rules_src = os.path.join(get_resource_dir(), "rules", "99-areyoulowbattery.rules")
    rules_dst = "/etc/udev/rules.d/99-areyoulowbattery.rules"

    need_udev = True
    if os.path.exists(rules_dst) and os.path.exists(rules_src):
        try:
            if open(rules_dst, "rb").read() == open(rules_src, "rb").read():
                need_udev = False
                print("[1/3] Udev rules are already installed and up to date.")
        except OSError:
            pass

    if need_udev and os.path.exists(rules_src):
        print("[1/3] Installing USB permission rules (udev)...")
        subprocess.run(["sudo", "cp", rules_src, rules_dst], check=True)
        subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["sudo", "udevadm", "trigger"], check=True)

    # Determine ExecStart command (standalone binary vs python script)
    if getattr(sys, "frozen", False):
        bin_dir = os.path.expanduser("~/.local/bin")
        os.makedirs(bin_dir, exist_ok=True)
        target_bin = os.path.join(bin_dir, "areyoulowbattery")
        src_bin = os.path.realpath(sys.executable)
        if src_bin != os.path.realpath(target_bin):
            shutil.copy2(src_bin, target_bin)
            os.chmod(target_bin, 0o755)
        exec_start = f"{target_bin} --tray"
        print(f"[2/3] Binary installed to {target_bin}")
    else:
        script_path = os.path.abspath(__file__)
        exec_start = f"{sys.executable} {script_path} --tray"
        print(f"[2/3] Configuring service from {script_path}")

    systemd_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(systemd_dir, exist_ok=True)
    service_path = os.path.join(systemd_dir, "areyoulowbattery.service")

    service_content = f"""[Unit]
Description=AreYouLowBattery - Wireless Peripheral Battery Monitor & System Tray
After=graphical-session.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
    with open(service_path, "w") as f:
        f.write(service_content)

    print("[3/3] Enabling and starting systemd --user service...")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "areyoulowbattery.service"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "areyoulowbattery.service"], check=True)
    print("\n✅ Done! The battery icon is now active in your System Tray.")


def cmd_uninstall():
    if sys.platform == "win32":
        print("=== Uninstalling AreYouLowBattery for Windows ===")
        startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        bat_path = os.path.join(startup_dir, "AreYouLowBattery.bat")
        if os.path.exists(bat_path):
            try:
                os.remove(bat_path)
                print(f"[1/3] Removed startup shortcut {bat_path}")
            except OSError:
                pass

        config_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "areyoulowbattery")
        if os.path.exists(config_dir):
            shutil.rmtree(config_dir, ignore_errors=True)
            print(f"[2/3] Removed {config_dir}")

        for f in glob.glob(os.path.join(CACHE_DIR, "areyoulowbattery*")):
            try:
                os.remove(f)
            except OSError:
                pass

        print("[3/3] Stopping running processes...")
        subprocess.run(["taskkill", "/F", "/IM", "areyoulowbattery.exe"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("\n✅ AreYouLowBattery was completely uninstalled.")
        return

    print("=== Uninstalling AreYouLowBattery ===")

    # 1. Stop and disable systemd user service
    print("[1/4] Stopping and disabling systemd service...")
    subprocess.run(["systemctl", "--user", "stop", "areyoulowbattery.service"], check=False)
    subprocess.run(["systemctl", "--user", "disable", "areyoulowbattery.service"], check=False)
    service_path = os.path.expanduser("~/.config/systemd/user/areyoulowbattery.service")
    if os.path.exists(service_path):
        os.remove(service_path)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    # 2. Remove installed binary in ~/.local/bin if present
    print("[2/4] Removing binary from ~/.local/bin...")
    target_bin = os.path.expanduser("~/.local/bin/areyoulowbattery")
    if os.path.exists(target_bin):
        try:
            os.remove(target_bin)
            print(f"  Removed {target_bin}")
        except OSError as e:
            print(f"  Could not remove {target_bin}: {e}")

    # 3. Clean up user configuration and shared memory cache
    print("[3/4] Cleaning user config and memory cache...")
    config_dir = os.path.expanduser("~/.config/areyoulowbattery")
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir, ignore_errors=True)
        print(f"  Removed {config_dir}")

    for f in glob.glob(os.path.join(CACHE_DIR, "areyoulowbattery*")):
        try:
            os.remove(f)
        except OSError:
            pass

    # 4. Remove udev rules if present
    udev_path = "/etc/udev/rules.d/99-areyoulowbattery.rules"
    if os.path.exists(udev_path):
        print(f"[4/4] Removing {udev_path}...")
        try:
            res = subprocess.run(["sudo", "rm", "-f", udev_path], check=False)
            if res.returncode == 0:
                subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=False)
                subprocess.run(["sudo", "udevadm", "trigger"], check=False)
                print("  Udev rules removed.")
        except Exception:
            print(f"  Note: To remove udev rules manually, run: sudo rm {udev_path}")
    else:
        print("[4/4] No udev rules to remove.")

    print("\n✅ AreYouLowBattery was completely uninstalled. No background services or files remain.")


def cmd_list_devices():
    devices = enumerate_hidraw()
    print("=== Connected HID Devices ===")
    for dev in devices:
        upage_str = f" Page: {hex(dev.usage_page)}" if dev.usage_page else ""
        print(f"Path: {dev.dev_path:<16} ID: {hex(dev.vendor_id)}:{hex(dev.product_id):<8} Iface: {dev.interface_number}{upage_str} Name: {dev.name}")

def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.AttachConsole(-1)
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="areyoulowbattery",
        description="Lightweight battery reader for wireless peripherals (mice, headsets, keyboards) on Linux."
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["install", "uninstall", "tray", "daemon"],
        help="Optional command: 'install' configures udev + systemd + System Tray automatically"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json", "full"],
        default="text",
        help="Output format (default: text for KDE Command Output / Waybar)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Show all devices even if battery is currently 0%% or unsupported"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run in background daemon mode to monitor and cache telemetry"
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run System Tray icon + background cache daemon"
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Force direct hardware poll ignoring cache"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all active /dev/hidraw nodes and exit"
    )
    parser.add_argument(
        "--install-rules",
        action="store_true",
        help="Show instructions to install udev rules for non-root access"
    )

    args = parser.parse_args()

    # When double-clicked in Windows Explorer or launched without CLI arguments, default to Tray mode
    is_cli_query = any(
        arg in sys.argv for arg in [
            "--format", "-f", "--poll", "--list-devices", "--daemon",
            "--all", "-a", "--install-rules", "install", "uninstall", "daemon"
        ]
    )
    if not is_cli_query or args.tray or args.action == "tray":
        from areyoulowbattery.tray import run_tray
        run_tray()
        return

    if args.action == "install":
        cmd_install()
        return

    if args.action == "uninstall":
        cmd_uninstall()
        return

    if args.install_rules:
        cmd_install_rules()
        return

    if args.list_devices:
        cmd_list_devices()
        return

    if args.daemon or args.action == "daemon":
        run_daemon_loop()
        return

    results = read_from_cache_or_poll(force_poll=args.poll)

    if args.format == "json":
        print(format_json_output(results))
    elif args.format == "full":
        print(format_full_output(results))
    else:
        print(format_text_output(results, show_all=args.all))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        log_file = os.path.join(tempfile.gettempdir(), "areyoulowbattery_error.log")
        try:
            with open(log_file, "w") as f:
                f.write(err_msg)
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.critical(None, "AreYouLowBattery Error", f"An error occurred:\n\n{e}\n\nLog saved to:\n{log_file}")
            except Exception:
                pass
        raise
