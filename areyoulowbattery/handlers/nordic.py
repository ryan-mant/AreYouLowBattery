import os
import sys
import json
import time
import tempfile
from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport, enumerate_hidraw
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger

CACHE_DIR = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
CACHE_TTL = 3600


class NordicHandler(BaseProtocolHandler):
    """
    Protocol handler for Nordic nRF52840 / Compx 4K & 8K high-polling wireless mice
    (VID: 0x3554 / 0x1915, e.g. VXE R1 Pro / Mad R, ATK F1/X1, Scyrox V8, Lamzu 4K,
    Zaopin Z1 Pro / Z2, Ninjutso Sora 4K, Darmoshark M3 4K).

    Queries ONLY the vendor telemetry collection (Report ID 0x08 / 0x09) and never
    touches the high-speed mouse motion endpoint.
    """

    _desc_cache: dict = {}

    def _cache_path(self, profile: DeviceProfile, dev: Optional[HidrawDevice] = None) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in profile.name.lower())
        vid = profile.match.vendor_id or (dev.vendor_id if dev else 0)
        pid = dev.product_id if dev else 0
        return os.path.join(CACHE_DIR, f"areyoulowbattery_nordic_{safe}_{vid:04x}_{pid:04x}.json")

    def _read_cache(self, profile: DeviceProfile, dev: Optional[HidrawDevice] = None) -> Optional[dict]:
        try:
            with open(self._cache_path(profile, dev), "r") as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                return data
        except Exception as e:
            logger.debug("Nordic cache read miss for %s: %s", profile.name, e)
        return None

    def _write_cache(self, profile: DeviceProfile, data: dict, dev: Optional[HidrawDevice] = None):
        try:
            data["timestamp"] = time.time()
            with open(self._cache_path(profile, dev), "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.debug("Nordic cache write failed for %s: %s", profile.name, e)

    def _has_vendor_descriptor(self, dev: HidrawDevice) -> bool:
        if sys.platform == "win32":
            if dev.usage_page is not None:
                return dev.usage_page >= 0xFF00
            return dev.interface_number in (1, 2, None)

        key = (dev.dev_path, dev.vendor_id, dev.product_id)
        if key not in self._desc_cache:
            try:
                hid_name = os.path.basename(dev.dev_path)
                desc_path = f"/sys/class/hidraw/{hid_name}/device/report_descriptor"
                if os.path.exists(desc_path):
                    self._desc_cache[key] = open(desc_path, "rb").read()
                else:
                    self._desc_cache[key] = b""
            except Exception:
                self._desc_cache[key] = b""
        desc = self._desc_cache[key]
        return b"\x85\x08" in desc or b"\x85\x09" in desc or b"\x06\x00\xff" in desc

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        if not self._has_vendor_descriptor(dev):
            return None

        cached = self._read_cache(profile, dev)
        candidates = [dev]
        if sys.platform == "win32":
            all_devs = enumerate_hidraw()
            siblings = [
                d for d in all_devs
                if (
                    d.vendor_id == dev.vendor_id
                    and d.product_id == dev.product_id
                    and d.dev_path != dev.dev_path
                    and (d.usage_page is None or d.usage_page >= 0xFF00)
                )
            ]
            candidates.extend(siblings)

        # Standard 17-byte Compx/Nordic 4K/8K battery query: [0x08, 0x04, 0x00..., 0x49]
        req = bytearray(17)
        req[0] = 0x08
        req[1] = 0x04
        req[16] = 0x49

        pkt = None
        open_transports = []
        try:
            for candidate in candidates:
                t = HidrawTransport(candidate.dev_path, read_only=False)
                try:
                    t.open()
                    open_transports.append(t)
                except Exception as e:
                    logger.debug("Could not open Nordic candidate %s: %s", candidate.dev_path, e)

            if not open_transports:
                return BatteryStatus(0, is_connected=False, details="Failed to open HID vendor interface")

            for t in open_transports:
                try:
                    t.send_feature_report(bytes(req))
                except Exception:
                    try:
                        t.write_output_report(bytes(req))
                    except Exception:
                        pass

            deadline = time.time() + 0.45
            per_handle_timeout = 0.04 if len(open_transports) > 1 else 0.12
            while time.time() < deadline and pkt is None:
                for t in open_transports:
                    rx = t.read_input_report(
                        length=64,
                        timeout_sec=min(per_handle_timeout, max(0.01, deadline - time.time()))
                    )
                    if rx and len(rx) >= 8 and rx[0] in (0x08, 0x09) and rx[1] in (0x04, 0x07):
                        if not (rx[5] == 0 and rx[6] == 0 and rx[7] == 0):
                            pkt = rx
                            break
                        elif pkt is None:
                            pkt = rx
        finally:
            for t in open_transports:
                t.close()

        if pkt is None or (len(pkt) > 7 and pkt[5] == 0 and pkt[6] == 0 and pkt[7] == 0):
            if cached and cached.get("percentage") is not None:
                age = int(time.time() - cached["timestamp"])
                return BatteryStatus(
                    cached["percentage"],
                    is_charging=cached.get("is_charging", False),
                    is_connected=True,
                    details=f"Cached ({age}s ago, mouse asleep)"
                )
            return BatteryStatus(0, is_connected=False, details="Mouse in sleep mode or turned off")

        raw_pct = max(0, min(100, pkt[6]))
        is_charging = bool(pkt[7])
        raw_hex = pkt.hex()
        secs_per_pct = profile.config.get("charging_seconds_per_percent", 75)
        eta_seconds = (
            max(60, int((100 - raw_pct) * secs_per_pct))
            if (is_charging and raw_pct < 100)
            else None
        )

        self._write_cache(profile, {
            "percentage": raw_pct,
            "is_charging": is_charging,
            "eta_seconds": eta_seconds,
            "raw": raw_hex,
        }, dev)
        return BatteryStatus(
            raw_pct,
            is_charging=is_charging,
            is_connected=True,
            details=f"Live report: {raw_hex}",
            eta_seconds=eta_seconds,
        )
