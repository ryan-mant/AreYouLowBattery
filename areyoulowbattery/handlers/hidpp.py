import os
import sys
import glob
import json
import time
import tempfile
from typing import Optional, Tuple
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport, enumerate_hidraw
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.logger import logger

CACHE_DIR = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
CACHE_TTL = 3600

LOGITECH_WIRED_PIDS = {
    0xc083,  # G403 HERO / Prodigy Wired
    0xc084,  # G203 Prodigy Wired
    0xc092,  # G203 Lightsync Wired
    0xc08b,  # G502 HERO Wired
    0xc07d,  # G502 Proteus Spectrum Wired
    0xc094,  # G502 HERO SE Wired
    0xc087,  # G Pro Gaming Mouse Wired
    0xc08c,  # G402 Hyperion Fury Wired
    0xc07e,  # G302 Daedalus Prime Wired
    0xc07f,  # G303 Daedalus Apex Wired
    0xc069,  # M500 Corded Mouse
    0xc016, 0xc01a, 0xc077,  # M100 / B100 corded
    0xc332,  # G213 Prodigy Keyboard
    0xc33a,  # G413 Carbon Mechanical Keyboard
    0xc33f,  # G512 Mechanical Gaming Keyboard
    0xc33c,  # G513 Mechanical Gaming Keyboard
    0xc330,  # G810 Orion Spectrum Keyboard
    0xc335,  # G910 Orion Spectrum Keyboard
}


def _mv_to_percentage(mv: int) -> int:
    """Maps Logitech Li-Po battery millivolts (3500mV..4180mV) to 0..100%."""
    if mv >= 4180:
        return 100
    if mv <= 3500:
        return 0
    # Piecewise Li-Po discharge curve matching Logitech G HUB
    table = [
        (4180, 100), (4100, 90), (4020, 80), (3950, 70),
        (3880, 60), (3820, 50), (3770, 40), (3730, 30),
        (3680, 20), (3600, 10), (3500, 0),
    ]
    for i in range(len(table) - 1):
        v_hi, p_hi = table[i]
        v_lo, p_lo = table[i + 1]
        if mv >= v_lo:
            ratio = (mv - v_lo) / float(v_hi - v_lo)
            return int(round(p_lo + ratio * (p_hi - p_lo)))
    return 0


