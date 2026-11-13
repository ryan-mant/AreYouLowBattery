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
from areyoulowbattery.logger import logger

def _get_config_dir() -> str:
    config_base = (
        os.environ.get("LOCALAPPDATA")
        if sys.platform == "win32"
        else os.path.expanduser("~/.config")
    ) or os.path.expanduser("~/.config")
    d = os.path.join(config_base, "areyoulowbattery")
    os.makedirs(d, exist_ok=True)
    return d


def _get_overrides_path() -> str:
    return os.path.join(_get_config_dir(), "device_overrides.json")


def _get_ignored_devices_path() -> str:
    return os.path.join(_get_config_dir(), "ignored_devices.json")


OVERRIDES_FILE = _get_overrides_path()
LEGACY_NAMES_FILE = os.path.expanduser("~/.config/areyoulowbattery/device_names.json")


def load_ignored_devices() -> set:
    path = _get_ignored_devices_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception as e:
            logger.debug("Failed loading ignored devices: %s", e)
    return set()


def save_ignored_devices(ignored: set):
    path = _get_ignored_devices_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(ignored)), f, indent=2)
    except Exception as e:
        logger.debug("Failed saving ignored devices: %s", e)


def ignore_device(identifier: str):
    ignored = load_ignored_devices()
    ignored.add(identifier)
    save_ignored_devices(ignored)


def unignore_device(identifier: str):
    ignored = load_ignored_devices()
    ignored.discard(identifier)
    save_ignored_devices(ignored)


def remove_device(
    profile_name: str,
    vid: Optional[int] = None,
    pid: Optional[int] = None,
    pids: Optional[List[int]] = None,
):
    """
    Hides/removes a device from the dashboard:
    1. Adds profile name and specific hardware IDs to ignored_devices.json.
    2. Deletes user custom YAML file if it was generated in profiles directory.
    """
    ignored = load_ignored_devices()
    ignored.add(profile_name)
    if vid is not None:
        if pid is not None:
            ignored.add(f"{vid:04x}:{pid:04x}")
        if pids:
            for p in pids:
                ignored.add(f"{vid:04x}:{p:04x}")
    save_ignored_devices(ignored)

    # Check and remove custom YAML profile if present
    from areyoulowbattery.discovery import get_user_profiles_dir
    user_dir = get_user_profiles_dir()
    for fpath in glob.glob(os.path.join(user_dir, "**", "*.yaml"), recursive=True):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
                if profile_name in content or (vid and f"{vid:04x}" in content.lower()):
                    os.remove(fpath)
                    logger.info("Removed custom profile YAML: %s", fpath)
        except Exception as e:
            logger.debug("Could not delete custom profile %s: %s", fpath, e)


def restore_device(
    profile_name: str,
    vid: Optional[int] = None,
    pid: Optional[int] = None,
    pids: Optional[List[int]] = None,
):
    """Restores/unhides a device that was previously removed."""
    ignored = load_ignored_devices()
    ignored.discard(profile_name)
    if vid is not None:
        if pid is not None:
            ignored.discard(f"{vid:04x}:{pid:04x}")
        if pids:
            for p in pids:
                ignored.discard(f"{vid:04x}:{p:04x}")
        ignored.discard(f"{vid:04x}")
        # Clean any override custom names associated with this hardware ID
        try:
            overrides = load_device_overrides()
            for key in (f"{vid:04x}:{pid:04x}" if pid else "", f"{vid:04x}"):
                if key and key in overrides:
                    ovr = overrides[key].get("name")
                    if ovr:
                        ignored.discard(ovr)
        except Exception:
            pass
    save_ignored_devices(ignored)


def load_device_overrides() -> Dict[str, dict]:
    overrides = {}
    if os.path.exists(LEGACY_NAMES_FILE):
        try:
            with open(LEGACY_NAMES_FILE, "r") as f:
                for k, v in json.load(f).items():
                    overrides[k] = {"name": v}
        except Exception:
            pass
    overrides_file = _get_overrides_path()
    if os.path.exists(overrides_file):
        try:
            with open(overrides_file, "r") as f:
                for k, v in json.load(f).items():
                    if k in overrides:
                        overrides[k].update(v)
                    else:
                        overrides[k] = v
        except Exception:
            pass
    return overrides


