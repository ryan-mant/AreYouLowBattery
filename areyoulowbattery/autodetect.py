"""
Zero-config device auto-detection.

Runs once per newly connected peripheral (hotplug / app start) and tries to make it
"just work" without any user action, while never sending packets blindly:

  * Vendor family known (VID in VENDOR_PROTOCOL_MAP): only that vendor's own protocols are
    probed (the very same frames the app already sends to supported devices of that vendor).
    The answer must be validated by two consistent reads before a profile is created.
  * Vendor family unknown: NOTHING is written to the device. If it looks like a wireless
    peripheral, the user gets a single "unrecognized device" notification (1 click to identify).

Every device model (VID:PID) is remembered, so it is never probed or announced twice
(failed probes - one probe each, no re-probing - are retried at most MAX_ATTEMPTS times, spaced RETRY_INTERVAL seconds apart,
because the mouse may simply have been asleep when the dongle was plugged in).
"""
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from areyoulowbattery.discovery import (
    DiscoveredDevice,
    VENDOR_PROTOCOL_MAP,
    confirm_probe,
    probe_device_protocol_live,
    save_custom_profile,
    scan_unmapped_devices,
)
from areyoulowbattery.engine import _get_config_dir, load_ignored_devices
from areyoulowbattery.logger import logger
from areyoulowbattery.models import DeviceProfile

MAX_ATTEMPTS = 3
RETRY_INTERVAL = 300.0  # seconds between probe retries for the same VID:PID
VALIDATION_DELAY = 0.4  # seconds between the two validation reads
MAX_PCT_DRIFT = 3       # max % difference tolerated between the two reads

WIRELESS_HINT = re.compile(
    r"receiver|dongle|2\.4\s?g|wireless|lightspeed|unifying|bolt|nano|hyperspeed|slipstream|\brf\b",
    re.IGNORECASE,
)

PROTOCOL_LABELS = {
    "hidpp_v2": "Logitech HID++ 2.0",
    "hidpp_v1": "Logitech HID++ 1.0",
    "razer_v1": "Razer HyperSpeed",
    "steelseries_v1": "SteelSeries Wireless",
    "corsair_v1": "Corsair Slipstream",
    "hyperx_v1": "HyperX Wireless",
    "actions_v1": "Actions Semi",
    "compx_v1": "CompX / Areson",
    "nordic_v1": "Nordic 4K/8K",
    "generic_hid": "Standard HID",
}


@dataclass
class AutoDetectEvent:
    kind: str  # "profiled" (profile auto-created) | "unrecognized" (needs 1 click)
    name: str
    vendor_id: int
    product_id: int
    protocol: Optional[str] = None
    percentage: Optional[int] = None

    @property
    def title(self) -> str:
        return "New device detected" if self.kind == "profiled" else "Unrecognized device"

    @property
    def message(self) -> str:
        if self.kind == "profiled":
            label = PROTOCOL_LABELS.get(self.protocol or "", self.protocol or "auto")
            pct = f", {self.percentage}%" if self.percentage is not None else ""
            return (
                f"{self.name} was set up automatically ({label}{pct}). "
                f"Wrong? Use the card menu to change the protocol or remove it."
            )
        return (
            f"{self.name} ({self.vendor_id:04x}:{self.product_id:04x}) looks like a wireless "
            f"device but is not supported yet. Click here to identify it."
        )


def _state_path() -> str:
    return os.path.join(_get_config_dir(), "auto_detect_state.json")


def _looks_wireless(name: str) -> bool:
    return bool(WIRELESS_HINT.search(name or ""))


class AutoDetector:
    def __init__(self, state_path: Optional[str] = None):
        self.state_path = state_path or _state_path()
        self.state: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.debug("Could not persist auto-detect state: %s", e)

    @staticmethod
    def _key(dev: DiscoveredDevice) -> str:
        return f"{dev.vendor_id:04x}:{dev.product_id:04x}"

    def _probe_validated(self, dev: DiscoveredDevice):
        """
        One vendor-protocol probe (live answers only; cached values are rejected), then ONE
        confirmation re-read on the exact node/protocol that answered. Cost of a failed attempt
        is a single probe; cost of a successful one is the probe plus one extra read.
        Returns (protocol, pct) or None.
        """
        first = probe_device_protocol_live(dev)
        if not first:
            return None
        time.sleep(VALIDATION_DELAY)
        second_pct = confirm_probe(first)
        if second_pct is None or abs(first.percentage - second_pct) > MAX_PCT_DRIFT:
            return None
        return first.protocol, second_pct

    def run(self, profiles: List[DeviceProfile]) -> List[AutoDetectEvent]:
        events: List[AutoDetectEvent] = []
        try:
            candidates = scan_unmapped_devices(profiles, include_ignored=False)
        except Exception as e:
            logger.debug("Auto-detect scan failed: %s", e)
            return events

        ignored = load_ignored_devices()
        now = time.time()
        dirty = False

        for dev in candidates:
            key = self._key(dev)
            entry = self.state.get(key)

            if dev.is_xpad or dev.name in ignored:
                if not entry:
                    self.state[key] = {"status": "skipped", "ts": now}
                    dirty = True
                continue

            if entry and entry.get("status") in ("profiled", "notified", "silent", "skipped"):
                continue

            known_vendor = dev.vendor_id in VENDOR_PROTOCOL_MAP
            attempts = int(entry.get("attempts", 0)) if entry else 0

            if known_vendor:
                if entry and (
                    attempts >= MAX_ATTEMPTS or now - float(entry.get("ts", 0)) < RETRY_INTERVAL
                ):
                    continue
                result = self._probe_validated(dev)
                if result:
                    proto, pct = result
                    save_custom_profile(
                        name=dev.name,
                        category=dev.suggested_category,
                        icon=dev.suggested_icon,
                        vendor_id=dev.vendor_id,
                        product_id=dev.product_id,
                        protocol=proto,
                    )
                    self.state[key] = {"status": "profiled", "protocol": proto, "ts": now}
                    events.append(AutoDetectEvent("profiled", dev.name, dev.vendor_id, dev.product_id, proto, pct))
                else:
                    attempts += 1
                    notify = not (entry and entry.get("announced"))
                    self.state[key] = {
                        "status": "pending" if attempts < MAX_ATTEMPTS else "notified",
                        "attempts": attempts,
                        "announced": True,
                        "ts": now,
                    }
                    if notify:
                        events.append(AutoDetectEvent("unrecognized", dev.name, dev.vendor_id, dev.product_id))
                dirty = True
            else:
                # Unknown vendor: never write anything. At most one notification per model.
                if _looks_wireless(dev.name):
                    self.state[key] = {"status": "notified", "ts": now}
                    events.append(AutoDetectEvent("unrecognized", dev.name, dev.vendor_id, dev.product_id))
                else:
                    self.state[key] = {"status": "silent", "ts": now}
                dirty = True

        if dirty:
            self._save()
        return events
