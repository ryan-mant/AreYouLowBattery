from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice
from areyoulowbattery.handlers.base import BaseProtocolHandler


class ActionsHandler(BaseProtocolHandler):
    """
    Protocol handler for Actions Semiconductor ATS28xx series wireless audio dongles (VID: 0x10d6).
    Used by Baseus AeQur GH02 and related 2.4G wireless headsets.

    WARNING / HARDWARE FINDING:
      - Report IDs 0x55 ('U', Usage Page 0xFF90) and 0x41 ('A', Usage Page 0xFF82) on 10d6:4802
        are NOT battery telemetry channels: they are the Actions ADFU (Firmware Upgrade / Bootloader)
        entry triggers! Writing output reports to 0x55/0x41 switches the dongle into ADFU mode
        (10d6:10d6) until it is physically replugged.
      - Report IDs 0x06 and 0x07 are standard Consumer Control (volume/media) and Telephony (mute LED).
      - The 2.4GHz USB dongle does not expose battery telemetry over USB HID (Baseus only exposes
        battery on the GH02 over Bluetooth BLE/HFP to its mobile app).
    """
    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        return BatteryStatus(
            percentage=0,
            is_connected=True,
            supported=False,
            details="2.4GHz dongle has no HID battery channel (0x55/0x41 are ADFU bootloader triggers)"
        )
