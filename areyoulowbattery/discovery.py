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


# Well-known host hardware to ignore during device discovery (motherboard, hubs, webcams, audio, internal touchpads)
IGNORED_VENDORS = {
    0x1D6B,  # Linux Foundation Root Hubs
    0x05E3,  # Genesys Logic USB Hub
    0x1462,  # MSI Motherboard Mystic Light
    0x0BDA,  # Realtek Audio / Ethernet
    0x8087,  # Intel Bluetooth / Hub
    0x0A12,  # Cambridge Silicon Radio Bluetooth Host Adapter
    0x04F2,  # Chicony Webcam
    0x27C6,  # Goodix (Laptop Touchpads / Fingerprint readers)
}

IGNORED_PRODUCT_PATTERNS = [
    r"hub\b", r"host controller", r"root hub", r"camera", r"webcam",
    r"microphone", r"audio dac", r"mystic light", r"aura led", r"rgb header",
    r"bt dongle", r"bluetooth adapter", r"bluetooth host",
    r"hidi2c", r"touchpad", r"trackpad", r"converteddevice",
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
        else os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    ) or os.path.expanduser("~/.config")
    d = os.path.join(config_base, "areyoulowbattery", "profiles")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def is_device_ignored(name: str, vid: int, pid: int = 0) -> bool:
    if vid in IGNORED_VENDORS:
        return True
    # Ignore Microsoft virtual / converted devices (PID 0x0000)
    if vid == 0x045E and pid == 0x0000:
        return True
    lower = name.lower()
    for pat in IGNORED_PRODUCT_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def is_profile_already_mapped(
    vid: int,
    pid: int,
    profiles: List[DeviceProfile],
    ignored: Optional[set] = None,
    dev_name: Optional[str] = None,
) -> bool:
    from areyoulowbattery.engine import load_device_overrides
    overrides = load_device_overrides() if ignored is not None else {}
    vid_key = f"{vid:04x}:{pid:04x}"

    if ignored is not None:
        if (
            vid_key in ignored
            or f"{vid:04x}" in ignored
            or (dev_name and dev_name in ignored)
        ):
            return False  # Device is currently ignored/hidden, so it should be visible in Find Devices to restore!

    for p in profiles:
        m = p.match
        if m.vendor_id == vid:
            if not m.product_ids and m.product_id is None:
                has_match = True
            elif m.product_id == pid or (m.product_ids and pid in m.product_ids):
                has_match = True
            else:
                has_match = False

            if has_match:
                if ignored is not None:
                    ovr_name = overrides.get(p.name, {}).get("name") or overrides.get(vid_key, {}).get("name")
                    if (
                        p.name in ignored
                        or (ovr_name and ovr_name in ignored)
                        or (dev_name and dev_name in ignored)
                        or vid_key in ignored
                        or f"{vid:04x}" in ignored
                    ):
                        continue
                return True
    return False


def scan_unmapped_devices(
    profiles: List[DeviceProfile], include_ignored: bool = True
) -> List[DiscoveredDevice]:
    """
    Scans all connected USB ports and HID nodes for peripherals that do not yet have
    a matching active YAML profile. If include_ignored is True, devices that were previously
    hidden/removed are also returned so the user can easily un-hide and restore them.
    """
    from areyoulowbattery.engine import load_ignored_devices
    ignored = load_ignored_devices() if include_ignored else None
    candidates: Dict[Tuple[int, int], DiscoveredDevice] = {}

    # 1. Scan /dev/hidraw nodes
    hid_nodes = enumerate_hidraw()
    for dev in hid_nodes:
        if not include_ignored and is_device_ignored(dev.name, dev.vendor_id, dev.product_id):
            continue
        if is_profile_already_mapped(dev.vendor_id, dev.product_id, profiles, ignored=ignored, dev_name=dev.name):
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
                with open(v_file, "r") as vf, open(p_file, "r") as pf:
                    vid = int(vf.read().strip(), 16)
                    pid = int(pf.read().strip(), 16)
            except Exception:
                continue

            prod_file = os.path.join(u_dir, "product")
            name = None
            if os.path.exists(prod_file):
                try:
                    with open(prod_file, "r") as prf:
                        name = prf.read().strip()
                except Exception:
                    pass
            if not name:
                name = f"USB Device 0x{vid:04x}:0x{pid:04x}"

            # If product string is generic (e.g. "IDLE"), try reading xpad input name
            if name.lower() in ("idle", "unknown", "") or name.startswith("USB Device"):
                for in_name in glob.glob(f"{u_dir}/*:*/input/input*/name"):
                    try:
                        with open(in_name, "r") as inf:
                            n = inf.read().strip()
                        if n:
                            name = n
                            break
                    except Exception:
                        pass

            if not include_ignored and is_device_ignored(name, vid, pid):
                continue
            if is_profile_already_mapped(vid, pid, profiles, ignored=ignored, dev_name=name):
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

    # 3. Scan connected Bluetooth devices (Windows Registry/PnP, BlueZ D-Bus, UPower)
    try:
        from areyoulowbattery.engine import BatteryEngine, _parse_modalias_vid_pid
        eng = BatteryEngine()
        bt_devs = eng._poll_bluetooth_peripheral_batteries()
        for bt_name, bt_pct, bt_source, bt_modalias, bt_icon in bt_devs:
            vid, pid = _parse_modalias_vid_pid(bt_modalias) if bt_modalias else (0, 0)
            if not include_ignored and is_device_ignored(bt_name, vid or 0, pid or 0):
                continue
            if vid and pid and is_profile_already_mapped(vid, pid, profiles, ignored=ignored, dev_name=bt_name):
                continue
            key = (vid or 0, pid or (hash(bt_name) & 0xFFFF))
            if key not in candidates:
                cat, icon = _infer_category_and_icon(bt_name)
                candidates[key] = DiscoveredDevice(
                    name=bt_name,
                    vendor_id=vid or 0,
                    product_id=pid or 0,
                    interface_number=None,
                    dev_path=None,
                    is_xpad=False,
                    suggested_category=cat,
                    suggested_icon=icon,
                )
    except Exception as e:
        logger.debug("Bluetooth discovery scan failed: %s", e)

    return list(candidates.values())