def save_device_override(
    key: str,
    name: Optional[str] = None,
    category: Optional[str] = None,
    icon: Optional[str] = None,
    protocol: Optional[str] = None,
    config: Optional[dict] = None,
):
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
    if protocol is not None:
        item["protocol"] = protocol
    if config is not None:
        item["config"] = config

    overrides_file = _get_overrides_path()
    with open(overrides_file, "w") as f:
        json.dump(overrides, f, indent=2)


def save_custom_name(key: str, custom_name: str):
    save_device_override(key, name=custom_name)


def save_custom_category(key: str, category: str, icon: str):
    save_device_override(key, category=category, icon=icon)


def save_device_protocol(key: str, protocol: str, config: Optional[dict] = None):
    save_device_override(key, protocol=protocol, config=config)


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


def _infer_bluetooth_icon(name: str) -> Optional[str]:
    lower = name.lower()
    if any(k in lower for k in ("mouse", "mice", "trackball", "optical")):
        return "input-mouse"
    if any(k in lower for k in ("keyboard", "keypad", "keys")):
        return "input-keyboard"
    if any(k in lower for k in ("headset", "headphone", "audio", "earbud", "earphone", "airpod", "buds")):
        return "audio-headset"
    if any(k in lower for k in ("controller", "gamepad", "joystick")):
        return "input-gaming"
    return None


