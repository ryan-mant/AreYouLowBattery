import os
import sys
import glob
import re
import yaml
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from areyoulowbattery.models import DeviceCategory, DeviceProfile, DeviceMatch, CATEGORY_ICONS
from areyoulowbattery.profile_loader import get_resource_dir
from areyoulowbattery.transport import enumerate_hidraw, HidrawDevice
from areyoulowbattery.handlers import get_handler


# Well-known host hardware to ignore during device discovery (motherboard, hubs, webcams, audio)
IGNORED_VENDORS = {
    0x1D6B,  # Linux Foundation Root Hubs
    0x05E3,  # Genesys Logic USB Hub
    0x1462,  # MSI Motherboard Mystic Light
    0x0BDA,  # Realtek Audio / Ethernet
    0x8087,  # Intel Bluetooth / Hub
    0x0A12,  # Cambridge Silicon Radio Bluetooth Host Adapter
    0x04F2,  # Chicony Webcam
}

IGNORED_PRODUCT_PATTERNS = [
    r"hub\b", r"host controller", r"root hub", r"camera", r"webcam",
    r"microphone", r"audio dac", r"mystic light", r"aura led", r"rgb header",
    r"bt dongle", r"bluetooth adapter", r"bluetooth host",
]


@dataclass
class DiscoveredDevice:
    name: str
    vendor_id: int
    product_id: int
    interface_number: Optional[int] = None
    dev_path: Optional[str] = None
    is_xpad: bool = False
    suggested_category: DeviceCategory = DeviceCategory.OTHER
    suggested_icon: str = "🔋"


def _infer_category_and_icon(name: str) -> Tuple[DeviceCategory, str]:
    lower = name.lower()
    if any(k in lower for k in ("controller", "gamepad", "joystick", "8bitdo", "xbox", "dualsense", "switch")):
        return DeviceCategory.GAMEPAD, "🎮"
    if any(k in lower for k in ("headset", "headphone", "earbud", "audio", "gh02")):
        return DeviceCategory.HEADSET, "🎧"
    if any(k in lower for k in ("mouse", "mice", "optical", "viper", "deathadder", "basilisk")):
        return DeviceCategory.MOUSE, "🖱️"
    if any(k in lower for k in ("keyboard", "keychron", "royalaxe", "k552", "blackwidow", "huntsman")):
        return DeviceCategory.KEYBOARD, "⌨️"
    return DeviceCategory.OTHER, "🔋"


def get_user_profiles_dir() -> str:
    """Returns directory where user custom YAML profiles are stored."""
    config_base = (
        os.environ.get("LOCALAPPDATA")
        if sys.platform == "win32"
        else os.path.expanduser("~/.config")
    ) or os.path.expanduser("~/.config")
    d = os.path.join(config_base, "areyoulowbattery", "profiles")
    os.makedirs(d, exist_ok=True)
    return d


def is_device_ignored(name: str, vid: int) -> bool:
    if vid in IGNORED_VENDORS:
        return True
    lower = name.lower()
    for pat in IGNORED_PRODUCT_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def is_profile_already_mapped(vid: int, pid: int, profiles: List[DeviceProfile]) -> bool:
    for p in profiles:
        m = p.match
        if m.vendor_id == vid:
            if not m.product_ids and m.product_id is None:
                # VID-only generic profile
                return True
            if m.product_id == pid or (m.product_ids and pid in m.product_ids):
                return True
    return False


def scan_unmapped_devices(profiles: List[DeviceProfile]) -> List[DiscoveredDevice]:
    """
    Scans all connected USB ports and HID nodes for peripherals that do not yet have
    a matching YAML profile.
    """
    candidates: Dict[Tuple[int, int], DiscoveredDevice] = {}

    # 1. Scan /dev/hidraw nodes
    hid_nodes = enumerate_hidraw()
    for dev in hid_nodes:
        if is_device_ignored(dev.name, dev.vendor_id):
            continue
        if is_profile_already_mapped(dev.vendor_id, dev.product_id, profiles):
            continue
        key = (dev.vendor_id, dev.product_id)
        if key not in candidates:
            cat, icon = _infer_category_and_icon(dev.name)
            candidates[key] = DiscoveredDevice(
                name=dev.name,
                vendor_id=dev.vendor_id,
                product_id=dev.product_id,
                interface_number=dev.interface_number,
                dev_path=dev.dev_path,
                is_xpad=False,
                suggested_category=cat,
                suggested_icon=icon,
            )

    # 2. Scan Linux USB bus sysfs (captures xpad controllers and non-HID dongles like 8BitDo)
    if sys.platform != "win32":
        for u_dir in sorted(glob.glob("/sys/bus/usb/devices/*")):
            v_file = os.path.join(u_dir, "idVendor")
            p_file = os.path.join(u_dir, "idProduct")
            if not (os.path.exists(v_file) and os.path.exists(p_file)):
                continue
            try:
                vid = int(open(v_file).read().strip(), 16)
                pid = int(open(p_file).read().strip(), 16)
            except Exception:
                continue

            prod_file = os.path.join(u_dir, "product")
            name = (
                open(prod_file).read().strip()
                if os.path.exists(prod_file)
                else f"USB Device 0x{vid:04x}:0x{pid:04x}"
            )
            # If product string is generic (e.g. "IDLE"), try reading xpad input name
            if name.lower() in ("idle", "unknown", "") or name.startswith("USB Device"):
                for in_name in glob.glob(f"{u_dir}/*:*/input/input*/name"):
                    try:
                        n = open(in_name).read().strip()
                        if n:
                            name = n
                            break
                    except Exception:
                        pass

            if is_device_ignored(name, vid):
                continue
            if is_profile_already_mapped(vid, pid, profiles):
                continue

            key = (vid, pid)
            if key not in candidates:
                cat, icon = _infer_category_and_icon(name)
                # Check if bound to xpad driver
                is_xpad = False
                for iface_dir in glob.glob(f"{u_dir}/*:*"):
                    driver_link = os.path.join(iface_dir, "driver")
                    if os.path.exists(driver_link):
                        try:
                            if "xpad" in os.path.realpath(driver_link):
                                is_xpad = True
                                cat, icon = DeviceCategory.GAMEPAD, "🎮"
                                break
                        except Exception:
                            pass

                # If this device also has a hidraw node, link it
                matched_hid = next((h for h in hid_nodes if h.vendor_id == vid and h.product_id == pid), None)
                dev_path = matched_hid.dev_path if matched_hid else None
                interface_num = matched_hid.interface_number if matched_hid else None

                candidates[key] = DiscoveredDevice(
                    name=name,
                    vendor_id=vid,
                    product_id=pid,
                    interface_number=interface_num,
                    dev_path=dev_path,
                    is_xpad=is_xpad,
                    suggested_category=cat,
                    suggested_icon=icon,
                )

    return list(candidates.values())


