import os
import sys
import glob
import json
import time
import re
from typing import List, Tuple, Optional, Dict
from areyoulowbattery.models import DeviceProfile, BatteryStatus, DeviceCategory, DeviceMatch, CATEGORY_ICONS
from areyoulowbattery.transport import enumerate_hidraw, HidrawDevice
from areyoulowbattery.profile_loader import load_all_profiles
from areyoulowbattery.handlers import get_handler

OVERRIDES_FILE = os.path.expanduser("~/.config/areyoulowbattery/device_overrides.json")
LEGACY_NAMES_FILE = os.path.expanduser("~/.config/areyoulowbattery/device_names.json")


def load_device_overrides() -> Dict[str, dict]:
    overrides = {}
    if os.path.exists(LEGACY_NAMES_FILE):
        try:
            with open(LEGACY_NAMES_FILE, "r") as f:
                for k, v in json.load(f).items():
                    overrides[k] = {"name": v}
        except Exception:
            pass
    if os.path.exists(OVERRIDES_FILE):
        try:
            with open(OVERRIDES_FILE, "r") as f:
                for k, v in json.load(f).items():
                    if k in overrides:
                        overrides[k].update(v)
                    else:
                        overrides[k] = v
        except Exception:
            pass
    return overrides


def save_device_override(key: str, name: Optional[str] = None, category: Optional[str] = None, icon: Optional[str] = None):
    overrides = load_device_overrides()
    item = overrides.setdefault(key, {})
    if name is not None:
        if name.strip():
            item["name"] = name.strip()
        else:
            item.pop("name", None)
    if category is not None:
        item["category"] = category
    if icon is not None:
        item["icon"] = icon

    os.makedirs(os.path.dirname(OVERRIDES_FILE), exist_ok=True)
    with open(OVERRIDES_FILE, "w") as f:
        json.dump(overrides, f, indent=2)


def save_custom_name(key: str, custom_name: str):
    save_device_override(key, name=custom_name)


def save_custom_category(key: str, category: str, icon: str):
    save_device_override(key, category=category, icon=icon)


def _infer_category_and_icon(name: str) -> Tuple[DeviceCategory, str]:
    lower = name.lower()
    if any(k in lower for k in ("headset", "headphone", "earbud", "airpod", "buds", "gh02", "audio")):
        return DeviceCategory.HEADSET, "🎧"
    if "mouse" in lower:
        return DeviceCategory.MOUSE, "🖱️"
    if any(k in lower for k in ("keyboard", "keychron", "royalaxe")):
        return DeviceCategory.KEYBOARD, "⌨️"
    if any(k in lower for k in ("gamepad", "controller", "joystick", "xbox", "dualsense")):
        return DeviceCategory.GAMEPAD, "🎮"
    return DeviceCategory.OTHER, "🔋"


