import os
import json
import time
from typing import Optional
from areyoulowbattery.models import BatteryStatus, DeviceProfile
from areyoulowbattery.transport import HidrawDevice, HidrawTransport
from areyoulowbattery.handlers.base import BaseProtocolHandler

CACHE_DIR = "/dev/shm"
CACHE_TTL = 3600  # seconds a cached reading is still considered valid

# CompX / Beken event 0x40 battery state values (byte 3):
STATE_NORMAL = 0x01
STATE_FULLY_CHARGED = 0x02
STATE_CHARGING = 0x03


class CompXHandler(BaseProtocolHandler):
    """
    Protocol handler for CompX / Beken / Xenta OEM wireless mouse platforms (VID: 0x1d57).

    Protocol (validated by capture on Delux M900 Pro + CompX firmware disassembly):
      - The mouse PUSHES a 5-byte event report every ~2s on the vendor interface (iface 2):
            [0x03, <device_id>, 0x40, <state>, <battery %>]
      - state byte (offset 3):
          0x01 = Normal (on battery, live ADC percentage in byte 4)
          0x02 = Fully charged (100%, byte 4 = 0x64)
          0x03 = Charging in progress (firmware freezes byte 4 at the pre-charge value
                 until charging finishes and transitions to 0x02)
      - Because the firmware freezes byte 4 during 0x03, we interpolate charging progress
        over time (~1% per 75s for the 400mAh cell, capped at 99%) until the hardware
        reports 0x02 (100%) or returns to 0x01 (live ADC reading).
    """

    def _cache_path(self, profile: DeviceProfile) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in profile.name.lower())
        return os.path.join(CACHE_DIR, f"areyoulowbattery_{safe}.json")

    def _read_cache(self, profile: DeviceProfile) -> Optional[dict]:
        try:
            with open(self._cache_path(profile), "r") as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                return data
        except Exception:
            pass
        return None

    def _write_cache(self, profile: DeviceProfile, data: dict):
        try:
            data["timestamp"] = time.time()
            with open(self._cache_path(profile), "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _listen_for_report(self, transport: HidrawTransport, cfg: dict) -> Optional[bytes]:
        report_id = cfg.get("report_id", 0x03)
        timeout = cfg.get("listen_timeout", 4.5)

        query = cfg.get("query_payload")
        if query:
            try:
                transport.write_output_report(bytes(query + [0] * (64 - len(query))))
            except OSError:
                pass

        deadline = time.time() + timeout
        while time.time() < deadline:
            pkt = transport.read_input_report(
                length=64,
                timeout_sec=min(0.2, max(0.01, deadline - time.time()))
            )
            if pkt and pkt[0] == report_id and len(pkt) >= 5 and pkt[2] in (0x40, 0x41):
                return pkt
        return None

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        cfg = profile.config
        batt_offset = cfg.get("battery_offset", 4)
        status_offset = cfg.get("status_offset", 3)
        secs_per_pct = cfg.get("charging_seconds_per_percent", 75)

        transport = HidrawTransport(dev.dev_path)
        try:
            transport.open()
        except PermissionError:
            return BatteryStatus(0, is_connected=False,
                                 details="Permission denied. Please install udev rules.")
        except OSError as e:
            return BatteryStatus(0, is_connected=False, details=f"Failed to open device: {e}")

        cached = self._read_cache(profile)

        with transport:
            pkt = self._listen_for_report(transport, cfg)

            # Filter the transient 0x64 (100%) packet emitted right when the mouse
            # is lifted from the dock or initializes communication before the first ADC read.
            if (
                pkt is not None
                and cached
                and pkt[status_offset] == STATE_NORMAL
                and pkt[batt_offset] >= 100
                and cached.get("percentage", 0) < 95
            ):
                retry_pkt = self._listen_for_report(transport, cfg)
                if retry_pkt is not None:
                    pkt = retry_pkt

        if pkt is None:
            if cached:
                age = int(time.time() - cached["timestamp"])
                return BatteryStatus(
                    cached["percentage"],
                    is_charging=cached.get("is_charging", False),
                    is_connected=True,
                    details=f"Cached ({age}s ago, no live report)"
                )
            return BatteryStatus(0, is_connected=False, details="No report from mouse (asleep or off)")

        state = pkt[status_offset]
        raw_pct = min(pkt[batt_offset], 100)
        raw_hex = pkt.hex()
        now = time.time()

        if state == STATE_FULLY_CHARGED:
            percentage = 100
            is_charging = False
            charge_start = None
            charge_base = None
            details = f"Live report: {raw_hex} (fully charged)"
        elif state == STATE_CHARGING:
            is_charging = True
            # Keep track of when charging started and the initial frozen percentage
            if cached and cached.get("charge_start") and cached.get("charge_base") == raw_pct:
                charge_start = cached["charge_start"]
                charge_base = cached["charge_base"]
            else:
                charge_start = now
                charge_base = raw_pct

            elapsed = max(0.0, now - charge_start)
            estimated_gain = int(elapsed // secs_per_pct)
            percentage = min(99, charge_base + estimated_gain)
            details = (
                f"Live report: {raw_hex} (charging: base {charge_base}% "
                f"+ ~{estimated_gain}% over {int(elapsed)}s)"
            )
        else:
            # STATE_NORMAL (0x01)
            percentage = raw_pct
            is_charging = False
            charge_start = None
            charge_base = None
            details = f"Live report: {raw_hex}"

        self._write_cache(profile, {
            "percentage": percentage,
            "is_charging": is_charging,
            "charge_start": charge_start,
            "charge_base": charge_base,
            "raw": raw_hex,
        })

        return BatteryStatus(percentage, is_charging=is_charging, is_connected=True, details=details)