def probe_device_protocol(dev: DiscoveredDevice) -> Optional[Tuple[str, int]]:
    """
    Attempts to read live battery percentage from an unmapped device using standard 2.4G protocols.
    Returns (protocol_name, battery_percentage) on success, or None if probe failed.
    """
    target_path = dev.dev_path
    if not target_path:
        # Check if a hidraw node exists now
        matching = [h for h in enumerate_hidraw() if h.vendor_id == dev.vendor_id and h.product_id == dev.product_id]
        if matching:
            target_path = matching[0].dev_path

    if not target_path:
        return None

    hid_dev = HidrawDevice(
        dev_path=target_path,
        vendor_id=dev.vendor_id,
        product_id=dev.product_id,
        interface_number=dev.interface_number or 0,
        name=dev.name,
    )

    dummy_profile = DeviceProfile(
        name=dev.name,
        category=dev.suggested_category,
        icon=dev.suggested_icon,
        match=DeviceMatch(
            vendor_id=dev.vendor_id,
            product_id=dev.product_id,
            interface_number=dev.interface_number,
        ),
        protocol="compx_v1",
    )

    # 1. Try CompX 1K / 4K
    try:
        handler = get_handler("compx_v1")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("compx_v1", st.percentage)
    except Exception:
        pass

    # 2. Try Nordic 4K/8K RF
    try:
        dummy_profile.protocol = "nordic_v1"
        handler = get_handler("nordic_v1")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("nordic_v1", st.percentage)
    except Exception:
        pass

    # 3. Try Logitech HID++ 2.0
    try:
        dummy_profile.protocol = "hidpp_v2"
        handler = get_handler("hidpp_v2")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("hidpp_v2", st.percentage)
    except Exception:
        pass

    # 4. Try Razer HyperSpeed
    try:
        dummy_profile.protocol = "razer_v1"
        handler = get_handler("razer_v1")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("razer_v1", st.percentage)
    except Exception:
        pass

    # 5. Try SteelSeries
    try:
        dummy_profile.protocol = "steelseries_v1"
        handler = get_handler("steelseries_v1")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("steelseries_v1", st.percentage)
    except Exception:
        pass

    # 6. Try Corsair Slipstream
    try:
        dummy_profile.protocol = "corsair_v1"
        handler = get_handler("corsair_v1")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("corsair_v1", st.percentage)
    except Exception:
        pass

    # 7. Try HyperX Wireless
    try:
        dummy_profile.protocol = "hyperx_v1"
        handler = get_handler("hyperx_v1")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("hyperx_v1", st.percentage)
    except Exception:
        pass

    # 8. Try Generic HID Battery
    try:
        dummy_profile.protocol = "generic_hid"
        handler = get_handler("generic_hid")
        st = handler.read_battery(hid_dev, dummy_profile)
        if st and st.is_connected and st.percentage is not None and st.percentage > 0:
            return ("generic_hid", st.percentage)
    except Exception:
        pass

    return None


def save_custom_profile(
    name: str,
    category: DeviceCategory,
    icon: str,
    vendor_id: int,
    product_id: int,
    protocol: str = "compx_v1",
    requires_bluetooth: bool = False,
    is_wired: bool = False,
) -> str:
    """
    Generates and saves a clean YAML profile into the user's config directory.
    Returns the absolute path to the saved profile.
    """
    base_dir = get_user_profiles_dir()
    cat_dir = os.path.join(base_dir, category.value)
    os.makedirs(cat_dir, exist_ok=True)

    safe_name = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    filename = f"{safe_name}_{vendor_id:04x}_{product_id:04x}.yaml"
    target_path = os.path.join(cat_dir, filename)

    data: Dict[str, Any] = {
        "name": name.strip(),
        "category": category.value,
        "icon": icon,
        "match": {
            "vendor_id": f"0x{vendor_id:04x}",
            "product_id": f"0x{product_id:04x}",
        },
        "protocol": protocol,
        "config": {},
    }

    if requires_bluetooth:
        data["config"]["requires_bluetooth"] = True
    if is_wired:
        data["config"]["is_wired"] = True

    with open(target_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return target_path
