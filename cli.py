#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
from typing import List, Tuple

# Ensure package is discoverable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from areyoulowbattery.engine import BatteryEngine
from areyoulowbattery.transport import enumerate_hidraw
from areyoulowbattery.models import DeviceProfile, BatteryStatus, DeviceCategory

CACHE_FILE = "/dev/shm/areyoulowbattery_status.json"

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
        pct_str = f" {status.percentage}%" if status.percentage is not None else ""
        lines.append(f"Device: {profile.name} [{profile.category.value.upper()}]")
        lines.append(f"  Status: {state}{pct_str}{chg}")
        if status.details:
            lines.append(f"  Details: {status.details}")
        lines.append("-" * 32)
    return "\n".join(lines)

def run_daemon_loop():
    """Lightweight background daemon that monitors events and keeps /dev/shm cache fresh."""
    print("Starting AreYouLowBattery daemon (caching to /dev/shm)...")
    engine = BatteryEngine()
    
    while True:
        try:
            results = engine.poll_all_devices()
            cached_data = []
            for profile, status in results:
                cached_data.append({
                    "name": profile.name,
                    "category": profile.category.value,
                    "icon": profile.icon,
                    "percentage": status.percentage,
                    "is_charging": status.is_charging,
                    "is_connected": status.is_connected,
                    "details": status.details,
                    "timestamp": time.time()
                })
            with open(CACHE_FILE, "w") as f:
                json.dump(cached_data, f)
        except Exception as e:
            print(f"Daemon error: {e}", file=sys.stderr)
        
        time.sleep(10)

def read_from_cache_or_poll(engine: BatteryEngine, force_poll: bool = False):
    # Only trust the daemon cache if it was refreshed recently (daemon is alive)
    cache_fresh = os.path.exists(CACHE_FILE) and time.time() - os.path.getmtime(CACHE_FILE) < 30
    if not force_poll and cache_fresh:
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            results = []
            for item in data:
                matching = [p for p in engine.profiles if p.name == item["name"]]
                if matching:
                    profile = matching[0]
                    status = BatteryStatus(
                        percentage=item["percentage"],
                        is_charging=item.get("is_charging", False),
                        is_connected=item.get("is_connected", False),
                        details=item.get("details")
                    )
                    results.append((profile, status))
            if results:
                return results
        except Exception:
            pass
    return engine.poll_all_devices()

def cmd_install_rules():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    rules_src = os.path.join(project_dir, "rules", "99-areyoulowbattery.rules")
    rules_dst = "/etc/udev/rules.d/99-areyoulowbattery.rules"

    if not os.path.exists(rules_src):
        print(f"Error: Rules file not found at {rules_src}", file=sys.stderr)
        sys.exit(1)

    print(f"To install udev rules, run the following command:")
    print(f"\n  sudo cp \"{rules_src}\" \"{rules_dst}\" && sudo udevadm control --reload-rules && sudo udevadm trigger\n")

def cmd_list_devices():
    devices = enumerate_hidraw()
    print("=== Connected HIDRaw Devices ===")
    for dev in devices:
        print(f"Path: {dev.dev_path:<16} ID: {hex(dev.vendor_id)}:{hex(dev.product_id):<8} Iface: {dev.interface_number} Name: {dev.name}")

def main():
    parser = argparse.ArgumentParser(
        prog="areyoulowbattery",
        description="Lightweight battery reader for wireless peripherals (mice, headsets, keyboards) on Linux."
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

    if args.install_rules:
        cmd_install_rules()
        return

    if args.list_devices:
        cmd_list_devices()
        return

    if args.daemon:
        run_daemon_loop()
        return

    engine = BatteryEngine()
    results = read_from_cache_or_poll(engine, force_poll=args.poll)

    if args.format == "json":
        print(format_json_output(results))
    elif args.format == "full":
        print(format_full_output(results))
    else:
        print(format_text_output(results, show_all=args.all))

if __name__ == "__main__":
    main()
