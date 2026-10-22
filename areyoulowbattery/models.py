from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List

class DeviceCategory(str, Enum):
    MOUSE = "mouse"
    HEADSET = "headset"
    KEYBOARD = "keyboard"
    OTHER = "other"

@dataclass
class BatteryStatus:
    percentage: Optional[int]
    is_charging: bool = False
    is_connected: bool = True
    details: Optional[str] = None
    supported: bool = True  # False when the device was found but its protocol is not mapped yet
    eta_seconds: Optional[int] = None  # Estimated seconds until 100% when charging

    def format_eta(self) -> Optional[str]:
        if not self.is_charging or not self.eta_seconds or self.eta_seconds <= 0:
            return None
        mins = max(1, round(self.eta_seconds / 60))
        if mins >= 60:
            h, m = divmod(mins, 60)
            return f"~{h}h {m}m to 100%" if m else f"~{h}h to 100%"
        return f"~{mins} min to 100%"

@dataclass
class DeviceMatch:
    vendor_id: int
    product_id: Optional[int] = None
    product_ids: List[int] = field(default_factory=list)
    interface_number: Optional[int] = None
    usage_page: Optional[int] = None

@dataclass
class DeviceProfile:
    name: str
    category: DeviceCategory
    icon: str
    match: DeviceMatch
    protocol: str
    config: Dict[str, Any] = field(default_factory=dict)
