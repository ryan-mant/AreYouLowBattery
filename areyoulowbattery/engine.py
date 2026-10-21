from typing import List, Tuple, Optional
from areyoulowbattery.models import DeviceProfile, BatteryStatus
from areyoulowbattery.transport import enumerate_hidraw, HidrawDevice
from areyoulowbattery.profile_loader import load_all_profiles
from areyoulowbattery.handlers import get_handler

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

        return results