class BatteryEngine:
    MIN_QUERY_INTERVAL = 5.0  # seconds between hardware queries of the same device (non-forced)

    def __init__(self, profiles_dir: Optional[str] = None):
        self.profiles = load_all_profiles(profiles_dir)
        self._smoothed_levels: Dict[str, dict] = {}
        self._win_bt_cache: List[Tuple[str, int, str, Optional[str], Optional[str]]] = []
        self._win_bt_cache_ts: float = 0.0
        self._offline_devices: Dict[str, Tuple[BatteryStatus, float]] = {}
        # Per-device rate limiter: last (profile, status, timestamp) of a hardware query.
        self._recent_queries: Dict[str, Tuple[DeviceProfile, BatteryStatus, float]] = {}

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
                ignored = load_ignored_devices()
                if (
                    base_name in ignored
                    or profile.name in ignored
                    or vid_key in ignored
                    or f"{dev.vendor_id:04x}" in ignored
                ):
                    continue

                ovr = (
                    overrides.get(vid_key)
                    or overrides.get(base_name)
                    or overrides.get(profile.name)
                    or {}
                )
                final_name = ovr.get("name") or base_name
                if final_name in ignored:
                    continue

                final_cat = (
                    DeviceCategory(ovr["category"])
                    if "category" in ovr
                    else profile.category
                )
                final_icon = ovr.get("icon") or CATEGORY_ICONS.get(final_cat, profile.icon)
                final_protocol = ovr.get("protocol") or profile.protocol
                final_config = ovr.get("config") if "config" in ovr else profile.config
                if (
                    final_name != profile.name
                    or final_cat != profile.category
                    or final_icon != profile.icon
                    or final_protocol != profile.protocol
                    or final_config != profile.config
                ):
                    return DeviceProfile(
                        name=final_name,
                        category=final_cat,
                        icon=final_icon,
                        match=profile.match,
                        protocol=final_protocol,
                        config=final_config,
                    )
                return profile
        return None

    def _poll_bluetooth_windows(self) -> List[Tuple[str, int, str, Optional[str], Optional[str]]]:
        """
        Polls connected Bluetooth peripheral batteries on Windows using the native
        Windows PnP Device Property {104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2 (DEVPKEY_Device_BatteryLevel).
        Tries fast in-process Windows Registry query first, then PowerShell PnP query fallback.
        Cached for 15s to guarantee 0.0% CPU overhead.
        """
        now = time.time()
        if now - self._win_bt_cache_ts < 15.0 and self._win_bt_cache:
            return self._win_bt_cache

        results = []

        # 1. In-process Windows Registry query (instantaneous, zero subprocess overhead)
        try:
            import winreg
            base_path = r"SYSTEM\CurrentControlSet\Enum"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path) as enum_key:
                for bus_name in ("BTHENUM", "BTHLE", "BTHLEDevice", "BTH", "HID"):
                    try:
                        with winreg.OpenKey(enum_key, bus_name) as bus_key:
                            num_devs = winreg.QueryInfoKey(bus_key)[0]
                            for i in range(num_devs):
                                dev_sub = winreg.EnumKey(bus_key, i)
                                try:
                                    with winreg.OpenKey(bus_key, dev_sub) as sub_key:
                                        num_inst = winreg.QueryInfoKey(sub_key)[0]
                                        for j in range(num_inst):
                                            inst_name = winreg.EnumKey(sub_key, j)
                                            try:
                                                with winreg.OpenKey(sub_key, inst_name) as inst_key:
                                                    friendly_name = None
                                                    try:
                                                        friendly_name, _ = winreg.QueryValueEx(inst_key, "FriendlyName")
                                                    except OSError:
                                                        try:
                                                            friendly_name, _ = winreg.QueryValueEx(inst_key, "DeviceDesc")
                                                        except OSError:
                                                            pass

                                                    for prop_sub in (
                                                        r"Properties\{104EA319-6EE2-4701-BD47-8DDBF425BBE5}\00000002",
                                                        r"Properties\{104EA319-6EE2-4701-BD47-8DDBF425BBE5}\0002"
                                                    ):
                                                        try:
                                                            with winreg.OpenKey(inst_key, prop_sub) as prop_key:
                                                                val, _ = winreg.QueryValueEx(prop_key, "")
                                                                pct = None
                                                                if isinstance(val, (int, float)):
                                                                    pct = int(val)
                                                                elif isinstance(val, (bytes, bytearray)) and len(val) >= 1:
                                                                    pct = int(val[0])
                                                                if pct is not None and 0 <= pct <= 100 and friendly_name:
                                                                    icon_hint = _infer_bluetooth_icon(friendly_name)
                                                                    results.append((friendly_name, pct, "Windows Registry", None, icon_hint))
                                                                    break
                                                        except OSError:
                                                            pass
                                            except OSError:
                                                continue
                                except OSError:
                                    continue
                    except OSError:
                        continue
            if results:
                self._win_bt_cache = results
                self._win_bt_cache_ts = now
                return results
        except Exception as e:
            logger.debug("Windows registry Bluetooth query failed: %s", e)

        # 2. Fallback: PowerShell PnP query
        try:
            import subprocess
            ps_script = (
                "Get-PnpDevice -Status OK -ErrorAction SilentlyContinue | "
                "Where-Object { $_.InstanceId -match 'BTH' } | "
                "ForEach-Object { "
                "$prop = $_ | Get-PnpDeviceProperty -KeyName '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction SilentlyContinue; "
                "if ($prop -and $prop.Data -ne $null) { \"$($_.FriendlyName)|$($prop.Data)\" } "
                "}"
            )
            startupinfo = None
            if hasattr(subprocess, "STARTUPINFO"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=5.0, startupinfo=startupinfo
            )
            for line in res.stdout.splitlines():
                if "|" in line:
                    parts = line.strip().split("|", 1)
                    name = parts[0].strip()
                    try:
                        pct = int(parts[1].strip())
                        if 0 <= pct <= 100:
                            icon_hint = _infer_bluetooth_icon(name)
                            results.append((name, pct, "Windows PnP", None, icon_hint))
                    except ValueError:
                        continue
            if results:
                self._win_bt_cache = results
                self._win_bt_cache_ts = now
                return results
        except Exception as e:
            logger.debug("Windows PowerShell Bluetooth query failed: %s", e)

        return results

    def _poll_bluetooth_peripheral_batteries(self) -> List[Tuple[str, int, str, Optional[str], Optional[str]]]:
        """
        Polls connected Bluetooth peripheral batteries using BlueZ D-Bus / UPower D-Bus on Linux,
        and Windows PnP Registry / SetupAPI on Windows. Returns list of (device_name, percentage, details, modalias, icon).
        """
        if sys.platform == "win32":
            return self._poll_bluetooth_windows()

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

    def poll_all_devices(self, force: bool = False) -> List[Tuple[DeviceProfile, BatteryStatus]]:
        ignored = load_ignored_devices()
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

            # Zero-energy passive sleep guard:
            # If the device was confirmed asleep/offline within the last 5 minutes (300s)
            # and this is not an explicit user force refresh (e.g. tray click or refresh button),
            # reuse cached offline status instead of sending active RF pings over USB!
            if not force and name in self._offline_devices:
                last_stat, last_ts = self._offline_devices[name]
                if time.time() - last_ts < 300.0:
                    best_profile = dev_list[0][0]
                    best_status = last_stat

            # Per-device rate limit: never hit the same device's hardware more than once
            # every MIN_QUERY_INTERVAL seconds (hotplug storms, rapid UI events), unless forced.
            if not force and best_status is None and name in self._recent_queries:
                r_prof, r_stat, r_ts = self._recent_queries[name]
                if time.time() - r_ts < self.MIN_QUERY_INTERVAL:
                    best_profile, best_status = r_prof, r_stat

            if best_status is None:
                for profile, dev in dev_list:
                    try:
                        handler = get_handler(profile.protocol)
                        status = handler.read_battery(dev, profile)
                        if status and status.is_connected:
                            if status.percentage is not None and status.percentage > 0:
                                best_profile = profile
                                best_status = status
                                if not status.details.startswith("Cached"):
                                    break
                            elif best_status is None or best_status.percentage is None:
                                best_profile = profile
                                best_status = status
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
                if name not in self._recent_queries or self._recent_queries[name][1] is not best_status:
                    self._recent_queries[name] = (best_profile, best_status, time.time())
                if not best_status.is_connected:
                    self._offline_devices[name] = (best_status, time.time())
                else:
                    self._offline_devices.pop(name, None)

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
                is_same_device = (
                    vid_pid_match
                    or existing_prof.name.lower() in final_name.lower()
                    or final_name.lower() in existing_prof.name.lower()
                    or bool(common_tokens)
                )
                if is_same_device:
                    if existing_status.requires_bluetooth:
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
                    elif existing_status.is_connected and existing_status.percentage is not None:
                        # Direct hardware telemetry (e.g. Pebble K380s HID++ 15%) takes precedence over Windows GATT cache
                        matched_profiles.add(existing_prof.name)
                        matched_profiles.add(final_name)
                        matched_profiles.add(bt_name)
                        replaced = True
                        break
                    elif not existing_status.is_connected and bt_pct > 0:
                        results[idx] = (existing_prof, bt_status)
                        matched_profiles.add(existing_prof.name)
                        matched_profiles.add(final_name)
                        matched_profiles.add(bt_name)
                        replaced = True
                        break

            if not replaced and final_name not in matched_profiles and final_name not in ignored and bt_name not in ignored:
                results.append((bt_profile, bt_status))
                matched_profiles.add(final_name)
                matched_profiles.add(bt_name)

        results.extend(self._poll_sysfs_peripheral_batteries(matched_profiles))

        # Apply anti-jitter smoothing filter to eliminate voltage sag bounces and filter ignored
        smoothed = []
        for prof, stat in results:
            vid_key = f"{prof.match.vendor_id:04x}:{prof.match.product_id or 0:04x}"
            if prof.name in ignored or vid_key in ignored or f"{prof.match.vendor_id:04x}" in ignored:
                continue
            key = f"{prof.name}:{prof.match.vendor_id:04x}:{prof.match.product_id or 0:04x}"
            filtered_stat = self._filter_battery_jitter(key, stat)
            smoothed.append((prof, filtered_stat))

        # Deduplicate multiple endpoints of the exact same physical peripheral (e.g. 2.4G dongle + wired USB mode of same keyboard)
        deduped: List[Tuple[DeviceProfile, BatteryStatus]] = []
        for prof, stat in smoothed:
            merged = False
            prof_tokens = set(re.findall(r"[a-z0-9]+", prof.name.lower())) - {
                "keyboard", "mouse", "headset", "controller", "dongle", "wireless", "2", "4g", "usb", "dual", "mode"
            }
            for idx, (existing_prof, existing_stat) in enumerate(deduped):
                if existing_prof.category != prof.category:
                    continue
                ex_tokens = set(re.findall(r"[a-z0-9]+", existing_prof.name.lower())) - {
                    "keyboard", "mouse", "headset", "controller", "dongle", "wireless", "2", "4g", "usb", "dual", "mode"
                }
                common = prof_tokens & ex_tokens
                if common and (prof_tokens.issubset(ex_tokens) or ex_tokens.issubset(prof_tokens) or len(common) >= 2):
                    # Same physical peripheral! Keep whichever endpoint has live telemetry (real % > requires_bt)
                    if (existing_stat.percentage is None or existing_stat.requires_bluetooth) and stat.percentage is not None:
                        deduped[idx] = (prof, stat)
                    merged = True
                    break
            if not merged:
                deduped.append((prof, stat))

        return deduped
