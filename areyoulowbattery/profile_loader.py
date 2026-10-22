import os
import sys
import glob
import yaml
from typing import List, Optional
from areyoulowbattery.models import DeviceProfile, DeviceMatch, DeviceCategory


def get_resource_dir() -> str:
    """Returns base directory for bundled resources (supports PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def parse_int_or_hex(val) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        val = val.strip()
        if val.startswith("0x") or val.startswith("0X"):
            return int(val, 16)
        return int(val)
    return None

def load_profile(file_path: str) -> Optional[DeviceProfile]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        match_data = data.get("match", {})
        vid = parse_int_or_hex(match_data.get("vendor_id"))
        if vid is None:
            return None
            
        raw_pid = match_data.get("product_id")
        pids = []
        pid = None
        if isinstance(raw_pid, list):
            pids = [p for p in (parse_int_or_hex(x) for x in raw_pid) if p is not None]
        else:
            pid = parse_int_or_hex(raw_pid)
            if pid is not None:
                pids = [pid]

        iface = match_data.get("interface_number")
        if iface is not None:
            iface = int(iface)
            
        match = DeviceMatch(
            vendor_id=vid,
            product_id=pid,
            product_ids=pids,
            interface_number=iface,
            usage_page=parse_int_or_hex(match_data.get("usage_page"))
        )
        
        category = DeviceCategory(data.get("category", "other"))
        
        return DeviceProfile(
            name=data.get("name", "Unknown Device"),
            category=category,
            icon=data.get("icon", "🔋"),
            match=match,
            protocol=data.get("protocol", "generic"),
            config=data.get("config", {})
        )
    except Exception as e:
        print(f"Error loading profile {file_path}: {e}")
        return None

def load_all_profiles(profiles_dir: Optional[str] = None) -> List[DeviceProfile]:
    search_dirs = []
    if profiles_dir is not None:
        search_dirs.append(profiles_dir)
    else:
        # User custom profiles override/extend bundled profiles
        user_profiles = os.path.expanduser("~/.config/areyoulowbattery/profiles")
        if os.path.isdir(user_profiles):
            search_dirs.append(user_profiles)
        search_dirs.append(os.path.join(get_resource_dir(), "profiles"))

    profiles = []
    for d in search_dirs:
        for yaml_path in sorted(glob.glob(f"{d}/**/*.yaml", recursive=True)):
            p = load_profile(yaml_path)
            if p:
                profiles.append(p)
    return profiles