class LogitechHidppHandler(BaseProtocolHandler):
    """
    Protocol handler for Logitech Lightspeed / PRO / Unifying / Bolt peripherals (VID: 0x046d)
    using Logitech HID++ 2.0 (Features 0x1004 Unified Battery, 0x1000 Battery Level Status,
    and 0x1001 Battery Voltage).

    Supports both Short (0x10, 7-byte) and Long (0x11, 20-byte) HID++ reports across
    UsagePage 0xFF00 and 0xFF43 (used by G Pro X Superlight 1 & 2 Lightspeed receivers).
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
        # Try 7-byte short HID++ report (0x10) first, then 20-byte long HID++ report (0x11)
        # (G Pro X Superlight 2 4K/8K receiver often only accepts 0x11 long reports on its vendor collection)
        short_pkt = bytes([0x10, dev_idx, feat_idx, fn_byte, param1, param2, 0x00])
        long_pkt = bytes([0x11, dev_idx, feat_idx, fn_byte, param1, param2] + [0x00] * 14)

        for pkt in (short_pkt, long_pkt):
            try:
                transport.write_output_report(pkt)
            except Exception as e:
                logger.debug("HID++ write report 0x%02x failed: %s", pkt[0], e)
                continue

            deadline = time.time() + 0.18
            while time.time() < deadline:
                rx = transport.read_input_report(
                    length=64,
                    timeout_sec=min(0.08, max(0.01, deadline - time.time()))
                )
                if not rx or len(rx) < 7:
                    continue
                # Ignore HID++ 1.0 / 2.0 error responses (0x8F / 0xFF)
                if rx[2] in (0x8F, 0xFF):
                    break
                if rx[0] in (0x10, 0x11) and rx[1] == dev_idx and rx[2] == feat_idx and (rx[3] & 0x0F) == sw_id:
                    return rx
        return None

    def _discover_battery_feature(self, transport: HidrawTransport, is_receiver: bool = False) -> Optional[Tuple[int, int, int]]:
        # Device index: 0x01 (Lightspeed / Unifying slot 1), 0xFF (direct wired / receiver), 0x02 (slot 2)
        wired_responded = False
        for dev_idx in (0x01, 0xFF, 0x02, 0x00):
            for feat_id in (0x1004, 0x1000, 0x1001):
                rx = self._transceive_hidpp(
                    transport,
                    dev_idx=dev_idx,
                    feat_idx=0x00,
                    func_id=0x00,
                    param1=(feat_id >> 8) & 0xFF,
                    param2=feat_id & 0xFF,
                )
                if rx:
                    if dev_idx == 0xFF:
                        wired_responded = True
                    if rx[4] != 0x00:
                        return (dev_idx, rx[4], feat_id)
        if wired_responded and not is_receiver:
            # Active wired device responded to HID++ root but lacks battery features (wired mouse/keyboard)
            return (0xFF, 0, 0)
        return None

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        # Fast path: known corded / wired Logitech peripherals without battery
        if dev.product_id in LOGITECH_WIRED_PIDS or profile.config.get("is_wired"):
            return BatteryStatus(
                percentage=None,
                is_charging=False,
                is_connected=True,
                is_wired=True,
                details=f"Wired Logitech device (PID 0x{dev.product_id:04x}, continuous USB power)",
            )

        sysfs_status = self._read_linux_sysfs_hidpp()
        if sysfs_status is not None:
            return sysfs_status

        if sys.platform == "win32" and dev.usage_page is not None and dev.usage_page < 0xFF00:
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

        is_receiver = "receiver" in (dev.name or "").lower()

        for candidate in candidates:
            transport = HidrawTransport(candidate.dev_path, read_only=False)
            try:
                transport.open()
            except Exception as e:
                logger.debug("Could not open Logitech candidate %s: %s", candidate.dev_path, e)
                continue

            with transport:
                info = self._feature_cache.get(candidate.dev_path)
                if not info:
                    info = self._discover_battery_feature(transport, is_receiver=is_receiver)
                    if info:
                        self._feature_cache[candidate.dev_path] = info

                if not info:
                    continue

                dev_idx, feat_idx, feat_id = info
                if dev_idx == 0xFF and feat_id == 0:
                    # Identified as wired Logitech device with continuous power
                    return BatteryStatus(
                        percentage=None,
                        is_charging=False,
                        is_connected=True,
                        is_wired=True,
                        details=f"Wired Logitech peripheral (PID 0x{candidate.product_id:04x}, continuous USB power)",
                    )
                # 0x1004 (Unified Battery: get_status = func 1), 0x1000 / 0x1001 (func 0)
                func_id = 0x01 if feat_id == 0x1004 else 0x00
                rx = self._transceive_hidpp(transport, dev_idx, feat_idx, func_id)
                if not rx:
                    self._feature_cache.pop(candidate.dev_path, None)
                    continue

                if feat_id == 0x1004:
                    # 0x1004 Unified Battery: rx[4]=SoC%, rx[6]=charging_status (0=discharging, 1=charging, 2=slow, 3=full)
                    pct = max(0, min(100, rx[4]))
                    chg_byte = rx[6] if len(rx) > 6 else rx[5]
                    is_charging = chg_byte in (1, 2)
                elif feat_id == 0x1000:
                    # 0x1000 Battery Unified Level: rx[4]=SoC%, rx[6]=status (0=discharging, 1..4=charging)
                    pct = max(0, min(100, rx[4]))
                    chg_byte = rx[6] if len(rx) > 6 else 0
                    is_charging = chg_byte in (1, 2, 3)
                else:
                    # 0x1001 Battery Voltage: rx[4..5]=mV big-endian, rx[6]=flags (0x80=charging)
                    mv = (rx[4] << 8) | rx[5]
                    pct = _mv_to_percentage(mv)
                    flags = rx[6] if len(rx) > 6 else 0
                    is_charging = bool(flags & 0x80) or (flags in (1, 2))

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

        if cached and cached.get("percentage") is not None:
            age = int(time.time() - cached["timestamp"])
            return BatteryStatus(
                cached["percentage"],
                is_charging=cached.get("is_charging", False),
                is_connected=True,
                details=f"Cached ({age}s ago, device asleep)",
            )
        return BatteryStatus(0, is_connected=False, details="Logitech device asleep or off")
