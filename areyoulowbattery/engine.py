import os
import glob
from typing import List, Tuple, Optional
from areyoulowbattery.models import DeviceProfile, BatteryStatus, DeviceCategory, DeviceMatch
from areyoulowbattery.transport import enumerate_hidraw, HidrawDevice
from areyoulowbattery.profile_loader import load_all_profiles
from areyoulowbattery.handlers import get_handler


def _infer_category_and_icon(name: str) -> Tuple[DeviceCategory, str]:
    lower = name.lower()
    if any(k in lower for k in ("headset", "headphone", "earbud", "airpod", "buds", "gh02", "audio")):
        return DeviceCategory.HEADSET, "🎧"
    if "mouse" in lower:
        return DeviceCategory.MOUSE, "🖱️"
    if any(k in lower for k in ("keyboard", "keychron", "royalaxe")):
        return DeviceCategory.KEYBOARD, "⌨️"
    return DeviceCategory.OTHER, "🔋"


class BatteryEngine:
    def __init__(self, profiles_dir: Optional[str] = None):
        self.profiles = load_all_profiles(profiles_dir)

    def find_profile_for_device(self, dev: HidrawDevice) -> Optional[DeviceProfile]:
        for profile in self.profiles:
            match = profile.match
            if match.vendor_id != dev.vendor_id:
                continue
            if match.product_ids and dev.product_id not in match.product_ids:
                continue
            elif not match.product_ids and match.product_id is not None and match.product_id != dev.product_id:
                continue
            if match.interface_number is not None and match.interface_number != dev.interface_number:
                continue
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
            profile = DeviceProfile(
                name=name,
                category=cat,
                icon=icon,
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