# Map known vendor IDs strictly to their legitimate protocols to prevent foreign packet bombardment
VENDOR_PROTOCOL_MAP = {
    0x046D: ["hidpp_v2", "hidpp_v1"],            # Logitech Lightspeed / Unifying / Nano
    0x1532: ["razer_v1"],                         # Razer HyperSpeed
    0x1038: ["steelseries_v1"],                   # SteelSeries Quantum Wireless
    0x1B1C: ["corsair_v1"],                       # Corsair Slipstream
    0x0951: ["hyperx_v1"],                        # HyperX (Kingston)
    0x03F0: ["hyperx_v1"],                        # HyperX (HP)
    0x10D6: ["actions_v1"],                       # Actions Semi (Baseus GH02)
    0x25A7: ["compx_v1"],                         # CompX / Areson (Ajazz, Pulsar, etc.)
    0x1D57: ["compx_v1"],                         # CompX / Delux
    0x3554: ["nordic_v1"],                        # Nordic Semiconductor RF (VXE, ATK, Scyrox)
    0x1915: ["nordic_v1"],                        # Nordic Semiconductor
}


@dataclass
class ProbeResult:
    protocol: str
    percentage: int
    hid_dev: HidrawDevice
    profile: DeviceProfile


def _is_live_reading(st) -> bool:
    """A usable probe answer: connected, has a real percentage and is NOT a cached value."""
    return bool(
        st
        and st.is_connected
        and st.percentage is not None
        and st.percentage > 0
        and not str(st.details or "").lower().startswith("cached")
    )


def probe_device_protocol_live(dev: DiscoveredDevice) -> Optional[ProbeResult]:
    """
    Safely probes an unmapped peripheral using protocols appropriate for its vendor ID.
    Guarantees cross-manufacturer packet isolation (e.g. never sends Razer commands to a Logitech device).
    Only LIVE answers count: values served from the handlers' cache (device asleep) are rejected,
    so a profile is never created without confirmed live communication.
    """
    # All HID nodes of this exact device (a dongle exposes several interfaces; only one carries
    # the vendor telemetry channel). The node found at scan time is tried first.
    node_paths = []
    if dev.dev_path:
        node_paths.append((dev.dev_path, dev.interface_number))
    for h in enumerate_hidraw():
        if h.vendor_id == dev.vendor_id and h.product_id == dev.product_id:
            if all(h.dev_path != p for p, _ in node_paths):
                node_paths.append((h.dev_path, h.interface_number))

    if not node_paths:
        return None

    # Strictly restrict protocol probes to vendor-appropriate candidates
    # Unknown vendors only get the passive, read-only standard HID handler.
    # Vendor-specific (write) protocols are never guessed for unidentified hardware;
    # users can pick one manually via "Change protocol...".
    candidate_protocols = VENDOR_PROTOCOL_MAP.get(dev.vendor_id, ["generic_hid"])

    for target_path, iface in node_paths:
        hid_dev = HidrawDevice(
            dev_path=target_path,
            vendor_id=dev.vendor_id,
            product_id=dev.product_id,
            interface_number=iface or 0,
            name=dev.name,
        )
        dummy_profile = DeviceProfile(
            name=dev.name,
            category=dev.suggested_category,
            icon=dev.suggested_icon,
            match=DeviceMatch(
                vendor_id=dev.vendor_id,
                product_id=dev.product_id,
                interface_number=iface,
            ),
            protocol="generic_hid",
        )
        for proto in candidate_protocols:
            try:
                dummy_profile.protocol = proto
                handler = get_handler(proto)
                st = handler.read_battery(hid_dev, dummy_profile)
                if _is_live_reading(st):
                    return ProbeResult(proto, st.percentage, hid_dev, dummy_profile)
            except Exception:
                continue

    return None


def confirm_probe(result: ProbeResult) -> Optional[int]:
    """
    Re-reads the battery ONCE using the exact protocol and HID node that already answered
    (no re-probing of other nodes/protocols). Returns the live percentage or None.
    """
    try:
        st = get_handler(result.protocol).read_battery(result.hid_dev, result.profile)
        if _is_live_reading(st):
            return st.percentage
    except Exception:
        pass
    return None


def probe_device_protocol(dev: DiscoveredDevice) -> Optional[Tuple[str, int]]:
    """Returns (protocol_name, battery_percentage) on a live answer, or None if probe failed."""
    res = probe_device_protocol_live(dev)
    return (res.protocol, res.percentage) if res else None


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