def _parse_modalias_vid_pid(modalias: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not modalias:
        return None, None
    import re
    m = re.search(r"v([0-9A-Fa-f]{4})p([0-9A-Fa-f]{4})", modalias)
    if m:
        try:
            return int(m.group(1), 16), int(m.group(2), 16)
        except ValueError:
            pass
    return None, None


BLUEZ_ICON_MAP = {
    "input-keyboard": (DeviceCategory.KEYBOARD, "⌨️"),
    "input-mouse": (DeviceCategory.MOUSE, "🖱️"),
    "audio-headset": (DeviceCategory.HEADSET, "🎧"),
    "audio-headphones": (DeviceCategory.HEADSET, "🎧"),
    "audio-card": (DeviceCategory.HEADSET, "🎧"),
    "input-gaming": (DeviceCategory.GAMEPAD, "🎮"),
}


class BatteryEngine:
    def __init__(self, profiles_dir: Optional[str] = None):
        self.profiles = load_all_profiles(profiles_dir)
        self._smoothed_levels: Dict[str, dict] = {}

    def _filter_battery_jitter(self, key: str, status: BatteryStatus) -> BatteryStatus:
        """
        Anti-jitter filter for discharging peripherals:
        Suppresses momentary upward voltage spikes caused by RGB LEDs turning off (voltage sag bounce).
        Allows immediate downward updates, staleness resets (> 3 min), charging updates,
        or sustained (> 60s) higher readings from external chargers.
        """
        if (
            status.percentage is None
            or not status.is_connected
            or status.is_wired
            or status.requires_bluetooth
        ):
            return status

        now = time.time()
        hist = self._smoothed_levels.get(key)
        raw_pct = status.percentage

        if not hist:
            self._smoothed_levels[key] = {
                "level": raw_pct,
                "timestamp": now,
                "spike_val": None,
                "spike_ts": None,
            }
            return status

        last_lvl = hist["level"]
        last_ts = hist["timestamp"]

        # If device is charging, accept immediate upward reading
        if status.is_charging:
            hist["level"] = raw_pct
            hist["timestamp"] = now
            hist["spike_val"] = None
            hist["spike_ts"] = None
            return status

        # If the device was off or disconnected for > 3 minutes, accept fresh reading
        if now - last_ts > 180.0:
            hist["level"] = raw_pct
            hist["timestamp"] = now
            hist["spike_val"] = None
            hist["spike_ts"] = None
            return status

        # Normal discharge (going down or holding steady): accept immediately
        if raw_pct <= last_lvl:
            hist["level"] = raw_pct
            hist["timestamp"] = now
            hist["spike_val"] = None
            hist["spike_ts"] = None
            return status

        # Upward spike while discharging (e.g. RGB LEDs turned off -> voltage bounce):
        # Only accept if sustained continuously for >= 60 seconds (external wall charging)
        if hist.get("spike_val") == raw_pct:
            if now - (hist.get("spike_ts") or now) >= 60.0:
                hist["level"] = raw_pct
                hist["timestamp"] = now
                hist["spike_val"] = None
                hist["spike_ts"] = None
                return status
        else:
            hist["spike_val"] = raw_pct
            hist["spike_ts"] = now

        # Suppress upward spike: clamp to last stable known percentage
        return BatteryStatus(
            percentage=last_lvl,
            is_charging=status.is_charging,
            is_connected=status.is_connected,
            details=status.details,
            supported=status.supported,
            eta_seconds=status.eta_seconds,
            is_wired=status.is_wired,
            requires_bluetooth=status.requires_bluetooth,
        )

    def find_profile_for_device(self, dev: HidrawDevice) -> Optional[DeviceProfile]:
        # First pass: exact VID + PID match
        # Second pass: generic VID-only fallback profile
        for require_pid in (True, False):
            for profile in self.profiles:
                match = profile.match
                if match.vendor_id != dev.vendor_id:
                    continue
                has_pid = bool(match.product_ids or match.product_id is not None)
                if require_pid != has_pid:
                    continue
                if match.product_ids and dev.product_id not in match.product_ids:
                    continue
                elif not match.product_ids and match.product_id is not None and match.product_id != dev.product_id:
                    continue
                if match.interface_number is not None:
                    if dev.interface_number is not None and match.interface_number != dev.interface_number:
                        continue
                base_name = (
                    dev.name.strip()
                    if (not has_pid and dev.name and dev.name != "Unknown")
                    else profile.name
                )
                overrides = load_device_overrides()
                vid_key = f"{dev.vendor_id:04x}:{dev.product_id:04x}"
                ovr = (
                    overrides.get(vid_key)
                    or overrides.get(base_name)
                    or overrides.get(profile.name)
                    or {}
                )
                final_name = ovr.get("name") or base_name
                final_cat = (
                    DeviceCategory(ovr["category"])
                    if "category" in ovr
                    else profile.category
                )
                final_icon = ovr.get("icon") or CATEGORY_ICONS.get(final_cat, profile.icon)
                if (
                    final_name != profile.name
                    or final_cat != profile.category
                    or final_icon != profile.icon
                ):
                    return DeviceProfile(
                        name=final_name,
                        category=final_cat,
                        icon=final_icon,
                        match=profile.match,
                        protocol=profile.protocol,
                        config=profile.config,
                    )
                return profile
        return None

    def _poll_bluetooth_peripheral_batteries(self) -> List[Tuple[str, int, str, Optional[str], Optional[str]]]:
        """
        Polls connected Bluetooth peripheral batteries using BlueZ D-Bus, UPower D-Bus,
        or bluetoothctl CLI fallback. Returns list of (device_name, percentage, details, modalias, icon).
        """
        if sys.platform == "win32":
            return []

        results = []
        # 1. Try BlueZ D-Bus directly (fastest, in-process, non-blocking)
        try:
            import dbus
            bus = dbus.SystemBus()
            om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
            for path, ifaces in objects.items():
                if "org.bluez.Device1" in ifaces:
                    dev = ifaces["org.bluez.Device1"]
                    if bool(dev.get("Connected", False)):
                        name = str(dev.get("Name", dev.get("Alias", "Bluetooth Device")))
                        modalias = str(dev.get("Modalias")) if dev.get("Modalias") else None
                        icon_hint = str(dev.get("Icon")) if dev.get("Icon") else None
                        batt = ifaces.get("org.bluez.Battery1", {}).get("Percentage")
                        if batt is not None:
                            results.append((name, int(batt), "BlueZ D-Bus", modalias, icon_hint))
            if results:
                return results
        except Exception:
            pass

        # 2. Try UPower D-Bus
        try:
            import dbus
            bus = dbus.SystemBus()
            upower_obj = bus.get_object("org.freedesktop.UPower", "/org/freedesktop/UPower")
            upower = dbus.Interface(upower_obj, "org.freedesktop.UPower")
            for dev_path in upower.EnumerateDevices():
                d_obj = bus.get_object("org.freedesktop.UPower", dev_path)
                props = dbus.Interface(d_obj, "org.freedesktop.DBus.Properties")
                model = str(props.Get("org.freedesktop.UPower.Device", "Model"))
                dev_type = int(props.Get("org.freedesktop.UPower.Device", "Type"))
                pct = float(props.Get("org.freedesktop.UPower.Device", "Percentage"))
                # 5=mouse, 6=keyboard, 10=headset, 17=headset, 24=wearable
                if model and pct > 0 and dev_type in (5, 6, 10, 17, 24):
                    icon_hint = "input-keyboard" if dev_type == 6 else ("input-mouse" if dev_type == 5 else "audio-headset")
                    results.append((model, int(pct), "UPower D-Bus", None, icon_hint))
            if results:
                return results
        except Exception:
            pass

        # 3. Fallback: bluetoothctl CLI
        try:
            import subprocess
            out = subprocess.run(
                ["bluetoothctl", "devices", "Connected"],
                capture_output=True, text=True, timeout=1.0
            )
            for line in out.stdout.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) >= 3 and parts[0] == "Device":
                    mac, dev_name = parts[1], parts[2]
                    info_out = subprocess.run(
                        ["bluetoothctl", "info", mac],
                        capture_output=True, text=True, timeout=1.0
                    )
                    modalias = None
                    icon_hint = None
                    pct_int = None
                    for info_line in info_out.stdout.splitlines():
                        if "Modalias:" in info_line:
                            modalias = info_line.split(":")[-1].strip()
                        if "Icon:" in info_line:
                            icon_hint = info_line.split(":")[-1].strip()
                        if "Battery Percentage:" in info_line:
                            pct_val = info_line.split(":")[-1].strip()
                            if "(" in pct_val:
                                pct_int = int(pct_val.split("(")[-1].replace(")", "").strip())
                    if pct_int is not None:
                        results.append((dev_name, pct_int, "bluetoothctl", modalias, icon_hint))
        except Exception:
            pass

        return results

    def _poll_sysfs_peripheral_batteries(self, seen_names: set) -> List[Tuple[DeviceProfile, BatteryStatus]]:
        """Reads peripheral batteries exposed by Linux kernel / BlueZ in /sys/class/power_supply/."""
        results = []
        for ps_path in sorted(glob.glob("/sys/class/power_supply/*")):
            scope_file = os.path.join(ps_path, "scope")
            cap_file = os.path.join(ps_path, "capacity")
            if not (os.path.exists(scope_file) and os.path.exists(cap_file)):
                continue
            try:
                scope = open(scope_file, "r").read().strip()
                if scope.lower() != "device":
                    continue
                capacity = int(open(cap_file, "r").read().strip())
            except Exception:
                continue

            model_file = os.path.join(ps_path, "model_name")
            name = (
                open(model_file, "r").read().strip()
                if os.path.exists(model_file)
                else os.path.basename(ps_path)
            )
            if name in seen_names:
                continue

            status_file = os.path.join(ps_path, "status")
            status_str = open(status_file, "r").read().strip().lower() if os.path.exists(status_file) else ""
            is_charging = status_str == "charging"

            cat, icon = _infer_category_and_icon(name)
            overrides = load_device_overrides()
            ovr = overrides.get(name) or {}
            final_name = ovr.get("name") or name
            final_cat = (
                DeviceCategory(ovr["category"])
                if "category" in ovr
                else cat
            )
            final_icon = ovr.get("icon") or CATEGORY_ICONS.get(final_cat, icon)
            profile = DeviceProfile(
                name=final_name,
                category=final_cat,
                icon=final_icon,
                match=DeviceMatch(vendor_id=0),
                protocol="sysfs_power_supply",
            )
            results.append((
                profile,
                BatteryStatus(
                    percentage=capacity,
                    is_charging=is_charging,
                    is_connected=True,
                    details=f"Kernel power_supply ({os.path.basename(ps_path)})",
                ),
            ))
            seen_names.add(name)
        return results

    def poll_all_devices(self) -> List[Tuple[DeviceProfile, BatteryStatus]]:
        connected_hid = enumerate_hidraw()
        results = []

        # Group candidate HID nodes by matched profile name
        # This allows multiple collections/endpoints of the same device on Windows
        # to be queried until an active, connected telemetry packet is received.
        candidates: Dict[str, List[Tuple[DeviceProfile, HidrawDevice]]] = {}
        for dev in connected_hid:
            profile = self.find_profile_for_device(dev)
            if profile:
                candidates.setdefault(profile.name, []).append((profile, dev))

        matched_profiles = set()
        for name, dev_list in candidates.items():
            best_profile = None
            best_status = None
            for profile, dev in dev_list:
                try:
                    handler = get_handler(profile.protocol)
                    status = handler.read_battery(dev, profile)
                    if status and status.is_connected:
                        best_profile = profile
                        best_status = status
                        if not status.details.startswith("Cached"):
                            break
                    elif status and (best_status is None or not best_status.is_connected):
                        best_profile = profile
                        best_status = status
                except Exception as e:
                    if best_status is None:
                        best_profile = profile
                        best_status = BatteryStatus(
                            percentage=0,
                            is_connected=False,
                            details=f"Handler error: {e}"
                        )

            if best_profile and best_status:
                results.append((best_profile, best_status))
                matched_profiles.add(best_profile.name)

        # Check Bluetooth peripherals (BlueZ D-Bus / UPower)
        bt_devices = self._poll_bluetooth_peripheral_batteries()
        for bt_name, bt_pct, bt_source, bt_modalias, bt_icon in bt_devices:
            vid, pid = _parse_modalias_vid_pid(bt_modalias)
            matched_yaml_prof = None
            if vid and pid:
                for p in self.profiles:
                    if p.match.vendor_id == vid and (pid in p.match.product_ids or p.match.product_id == pid):
                        matched_yaml_prof = p
                        break

            if matched_yaml_prof:
                cat, icon = matched_yaml_prof.category, matched_yaml_prof.icon
                base_name = matched_yaml_prof.name
            elif bt_icon and bt_icon in BLUEZ_ICON_MAP:
                cat, icon = BLUEZ_ICON_MAP[bt_icon]
                base_name = bt_name
            else:
                cat, icon = _infer_category_and_icon(bt_name)
                base_name = bt_name

            overrides = load_device_overrides()
            ovr = overrides.get(base_name) or overrides.get(bt_name) or {}
            final_name = ovr.get("name") or base_name
            final_cat = DeviceCategory(ovr["category"]) if "category" in ovr else cat
            final_icon = ovr.get("icon") or CATEGORY_ICONS.get(final_cat, icon)

            bt_profile = DeviceProfile(
                name=final_name,
                category=final_cat,
                icon=final_icon,
                match=DeviceMatch(vendor_id=vid or 0, product_id=pid),
                protocol="bluetooth",
            )
            bt_status = BatteryStatus(
                percentage=bt_pct,
                is_charging=False,
                is_connected=True,
                details=f"Connected via Bluetooth ({bt_source})",
            )

            # Check if this peripheral was already listed as "requires_bluetooth" from its 2.4G dongle
            replaced = False
            import re
            bt_tokens = set(re.findall(r"[a-z0-9]+", bt_name.lower())) | set(re.findall(r"[a-z0-9]+", final_name.lower()))
            for idx, (existing_prof, existing_status) in enumerate(results):
                # Category guard: Never merge different hardware categories (e.g. Mouse can NEVER replace Keyboard)
                if (
                    existing_prof.category != DeviceCategory.OTHER
                    and final_cat != DeviceCategory.OTHER
                    and existing_prof.category != final_cat
                ):
                    continue

                ex_tokens = set(re.findall(r"[a-z0-9]+", existing_prof.name.lower()))
                common_tokens = (bt_tokens & ex_tokens) - {"keyboard", "mouse", "headset", "bt", "bt5", "bt50", "2", "4g", "pro", "dual", "mode"}
                vid_pid_match = bool(
                    vid and pid and existing_prof.match.vendor_id == vid
                    and (pid in existing_prof.match.product_ids or existing_prof.match.product_id == pid)
                )
                if existing_status.requires_bluetooth and (
                    vid_pid_match
                    or existing_prof.name.lower() in final_name.lower()
                    or final_name.lower() in existing_prof.name.lower()
                    or bool(common_tokens)
                ):
                    # Upgrade the 2.4G placeholder to active live Bluetooth telemetry!
                    upgraded_prof = DeviceProfile(
                        name=existing_prof.name,
                        category=existing_prof.category,
                        icon=existing_prof.icon,
                        match=existing_prof.match,
                        protocol="bluetooth",
                        config=existing_prof.config,
                    )
                    results[idx] = (upgraded_prof, bt_status)
                    matched_profiles.add(existing_prof.name)
                    matched_profiles.add(final_name)
                    matched_profiles.add(bt_name)
                    replaced = True
                    break

            if not replaced and final_name not in matched_profiles:
                results.append((bt_profile, bt_status))
                matched_profiles.add(final_name)
                matched_profiles.add(bt_name)

        results.extend(self._poll_sysfs_peripheral_batteries(matched_profiles))

        # Apply anti-jitter smoothing filter to eliminate voltage sag bounces
        smoothed = []
        for prof, stat in results:
            key = f"{prof.name}:{prof.match.vendor_id:04x}:{prof.match.product_id or 0:04x}"
            filtered_stat = self._filter_battery_jitter(key, stat)
            smoothed.append((prof, filtered_stat))
        return smoothed
