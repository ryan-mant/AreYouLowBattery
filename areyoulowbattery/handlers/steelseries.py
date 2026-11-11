from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger


class SteelSeriesHandler(BaseProtocolHandler):
    """
    Protocol handler for SteelSeries wireless peripherals (VID: 0x1038, e.g.
    Aerox 3/5/9 Wireless, Rival 3/650 Wireless, Arctis 7 / 7+ / 9 / Nova 7).
    """

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        if profile.config.get("requires_bluetooth"):
            return BatteryStatus(
                percentage=None,
                is_connected=True,
                supported=True,
                requires_bluetooth=True,
                details="Requires Bluetooth for battery telemetry",
            )

        # 1. Try headset telemetry probe (0x06, 0x18 command)
        try:
            with HidrawTransport(dev.dev_path) as tp:
                cmd = bytearray(64)
                cmd[0] = 0x06
                cmd[1] = 0x18
                tp.write_output_report(bytes(cmd))
                resp = tp.read_input_report(length=64, timeout_sec=0.25)
                if resp and len(resp) >= 3 and resp[0] == 0x06:
                    pct = resp[2]
                    if 0 <= pct <= 100:
                        is_charging = bool(resp[3]) if len(resp) > 3 else False
                        return BatteryStatus(
                            percentage=pct,
                            is_charging=is_charging,
                            is_connected=True,
                            supported=True,
                            details=f"SteelSeries Headset ({pct}%)",
                        )
        except Exception:
            pass

        # 2. Try mouse telemetry probe (Report ID 0x90 or 0x92)
        try:
            with HidrawTransport(dev.dev_path) as tp:
                cmd = bytearray(64)
                cmd[0] = 0x90
                tp.write_output_report(bytes(cmd))
                resp = tp.read_input_report(length=64, timeout_sec=0.25)
                if resp and len(resp) >= 4 and resp[0] in (0x90, 0x92):
                    pct = resp[2]
                    if 0 <= pct <= 100:
                        return BatteryStatus(
                            percentage=pct,
                            is_connected=True,
                            supported=True,
                            details=f"SteelSeries Mouse ({pct}%)",
                        )
        except Exception as e:
            logger.debug("SteelSeries probe failed: %s", e)

        return None
