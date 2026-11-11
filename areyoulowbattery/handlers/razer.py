import time
from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger


class RazerHandler(BaseProtocolHandler):
    """
    Protocol handler for Razer HyperSpeed wireless peripherals (VID: 0x1532, e.g.
    Viper Ultimate/V2/V3 Pro, DeathAdder V2/V3 Pro, Basilisk Ultimate/V3 Pro,
    Naga Pro, BlackWidow V3 Pro).

    Uses standard Razer 90-byte vendor reports (command class 0x07 = Battery).
    """

    @staticmethod
    def _create_razer_report(command_class: int, command_id: int, data_size: int = 2) -> bytes:
        buf = bytearray(90)
        buf[0] = 0x00  # Status
        buf[1] = 0x1F  # Transaction ID
        buf[2] = 0x00  # Remaining packets MSB
        buf[3] = 0x00  # Remaining packets LSB
        buf[4] = 0x00  # Protocol type
        buf[5] = data_size
        buf[6] = command_class
        buf[7] = command_id

        checksum = 0
        for b in buf[2:88]:
            checksum ^= b
        buf[88] = checksum
        buf[89] = 0x00
        return bytes(buf)

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        req = self._create_razer_report(command_class=0x07, command_id=0x80)
        try:
            with HidrawTransport(dev.dev_path) as tp:
                # Prepend report ID 0x00 for standard HID raw write (91 bytes total)
                payload = b"\x00" + req
                tp.write_output_report(payload)
                resp = tp.read_input_report(length=90, timeout_sec=0.3)
                if not resp or len(resp) < 10:
                    return None

                offset = 1 if len(resp) == 91 else 0
                cmd_class = resp[offset + 6]
                cmd_id = resp[offset + 7]
                if cmd_class != 0x07 or cmd_id != 0x80:
                    return None

                raw_val = resp[offset + 9]
                if raw_val > 100:
                    pct = int(round(raw_val * 100.0 / 255.0))
                else:
                    pct = raw_val

                pct = max(0, min(100, pct))
                return BatteryStatus(
                    percentage=pct,
                    is_connected=True,
                    supported=True,
                    details=f"Razer HyperSpeed ({pct}%)",
                )
        except Exception as e:
            logger.debug("Razer telemetry probe failed: %s", e)
            return None
