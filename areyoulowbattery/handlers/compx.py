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
CACHE_TTL = 3600  # seconds a cached reading is still considered valid
WIRED_BASE_MAX_AGE = 300  # max age (5 min) of a pre-cable wireless reading to trust as wired charge base

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

    def _cache_path(self, profile: DeviceProfile, dev: Optional[HidrawDevice] = None) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in profile.name.lower())
        vid = profile.match.vendor_id or (dev.vendor_id if dev else 0)
        if profile.match.product_ids:
            pid = profile.match.product_ids[0]
        elif profile.match.product_id is not None:
            pid = profile.match.product_id
        else:
            pid = dev.product_id if dev else 0
        return os.path.join(CACHE_DIR, f"areyoulowbattery_{safe}_{vid:04x}_{pid:04x}.json")

    def _read_cache(self, profile: DeviceProfile, dev: Optional[HidrawDevice] = None) -> Optional[dict]:
        try:
            with open(self._cache_path(profile, dev), "r") as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                return data
        except Exception as e:
            logger.debug("CompX cache read miss for %s: %s", profile.name, e)
        return None

    def _write_cache(self, profile: DeviceProfile, data: dict, dev: Optional[HidrawDevice] = None):
        try:
            data["timestamp"] = time.time()
            with open(self._cache_path(profile, dev), "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.debug("CompX cache write failed for %s: %s", profile.name, e)

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
            time.sleep(0.02)
        return None

    _desc_cache: dict = {}

    def _get_report_descriptor(self, dev: HidrawDevice) -> bytes:
        key = (dev.dev_path, dev.vendor_id, dev.product_id)
        if key in self._desc_cache:
            return self._desc_cache[key]
        try:
            hid_name = os.path.basename(dev.dev_path)
            desc_path = f"/sys/class/hidraw/{hid_name}/device/report_descriptor"
            if os.path.exists(desc_path):
                data = open(desc_path, "rb").read()
                self._desc_cache[key] = data
                return data
        except Exception:
            pass
        return b""

    def _has_feature_08_descriptor(self, dev: HidrawDevice) -> bool:
        if sys.platform == "win32":
            return dev.vendor_id == 0x25a7 and dev.interface_number in (1, None)
        desc = self._get_report_descriptor(dev)
        return b"\x85\x08" in desc and b"\x85\x09" in desc

    def _has_vendor_03_descriptor(self, dev: HidrawDevice) -> bool:
        if sys.platform == "win32":
            return dev.vendor_id == 0x1d57 and dev.interface_number in (2, None)
        desc = self._get_report_descriptor(dev)
        return b"\x06\x00\xff" in desc and b"\x85\x03" in desc

    def _read_feature_08_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> BatteryStatus:
        """
        CompX 1K / Areson protocol (VID: 0x25a7, e.g. Ajazz, Attack Shark X3/X6, Pulsar, Lamzu, VXE):
          - Sends 17-byte Feature Report 0x08: [0x08, 0x04, 0x00 * 14, 0x49]
            (where byte 16 is checksum: (0x55 - sum(bytes[0..15])) & 0xFF = 0x49)
          - Reads 17-byte Input Report 0x09:
            [0x09, 0x04, <status>, 0x00, 0x00, <level>, <battery_pct>, <is_charging>, ..., <checksum>]
        """
        cached = self._read_cache(profile, dev)

        # On Windows, composite USB peripherals split each Application Collection into a
        # separate device handle:
        #   - UsagePage 0xFF02 owns Feature Report 0x08 (TX command)
        #   - UsagePage 0xFF01 owns Input Report 0x09 (RX battery response)
        # Windows hid.dll only buffers Input Report 0x09 on the 0xFF01 handle if that handle
        # is ALREADY open when Feature Report 0x08 is sent on the 0xFF02 handle!
        # Therefore, open all vendor sibling collections simultaneously before sending 0x08.
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

        pkt = None
        req = bytearray(17)
        req[0] = 0x08
        req[1] = 0x04
        req[16] = 0x49  # (0x55 - (0x08 + 0x04)) & 0xFF

        open_transports = []
        try:
            for candidate in candidates:
                t = HidrawTransport(candidate.dev_path, read_only=False)
                try:
                    t.open()
                    open_transports.append(t)
                except Exception as e:
                    logger.debug("Could not open candidate %s: %s", candidate.dev_path, e)

            if not open_transports:
                return BatteryStatus(0, is_connected=False, details="Failed to open HID vendor interface")

            # 1. With ALL vendor collections (including 0xFF01 RX) already open and listening,
            #    send Feature Report 0x08 across open handles (succeeds on 0xFF02 TX).
            for t in open_transports:
                try:
                    t.send_feature_report(bytes(req))
                except Exception:
                    try:
                        t.write_output_report(bytes(req))
                    except Exception:
                        pass

            # 2. Poll all open handles for the incoming Input Report 0x09 (arrives on 0xFF01 RX).
            deadline = time.time() + 0.45
            per_handle_timeout = 0.04 if len(open_transports) > 1 else 0.12
            while time.time() < deadline and pkt is None:
                for t in open_transports:
                    rx = t.read_input_report(
                        length=64,
                        timeout_sec=min(per_handle_timeout, max(0.01, deadline - time.time()))
                    )
                    if rx and len(rx) >= 8 and rx[0] == 0x09 and rx[1] == 0x04:
                        if not (len(rx) > 7 and rx[5] == 0 and rx[6] == 0 and rx[7] == 0):
                            pkt = rx
                            break
                        elif pkt is None:
                            pkt = rx

            # 3. Fallback: check GetFeature on 0x09 / 0x08 if no interrupt packet arrived
            if pkt is None and sys.platform == "win32":
                for t in open_transports:
                    for rid in (0x09, 0x08):
                        try:
                            feat = t.get_feature_report(rid, 17)
                            if feat and len(feat) >= 8 and (feat[0] in (0x08, 0x09)) and feat[1] == 0x04:
                                pkt = feat
                                break
                        except Exception:
                            pass
                    if pkt is not None:
                        break
        finally:
            for t in open_transports:
                t.close()

        if pkt is None:
            if cached and cached.get("percentage") is not None:
                age = int(time.time() - cached["timestamp"])
                return BatteryStatus(
                    cached["percentage"],
                    is_charging=cached.get("is_charging", False),
                    is_connected=True,
                    details=f"Cached ({age}s ago, mouse asleep)"
                )
            return BatteryStatus(0, is_connected=False, details="No response from dongle (timeout)")

        if len(pkt) > 7 and pkt[5] == 0 and pkt[6] == 0 and pkt[7] == 0:
            if cached and cached.get("percentage") is not None:
                age = int(time.time() - cached["timestamp"])
                return BatteryStatus(
                    cached["percentage"],
                    is_charging=cached.get("is_charging", False),
                    is_connected=True,
                    details=f"Cached ({age}s ago, mouse asleep)"
                )
            return BatteryStatus(0, is_connected=False, details="Mouse in standby/sleep mode (move mouse to wake)")

        level_bar = pkt[5]
        raw_pct = max(0, min(100, pkt[6]))
        is_charging = bool(pkt[7])
        raw_hex = pkt.hex()
        now = time.time()
        secs_per_pct = profile.config.get("charging_seconds_per_percent", 75)

        # When the mouse reaches 100% on the cable (Green LED), the charger IC cuts off
        # and reports [0x64, 0x00] (100%, not charging), but periodically pulses a brief
        # trickle top-off [0x5f, 0x01] (95%, charging) as voltage relaxes by ~10mV.
        # Once 100% cutoff is reached, latch at 100% across trickle top-off pulses.
        full_latched = bool(cached.get("full_latched", False)) if cached else False
        if raw_pct == 100 and not is_charging:
            full_latched = True
        elif full_latched and is_charging and raw_pct >= 95:
            raw_pct = 100
            is_charging = False
        else:
            full_latched = False

        # On CompX 1K / Areson mice (0x25a7, e.g. Ajazz AJ199), the MCU has no fuel-gauge IC
        # and reads battery voltage via an ADC divider. As soon as the 5V USB-C cable is plugged in
        # (is_charging == True), the charger rail pulls terminal voltage to ~4.15V (reporting 0x5f = 95%
        # or 0x0a = 10% placeholder) even if the cell was at 75%.
        # Just like on the Delux M900 Pro, lock onto the pre-charge wireless reading (charge_base)
        # and interpolate smoothly over time until the hardware charger cuts off at 100%.
        charge_start = cached.get("charge_start") if cached else None
        charge_base = cached.get("charge_base") if cached else None
        last_wireless_pct = cached.get("last_wireless_pct") if cached else None

        if is_charging:
            if charge_base is None or charge_start is None:
                if last_wireless_pct is not None and 0 < last_wireless_pct < 100:
                    charge_base = last_wireless_pct
                elif raw_pct not in (10, 95, 100) and 0 < raw_pct < 100:
                    charge_base = raw_pct
                else:
                    charge_base = {1: 45, 2: 75, 3: 90}.get(level_bar, 75)
                charge_start = now
            elapsed = max(0.0, now - charge_start)
            estimated_gain = int(elapsed // secs_per_pct)
            percentage = min(99, charge_base + estimated_gain)
        else:
            percentage = raw_pct
            last_wireless_pct = raw_pct
            charge_start = None
            charge_base = None

        eta_seconds = (
            max(60, int((100 - percentage) * secs_per_pct))
            if (is_charging and percentage < 100)
            else None
        )

        self._write_cache(profile, {
            "percentage": percentage,
            "is_charging": is_charging,
            "charge_start": charge_start,
            "charge_base": charge_base,
            "last_wireless_pct": last_wireless_pct,
            "full_latched": full_latched,
            "eta_seconds": eta_seconds,
            "raw": raw_hex,
        }, dev)
        return BatteryStatus(
            percentage,
            is_charging=is_charging,
            is_connected=True,
            details=f"Live report: {raw_hex}",
            eta_seconds=eta_seconds,
        )

    def read_battery(self, dev: HidrawDevice, profile: DeviceProfile) -> Optional[BatteryStatus]:
        cfg = profile.config
        if cfg.get("feature_report_id") == 0x08 or self._has_feature_08_descriptor(dev):
            return self._read_feature_08_battery(dev, profile)

        if not self._has_vendor_03_descriptor(dev):
            return BatteryStatus(
                0,
                is_connected=True,
                supported=False,
                details="2.4GHz receiver does not expose a CompX battery telemetry report (Bluetooth only)",
            )

        batt_offset = cfg.get("battery_offset", 4)
        status_offset = cfg.get("status_offset", 3)
        secs_per_pct = cfg.get("charging_seconds_per_percent", 75)

        query = cfg.get("query_payload")
        transport = HidrawTransport(dev.dev_path, read_only=not bool(query))
        try:
            transport.open()
        except PermissionError:
            return BatteryStatus(0, is_connected=False,
                                 details="Permission denied. Please install udev rules.")
        except OSError as e:
            return BatteryStatus(0, is_connected=False, details=f"Failed to open device: {e}")

        cached = self._read_cache(profile, dev)

        with transport:
            pkt = self._listen_for_report(transport, cfg)

            # Filter the transient 0x64 (100%) packet emitted right when the mouse
            # is lifted from the dock or initializes communication before the first ADC read.
            prev_pct = cached.get("percentage") if cached else None
            if (
                pkt is not None
                and prev_pct is not None
                and pkt[status_offset] == STATE_NORMAL
                and pkt[batt_offset] >= 100
                and prev_pct < 95
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
            cache_age = (now - cached.get("timestamp", 0)) if cached else float("inf")

            if raw_pct < 100:
                # Magnetic dock mode: the mouse itself reports the frozen pre-dock percentage
                if cached and cached.get("charge_start") and cached.get("charge_base") == raw_pct:
                    charge_start = cached["charge_start"]
                    charge_base = cached["charge_base"]
                else:
                    charge_start = now
                    charge_base = raw_pct
            elif cached and cache_age <= WIRED_BASE_MAX_AGE and cached.get("charge_base") is not None:
                # Wired USB-C mode continuing an active tracked charging session
                charge_start = cached["charge_start"]
                charge_base = cached["charge_base"]
            elif (
                cached
                and cache_age <= WIRED_BASE_MAX_AGE
                and cached.get("percentage") is not None
                and cached["percentage"] < 100
            ):
                # Wired USB-C mode right after a fresh wireless reading (< 5 min ago)
                charge_start = now
                charge_base = cached["percentage"]
            else:
                # Wired USB-C mode with no recent pre-cable reading: do not invent a percentage
                charge_start = None
                charge_base = None

            if charge_base is not None and charge_start is not None:
                elapsed = max(0.0, now - charge_start)
                estimated_gain = int(elapsed // secs_per_pct)
                percentage = min(99, charge_base + estimated_gain)
                total_needed = (100 - charge_base) * secs_per_pct
                eta_seconds = max(60, int(total_needed - elapsed))
                details = (
                    f"Live report: {raw_hex} (charging: base {charge_base}% "
                    f"+ ~{estimated_gain}% over {int(elapsed)}s)"
                )
            else:
                percentage = None
                eta_seconds = None
                details = (
                    f"Live report: {raw_hex} (charging via USB-C cable; "
                    f"initial % unknown without recent wireless reading)"
                )
        else:
            # STATE_NORMAL (0x01)
            percentage = raw_pct
            is_charging = False
            charge_start = None
            charge_base = None
            eta_seconds = None
            details = f"Live report: {raw_hex}"

        if state == STATE_FULLY_CHARGED:
            eta_seconds = None

        self._write_cache(profile, {
            "percentage": percentage,
            "is_charging": is_charging,
            "charge_start": charge_start,
            "charge_base": charge_base,
            "eta_seconds": eta_seconds,
            "raw": raw_hex,
        }, dev)

        return BatteryStatus(
            percentage,
            is_charging=is_charging,
            is_connected=True,
            details=details,
            eta_seconds=eta_seconds,
        )
