from abc import ABC, abstractmethod
from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport

class BaseProtocolHandler(ABC):
    @abstractmethod
    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        """Queries the device for its battery status."""
        pass
