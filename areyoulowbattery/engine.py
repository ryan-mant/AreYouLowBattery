import os
import glob
import json
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


class BatteryEngine:
    def __init__(self, profiles_dir: Optional[str] = None):
        self.profiles = load_all_profiles(profiles_dir)

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
                if match.interface_number is not None and match.interface_number != dev.interface_number:
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
        matched_profiles = set()

        for dev in connected_hid:
            profile = self.find_profile_for_device(dev)
            if not profile or profile.name in matched_profiles:
                continue

            try:
                handler = get_handler(profile.protocol)
                status = handler.read_battery(dev, profile)
                if status:
                    results.append((profile, status))
                    matched_profiles.add(profile.name)
            except Exception as e:
                status = BatteryStatus(
                    percentage=0,
                    is_connected=False,
                    details=f"Handler error: {e}"
                )
                results.append((profile, status))
                matched_profiles.add(profile.name)

        results.extend(self._poll_sysfs_peripheral_batteries(matched_profiles))
        return results
