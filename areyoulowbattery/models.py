from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

class DeviceCategory(str, Enum):
    MOUSE = "mouse"
    HEADSET = "headset"
    KEYBOARD = "keyboard"
    OTHER = "other"

@dataclass
class BatteryStatus:
    percentage: int
    is_charging: bool = False
    is_connected: bool = True
    details: Optional[str] = None
    supported: bool = True  # False when the device was found but its protocol is not mapped yet

@dataclass
class DeviceMatch:
    vendor_id: int
    product_id: Optional[int] = None
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
