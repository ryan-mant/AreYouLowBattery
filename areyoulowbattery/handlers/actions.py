from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice
from areyoulowbattery.handlers.base import BaseProtocolHandler


class ActionsHandler(BaseProtocolHandler):
    """
    Protocol handler for Actions Semiconductor ATS28xx series wireless audio dongles (VID: 0x10d6).
    Used by Baseus AeQur GH02 and related 2.4G wireless headsets.

    STATUS: protocol NOT mapped yet. Probing showed the dongle only echoes back the
    feature reports we send (0x55 / 0x41) and pushes no passive reports, so no battery
    field has been identified. Until a capture proves otherwise, this handler reports
    the device as unsupported instead of returning a fake value.
    """
    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        return BatteryStatus(
            percentage=0,
            is_connected=True,
            supported=False,
            details="Dongle detected, battery protocol not mapped yet"
        )
