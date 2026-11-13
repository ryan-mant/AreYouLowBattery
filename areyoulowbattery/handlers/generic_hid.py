from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger


class GenericHidHandler(BaseProtocolHandler):
    """
    Protocol handler for standard USB HID Power Device / Battery System (Usage Page 0x85).
    Reads input/feature reports from compliant peripherals.
    """

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        if profile.config.get("is_wired"):
            return BatteryStatus(
                percentage=100,
                is_connected=True,
                supported=True,
                is_wired=True,
                details="Wired USB (Continuous power)",
            )

        if profile.config.get("requires_bluetooth"):
            return BatteryStatus(
                percentage=None,
                is_connected=True,
                supported=True,
                requires_bluetooth=True,
                details="Requires Bluetooth for battery telemetry",
            )

        try:
            with HidrawTransport(dev.dev_path, read_only=True) as tp:
                data = tp.read_input_report(length=64, timeout_sec=0.25)
                if data and len(data) >= 2:
                    val = data[1]
                    if 0 < val <= 100:
                        return BatteryStatus(
                            percentage=val,
                            is_connected=True,
                            supported=True,
                            details=f"Standard HID ({val}%)",
                        )
        except Exception as e:
            logger.debug("Generic HID probe failed: %s", e)

        return None
