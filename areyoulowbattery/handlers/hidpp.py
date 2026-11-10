import os
import sys
import glob
import json
import time
import tempfile
from typing import Optional, Tuple
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger

CACHE_DIR = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
CACHE_TTL = 3600


class LogitechHidppHandler(BaseProtocolHandler):
    """
    Protocol handler for Logitech Lightspeed / Unifying / Bolt peripherals (VID: 0x046d)
    using the standard Logitech HID++ 2.0 protocol (Features 0x1004 Unified Battery and
    0x1000 Battery Level Status).

    - On Linux: Prefers the passive kernel `hidpp_battery_*` sysfs node if available.
    - On Windows (or Linux without hid-logitech-hidpp): Queries HID++ 2.0 directly over
      the vendor HID collection (Report ID 0x10 short / 0x11 long) so Logitech G HUB is
      never required.
    """

    _feature_cache: dict = {}

    def _cache_path(self, profile: DeviceProfile, dev: Optional[HidrawDevice] = None) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in profile.name.lower())
        vid = profile.match.vendor_id or (dev.vendor_id if dev else 0)
        pid = dev.product_id if dev else 0
        return os.path.join(CACHE_DIR, f"areyoulowbattery_hidpp_{safe}_{vid:04x}_{pid:04x}.json")

    def _read_cache(self, profile: DeviceProfile, dev: Optional[HidrawDevice] = None) -> Optional[dict]:
        try:
            with open(self._cache_path(profile, dev), "r") as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                return data
        except Exception as e:
            logger.debug("HID++ cache read miss for %s: %s", profile.name, e)
        return None

    def _write_cache(self, profile: DeviceProfile, data: dict, dev: Optional[HidrawDevice] = None):
        try:
            data["timestamp"] = time.time()
            with open(self._cache_path(profile, dev), "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.debug("HID++ cache write failed for %s: %s", profile.name, e)

    def _read_linux_sysfs_hidpp(self) -> Optional[BatteryStatus]:
        if sys.platform == "win32":
            return None
        for ps_path in sorted(glob.glob("/sys/class/power_supply/hidpp_battery_*")):
            cap_file = os.path.join(ps_path, "capacity")
            status_file = os.path.join(ps_path, "status")
            if not os.path.exists(cap_file):
                continue
            try:
                pct = int(open(cap_file, "r").read().strip())
                st = open(status_file, "r").read().strip().lower() if os.path.exists(status_file) else ""
                is_charging = st in ("charging", "full")
                return BatteryStatus(
                    percentage=max(0, min(100, pct)),
                    is_charging=(st == "charging"),
                    is_connected=True,
                    details=f"Kernel hidpp_battery ({os.path.basename(ps_path)})",
                )
            except Exception:
                continue
        return None

    def _transceive_hidpp(
        self, transport: HidrawTransport, dev_idx: int, feat_idx: int, func_id: int, param1: int = 0, param2: int = 0
    ) -> Optional[bytes]:
        sw_id = 0x0A
        fn_byte = ((func_id & 0x0F) << 4) | sw_id
        # Send 7-byte short HID++ report (0x10)
        pkt = bytes([0x10, dev_idx, feat_idx, fn_byte, param1, param2, 0x00])
        try:
            transport.write_output_report(pkt)
        except Exception:
            return None

        deadline = time.time() + 0.25
        while time.time() < deadline:
            rx = transport.read_input_report(
                length=64,
                timeout_sec=min(0.1, max(0.01, deadline - time.time()))
            )
            if not rx or len(rx) < 7:
                continue
            if rx[0] in (0x10, 0x11) and rx[1] == dev_idx and rx[2] == feat_idx and (rx[3] & 0x0F) == sw_id:
                return rx
        return None

    def _discover_battery_feature(self, transport: HidrawTransport) -> Optional[Tuple[int, int, int]]:
        # Device index: 0x01 (Lightspeed / Unifying slot 1) or 0xFF (direct wired / single receiver)
        for dev_idx in (0x01, 0xFF, 0x02):
            for feat_id in (0x1004, 0x1000):
                rx = self._transceive_hidpp(
                    transport,
                    dev_idx=dev_idx,
                    feat_idx=0x00,
                    func_id=0x00,
                    param1=(feat_id >> 8) & 0xFF,
                    param2=feat_id & 0xFF,
                )
                if rx and rx[4] != 0x00:
                    return (dev_idx, rx[4], feat_id)
        return None

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        sysfs_status = self._read_linux_sysfs_hidpp()
        if sysfs_status is not None:
            return sysfs_status

        if sys.platform == "win32" and dev.usage_page is not None and dev.usage_page < 0xFF00:
            return None

        cached = self._read_cache(profile, dev)
        transport = HidrawTransport(dev.dev_path, read_only=False)
        try:
            transport.open()
        except Exception:
            return None

        with transport:
            info = self._feature_cache.get(dev.dev_path)
            if not info:
                info = self._discover_battery_feature(transport)
                if info:
                    self._feature_cache[dev.dev_path] = info

            if not info:
                if cached and cached.get("percentage") is not None:
                    age = int(time.time() - cached["timestamp"])
                    return BatteryStatus(
                        cached["percentage"],
                        is_charging=cached.get("is_charging", False),
                        is_connected=True,
                        details=f"Cached ({age}s ago, device asleep)",
                    )
                return None

            dev_idx, feat_idx, feat_id = info
            # Both 0x1004 (get_status = func 1) and 0x1000 (get_battery_level_status = func 0)
            func_id = 0x01 if feat_id == 0x1004 else 0x00
            rx = self._transceive_hidpp(transport, dev_idx, feat_idx, func_id)
            if not rx:
                self._feature_cache.pop(dev.dev_path, None)
                if cached and cached.get("percentage") is not None:
                    age = int(time.time() - cached["timestamp"])
                    return BatteryStatus(
                        cached["percentage"],
                        is_charging=cached.get("is_charging", False),
                        is_connected=True,
                        details=f"Cached ({age}s ago, device asleep)",
                    )
                return BatteryStatus(0, is_connected=False, details="Logitech device asleep or off")

            pct = max(0, min(100, rx[4]))
            if feat_id == 0x1004:
                # 0x1004 Unified Battery: rx[4]=SoC%, rx[6]=charging_status (0=discharging, 1=charging, 2=slow, 3=full)
                chg_byte = rx[6] if len(rx) > 6 else rx[5]
                is_charging = chg_byte in (1, 2)
            else:
                # 0x1000 Battery Unified Level: rx[4]=SoC%, rx[6]=status (0=discharging, 1..4=charging)
                chg_byte = rx[6] if len(rx) > 6 else 0
                is_charging = chg_byte in (1, 2, 3)

            raw_hex = rx.hex()
            self._write_cache(profile, {
                "percentage": pct,
                "is_charging": is_charging,
                "raw": raw_hex,
            }, dev)
            return BatteryStatus(
                percentage=pct,
                is_charging=is_charging,
                is_connected=True,
                details=f"HID++ 2.0 (0x{feat_id:04x}): {raw_hex}",
            )
