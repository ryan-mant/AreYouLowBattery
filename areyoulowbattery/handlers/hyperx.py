from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger


class HyperXHandler(BaseProtocolHandler):
    """
    Protocol handler for HyperX wireless peripherals (VID: 0x0951 Kingston / 0x03F0 HP, e.g.
    Cloud Flight, Cloud II Wireless, Cloud Alpha Wireless, Cloud III Wireless,
    Pulsefire Haste Wireless).
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

        # 1. Try Cloud II / Alpha / Flight query command [0x21, 0xBB]
        try:
            with HidrawTransport(dev.dev_path) as tp:
                cmd = bytearray([0x21, 0xBB, 0x0B, 0x00, 0x00, 0x00, 0x00, 0x00])
                tp.write_output_report(bytes(cmd))
                resp = tp.read_input_report(length=32, timeout_sec=0.25)
                if resp and len(resp) >= 5 and resp[0] == 0x21:
                    pct = resp[3]
                    if 0 <= pct <= 100:
                        is_charging = bool(resp[4] == 1) if len(resp) > 4 else False
                        return BatteryStatus(
                            percentage=pct,
                            is_charging=is_charging,
                            is_connected=True,
                            supported=True,
                            details=f"HyperX Wireless ({pct}%)",
                        )
        except Exception:
            pass

        # 2. Try Pulsefire mouse / headset command [0x06, 0x00]
        try:
            with HidrawTransport(dev.dev_path) as tp:
                cmd = bytearray(64)
                cmd[0] = 0x06
                tp.write_output_report(bytes(cmd))
                resp = tp.read_input_report(length=64, timeout_sec=0.25)
                if resp and len(resp) >= 4 and resp[0] == 0x06:
                    pct = resp[2]
                    if 0 <= pct <= 100:
                        return BatteryStatus(
                            percentage=pct,
                            is_connected=True,
                            supported=True,
                            details=f"HyperX ({pct}%)",
                        )
        except Exception as e:
            logger.debug("HyperX probe failed: %s", e)

        return None
