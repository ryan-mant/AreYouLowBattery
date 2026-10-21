import os
import glob
import yaml
from typing import List, Optional
from areyoulowbattery.models import DeviceProfile, DeviceMatch, DeviceCategory

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
            
        pid = parse_int_or_hex(match_data.get("product_id"))
        iface = match_data.get("interface_number")
        if iface is not None:
            iface = int(iface)
            
        match = DeviceMatch(
            vendor_id=vid,
            product_id=pid,
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
    if profiles_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profiles_dir = os.path.join(base_dir, "profiles")
        
    profiles = []
    for yaml_path in glob.glob(f"{profiles_dir}/**/*.yaml", recursive=True):
        p = load_profile(yaml_path)
        if p:
            profiles.append(p)
    return profiles
