from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger


class CorsairHandler(BaseProtocolHandler):
    """
    Protocol handler for Corsair Slipstream wireless peripherals (VID: 0x1B1C, e.g.
    Dark Core RGB Pro, Katar Pro Wireless, Ironclaw RGB, Harpoon RGB Wireless,
    Virtuoso RGB Wireless, Void RGB Elite, HS70/HS80 Wireless).
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

        # 1. Try Corsair Slipstream query command [0x08, 0x01, 0x03]
        try:
            with HidrawTransport(dev.dev_path) as tp:
                cmd = bytearray(64)
                cmd[0] = 0x08
                cmd[1] = 0x01
                cmd[2] = 0x03
                tp.write_output_report(bytes(cmd))
                resp = tp.read_input_report(length=64, timeout_sec=0.25)
                if resp and len(resp) >= 5 and resp[0] == 0x08:
                    pct = resp[3]
                    if 0 <= pct <= 100:
                        is_charging = bool(resp[4] == 1) if len(resp) > 4 else False
                        return BatteryStatus(
                            percentage=pct,
                            is_charging=is_charging,
                            is_connected=True,
                            supported=True,
                            details=f"Corsair Slipstream ({pct}%)",
                        )
        except Exception:
            pass

        # 2. Try Corsair Void/HS series feature report [0x0E]
        try:
            with HidrawTransport(dev.dev_path) as tp:
                cmd = bytearray(64)
                cmd[0] = 0x0E
                tp.write_output_report(bytes(cmd))
                resp = tp.read_input_report(length=64, timeout_sec=0.25)
                if resp and len(resp) >= 4 and resp[0] == 0x0E:
                    pct = resp[2]
                    if 0 <= pct <= 100:
                        return BatteryStatus(
                            percentage=pct,
                            is_connected=True,
                            supported=True,
                            details=f"Corsair Headset ({pct}%)",
                        )
        except Exception as e:
            logger.debug("Corsair probe failed: %s", e)

        return None
