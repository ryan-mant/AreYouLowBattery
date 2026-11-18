import os
import re
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open

from areyoulowbattery.models import DeviceProfile, DeviceMatch, DeviceCategory, BatteryStatus
from areyoulowbattery.profile_loader import load_all_profiles
from areyoulowbattery.handlers import HANDLER_REGISTRY, get_handler
from areyoulowbattery.handlers.compx import CompXHandler
from areyoulowbattery.handlers.nordic import NordicHandler
from areyoulowbattery.handlers.hidpp import LogitechHidppHandler
from areyoulowbattery.handlers.yjx import YjxHandler, QUERY_PAYLOAD
from areyoulowbattery.handlers.gamesir import GamesirHandler, WAKE_PAYLOAD
from areyoulowbattery.transport import HidrawDevice


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent_features = []
        self.sent_outputs = []

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def send_feature_report(self, data: bytes):
        self.sent_features.append(data)

    def write_output_report(self, data: bytes):
        self.sent_outputs.append(data)

    def read_input_report(self, length: int = 64, timeout_sec: float = 0.1):
        if self.responses:
            return self.responses.pop(0)
        return None


# YJX-CHIP hardware capture fixtures (64-byte vendor reports, no report ID)
YJX_RESPONSE_62 = bytes.fromhex("aa30a50b0a0101013e00" + "00" * 55)
YJX_RESPONSE_46_CHARGING = bytes.fromhex("aa30a53c0a0101012e01" + "00" * 55)
YJX_RESPONSE_INVALID = bytes.fromhex("aa30a50b0a010101ff00" + "00" * 55)
YJX_HEARTBEAT_62 = bytes.fromhex("aafaaec80a010101013e" + "00" * 55)

# Charging-over-cable captures: byte 8 = live level, byte 9 = charging flag.
# The 2.4GHz receiver replays its last RF frame (43%, flag 0x00) while on the cable,
# whereas the wired node (0xa8a4) reports the real, rising level with flag 0x01.
YJX_RECEIVER_FROZEN_43 = bytes.fromhex("aa30a50b0a0101012b00" + "00" * 55)
YJX_CABLE_LIVE_87_CHARGING = bytes.fromhex("aa30a50b0a0101015701" + "00" * 55)

# GameSir Cyclone 2 (3537:100b) hardware capture fixtures (64-byte vendor reports,
# report ID included as byte 0). b35 = charging flag, b36 = battery level.
GAMESIR_FRAME_100 = bytes.fromhex(
    "12808080800f00000000c78e00410001008dff0601c81f5e0100000000"
    "000000000000006400330006000000000000000000000000007f80848a0f0000000000"
)
GAMESIR_EVENT_10 = bytes.fromhex("100600" + "00" * 61)
GAMESIR_FRAME_100_CHARGING = GAMESIR_FRAME_100[:35] + b"\x01" + GAMESIR_FRAME_100[36:]
GAMESIR_FRAME_INVALID = GAMESIR_FRAME_100[:36] + b"\xfe" + GAMESIR_FRAME_100[37:]


class TestAreYouLowBattery(unittest.TestCase):
    def test_all_yaml_profiles_are_valid(self):
        profiles = load_all_profiles()
        self.assertGreaterEqual(len(profiles), 6)
        for prof in profiles:
            self.assertTrue(prof.name)
            self.assertIn(prof.protocol, HANDLER_REGISTRY)
            self.assertGreater(prof.match.vendor_id, 0)
            handler = get_handler(prof.protocol)
            self.assertIsNotNone(handler)

    def test_cache_key_isolation_and_dual_pid_sharing(self):
        handler = CompXHandler()
        # Generic VID-only profile: two different PIDs must NOT collide
        generic_prof = DeviceProfile(
            name="Generic CompX",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x25A7),
            protocol="compx_v1",
        )
        dev_a = HidrawDevice("/dev/hidraw0", 0x25A7, 0xFA7C, 1, "Mouse A")
        dev_b = HidrawDevice("/dev/hidraw1", 0x25A7, 0x2420, 1, "Keyboard B")
        self.assertNotEqual(
            handler._cache_path(generic_prof, dev_a),
            handler._cache_path(generic_prof, dev_b),
        )

        # Dual-PID profile (wired 0xfa7b + wireless 0xfa7c): must share cache for charge_base
        dual_prof = DeviceProfile(
            name="Ajazz AJ199",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x25A7, product_ids=[0xFA7B, 0xFA7C]),
            protocol="compx_v1",
        )
        dev_wired = HidrawDevice("/dev/hidraw2", 0x25A7, 0xFA7B, 1, "Ajazz Wired")
        dev_wireless = HidrawDevice("/dev/hidraw3", 0x25A7, 0xFA7C, 1, "Ajazz Dongle")
        self.assertEqual(
            handler._cache_path(dual_prof, dev_wired),
            handler._cache_path(dual_prof, dev_wireless),
        )

    def test_compx_8k_delux_protocol(self):
        handler = CompXHandler()
        prof = DeviceProfile(
            name="UnitTest Delux M900",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x1D57, product_id=0xFA65, interface_number=2),
            protocol="compx_v1",
            config={"report_id": 0x03, "battery_offset": 4, "status_offset": 3, "listen_timeout": 0.1},
        )
        dev = HidrawDevice("/dev/hidraw99", 0x1D57, 0xFA65, 2, "Delux Mouse")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            with patch.object(handler, "_has_feature_08_descriptor", return_value=False), \
                 patch.object(handler, "_has_vendor_03_descriptor", return_value=True), \
                 patch("areyoulowbattery.handlers.compx.HidrawTransport", return_value=FakeTransport([bytes([0x03, 0x01, 0x40, 0x01, 82])])):
                st = handler.read_battery(dev, prof)
                self.assertTrue(st.is_connected)
                self.assertFalse(st.is_charging)
                self.assertEqual(st.percentage, 82)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_compx_1k_ajazz_wireless_and_charging_interpolation(self):
        handler = CompXHandler()
        prof = DeviceProfile(
            name="UnitTest Ajazz AJ199",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x25A7, product_ids=[0xFA7B, 0xFA7C], interface_number=1),
            protocol="compx_v1",
            config={"feature_report_id": 0x08, "report_id": 0x09, "charging_seconds_per_percent": 75},
        )
        dev_dongle = HidrawDevice("/dev/hidraw98", 0x25A7, 0xFA7C, 1, "Ajazz Dongle")
        dev_cable = HidrawDevice("/dev/hidraw97", 0x25A7, 0xFA7B, 1, "Ajazz Cable")
        cache_file = handler._cache_path(prof, dev_dongle)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            # 1. Wireless reading at 75% (0x4b), discharging (0x00)
            wireless_pkt = bytes.fromhex("0904000000024b000000000000000000fb")
            with patch("areyoulowbattery.handlers.compx.HidrawTransport", return_value=FakeTransport([wireless_pkt])):
                st1 = handler.read_battery(dev_dongle, prof)
                self.assertEqual(st1.percentage, 75)
                self.assertFalse(st1.is_charging)

            # 2. Plug into USB-C cable: hardware ADC jumps to 0x5f (95%, charging=1),
            #    handler must lock onto 75% charge_base and interpolate smoothly!
            cable_pkt = bytes.fromhex("0904000000025f010000000000000000e6")
            with patch("areyoulowbattery.handlers.compx.HidrawTransport", return_value=FakeTransport([cable_pkt])):
                st2 = handler.read_battery(dev_cable, prof)
                self.assertEqual(st2.percentage, 75)
                self.assertTrue(st2.is_charging)
                self.assertIsNotNone(st2.eta_seconds)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_nordic_4k_handler(self):
        handler = NordicHandler()
        prof = DeviceProfile(
            name="UnitTest VXE R1 Pro",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x3554, interface_number=1),
            protocol="nordic_v1",
        )
        dev = HidrawDevice("/dev/hidraw96", 0x3554, 0xF58A, 1, "VXE 4K")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            pkt = bytes.fromhex("09040000000358000000000000000000ee")
            with patch.object(handler, "_has_vendor_descriptor", return_value=True), \
                 patch("areyoulowbattery.handlers.nordic.HidrawTransport", return_value=FakeTransport([pkt])):
                st = handler.read_battery(dev, prof)
                self.assertTrue(st.is_connected)
                self.assertEqual(st.percentage, 88)
                self.assertFalse(st.is_charging)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_logitech_hidpp_handler(self):
        handler = LogitechHidppHandler()
        prof = DeviceProfile(
            name="UnitTest Superlight",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, interface_number=2),
            protocol="hidpp_v2",
        )
        dev = HidrawDevice("/dev/hidraw95", 0x046D, 0xC547, 2, "Lightspeed Receiver")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            # 1st packet: Root GetFeature(0x1004) -> returns feature index 0x06 in byte 4
            # 2nd packet: Feature 0x06 get_status -> returns 91% (0x5b) in byte 4, charging=1 in byte 6
            responses = [
                bytes([0x10, 0x01, 0x00, 0x0A, 0x06, 0x00, 0x00]),
                bytes([0x10, 0x01, 0x06, 0x1A, 91, 0x00, 0x01]),
            ]
            with patch.object(handler, "_read_linux_sysfs_hidpp", return_value=None), \
                 patch("areyoulowbattery.handlers.hidpp.HidrawTransport", return_value=FakeTransport(responses)):
                st = handler.read_battery(dev, prof)
                self.assertTrue(st.is_connected)
                self.assertEqual(st.percentage, 91)
                self.assertTrue(st.is_charging)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_logitech_g403_wired_detected(self):
        handler = LogitechHidppHandler()
        prof = DeviceProfile(
            name="Logitech Lightspeed Peripheral",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D),
            protocol="hidpp_v2",
        )
        # G403 HERO Wired (PID 0xC083)
        dev = HidrawDevice("/dev/hidraw94", 0x046D, 0xC083, 1, "G403 HERO Gaming Mouse")
        st = handler.read_battery(dev, prof)
        self.assertTrue(st.is_connected)
        self.assertTrue(st.is_wired)
        self.assertTrue(st.supported)
        self.assertFalse(st.requires_bluetooth)
        self.assertIsNone(st.percentage)

    def test_actions_baseus_gh02_requires_bluetooth(self):
        handler = get_handler("actions_v1")
        prof = DeviceProfile(
            name="Baseus AeQur GH02",
            category=DeviceCategory.HEADSET,
            icon="🎧",
            match=DeviceMatch(vendor_id=0x10D6, product_id=0x4802),
            protocol="actions_v1",
            config={"requires_bluetooth": True},
        )
        dev = HidrawDevice("/dev/hidraw93", 0x10D6, 0x4802, 0, "Baseus Dongle")
        st = handler.read_battery(dev, prof)
        self.assertTrue(st.is_connected)
        self.assertTrue(st.requires_bluetooth)
        self.assertTrue(st.supported)
        self.assertFalse(st.is_wired)
        self.assertIsNone(st.percentage)

    def test_royalaxe_r68_requires_bluetooth(self):
        handler = CompXHandler()
        prof = DeviceProfile(
            name="Royalaxe R68",
            category=DeviceCategory.KEYBOARD,
            icon="⌨️",
            match=DeviceMatch(vendor_id=0x25A7, product_id=0x2420),
            protocol="compx_v1",
            config={"requires_bluetooth": True},
        )
        dev = HidrawDevice("/dev/hidraw92", 0x25A7, 0x2420, 1, "Royalaxe Dongle")
        st = handler.read_battery(dev, prof)
        self.assertTrue(st.is_connected)
        self.assertTrue(st.requires_bluetooth)
        self.assertTrue(st.supported)
        self.assertFalse(st.is_wired)
        self.assertIsNone(st.percentage)

    def test_category_guard_prevents_mouse_replacing_keyboard(self):
        from areyoulowbattery.engine import BatteryEngine
        engine = BatteryEngine()
        # Mock bluetooth returning a mouse with a similar name to a keyboard
        mock_bt = [("R68 Gaming Mouse", 90, "BlueZ", "usb:v9999p8888", "input-mouse")]
        with patch.object(engine, "_poll_bluetooth_peripheral_batteries", return_value=mock_bt), \
             patch("areyoulowbattery.engine.enumerate_hidraw", return_value=[]), \
             patch.object(engine, "_poll_sysfs_peripheral_batteries", return_value=[]):
            results = engine.poll_all_devices()
            self.assertEqual(len(results), 1)
            prof, stat = results[0]
            self.assertEqual(prof.category, DeviceCategory.MOUSE)
            self.assertEqual(stat.percentage, 90)

    def test_anti_jitter_filter_suppresses_voltage_sag_bounce(self):
        from areyoulowbattery.engine import BatteryEngine
        from areyoulowbattery.models import BatteryStatus
        engine = BatteryEngine()
        key = "Royalaxe R68:25a7:2420"

        # 1. Initial baseline at 80%
        s1 = engine._filter_battery_jitter(key, BatteryStatus(percentage=80, is_charging=False))
        self.assertEqual(s1.percentage, 80)

        # 2. Momentary voltage sag bounce to 90% (e.g. RGB LEDs turned off) -> MUST clamp at 80%
        s2 = engine._filter_battery_jitter(key, BatteryStatus(percentage=90, is_charging=False))
        self.assertEqual(s2.percentage, 80)

        # 3. Downward discharge to 78% (typing / LEDs on) -> immediate update
        s3 = engine._filter_battery_jitter(key, BatteryStatus(percentage=78, is_charging=False))
        self.assertEqual(s3.percentage, 78)

        # 4. Plugged into charger -> immediate update to higher reading
        s4 = engine._filter_battery_jitter(key, BatteryStatus(percentage=85, is_charging=True))
        self.assertEqual(s4.percentage, 85)

    def test_anti_jitter_accepts_charge_completion_right_after_unplug(self):
        from areyoulowbattery.engine import BatteryEngine
        from areyoulowbattery.models import BatteryStatus
        engine = BatteryEngine()
        key = "Smailwolf RS7:a8a5:2255"

        # 1. On the cable the receiver replays a frozen 43% while the real level rises
        s1 = engine._filter_battery_jitter(key, BatteryStatus(percentage=43, is_charging=True))
        self.assertEqual(s1.percentage, 43)
        self.assertTrue(engine._smoothed_levels[key]["was_charging"])
        s_rise = engine._filter_battery_jitter(key, BatteryStatus(percentage=46, is_charging=True))
        self.assertEqual(s_rise.percentage, 46)

        # 2. Cable unplugged at 100%: MUST show 100% immediately (no 60s spike hold)
        s2 = engine._filter_battery_jitter(key, BatteryStatus(percentage=100, is_charging=False))
        self.assertEqual(s2.percentage, 100)
        self.assertFalse(engine._smoothed_levels[key]["was_charging"])

        # 3. The post-charge acceptance is one-shot: a real bounce is still suppressed
        s3 = engine._filter_battery_jitter(key, BatteryStatus(percentage=97, is_charging=False))
        self.assertEqual(s3.percentage, 97)
        s4 = engine._filter_battery_jitter(key, BatteryStatus(percentage=100, is_charging=False))
        self.assertEqual(s4.percentage, 97)

    def test_discovery_and_custom_profile_generation(self):
        import tempfile
        import shutil
        from areyoulowbattery.discovery import save_custom_profile
        from areyoulowbattery.profile_loader import load_profile

        tmp_dir = tempfile.mkdtemp()
        try:
            with patch("areyoulowbattery.discovery.get_user_profiles_dir", return_value=tmp_dir):
                yaml_path = save_custom_profile(
                    name="Test 8BitDo Controller",
                    category=DeviceCategory.GAMEPAD,
                    icon="🎮",
                    vendor_id=0x2DC8,
                    product_id=0x3106,
                    protocol="compx_v1",
                    requires_bluetooth=True,
                )
                self.assertTrue(os.path.exists(yaml_path))
                prof = load_profile(yaml_path)
                self.assertIsNotNone(prof)
                self.assertEqual(prof.name, "Test 8BitDo Controller")
                self.assertEqual(prof.category, DeviceCategory.GAMEPAD)
                self.assertEqual(prof.match.vendor_id, 0x2DC8)
                self.assertEqual(prof.match.product_id, 0x3106)
                self.assertTrue(prof.config.get("requires_bluetooth"))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_razer_hyperspeed_handler(self):
        handler = get_handler("razer_v1")
        prof = DeviceProfile(
            name="Razer Viper V2 Pro",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x1532, product_id=0x00A5),
            protocol="razer_v1",
        )
        dev = HidrawDevice("/dev/hidraw90", 0x1532, 0x00A5, 2, "Razer Viper V2 Pro")

        # Response 90 bytes: Byte 6 is 0x07 (Battery), Byte 7 is 0x80 (Get battery), Byte 9 is percentage (85%)
        resp = bytearray(90)
        resp[6] = 0x07
        resp[7] = 0x80
        resp[9] = 85

        with patch("areyoulowbattery.handlers.razer.HidrawTransport", return_value=FakeTransport([bytes(resp)])):
            st = handler.read_battery(dev, prof)
            self.assertIsNotNone(st)
            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 85)

    def test_generic_hid_handler(self):
        handler = get_handler("generic_hid")
        prof = DeviceProfile(
            name="Generic Wireless Headset",
            category=DeviceCategory.HEADSET,
            icon="🎧",
            match=DeviceMatch(vendor_id=0x1234, product_id=0x5678),
            protocol="generic_hid",
        )
        dev = HidrawDevice("/dev/hidraw91", 0x1234, 0x5678, 0, "Generic USB Device")

        with patch("areyoulowbattery.handlers.generic_hid.HidrawTransport", return_value=FakeTransport([bytes([0x01, 72])])):
            st = handler.read_battery(dev, prof)
            self.assertIsNotNone(st)
            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 72)

    def test_steelseries_handler(self):
        handler = get_handler("steelseries_v1")
        prof = DeviceProfile(
            name="SteelSeries Arctis Nova 7",
            category=DeviceCategory.HEADSET,
            icon="🎧",
            match=DeviceMatch(vendor_id=0x1038, product_id=0x12AD),
            protocol="steelseries_v1",
        )
        dev = HidrawDevice("/dev/hidraw88", 0x1038, 0x12AD, 3, "SteelSeries Arctis Nova 7")
        resp = bytearray(64)
        resp[0] = 0x06
        resp[1] = 0x18
        resp[2] = 88  # 88% battery
        resp[3] = 0   # discharging

        with patch("areyoulowbattery.handlers.steelseries.HidrawTransport", return_value=FakeTransport([bytes(resp)])):
            st = handler.read_battery(dev, prof)
            self.assertIsNotNone(st)
            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 88)

    def test_corsair_slipstream_handler(self):
        handler = get_handler("corsair_v1")
        prof = DeviceProfile(
            name="Corsair Dark Core Pro",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x1B1C, product_id=0x1B7E),
            protocol="corsair_v1",
        )
        dev = HidrawDevice("/dev/hidraw87", 0x1B1C, 0x1B7E, 1, "Corsair Slipstream Receiver")
        resp = bytearray(64)
        resp[0] = 0x08
        resp[1] = 0x01
        resp[2] = 0x03
        resp[3] = 92  # 92% battery

        with patch("areyoulowbattery.handlers.corsair.HidrawTransport", return_value=FakeTransport([bytes(resp)])):
            st = handler.read_battery(dev, prof)
            self.assertIsNotNone(st)
            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 92)

    def test_hyperx_handler(self):
        handler = get_handler("hyperx_v1")
        prof = DeviceProfile(
            name="HyperX Cloud II Wireless",
            category=DeviceCategory.HEADSET,
            icon="🎧",
            match=DeviceMatch(vendor_id=0x0951, product_id=0x1718),
            protocol="hyperx_v1",
        )
        dev = HidrawDevice("/dev/hidraw86", 0x0951, 0x1718, 3, "HyperX Cloud II Wireless")
        resp = bytearray(32)
        resp[0] = 0x21
        resp[1] = 0xBB
        resp[3] = 77  # 77% battery

        with patch("areyoulowbattery.handlers.hyperx.HidrawTransport", return_value=FakeTransport([bytes(resp)])):
            st = handler.read_battery(dev, prof)
            self.assertIsNotNone(st)
            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 77)

    def test_windows_bluetooth_polling_powershell(self):
        from areyoulowbattery.engine import BatteryEngine
        engine = BatteryEngine()
        mock_output = "Generic Bluetooth Keyboard|85\nGeneric Optical Mouse|90\n"

        with patch("sys.platform", "win32"), \
             patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(stdout=mock_output)
            results = engine._poll_bluetooth_windows()
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0][0], "Generic Bluetooth Keyboard")
            self.assertEqual(results[0][1], 85)
            self.assertEqual(results[0][4], "input-keyboard")
            self.assertEqual(results[1][0], "Generic Optical Mouse")
            self.assertEqual(results[1][1], 90)
            self.assertEqual(results[1][4], "input-mouse")

    def test_windows_bluetooth_polling_registry(self):
        from areyoulowbattery.engine import BatteryEngine
        engine = BatteryEngine()

        mock_winreg = MagicMock()
        mock_winreg.HKEY_LOCAL_MACHINE = 1
        mock_winreg.OpenKey.return_value.__enter__.return_value = 10
        # When querying bus key info: 1 device
        mock_winreg.QueryInfoKey.return_value = (1, 0, 0)
        mock_winreg.EnumKey.return_value = "DEV_01"
        # QueryValueEx for FriendlyName and Battery property
        def fake_query_val(key, val_name):
            if val_name in ("FriendlyName", "DeviceDesc"):
                return ("Generic Wireless Keyboard", 1)
            if val_name == "":
                return (bytes([82]), 3)  # 82% battery
            raise OSError("Not found")

        mock_winreg.QueryValueEx.side_effect = fake_query_val

        with patch("sys.platform", "win32"), \
             patch.dict("sys.modules", {"winreg": mock_winreg}):
            results = engine._poll_bluetooth_windows()
            self.assertTrue(len(results) >= 1)
            self.assertEqual(results[0][0], "Generic Wireless Keyboard")
            self.assertEqual(results[0][1], 82)

    def test_updater_version_parsing_and_comparison(self):
        from areyoulowbattery.updater import parse_version, is_newer_version
        self.assertEqual(parse_version("v0.5.0"), (0, 5, 0))
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("0.6.0-beta"), (0, 6, 0))
        self.assertEqual(parse_version("v2.0.0.1"), (2, 0, 0, 1))

        self.assertTrue(is_newer_version("v0.5.1", "0.5.0"))
        self.assertTrue(is_newer_version("v1.0.0", "0.5.0"))
        self.assertFalse(is_newer_version("v0.5.0", "0.5.0"))
        self.assertFalse(is_newer_version("v0.4.9", "0.5.0"))

    def test_updater_asset_matching(self):
        from areyoulowbattery.updater import find_matching_asset
        mock_release = {
            "assets": [
                {"name": "areyoulowbattery-linux-x86_64", "browser_download_url": "https://fake/linux"},
                {"name": "AreYouLowBattery-Windows-Setup.exe", "browser_download_url": "https://fake/win"},
                {"name": "99-areyoulowbattery.rules", "browser_download_url": "https://fake/rules"},
            ]
        }
        win_asset = find_matching_asset(mock_release, platform="win32")
        self.assertIsNotNone(win_asset)
        self.assertEqual(win_asset["name"], "AreYouLowBattery-Windows-Setup.exe")

        linux_asset = find_matching_asset(mock_release, platform="linux")
        self.assertIsNotNone(linux_asset)
        self.assertEqual(linux_asset["name"], "areyoulowbattery-linux-x86_64")

    def test_updater_fetch_latest_release(self):
        from areyoulowbattery.updater import fetch_latest_release
        mock_data = json.dumps({
            "tag_name": "v0.5.1",
            "name": "Release v0.5.1",
            "body": "Bugfixes and updater feature.",
            "assets": [{"name": "AreYouLowBattery-Windows-Setup.exe"}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            data = fetch_latest_release("ryan-mant/AreYouLowBattery")
            self.assertEqual(data["tag_name"], "v0.5.1")
            self.assertEqual(len(data["assets"]), 1)

    def test_logitech_hidpp_10_mileage_register_0x0d(self):
        handler = LogitechHidppHandler()
        prof = DeviceProfile(
            name="Logitech M185",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, product_id=0xC534, interface_number=1),
            protocol="hidpp_v1",
        )
        dev = HidrawDevice("/dev/hidraw85", 0x046D, 0xC534, 1, "Logitech USB Receiver")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            # Short report 0x10, dev_idx 0x01, reg_type 0x81, reg_addr 0x0D, params[0] = 75 (75%), params[2] = 0x00
            resp_0x0d = bytes([0x10, 0x01, 0x81, 0x0D, 75, 0x00, 0x00])
            with patch.object(handler, "_read_linux_sysfs_hidpp", return_value=None), \
                 patch.object(handler, "_discover_battery_feature", return_value=None), \
                 patch("areyoulowbattery.handlers.hidpp.HidrawTransport", return_value=FakeTransport([resp_0x0d])):
                st = handler.read_battery(dev, prof)
                self.assertIsNotNone(st)
                self.assertTrue(st.is_connected)
                self.assertEqual(st.percentage, 75)
                self.assertFalse(st.is_charging)
                self.assertIn("HID++ 1.0 Mileage", st.details)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_logitech_hidpp_10_status_register_0x07(self):
        handler = LogitechHidppHandler()
        prof = DeviceProfile(
            name="Logitech M220",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, product_id=0xC534, interface_number=1),
            protocol="hidpp_v1",
        )
        dev = HidrawDevice("/dev/hidraw84", 0x046D, 0xC534, 1, "Logitech USB Receiver")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            # Short report 0x10, dev_idx 0x01, reg_type 0x80, reg_addr 0x07, params[0] = 3 (Good = 55%)
            resp_0x07 = bytes([0x10, 0x01, 0x80, 0x07, 0x03, 0x00, 0x00])
            with patch.object(handler, "_read_linux_sysfs_hidpp", return_value=None), \
                 patch.object(handler, "_discover_battery_feature", return_value=None), \
                 patch.object(handler, "_transceive_hidpp_10", side_effect=[None, resp_0x07]), \
                 patch("areyoulowbattery.handlers.hidpp.HidrawTransport", return_value=FakeTransport([])):
                st = handler.read_battery(dev, prof)
                self.assertIsNotNone(st)
                self.assertTrue(st.is_connected)
                self.assertEqual(st.percentage, 55)
                self.assertIn("HID++ 1.0 Status", st.details)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_discovery_filters_internal_hardware_touchpad_and_virtual_device(self):
        from areyoulowbattery.discovery import is_device_ignored, _infer_category_and_icon

        # Goodix touchpad / sensor
        self.assertTrue(is_device_ignored("Goodix Touchpad", 0x27C6))
        # Dell HIDI2C Touchpad
        self.assertTrue(is_device_ignored("HIDI2C Device", 0x04F3))
        # Microsoft Converted Device
        self.assertTrue(is_device_ignored("ConvertedDevice", 0x045E, 0x0000))
        # Internal trackpad
        self.assertTrue(is_device_ignored("Synaptics Trackpad", 0x06CB))

        # Real gaming mouse should NOT be ignored
        self.assertFalse(is_device_ignored("Razer Viper V2 Pro", 0x1532, 0x00A5))

        # Unrecognized peripheral fallback must be OTHER (🔋), never GAMEPAD
        cat, ico = _infer_category_and_icon("Wireless Peripheral")
        self.assertEqual(cat, DeviceCategory.OTHER)
        self.assertEqual(ico, "🔋")

    def test_updater_sha256_checksum_verification_and_mismatch(self):
        import hashlib
        from areyoulowbattery.updater import extract_expected_sha256, DownloadWorker

        # 1. Test hash extraction from release notes
        fake_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        release_info = {
            "body": f"Release notes.\nSHA256: {fake_sha}  AreYouLowBattery-Windows-Setup.exe"
        }
        extracted = extract_expected_sha256(release_info, "AreYouLowBattery-Windows-Setup.exe")
        self.assertEqual(extracted, fake_sha)

        # 2. Test DownloadWorker detecting SHA-256 mismatch
        fake_bytes = b"Hello Untrusted Update Payload!"
        mismatch_sha = "0000000000000000000000000000000000000000000000000000000000000000"
        worker = DownloadWorker(
            "https://fake/update.exe",
            "fake_test_update.exe",
            expected_sha256=mismatch_sha
        )
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": str(len(fake_bytes))}
        mock_resp.read.side_effect = [fake_bytes, b""]
        mock_resp.__enter__.return_value = mock_resp

        failed_messages = []
        worker.failed.connect(lambda msg: failed_messages.append(msg))

        with patch("urllib.request.urlopen", return_value=mock_resp):
            worker.run()
            self.assertEqual(len(failed_messages), 1)
            self.assertIn("Security Check Failed", failed_messages[0])

    def test_safe_protocol_probe_respects_vendor_isolation(self):
        from areyoulowbattery.discovery import probe_device_protocol, DiscoveredDevice

        # Razer VID 0x1532 should ONLY test razer_v1, NEVER Logitech or CompX
        razer_dev = DiscoveredDevice(
            name="Razer Viper",
            vendor_id=0x1532,
            product_id=0x00A5,
            dev_path="/dev/hidraw70",
        )
        tested_protocols = []
        def fake_get_handler(proto):
            tested_protocols.append(proto)
            mock_h = MagicMock()
            mock_h.read_battery.return_value = None
            return mock_h

        with patch("areyoulowbattery.discovery.get_handler", side_effect=fake_get_handler):
            probe_device_protocol(razer_dev)
            self.assertEqual(tested_protocols, ["razer_v1"])

    def test_passive_sleep_suppresses_redundant_rf_polling(self):
        from areyoulowbattery.engine import BatteryEngine
        from areyoulowbattery.models import BatteryStatus
        engine = BatteryEngine()

        prof = DeviceProfile(
            name="UnitTest Sleep Mouse",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x25A7, product_id=0xFA7C),
            protocol="compx_v1",
        )
        dev = HidrawDevice("/dev/hidraw69", 0x25A7, 0xFA7C, 1, "Dongle")

        mock_offline = BatteryStatus(percentage=0, is_connected=False, details="Device asleep")
        read_calls = 0

        def fake_get_handler(proto):
            nonlocal read_calls
            mock_h = MagicMock()
            def fake_read(*args, **kwargs):
                nonlocal read_calls
                read_calls += 1
                return mock_offline
            mock_h.read_battery = fake_read
            return mock_h

        with patch("areyoulowbattery.engine.enumerate_hidraw", return_value=[dev]), \
             patch.object(engine, "find_profile_for_device", return_value=prof), \
             patch("areyoulowbattery.engine.get_handler", side_effect=fake_get_handler):

            # 1. First poll: device is found asleep (read_calls = 1)
            res1 = engine.poll_all_devices(force=False)
            self.assertEqual(read_calls, 1)
            self.assertIn(prof.name, engine._offline_devices)

            # 2. Routine background poll 10s later: MUST NOT query hardware (read_calls remains 1!)
            res2 = engine.poll_all_devices(force=False)
            self.assertEqual(read_calls, 1)

            # 3. User clicks tray / opens flyout (force=True): MUST query hardware
            res3 = engine.poll_all_devices(force=True)
            self.assertEqual(read_calls, 2)

    def test_device_removal_and_ignored_devices(self):
        import tempfile
        from areyoulowbattery.engine import BatteryEngine, remove_device, load_ignored_devices, unignore_device

        tmp_dir = tempfile.mkdtemp()
        try:
            with patch("areyoulowbattery.engine._get_config_dir", return_value=tmp_dir):
                remove_device("Unwanted Peripheral", 0x9999, 0x8888)
                ignored = load_ignored_devices()
                self.assertIn("Unwanted Peripheral", ignored)
                self.assertIn("9999:8888", ignored)

                # Test restore_device
                from areyoulowbattery.engine import restore_device
                restore_device("Unwanted Peripheral", 0x9999, 0x8888)
                self.assertNotIn("Unwanted Peripheral", load_ignored_devices())
                self.assertNotIn("9999:8888", load_ignored_devices())
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_dynamic_protocol_change(self):
        import tempfile
        from areyoulowbattery.engine import BatteryEngine, save_device_protocol
        from areyoulowbattery.transport import HidrawDevice

        tmp_dir = tempfile.mkdtemp()
        try:
            with patch("areyoulowbattery.engine._get_config_dir", return_value=tmp_dir):
                engine = BatteryEngine()
                dev = HidrawDevice("/dev/hidraw83", 0x25A7, 0xFA7C, 1, "Ajazz Dongle")
                orig_prof = engine.find_profile_for_device(dev)
                self.assertIsNotNone(orig_prof)

                # Switch protocol to nordic_v1 dynamically
                save_device_protocol(orig_prof.name, "nordic_v1")
                new_prof = engine.find_profile_for_device(dev)
                self.assertIsNotNone(new_prof)
                self.assertEqual(new_prof.protocol, "nordic_v1")
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_ble_and_hidpp_deduplication(self):
        from areyoulowbattery.engine import BatteryEngine
        from areyoulowbattery.models import BatteryStatus
        engine = BatteryEngine()

        # Pebble K380s matched via HID++ reporting 15%
        prof_hidpp = DeviceProfile(
            name="Logitech Pebble Keys 2 K380s",
            category=DeviceCategory.KEYBOARD,
            icon="⌨️",
            match=DeviceMatch(vendor_id=0x046D, product_id=0xB377),
            protocol="hidpp_v2",
        )
        stat_hidpp = BatteryStatus(percentage=15, is_connected=True, is_charging=False, details="HID++ 2.0")

        # Windows Bluetooth cache reporting 95%
        mock_bt = [("Pebble K380s", 95, "Windows Registry", "bthle:v046dpb377", "input-keyboard")]
        mock_dev = HidrawDevice("/dev/hidraw82", 0x046D, 0xB377, 1, "Logitech Pebble Keys")

        with patch("areyoulowbattery.engine.enumerate_hidraw", return_value=[mock_dev]), \
             patch.object(engine, "find_profile_for_device", return_value=prof_hidpp), \
             patch.object(engine, "_poll_bluetooth_peripheral_batteries", return_value=mock_bt), \
             patch.object(engine, "_poll_sysfs_peripheral_batteries", return_value=[]), \
             patch("areyoulowbattery.engine.get_handler") as mock_get_handler:
            mock_h = MagicMock()
            mock_h.read_battery.return_value = stat_hidpp
            mock_get_handler.return_value = mock_h

            results = engine.poll_all_devices()

            # MUST have deduplicated into exactly 1 device card!
            self.assertEqual(len(results), 1)
            p, s = results[0]
            # Verified Bluetooth telemetry (95%) is authoritative over unverified HID responses
            self.assertEqual(s.percentage, 95)

    def test_updater_requires_published_checksum_and_prefers_github_digest(self):
        from areyoulowbattery.updater import extract_expected_sha256, DownloadWorker
        good = "a" * 64
        body_hash = "b" * 64
        release = {
            "body": f"SHA256: {body_hash}  setup.exe",
            "assets": [{"name": "setup.exe", "digest": f"sha256:{good}"}],
        }
        # GitHub-computed asset digest wins over text in release notes
        self.assertEqual(extract_expected_sha256(release, "setup.exe"), good)
        # Malformed digest is ignored
        bad = {"assets": [{"name": "setup.exe", "digest": "sha256:zzz"}], "body": ""}
        self.assertIsNone(extract_expected_sha256(bad, "setup.exe"))

        # Worker must refuse to download anything without an expected hash
        worker = DownloadWorker("https://fake/setup.exe", "setup.exe", expected_sha256=None)
        failed = []
        worker.failed.connect(lambda m: failed.append(m))
        with patch("urllib.request.urlopen") as mock_open:
            worker.run()
            mock_open.assert_not_called()
        self.assertEqual(len(failed), 1)
        self.assertIn("SHA-256", failed[0])

    def test_updater_sanitizes_filename_and_uses_private_dir(self):
        import hashlib
        from areyoulowbattery.updater import DownloadWorker
        payload = b"payload"
        worker = DownloadWorker(
            "https://fake/x", "../../evil.exe",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
        resp = MagicMock()
        resp.headers = {"Content-Length": str(len(payload))}
        resp.read.side_effect = [payload, b""]
        resp.__enter__.return_value = resp
        done = []
        worker.completed.connect(lambda p: done.append(p))
        with patch("urllib.request.urlopen", return_value=resp):
            worker.run()
        self.assertEqual(len(done), 1)
        path = done[0]
        try:
            self.assertEqual(os.path.basename(path), "evil.exe")
            self.assertIn("areyoulowbattery-update-", path)
            if os.name == "posix":
                self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)
        finally:
            os.remove(path)
            os.rmdir(os.path.dirname(path))

    def test_unknown_vendor_probe_is_passive_generic_hid_only(self):
        from areyoulowbattery.discovery import probe_device_protocol, DiscoveredDevice
        dev = DiscoveredDevice(name="Mystery", vendor_id=0xBEEF, product_id=0x0001, dev_path="/dev/hidraw71")
        tested = []
        def fake_get_handler(proto):
            tested.append(proto)
            h = MagicMock()
            h.read_battery.return_value = None
            return h
        with patch("areyoulowbattery.discovery.get_handler", side_effect=fake_get_handler):
            probe_device_protocol(dev)
        self.assertEqual(tested, ["generic_hid"])

    def test_generic_hid_opens_device_read_only(self):
        from areyoulowbattery.handlers.generic_hid import GenericHidHandler
        dev = HidrawDevice("/dev/hidraw72", 0xBEEF, 1, 0, "Mystery")
        prof = DeviceProfile(name="X", category=DeviceCategory.MOUSE, icon="", match=DeviceMatch(vendor_id=0xBEEF, product_id=1), protocol="generic_hid")
        with patch("areyoulowbattery.handlers.generic_hid.HidrawTransport") as mock_tp:
            mock_tp.return_value.__enter__.return_value.read_input_report.return_value = None
            GenericHidHandler().read_battery(dev, prof)
            self.assertTrue(mock_tp.call_args.kwargs.get("read_only"))

    def test_per_device_query_rate_limit(self):
        from areyoulowbattery.engine import BatteryEngine
        from areyoulowbattery.models import BatteryStatus
        engine = BatteryEngine()
        prof = DeviceProfile(
            name="UnitTest RateLimit Mouse", category=DeviceCategory.MOUSE, icon="",
            match=DeviceMatch(vendor_id=0x25A7, product_id=0xFA7D), protocol="compx_v1",
        )
        dev = HidrawDevice("/dev/hidraw73", 0x25A7, 0xFA7D, 1, "Dongle")
        calls = 0
        def fake_get_handler(proto):
            h = MagicMock()
            def fake_read(*a, **k):
                nonlocal calls
                calls += 1
                return BatteryStatus(percentage=80, is_connected=True, details="ok")
            h.read_battery = fake_read
            return h
        with patch("areyoulowbattery.engine.enumerate_hidraw", return_value=[dev]), \
             patch.object(engine, "find_profile_for_device", return_value=prof), \
             patch.object(engine, "_poll_bluetooth_peripheral_batteries", return_value=[]), \
             patch.object(engine, "_poll_sysfs_peripheral_batteries", return_value=[]), \
             patch("areyoulowbattery.engine.get_handler", side_effect=fake_get_handler):
            engine.poll_all_devices()
            engine.poll_all_devices()
            engine.poll_all_devices()
            self.assertEqual(calls, 1)  # rapid repeats are served from the limiter
            engine.poll_all_devices(force=True)
            self.assertEqual(calls, 2)  # explicit user refresh always hits hardware

    def test_systemd_service_does_not_restart_forever(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "systemd", "areyoulowbattery.service")) as f:
            text = f.read()
        self.assertIn("Restart=on-failure", text)
        self.assertNotIn("Restart=always", text)
        self.assertIn("StartLimitBurst", text)

    # ---- Zero-config auto-detection -------------------------------------------------------
    def _make_detector(self):
        import tempfile
        from areyoulowbattery.autodetect import AutoDetector
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        return AutoDetector(state_path=os.path.join(tmp, "state.json"))

    @staticmethod
    def _fake_probe(proto, pct):
        from areyoulowbattery.discovery import ProbeResult
        return ProbeResult(proto, pct, MagicMock(), MagicMock())

    def test_autodetect_known_vendor_creates_profile_after_two_consistent_reads(self):
        from areyoulowbattery.discovery import DiscoveredDevice
        det = self._make_detector()
        dev = DiscoveredDevice(name="Razer Viper Dongle", vendor_id=0x1532, product_id=0x00A5, dev_path="/dev/hidraw90")
        with patch("areyoulowbattery.autodetect.scan_unmapped_devices", return_value=[dev]), \
             patch("areyoulowbattery.autodetect.load_ignored_devices", return_value=set()), \
             patch("areyoulowbattery.autodetect.time.sleep"), \
             patch("areyoulowbattery.autodetect.probe_device_protocol_live", return_value=self._fake_probe("razer_v1", 80)) as probe, \
             patch("areyoulowbattery.autodetect.confirm_probe", return_value=79) as confirm, \
             patch("areyoulowbattery.autodetect.save_custom_profile") as save:
            events = det.run([])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].kind, "profiled")
            self.assertEqual(events[0].protocol, "razer_v1")
            save.assert_called_once()
            self.assertEqual(save.call_args.kwargs["protocol"], "razer_v1")
            # exactly ONE probe + ONE confirmation re-read (no second full probe)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(confirm.call_count, 1)
            # Same model again: never probed or announced twice
            self.assertEqual(det.run([]), [])
            self.assertEqual(probe.call_count, 1)

    def test_autodetect_rejects_inconsistent_probe_reads(self):
        from areyoulowbattery.discovery import DiscoveredDevice
        det = self._make_detector()
        dev = DiscoveredDevice(name="Corsair Dongle", vendor_id=0x1B1C, product_id=0x1B7A, dev_path="/dev/hidraw91")
        with patch("areyoulowbattery.autodetect.scan_unmapped_devices", return_value=[dev]), \
             patch("areyoulowbattery.autodetect.load_ignored_devices", return_value=set()), \
             patch("areyoulowbattery.autodetect.time.sleep"), \
             patch("areyoulowbattery.autodetect.probe_device_protocol_live", return_value=self._fake_probe("corsair_v1", 80)), \
             patch("areyoulowbattery.autodetect.confirm_probe", return_value=20), \
             patch("areyoulowbattery.autodetect.save_custom_profile") as save:
            events = det.run([])
            save.assert_not_called()  # false positive guard
            self.assertEqual([e.kind for e in events], ["unrecognized"])

    def test_autodetect_failed_probe_retries_limited_and_announces_once(self):
        from areyoulowbattery import autodetect
        from areyoulowbattery.discovery import DiscoveredDevice
        det = self._make_detector()
        dev = DiscoveredDevice(name="HyperX Dongle", vendor_id=0x0951, product_id=0x16A4, dev_path="/dev/hidraw92")
        announced = 0
        clock = [1000.0]
        with patch("areyoulowbattery.autodetect.scan_unmapped_devices", return_value=[dev]), \
             patch("areyoulowbattery.autodetect.load_ignored_devices", return_value=set()), \
             patch("areyoulowbattery.autodetect.time.time", side_effect=lambda: clock[0]), \
             patch("areyoulowbattery.autodetect.probe_device_protocol_live", return_value=None) as probe, \
             patch("areyoulowbattery.autodetect.confirm_probe") as confirm:
            for _ in range(6):
                announced += len(det.run([]))
                clock[0] += autodetect.RETRY_INTERVAL + 1
            self.assertEqual(announced, 1)
            self.assertEqual(probe.call_count, autodetect.MAX_ATTEMPTS)  # retries are bounded
            confirm.assert_not_called()  # a failed probe never triggers extra reads

    def test_autodetect_unknown_vendor_never_probes_or_writes(self):
        from areyoulowbattery.discovery import DiscoveredDevice
        det = self._make_detector()
        wireless = DiscoveredDevice(name="Cool 2.4G Wireless Receiver", vendor_id=0xBEEF, product_id=0x0001, dev_path="/dev/hidraw93")
        wired_kb = DiscoveredDevice(name="USB Keyboard", vendor_id=0xBEEF, product_id=0x0002, dev_path="/dev/hidraw94")
        with patch("areyoulowbattery.autodetect.scan_unmapped_devices", return_value=[wireless, wired_kb]), \
             patch("areyoulowbattery.autodetect.load_ignored_devices", return_value=set()), \
             patch("areyoulowbattery.autodetect.probe_device_protocol_live") as probe:
            events = det.run([])
            probe.assert_not_called()  # nothing is ever sent to unknown hardware
            self.assertEqual(len(events), 1)  # wired keyboard stays silent
            self.assertEqual(events[0].kind, "unrecognized")
            self.assertEqual(events[0].product_id, 0x0001)
            self.assertEqual(det.run([]), [])  # one notification per model, ever

    def test_autodetect_respects_ignored_devices_and_xpad(self):
        from areyoulowbattery.discovery import DiscoveredDevice
        det = self._make_detector()
        hidden = DiscoveredDevice(name="Hidden Mouse", vendor_id=0x1532, product_id=0x0001, dev_path="/dev/hidraw95")
        pad = DiscoveredDevice(name="Xbox Wireless Receiver", vendor_id=0x045E, product_id=0x02FE, is_xpad=True)
        with patch("areyoulowbattery.autodetect.scan_unmapped_devices", return_value=[hidden, pad]), \
             patch("areyoulowbattery.autodetect.load_ignored_devices", return_value={"Hidden Mouse"}), \
             patch("areyoulowbattery.autodetect.probe_device_protocol_live") as probe:
            self.assertEqual(det.run([]), [])
            probe.assert_not_called()

    def test_probe_rejects_cached_readings(self):
        from areyoulowbattery.discovery import probe_device_protocol, confirm_probe, DiscoveredDevice
        from areyoulowbattery.models import BatteryStatus
        dev = DiscoveredDevice(name="Nordic Mouse", vendor_id=0x3554, product_id=0xFA09, dev_path="/dev/hidraw98")
        cached = BatteryStatus(percentage=70, is_connected=True, details="Cached (30s ago, mouse asleep)")
        h = MagicMock()
        h.read_battery.return_value = cached
        with patch("areyoulowbattery.discovery.enumerate_hidraw", return_value=[]), \
             patch("areyoulowbattery.discovery.get_handler", return_value=h):
            # A stale cached value must never count as live communication
            self.assertIsNone(probe_device_protocol(dev))
            live = BatteryStatus(percentage=70, is_connected=True, details="Live")
            h.read_battery.return_value = live
            res = probe_device_protocol(dev)
            self.assertEqual(res, ("nordic_v1", 70))
            h.read_battery.return_value = cached
            from areyoulowbattery.discovery import ProbeResult
            self.assertIsNone(confirm_probe(ProbeResult("nordic_v1", 70, MagicMock(), MagicMock())))

    def test_probe_tries_every_hid_node_of_the_device(self):
        from areyoulowbattery.discovery import probe_device_protocol, DiscoveredDevice
        dev = DiscoveredDevice(name="Razer Dongle", vendor_id=0x1532, product_id=0x00A6,
                               dev_path="/dev/hidraw96", interface_number=0)
        nodes = [
            HidrawDevice("/dev/hidraw96", 0x1532, 0x00A6, 0, "Razer Dongle"),
            HidrawDevice("/dev/hidraw97", 0x1532, 0x00A6, 1, "Razer Dongle"),
        ]
        def fake_get_handler(proto):
            h = MagicMock()
            def read(d, p):
                from areyoulowbattery.models import BatteryStatus
                if d.dev_path.endswith("97"):
                    return BatteryStatus(percentage=66, is_connected=True, details="ok")
                return None
            h.read_battery = read
            return h
        with patch("areyoulowbattery.discovery.enumerate_hidraw", return_value=nodes), \
             patch("areyoulowbattery.discovery.get_handler", side_effect=fake_get_handler):
            self.assertEqual(probe_device_protocol(dev), ("razer_v1", 66))

    def test_clean_env_pyinstaller_isolation(self):
        from areyoulowbattery.clean_env import get_clean_env
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI12345/lib", "LD_LIBRARY_PATH_ORIG": "/usr/lib64"}):
            env = get_clean_env()
            self.assertEqual(env["LD_LIBRARY_PATH"], "/usr/lib64")
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI12345/lib"}, clear=True):
            env = get_clean_env()
            self.assertNotIn("LD_LIBRARY_PATH", env)

    def test_scan_unmapped_devices_includes_ignored_and_bluetooth(self):
        from areyoulowbattery.discovery import scan_unmapped_devices
        nodes = [
            HidrawDevice("/dev/hidraw10", 0x046D, 0xC534, 0, "USB Receiver"),
        ]
        mock_bt = [("Pebble Keys 2 K380s", 95, "Windows Registry", None, "input-keyboard")]
        with patch("areyoulowbattery.discovery.enumerate_hidraw", return_value=nodes), \
             patch("glob.glob", return_value=[]), \
             patch("areyoulowbattery.engine.load_ignored_devices", return_value={"USB Receiver", "Pebble Keys 2 K380s"}), \
             patch("areyoulowbattery.engine.BatteryEngine._poll_bluetooth_peripheral_batteries", return_value=mock_bt):
            # When include_ignored=False, user-ignored devices are omitted
            unmapped_clean = scan_unmapped_devices([], include_ignored=False)
            self.assertEqual(len(unmapped_clean), 0)
            # When include_ignored=True, both user-ignored USB and Bluetooth devices are returned to allow restore!
            unmapped_all = scan_unmapped_devices([], include_ignored=True)
            names = [d.name for d in unmapped_all]
            self.assertIn("USB Receiver", names)
            self.assertIn("Pebble Keys 2 K380s", names)

        # Hardware blacklisted devices (root hubs, webcams, etc.) must NEVER be returned, even with include_ignored=True
        with patch("areyoulowbattery.discovery.enumerate_hidraw", return_value=nodes), \
             patch("glob.glob", return_value=[]), \
             patch("areyoulowbattery.discovery.is_device_ignored", return_value=True), \
             patch("areyoulowbattery.engine.BatteryEngine._poll_bluetooth_peripheral_batteries", return_value=mock_bt):
            unmapped_hw = scan_unmapped_devices([], include_ignored=True)
            self.assertEqual(len(unmapped_hw), 0)

        # Active (non-ignored) Bluetooth devices already monitored in dashboard must NOT clutter Find Devices
        active_bt = [("Ba-FON240 Hands-Free AG", 90, "Windows SetupAPI", None, "🎧")]
        with patch("areyoulowbattery.discovery.enumerate_hidraw", return_value=[]), \
             patch("glob.glob", return_value=[]), \
             patch("areyoulowbattery.engine.load_ignored_devices", return_value=set()), \
             patch("areyoulowbattery.engine.BatteryEngine._poll_bluetooth_peripheral_batteries", return_value=active_bt):
            self.assertEqual(scan_unmapped_devices([], include_ignored=True), [])

    def test_is_profile_already_mapped_with_ignored_and_generic_profile(self):
        from areyoulowbattery.discovery import is_profile_already_mapped
        generic_prof = DeviceProfile(
            name="Logitech Lightspeed Peripheral",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, product_id=None),
            protocol="hidpp_v2",
        )
        # Normal unmapped device matches generic profile -> already mapped
        self.assertTrue(is_profile_already_mapped(0x046D, 0xC534, [generic_prof], ignored=set(), dev_name="USB Receiver"))
        # When device VID:PID is ignored, it must return False so it appears in Find Devices to restore
        self.assertFalse(is_profile_already_mapped(0x046D, 0xC534, [generic_prof], ignored={"046d:c534"}, dev_name="USB Receiver"))
        # When device name is ignored, it must also return False
        self.assertFalse(is_profile_already_mapped(0x046D, 0xC534, [generic_prof], ignored={"USB Receiver"}, dev_name="USB Receiver"))

    def test_find_profile_binds_concrete_pid_and_ignores_ble_hid(self):
        from areyoulowbattery.engine import BatteryEngine
        engine = BatteryEngine()
        generic_prof = DeviceProfile(
            name="Logitech Lightspeed Peripheral",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, product_id=None),
            protocol="hidpp_v2",
        )
        engine.profiles = [generic_prof]
        # 1. Generic match binds dev.product_id
        dev = HidrawDevice(r"\\?\hid#vid_046d&pid_c534&mi_01#...", 0x046D, 0xC534, 1, "USB Receiver")
        matched = engine.find_profile_for_device(dev)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.match.product_id, 0xC534)

        # 2. On Windows, Bluetooth LE endpoint with {00001812 is bypassed for 2.4G HID++
        ble_dev = HidrawDevice(r"\\?\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&02046d_PID&b377...", 0x046D, 0xB377, -1, "Pebble_K380s")
        with patch("sys.platform", "win32"):
            matched_ble = engine.find_profile_for_device(ble_dev)
            self.assertIsNone(matched_ble)

    def test_hidpp_handler_bypasses_ble_path_on_windows(self):
        from areyoulowbattery.handlers.hidpp import LogitechHidppHandler
        handler = LogitechHidppHandler()
        prof = DeviceProfile(
            name="Logitech Lightspeed Peripheral",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, product_id=0xB377),
            protocol="hidpp_v2",
        )
        ble_dev = HidrawDevice(r"\\?\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&02046d_PID&b377...", 0x046D, 0xB377, -1, "Pebble_K380s")
        with patch("sys.platform", "win32"):
            status = handler.read_battery(ble_dev, prof)
            self.assertIsNone(status)

    def test_game_mode_polling_suppresses_hardware_queries(self):
        import time
        from areyoulowbattery.engine import BatteryEngine
        from areyoulowbattery.models import BatteryStatus
        engine = BatteryEngine()
        prof = DeviceProfile(
            name="Test Gaming Mouse",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x25A7, product_id=0xFA08),
            protocol="compx_v1",
        )
        engine.profiles = [prof]
        dev = HidrawDevice("/dev/hidraw0", 0x25A7, 0xFA08, 1, "Gaming Mouse")

        # Mock recent query performed 30 seconds ago
        cached_status = BatteryStatus(85, False, True, "Cached 85%")
        engine._recent_queries["Test Gaming Mouse"] = (prof, cached_status, time.time() - 30.0)

        with patch("areyoulowbattery.engine.enumerate_hidraw", return_value=[dev]):
            with patch("areyoulowbattery.engine.get_handler") as mock_get_handler:
                # In game mode (in_game=True), recent query within 180s must be reused directly
                # without calling the handler at all!
                results = engine.poll_all_devices(force=False, in_game=True)
                mock_get_handler.assert_not_called()
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0][1].percentage, 85)

                # CRITICAL: Even with force=True (tray click, hotplug, dashboard open),
                # in_game=True MUST suppress hardware queries and never call handler!
                results_forced = engine.poll_all_devices(force=True, in_game=True)
                mock_get_handler.assert_not_called()
                self.assertEqual(results_forced[0][1].percentage, 85)

    def test_linux_bluetooth_never_calls_bluetoothctl(self):
        from areyoulowbattery.engine import BatteryEngine
        engine = BatteryEngine()
        mock_dbus = MagicMock()
        mock_dbus.SystemBus.side_effect = Exception("No DBus")
        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            with patch("sys.platform", "linux"):
                with patch("subprocess.run") as mock_subproc:
                    res = engine._poll_bluetooth_peripheral_batteries()
                    # Must never spawn bluetoothctl subprocess
                    mock_subproc.assert_not_called()
                    self.assertEqual(res, [])

    def test_get_app_icon_and_desktop_file_generation(self):
        import tempfile
        from areyoulowbattery.tray import _ensure_linux_desktop_entry

        # Test desktop file creation in a mocked home dir across all OSes
        with tempfile.TemporaryDirectory() as tmp_home:
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", tmp_home)):
                with patch("sys.platform", "linux"):
                    _ensure_linux_desktop_entry()
                    desktop_path = os.path.join(tmp_home, ".local", "share", "applications", "areyoulowbattery.desktop")
                    self.assertTrue(os.path.exists(desktop_path))
                    with open(desktop_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        self.assertIn("StartupWMClass=areyoulowbattery", content)
                        self.assertIn("Icon=areyoulowbattery", content)

    def test_vector_icons_and_host_controller_category_inference(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        from areyoulowbattery.vector_icons import render_category_icon, render_zap_icon
        from areyoulowbattery.models import DeviceCategory
        from areyoulowbattery.discovery import _infer_category_and_icon

        # Host Controller must NEVER be inferred as Gamepad
        cat, ico = _infer_category_and_icon("xHCI Host Controller")
        self.assertEqual(cat, DeviceCategory.OTHER)
        self.assertEqual(ico, "🔋")

        # Game controller must be GAMEPAD
        cat, ico = _infer_category_and_icon("Xbox Wireless Controller")
        self.assertEqual(cat, DeviceCategory.GAMEPAD)
        self.assertEqual(ico, "🎮")

        # Vector icon must render valid QIcon for all categories and actions
        for c in (DeviceCategory.MOUSE, DeviceCategory.KEYBOARD, DeviceCategory.HEADSET, DeviceCategory.GAMEPAD, DeviceCategory.OTHER):
            icon = render_category_icon(c, size=18)
            self.assertFalse(icon.isNull())

        zap_icon = render_zap_icon(size=14)
        self.assertFalse(zap_icon.isNull())

    def test_udev_installer_linux_detection_and_windows_isolation(self):
        from areyoulowbattery.udev_installer import (
            are_udev_rules_installed,
            install_udev_rules,
            get_rules_source_path,
        )

        # 1. On Windows, installer returns immediately and rules are considered not applicable/true
        with patch("sys.platform", "win32"):
            self.assertTrue(are_udev_rules_installed())
            self.assertFalse(install_udev_rules(None))

        # 2. Source rules path must exist in repo
        src_path = get_rules_source_path()
        self.assertIsNotNone(src_path)
        self.assertTrue(os.path.exists(src_path))

        # 3. Rules are compared against the bundled file, not a fixed list of vendor IDs
        with open(src_path, "r", encoding="utf-8") as f:
            bundled_rules = f.read()
        bundled_vids = set(re.findall(r'ATTRS\{idVendor\}=="([0-9a-f]{4})"', bundled_rules))
        self.assertTrue({"a8a5", "3537"} <= bundled_vids)

        with tempfile.TemporaryDirectory() as tmp:
            installed = os.path.join(tmp, "99-areyoulowbattery.rules")

            def check(content):
                with open(installed, "w", encoding="utf-8") as f:
                    f.write(content)
                with patch("sys.platform", "linux"):
                    with patch("areyoulowbattery.udev_installer.TARGET_RULES_PATH", installed):
                        return are_udev_rules_installed()

            # An exact copy of the bundled rules is up to date
            self.assertTrue(check(bundled_rules))

            # Comments, blank lines, indentation and rule order do not matter
            rule_lines = [l for l in bundled_rules.splitlines() if l.strip() and not l.startswith("#")]
            reordered = "# local note\n\n" + "\n".join("  " + l for l in reversed(rule_lines)) + "\n"
            self.assertTrue(check(reordered))

            # Rules from an older release that only know the three legacy VIDs are outdated
            legacy = [l for l in rule_lines if any(f'"{vid}"' in l for vid in ("1d57", "25a7", "046d"))]
            self.assertEqual(len(legacy), 3)
            self.assertFalse(check("\n".join(legacy) + "\n"))

            # Dropping any single newer VID makes the installed rules outdated
            for vid in ("a8a5", "3537"):
                self.assertFalse(check("\n".join(l for l in rule_lines if f'"{vid}"' not in l) + "\n"), vid)

            # Unrelated content is outdated
            self.assertFalse(check("old rules without hardening"))

        # 4. Successful installation via pkexec (passing args directly without sh -c)
        mock_proc_ok = MagicMock()
        mock_proc_ok.returncode = 0
        with patch("sys.platform", "linux"):
            with patch("shutil.which", return_value="/usr/bin/pkexec"):
                with patch("subprocess.run", return_value=mock_proc_ok) as mock_sub:
                    res = install_udev_rules(None)
                    self.assertTrue(res)
                    mock_sub.assert_called_once()
                    cmd = mock_sub.call_args[0][0]
                    self.assertEqual(cmd[0], "pkexec")

        # 5. User cancels pkexec prompt (exit 126)
        mock_proc_cancel = MagicMock()
        mock_proc_cancel.returncode = 126
        with patch("sys.platform", "linux"):
            with patch("shutil.which", return_value="/usr/bin/pkexec"):
                with patch("subprocess.run", return_value=mock_proc_cancel):
                    self.assertFalse(install_udev_rules(None))

        # 6. Not authorized (exit 127) must fail loudly instead of looking like a silent cancel
        mock_proc_denied = MagicMock()
        mock_proc_denied.returncode = 127
        mock_proc_denied.stderr = "Error executing command as another user: Not authorized"
        mock_proc_denied.stdout = ""
        with patch("sys.platform", "linux"):
            with patch("shutil.which", return_value="/usr/bin/pkexec"):
                with patch("subprocess.run", return_value=mock_proc_denied):
                    with patch("areyoulowbattery.udev_installer.logger") as mock_log:
                        self.assertFalse(install_udev_rules(None))
                        mock_log.warning.assert_called()


    def test_gamemode_shared_detection_and_non_game_fullscreen(self):
        from areyoulowbattery import gamemode

        # Browsers / media players in fullscreen are never games
        for exe in ("chrome.exe", "firefox.exe", "vlc.exe", "mpv.exe", "msedge.exe"):
            self.assertTrue(gamemode.is_non_game_fullscreen_exe(exe), exe)
        for exe in ("cs2.exe", "valorant-win64-shipping.exe", ""):
            self.assertFalse(gamemode.is_non_game_fullscreen_exe(exe), exe)

        # Linux process scan finds a game and ignores unrelated processes
        def fake_readlink(path):
            return {"/proc/101/exe": "/usr/bin/firefox", "/proc/202/exe": "/games/cs2"}[path]

        with patch("os.listdir", return_value=["101", "202", "self"]), \
             patch("os.readlink", side_effect=fake_readlink):
            self.assertTrue(gamemode._linux_game_running(my_pid=1))

        with patch("os.listdir", return_value=["101"]), \
             patch("os.readlink", return_value="/usr/bin/firefox"):
            self.assertFalse(gamemode._linux_game_running(my_pid=1))

        # TTL cache: second call within ttl must not rescan
        gamemode._last_check_ts = 0.0
        with patch.object(gamemode, "_linux_game_running", return_value=True) as scan, \
             patch("sys.platform", "linux"):
            self.assertTrue(gamemode.is_game_active(ttl=60))
            self.assertTrue(gamemode.is_game_active(ttl=60))
            scan.assert_called_once()
        gamemode._last_check_ts = 0.0
        gamemode._cached_state = False

    def test_cli_poll_never_touches_hardware_in_game(self):
        import cli

        with patch.object(cli, "is_game_active", return_value=True), \
             patch.object(cli, "BatteryEngine") as engine_cls, \
             patch("os.path.exists", return_value=False):
            self.assertEqual(cli.read_from_cache_or_poll(force_poll=True), [])
            engine_cls.assert_not_called()

    def test_daemon_loop_passes_in_game_to_engine(self):
        import cli

        engine = MagicMock()
        engine.poll_all_devices.return_value = []

        class Stop(Exception):
            pass

        with patch.object(cli, "BatteryEngine", return_value=engine), \
             patch.object(cli, "is_game_active", return_value=True), \
             patch("areyoulowbattery.transport.get_hid_topology_signature", return_value="sig"), \
             patch("builtins.open", mock_open()), \
             patch("os.replace"), \
             patch("time.sleep", side_effect=Stop):
            with self.assertRaises(Stop):
                cli.run_daemon_loop()
        engine.poll_all_devices.assert_called_once_with(force=False, in_game=True)

    def test_daemon_loop_forces_poll_after_topology_change(self):
        import cli

        engine = MagicMock()
        engine.poll_all_devices.return_value = []

        class Stop(Exception):
            pass

        # First signature is the baseline; the next check sees a USB plug/unplug event.
        with patch.object(cli, "BatteryEngine", return_value=engine), \
             patch.object(cli, "is_game_active", return_value=False), \
             patch("areyoulowbattery.transport.get_hid_topology_signature", side_effect=["sig1", "sig2"]), \
             patch("builtins.open", mock_open()), \
             patch("os.replace"), \
             patch("time.sleep", side_effect=[None, None, Stop]):
            with self.assertRaises(Stop):
                cli.run_daemon_loop()
        self.assertEqual(
            [c.kwargs for c in engine.poll_all_devices.call_args_list],
            [
                {"force": False, "in_game": False},
                {"force": True, "in_game": False},
            ],
        )

    def test_windows_hidpp_survives_read_error_on_locked_collections(self):
        from areyoulowbattery.handlers.hidpp import LogitechHidppHandler
        from areyoulowbattery.transport import HidrawDevice, HidrawTransport

        handler = LogitechHidppHandler()
        prof = DeviceProfile(
            name="USB Receiver",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x046D, product_id=0xC534),
            protocol="hidpp_v2",
        )
        kbd = HidrawDevice(r"\\?\HID#VID_046D&PID_C534&MI_00#7&e70d7a1&0&0000\KBD", 0x046D, 0xC534, 0, "USB Receiver", 0x0001)
        col4 = HidrawDevice(r"\\?\HID#VID_046D&PID_C534&MI_01&Col04#7&32481563&0&0003", 0x046D, 0xC534, 1, "USB Receiver", 0xFF00)
        col5 = HidrawDevice(r"\\?\HID#VID_046D&PID_C534&MI_01&Col05#7&32481563&0&0004", 0x046D, 0xC534, 1, "USB Receiver", 0xFF00)

        cache_file = handler._cache_path(prof, col4)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        class FakeWinTransport:
            def __init__(self, path, read_only=False):
                self.path = path
                self.had_read_error = False
                self._wrote_10_0d = False

            def open(self):
                if self.path.lower().endswith("\\kbd"):
                    raise PermissionError("Windows keyboard collection blocked")

            def close(self):
                pass

            def __enter__(self):
                self.open()
                return self

            def __exit__(self, *args):
                self.close()

            def write_output_report(self, data):
                if len(data) >= 4 and data[0] == 0x10 and data[2] == 0x81 and data[3] == 0x0D:
                    self._wrote_10_0d = True

            def read_input_report(self, length=64, timeout_sec=0.5):
                if "Col04" in self.path:
                    raise OSError("read error")
                if "Col05" in self.path and self._wrote_10_0d:
                    return bytes([0x10, 0x01, 0x81, 0x0D, 75, 0x00, 0x00])
                return None

        try:
            with patch("sys.platform", "win32"), \
                 patch("areyoulowbattery.handlers.hidpp.enumerate_hidraw", return_value=[kbd, col4, col5]), \
                 patch("areyoulowbattery.handlers.hidpp.HidrawTransport", side_effect=FakeWinTransport):
                st = handler.read_battery(kbd, prof)
                self.assertIsNotNone(st)
                self.assertTrue(st.is_connected)
                self.assertEqual(st.percentage, 75)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

        # HidrawTransport.read_input_report itself must catch OSError and flag had_read_error
        tp = HidrawTransport(r"\\?\HID#test", read_only=False)
        tp._hid_device = MagicMock()
        tp._hid_device.read.side_effect = OSError("read error")
        with patch("sys.platform", "win32"):
            self.assertIsNone(tp.read_input_report())
            self.assertTrue(tp.had_read_error)

    def test_windows_bluetooth_prefers_setupapi_before_powershell(self):
        from areyoulowbattery.engine import BatteryEngine

        eng = BatteryEngine()
        expected = [("Pebble_K380s", 80, "Windows SetupAPI", None, "⌨️")]
        with patch("sys.platform", "win32"), \
             patch.dict("sys.modules", {"winreg": MagicMock(OpenKey=MagicMock(side_effect=OSError("Access denied")))}), \
             patch.object(eng, "_query_windows_setupapi_bluetooth", return_value=expected) as mock_setupapi, \
             patch("subprocess.run") as mock_ps:
            res = eng._poll_bluetooth_windows()
            self.assertEqual(res, expected)
            mock_setupapi.assert_called_once()
            mock_ps.assert_not_called()

    # ------------------------------------------------------------------
    # YJX-CHIP (yjx_v1) - frames below are real hardware captures
    # ------------------------------------------------------------------

    @staticmethod
    def _yjx_profile(config=None):
        return DeviceProfile(
            name="UnitTest YJX RS7",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0xA8A5, product_id=0x2255, interface_number=2),
            protocol="yjx_v1",
            config=config or {"response_timeout": 0.1},
        )

    def test_yjx_query_parses_62_percent_not_charging(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        dev = HidrawDevice("/dev/hidraw91", 0xA8A5, 0x2255, 2, "Smailwolf RS7")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            transport = FakeTransport([YJX_RESPONSE_62])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=transport):
                st = handler.read_battery(dev, prof)

            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 62)
            self.assertFalse(st.is_charging)
            self.assertTrue(st.details.startswith("Live report: aa30a50b"))
            # Safety: only the documented query is ever written (65 bytes, no feature reports)
            self.assertEqual(len(QUERY_PAYLOAD), 65)
            self.assertEqual(transport.sent_outputs, [QUERY_PAYLOAD])
            self.assertEqual(transport.sent_features, [])
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_yjx_query_parses_46_percent_charging(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        dev = HidrawDevice("/dev/hidraw90", 0xA8A5, 0x2255, 2, "MCHOSE G7")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            transport = FakeTransport([YJX_RESPONSE_46_CHARGING])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=transport):
                st = handler.read_battery(dev, prof)

            self.assertEqual(st.percentage, 46)
            self.assertTrue(st.is_charging)
            self.assertEqual(transport.sent_outputs, [QUERY_PAYLOAD])
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_yjx_rejects_out_of_range_percentage(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        dev = HidrawDevice("/dev/hidraw89", 0xA8A5, 0x2255, 2, "EWEADN G5")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            # 0xFF (255%) is not a valid battery level: never clamp or invent a percentage
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([YJX_RESPONSE_INVALID])):
                st = handler.read_battery(dev, prof)
            self.assertTrue(st is None or st.percentage is None)

            # With a previous reading cached, the invalid frame is ignored and cache is served
            handler._write_cache(prof, {"percentage": 62, "is_charging": False, "raw": "aa30"}, dev)
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([YJX_RESPONSE_INVALID])):
                st_cached = handler.read_battery(dev, prof)
            self.assertEqual(st_cached.percentage, 62)
            self.assertTrue(st_cached.details.startswith("Cached ("))
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_yjx_silence_returns_cache_then_none(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        dev = HidrawDevice("/dev/hidraw88", 0xA8A5, 0x2255, 2, "Smailwolf RS7")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            # Sleeping mouse (no answer) and no cache: no percentage is fabricated
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([])):
                st = handler.read_battery(dev, prof)
            self.assertIsNone(st)

            # With a cache entry the last known value is served with a "Cached (...)" detail
            handler._write_cache(prof, {"percentage": 62, "is_charging": False, "raw": "aa30"}, dev)
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([])):
                st_cached = handler.read_battery(dev, prof)
            self.assertEqual(st_cached.percentage, 62)
            self.assertFalse(st_cached.is_charging)
            self.assertTrue(st_cached.details.startswith("Cached ("))
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_yjx_profile_loads_and_protocol_registered(self):
        profiles = [p for p in load_all_profiles() if p.match.vendor_id == 0xA8A5]
        self.assertEqual(len(profiles), 1)
        prof = profiles[0]
        self.assertEqual(prof.protocol, "yjx_v1")
        self.assertIn(prof.protocol, HANDLER_REGISTRY)
        self.assertEqual(prof.match.product_ids, [0x2255])
        self.assertEqual(prof.match.interface_number, 2)
        self.assertEqual(prof.category, DeviceCategory.MOUSE)
        self.assertIsNotNone(get_handler(prof.protocol))

    def test_yjx_passive_heartbeat_parses_level(self):
        handler = YjxHandler()
        prof = self._yjx_profile({"enable_passive_listen": True, "listen_timeout": 0.1})
        dev = HidrawDevice("/dev/hidraw87", 0xA8A5, 0x2255, 2, "Smailwolf RS7")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        try:
            transport = FakeTransport([YJX_HEARTBEAT_62])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=transport):
                st = handler.read_battery(dev, prof)

            self.assertEqual(st.percentage, 62)
            self.assertFalse(st.is_charging)
            self.assertTrue(st.details.startswith("Passive heartbeat: aafaaec8"))
            # Passive listening must never write anything to the receiver
            self.assertEqual(transport.sent_outputs, [])

            # Passive mode with no pushed frame falls back to the active documented query
            os.remove(cache_file)
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport",
                       side_effect=[FakeTransport([]), FakeTransport([YJX_RESPONSE_62])]):
                st_fallback = handler.read_battery(dev, prof)
            self.assertEqual(st_fallback.percentage, 62)
            self.assertTrue(st_fallback.details.startswith("Live report: aa30"))
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)


    # ------------------------------------------------------------------
    # Linux sysfs power_supply capacity_level fallback
    # ------------------------------------------------------------------

    def _sysfs_device(self, root, node, files):
        path = os.path.join(root, node)
        os.makedirs(path, exist_ok=True)
        for fname, value in files.items():
            with open(os.path.join(path, fname), "w") as f:
                f.write(value + "\n")
        return path

    def test_sysfs_capacity_level_is_mapped(self):
        from unittest.mock import MagicMock

        from areyoulowbattery.engine import BatteryEngine, SYSFS_CAPACITY_LEVEL_MAP

        expected = {
            "Full": 100,
            "High": 75,
            "Normal": 50,
            "Low": 25,
            "Critical": 10,
        }
        self.assertEqual(
            SYSFS_CAPACITY_LEVEL_MAP,
            {level.lower(): pct for level, pct in expected.items()},
        )

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for level, pct in expected.items():
                node = f"unit_test_{level.lower()}_battery"
                path = self._sysfs_device(
                    tmp, node, {"scope": "Device", "capacity_level": level}
                )
                fake_glob = MagicMock()
                fake_glob.glob.return_value = [path]
                seen = set()
                with patch("areyoulowbattery.engine.glob", fake_glob):
                    out = BatteryEngine()._poll_sysfs_peripheral_batteries(seen)

                self.assertEqual(len(out), 1, f"capacity_level={level} must be reported")
                profile, status = out[0]
                self.assertEqual(status.percentage, pct, level)
                self.assertTrue(status.is_connected)
                self.assertEqual(profile.protocol, "sysfs_power_supply")
                self.assertIn(f"capacity_level={level}", status.details)
                self.assertIn(node, status.details)
                self.assertIn(node, seen)

    def test_sysfs_numeric_capacity_takes_precedence(self):
        from unittest.mock import MagicMock

        from areyoulowbattery.engine import BatteryEngine

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._sysfs_device(
                tmp,
                "unit_test_precedence_battery",
                {"scope": "device", "capacity": "42", "capacity_level": "Critical"},
            )
            fake_glob = MagicMock()
            fake_glob.glob.return_value = [path]
            with patch("areyoulowbattery.engine.glob", fake_glob):
                out = BatteryEngine()._poll_sysfs_peripheral_batteries(set())

        self.assertEqual(len(out), 1)
        _profile, status = out[0]
        self.assertEqual(status.percentage, 42)
        self.assertNotIn("capacity_level", status.details)

    def test_sysfs_unparseable_capacity_falls_back_to_capacity_level(self):
        from unittest.mock import MagicMock

        from areyoulowbattery.engine import BatteryEngine

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._sysfs_device(
                tmp,
                "unit_test_garbage_capacity_battery",
                {"scope": "device", "capacity": "not-a-number", "capacity_level": "Low"},
            )
            fake_glob = MagicMock()
            fake_glob.glob.return_value = [path]
            with patch("areyoulowbattery.engine.glob", fake_glob):
                out = BatteryEngine()._poll_sysfs_peripheral_batteries(set())

        self.assertEqual(len(out), 1)
        _profile, status = out[0]
        self.assertEqual(status.percentage, 25)
        self.assertIn("capacity_level=Low", status.details)

    def test_sysfs_unknown_capacity_level_is_ignored(self):
        from unittest.mock import MagicMock

        from areyoulowbattery.engine import BatteryEngine

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            paths = [
                self._sysfs_device(
                    tmp,
                    f"unit_test_unknown_{idx}_battery",
                    {"scope": "device", "capacity_level": level},
                )
                for idx, level in enumerate(("Unknown", "None", ""))
            ]
            fake_glob = MagicMock()
            fake_glob.glob.return_value = paths
            with patch("areyoulowbattery.engine.glob", fake_glob):
                out = BatteryEngine()._poll_sysfs_peripheral_batteries(set())

        self.assertEqual(out, [])

    def test_sysfs_requires_device_scope(self):
        from unittest.mock import MagicMock

        from areyoulowbattery.engine import BatteryEngine

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            system_path = self._sysfs_device(
                tmp, "unit_test_system_battery", {"scope": "System", "capacity_level": "High"}
            )
            no_scope_path = self._sysfs_device(
                tmp, "unit_test_no_scope_battery", {"capacity_level": "High"}
            )
            fake_glob = MagicMock()
            fake_glob.glob.return_value = [system_path, no_scope_path]
            with patch("areyoulowbattery.engine.glob", fake_glob):
                out = BatteryEngine()._poll_sysfs_peripheral_batteries(set())

        self.assertEqual(out, [])

    # ------------------------------------------------------------------
    # Native Waybar output (--format waybar)
    # ------------------------------------------------------------------

    def _waybar_device(self, name="UnitTest Mouse", icon="🖱️", category=None):
        from areyoulowbattery.models import DeviceProfile, DeviceMatch

        return DeviceProfile(
            name=name,
            category=category or DeviceCategory.MOUSE,
            icon=icon,
            match=DeviceMatch(vendor_id=0),
            protocol="unittest",
        )

    def test_waybar_emits_single_json_object(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        prof = self._waybar_device()
        raw = cli.format_waybar_output([(prof, BatteryStatus(percentage=80))])
        self.assertTrue(raw.lstrip().startswith("{"), "Waybar expects one JSON object")
        payload = json.loads(raw)
        self.assertEqual(
            set(payload), {"text", "tooltip", "class", "percentage", "alt"}
        )
        self.assertEqual(payload["percentage"], 80)
        self.assertEqual(payload["class"], "good")
        self.assertEqual(payload["alt"], "good")
        self.assertIn("80%", payload["text"])
        self.assertIn("UnitTest Mouse: 80%", payload["tooltip"])

    def test_waybar_class_thresholds(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        prof = self._waybar_device()
        cases = [(90, "good"), (51, "good"), (50, "warning"), (16, "warning"), (15, "critical"), (5, "critical")]
        for pct, expected_cls in cases:
            payload = json.loads(cli.format_waybar_output([(prof, BatteryStatus(percentage=pct))]))
            self.assertEqual(payload["class"], expected_cls, f"{pct}% -> {expected_cls}")
            self.assertEqual(payload["alt"], expected_cls)
            self.assertEqual(payload["percentage"], pct)

    def test_waybar_charging_class_and_tooltip(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        prof = self._waybar_device(name="UnitTest Headset", icon="🎧", category=DeviceCategory.HEADSET)
        payload = json.loads(
            cli.format_waybar_output([(prof, BatteryStatus(percentage=80, is_charging=True))])
        )
        self.assertEqual(payload["class"], "charging")
        self.assertEqual(payload["alt"], "charging")
        self.assertEqual(payload["percentage"], 80)
        self.assertIn("UnitTest Headset: 80% ⚡ (Charging)", payload["tooltip"])

    def test_waybar_reports_lowest_connected_percentage(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        mouse = self._waybar_device()
        keyboard = self._waybar_device(
            name="UnitTest Keyboard", icon="⌨️", category=DeviceCategory.KEYBOARD
        )
        payload = json.loads(
            cli.format_waybar_output([
                (mouse, BatteryStatus(percentage=90)),
                (keyboard, BatteryStatus(percentage=45)),
            ])
        )
        self.assertEqual(payload["percentage"], 45)
        self.assertEqual(payload["class"], "warning")
        tooltip_lines = payload["tooltip"].split("\n")
        self.assertEqual(len(tooltip_lines), 2)
        self.assertIn("UnitTest Mouse: 90%", tooltip_lines[0])
        self.assertIn("UnitTest Keyboard: 45%", tooltip_lines[1])

    def test_waybar_disconnected_state(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        prof = self._waybar_device()
        payload = json.loads(
            cli.format_waybar_output([(prof, BatteryStatus(percentage=None, is_connected=False))])
        )
        self.assertEqual(payload["class"], "disconnected")
        self.assertEqual(payload["alt"], "disconnected")
        self.assertEqual(payload["percentage"], 0)
        self.assertIn("OFF", payload["text"])
        self.assertIn("UnitTest Mouse: Offline", payload["tooltip"])

    def test_waybar_empty_and_unsupported_results(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        empty = json.loads(cli.format_waybar_output([]))
        self.assertEqual(empty["text"], "")
        self.assertEqual(empty["tooltip"], "No supported devices detected")
        self.assertEqual(empty["class"], "disconnected")
        self.assertEqual(empty["percentage"], 0)

        unsupported = [
            (
                self._waybar_device(),
                BatteryStatus(percentage=70, supported=False),
            )
        ]
        # Hidden from the bar unless --all is used
        hidden = json.loads(cli.format_waybar_output(unsupported))
        self.assertEqual(hidden["text"], "")
        self.assertEqual(hidden["tooltip"], "No supported devices detected")

        shown = json.loads(cli.format_waybar_output(unsupported, show_all=True))
        self.assertIn("UnitTest Mouse: 70%", shown["tooltip"])
        self.assertEqual(shown["percentage"], 70)

    def test_waybar_wired_and_bluetooth_required(self):
        import cli
        from areyoulowbattery.models import BatteryStatus

        wired = self._waybar_device()
        payload = json.loads(
            cli.format_waybar_output([(wired, BatteryStatus(percentage=None, is_wired=True))])
        )
        self.assertEqual(payload["class"], "good")
        self.assertEqual(payload["percentage"], 100)
        self.assertIn("Wired USB", payload["tooltip"])

        bt = self._waybar_device()
        payload = json.loads(
            cli.format_waybar_output(
                [(bt, BatteryStatus(percentage=None, requires_bluetooth=True))]
            )
        )
        self.assertEqual(payload["class"], "disconnected")
        self.assertEqual(payload["percentage"], 0)
        self.assertIn("Bluetooth required", payload["tooltip"])

    def test_waybar_is_exposed_by_cli_parser(self):
        import sys

        import cli

        with patch.object(sys, "argv", ["areyoulowbattery", "--format", "waybar", "--poll"]), \
             patch.object(cli, "read_from_cache_or_poll", return_value=[]) as poll, \
             patch("builtins.print") as printed, \
             patch("areyoulowbattery.logger.setup_logging"):
            cli.main()

        poll.assert_called_once()
        payload = json.loads(printed.call_args[0][0])
        self.assertEqual(payload["tooltip"], "No supported devices detected")
        self.assertEqual(payload["class"], "disconnected")

    def test_yjx_usb_cable_forces_charging_even_with_stale_rf_frame(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        dev = HidrawDevice("/dev/hidraw86", 0xA8A5, 0x2255, 2, "Smailwolf RS7")
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        wired_mouse = HidrawDevice("/dev/hidraw85", 0xA8A4, 0x2255, 0, "YJX-CHIP USB MOUSE")
        real_exists = os.path.exists

        def fake_exists(path):
            if path == dev.dev_path:
                return True
            return real_exists(path)

        try:
            # Stale RF frame: byte[9] = 0x00 (not charging), but the mouse is on the cable
            with patch("areyoulowbattery.handlers.yjx.os.path.exists", side_effect=fake_exists), \
                 patch("areyoulowbattery.handlers.yjx.enumerate_hidraw", return_value=[wired_mouse]), \
                 patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([YJX_RESPONSE_62])):
                st = handler.read_battery(dev, prof)

            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 62)
            self.assertTrue(st.is_charging)

            # The charging state is persisted, so a silent receiver also reports charging
            with patch("areyoulowbattery.handlers.yjx.os.path.exists", side_effect=fake_exists), \
                 patch("areyoulowbattery.handlers.yjx.enumerate_hidraw", return_value=[wired_mouse]), \
                 patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([])):
                st_cached = handler.read_battery(dev, prof)
            self.assertEqual(st_cached.percentage, 62)
            self.assertTrue(st_cached.is_charging)
            self.assertTrue(st_cached.details.startswith("Cached ("))

            # Without the wired node on the bus the RF frame stays authoritative
            with patch("areyoulowbattery.handlers.yjx.os.path.exists", side_effect=fake_exists), \
                 patch("areyoulowbattery.handlers.yjx.enumerate_hidraw",
                       return_value=[HidrawDevice("/dev/hidraw84", 0xA8A5, 0x2255, 2, "YJX-CHIP USB_Receiver")]), \
                 patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", return_value=FakeTransport([YJX_RESPONSE_62])):
                st_unplugged = handler.read_battery(dev, prof)
            self.assertEqual(st_unplugged.percentage, 62)
            self.assertFalse(st_unplugged.is_charging)
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    @staticmethod
    def _yjx_cable_setup():
        receiver = HidrawDevice("/dev/hidraw86", 0xA8A5, 0x2255, 2, "Smailwolf RS7")
        wired = HidrawDevice("/dev/hidraw85", 0xA8A4, 0x2255, 2, "YJX-CHIP USB MOUSE")
        real_exists = os.path.exists

        def fake_exists(path):
            if path in (receiver.dev_path, wired.dev_path):
                return True
            return real_exists(path)

        return receiver, wired, fake_exists

    def test_yjx_reads_live_percentage_from_usb_cable_node(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        receiver, wired, fake_exists = self._yjx_cable_setup()
        cache_file = handler._cache_path(prof, receiver)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        cable_transport = FakeTransport([YJX_CABLE_LIVE_87_CHARGING])
        frozen_transport = FakeTransport([YJX_RECEIVER_FROZEN_43])

        def make_transport(path, read_only=False):
            if path == wired.dev_path:
                return cable_transport
            return frozen_transport

        try:
            with patch("areyoulowbattery.handlers.yjx.os.path.exists", side_effect=fake_exists), \
                 patch("areyoulowbattery.handlers.yjx.enumerate_hidraw", return_value=[receiver, wired]), \
                 patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", side_effect=make_transport):
                st = handler.read_battery(receiver, prof)

            self.assertTrue(st.is_connected)
            # The wired node carries the real, rising level (87%), not the frozen RF 43%
            self.assertEqual(st.percentage, 87)
            self.assertTrue(st.is_charging)
            self.assertTrue(st.details.startswith("Live report (USB cable): aa30a50b"))
            # Only the documented query is ever written, and only to the wired node
            self.assertEqual(cable_transport.sent_outputs, [QUERY_PAYLOAD])
            self.assertEqual(cable_transport.sent_features, [])
            self.assertEqual(frozen_transport.sent_outputs, [])
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_yjx_cable_permission_denied_falls_back_to_receiver(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        receiver, wired, fake_exists = self._yjx_cable_setup()
        cache_file = handler._cache_path(prof, receiver)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        class DeniedTransport(FakeTransport):
            def __init__(self, path, read_only=False):
                super().__init__([])

            def open(self):
                raise PermissionError("no udev rule for the wired node")

        frozen_transport = FakeTransport([YJX_RECEIVER_FROZEN_43])

        def make_transport(path, read_only=False):
            if path == wired.dev_path:
                return DeniedTransport(path)
            return frozen_transport

        try:
            with patch("areyoulowbattery.handlers.yjx.os.path.exists", side_effect=fake_exists), \
                 patch("areyoulowbattery.handlers.yjx.enumerate_hidraw", return_value=[receiver, wired]), \
                 patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", side_effect=make_transport):
                st = handler.read_battery(receiver, prof)

            # Receiver frame is stale (43%) but the cable presence still forces "charging"
            self.assertEqual(st.percentage, 43)
            self.assertTrue(st.is_charging)
            self.assertTrue(st.details.startswith("Live report: aa30"))
            self.assertEqual(frozen_transport.sent_outputs, [QUERY_PAYLOAD])
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)

    def test_yjx_silent_cable_node_falls_back_to_receiver(self):
        handler = YjxHandler()
        prof = self._yjx_profile()
        receiver, wired, fake_exists = self._yjx_cable_setup()
        cache_file = handler._cache_path(prof, receiver)
        if os.path.exists(cache_file):
            os.remove(cache_file)

        silent_transport = FakeTransport([])
        frozen_transport = FakeTransport([YJX_RECEIVER_FROZEN_43])

        def make_transport(path, read_only=False):
            if path == wired.dev_path:
                return silent_transport
            return frozen_transport

        try:
            with patch("areyoulowbattery.handlers.yjx.os.path.exists", side_effect=fake_exists), \
                 patch("areyoulowbattery.handlers.yjx.enumerate_hidraw", return_value=[receiver, wired]), \
                 patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.yjx.HidrawTransport", side_effect=make_transport):
                st = handler.read_battery(receiver, prof)

            self.assertEqual(st.percentage, 43)
            self.assertTrue(st.is_charging)
            self.assertTrue(st.details.startswith("Live report: aa30"))
        finally:
            if os.path.exists(cache_file):
                os.remove(cache_file)


    # ------------------------------------------------------------------
    # GameSir Cyclone 2 (gamesir_v1) - frames below are real hardware captures
    # ------------------------------------------------------------------

    @staticmethod
    def _gamesir_profile(config=None):
        return DeviceProfile(
            name="UnitTest GameSir Cyclone 2",
            category=DeviceCategory.GAMEPAD,
            icon="🎮",
            match=DeviceMatch(vendor_id=0x3537, product_id=0x100B, interface_number=1),
            protocol="gamesir_v1",
            config=config or {"response_timeout": 0.1, "query_interval": 60},
        )

    @staticmethod
    def _gamesir_cache_cleanup(handler, prof, dev):
        cache_file = handler._cache_path(prof, dev)
        if os.path.exists(cache_file):
            os.remove(cache_file)

    def test_gamesir_wake_parses_100_percent_not_charging(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile()
        dev = HidrawDevice("/dev/hidraw81", 0x3537, 0x100B, 1, "Xbox 360 Controller for Windows")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            transport = FakeTransport([GAMESIR_FRAME_100])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=transport):
                st = handler.read_battery(dev, prof)

            self.assertTrue(st.is_connected)
            self.assertEqual(st.percentage, 100)
            self.assertFalse(st.is_charging)
            self.assertTrue(st.details.startswith("Live report: 12808080"))
            # Safety: the wake frame is the ONLY thing ever written (64 bytes, no feature reports)
            self.assertEqual(len(WAKE_PAYLOAD), 64)
            self.assertEqual(WAKE_PAYLOAD.hex(), "0f03" + "00" * 62)
            self.assertEqual(transport.sent_outputs, [WAKE_PAYLOAD])
            self.assertEqual(transport.sent_features, [])
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_wake_parses_100_percent_charging(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile()
        dev = HidrawDevice("/dev/hidraw82", 0x3537, 0x100B, 1, "Cyclone 2")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            transport = FakeTransport([GAMESIR_FRAME_100_CHARGING])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=transport):
                st = handler.read_battery(dev, prof)

            self.assertEqual(st.percentage, 100)
            self.assertTrue(st.is_charging)
            self.assertEqual(transport.sent_outputs, [WAKE_PAYLOAD])
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_ignores_event_report_0x10(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile()
        dev = HidrawDevice("/dev/hidraw83", 0x3537, 0x100B, 1, "Cyclone 2")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            # The 0x10 event report carries no battery data and must be skipped silently
            transport = FakeTransport([GAMESIR_EVENT_10, GAMESIR_FRAME_100])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=transport):
                st = handler.read_battery(dev, prof)

            self.assertEqual(st.percentage, 100)
            self.assertFalse(st.is_charging)
            self.assertTrue(st.details.startswith("Live report: 12808080"))
            self.assertEqual(transport.sent_outputs, [WAKE_PAYLOAD])
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_rejects_out_of_range_percentage(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile({"response_timeout": 0.1, "query_interval": 0})
        dev = HidrawDevice("/dev/hidraw84", 0x3537, 0x100B, 1, "Cyclone 2")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            # 0xFE (254%) is not a valid battery level: never clamp or invent a percentage
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport",
                       return_value=FakeTransport([GAMESIR_FRAME_INVALID])):
                st = handler.read_battery(dev, prof)
            self.assertIsNone(st)

            # With a previous reading cached, the invalid frame is ignored and cache is served
            handler._write_cache(prof, {"percentage": 100, "is_charging": False, "raw": "1280"}, dev)
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport",
                       return_value=FakeTransport([GAMESIR_FRAME_INVALID])):
                st_cached = handler.read_battery(dev, prof)
            self.assertEqual(st_cached.percentage, 100)
            self.assertTrue(st_cached.details.startswith("Cached ("))
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_silence_returns_cache_then_none(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile({"response_timeout": 0.1, "query_interval": 0})
        dev = HidrawDevice("/dev/hidraw85", 0x3537, 0x100B, 1, "Cyclone 2")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            # Sleeping controller (no answer) and no cache: no percentage is fabricated
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=FakeTransport([])):
                st = handler.read_battery(dev, prof)
            self.assertIsNone(st)

            # With a cache entry the last known value is served with a "Cached (...)" detail
            handler._write_cache(prof, {"percentage": 100, "is_charging": False, "raw": "1280"}, dev)
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=FakeTransport([])):
                st_cached = handler.read_battery(dev, prof)
            self.assertEqual(st_cached.percentage, 100)
            self.assertFalse(st_cached.is_charging)
            self.assertTrue(st_cached.details.startswith("Cached ("))
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_throttles_queries_within_60s(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile()
        dev = HidrawDevice("/dev/hidraw86", 0x3537, 0x100B, 1, "Cyclone 2")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            transport = FakeTransport([GAMESIR_FRAME_100])
            with patch.object(handler, "_drain_input", return_value=None), \
                 patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=transport) as mock_tp:
                st_first = handler.read_battery(dev, prof)
                st_second = handler.read_battery(dev, prof)

            self.assertEqual(st_first.percentage, 100)
            self.assertTrue(st_first.details.startswith("Live report: "))
            # Second call within 60s is answered from cache without any device I/O
            self.assertEqual(st_second.percentage, 100)
            self.assertTrue(st_second.details.startswith("Cached ("))
            self.assertIn("throttled", st_second.details)
            self.assertEqual(mock_tp.call_count, 1)
            self.assertEqual(transport.sent_outputs, [WAKE_PAYLOAD])
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_pid_gate_never_writes(self):
        handler = GamesirHandler()
        prof = self._gamesir_profile()
        # Vendor 0x3537 also covers other PIDs/modes (0x0575 HID, 0x1053 post-flash)
        dev = HidrawDevice("/dev/hidraw87", 0x3537, 0x0575, 1, "GameSir HID")
        self._gamesir_cache_cleanup(handler, prof, dev)

        try:
            transport = FakeTransport([GAMESIR_FRAME_100])
            with patch("areyoulowbattery.handlers.gamesir.HidrawTransport", return_value=transport) as mock_tp:
                st = handler.read_battery(dev, prof)

            self.assertIsNone(st)
            mock_tp.assert_not_called()
            self.assertEqual(transport.sent_outputs, [])
        finally:
            self._gamesir_cache_cleanup(handler, prof, dev)

    def test_gamesir_profile_loads_and_protocol_registered(self):
        profiles = [p for p in load_all_profiles() if p.match.vendor_id == 0x3537]
        self.assertEqual(len(profiles), 1)
        prof = profiles[0]
        self.assertEqual(prof.protocol, "gamesir_v1")
        self.assertIn(prof.protocol, HANDLER_REGISTRY)
        self.assertEqual(prof.match.product_ids, [0x100B])
        self.assertEqual(prof.match.interface_number, 1)
        self.assertEqual(prof.category, DeviceCategory.GAMEPAD)
        self.assertEqual(prof.config.get("query_interval"), 60)
        self.assertIsInstance(get_handler(prof.protocol), GamesirHandler)


class TestI18n(unittest.TestCase):
    """Unit tests for the multi-language (en_US / pt_BR) i18n layer."""

    def setUp(self):
        import tempfile
        from areyoulowbattery import i18n

        self.i18n = i18n
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = os.path.join(self._tmp.name, "areyoulowbattery")
        self._env_patcher = patch.dict(os.environ, {"AREYOULOWBATTERY_CONFIG_DIR": self.config_dir})
        self._env_patcher.start()
        # Drop any language state cached from a previous configuration directory
        i18n._loaded_path = None
        i18n._current_language = i18n.DEFAULT_LANGUAGE

    def tearDown(self):
        self._env_patcher.stop()
        self.i18n._loaded_path = None
        self.i18n._current_language = self.i18n.DEFAULT_LANGUAGE
        self._tmp.cleanup()

    def test_supported_languages(self):
        self.assertEqual(
            self.i18n.SUPPORTED_LANGUAGES,
            [("en_US", "English (US)"), ("pt_BR", "Português (Brasil)")],
        )

    def test_default_language_is_en_us(self):
        self.assertEqual(self.i18n.get_language(), "en_US")
        self.assertEqual(self.i18n.tr("tray.menu.quit"), "Quit")

    def test_settings_path_uses_config_dir_override(self):
        self.assertEqual(
            self.i18n.get_settings_path(),
            os.path.join(self.config_dir, "settings.json"),
        )

    def test_set_language_persists_and_activates(self):
        self.assertEqual(self.i18n.set_language("pt_BR"), "pt_BR")
        self.assertEqual(self.i18n.get_language(), "pt_BR")

        settings_path = self.i18n.get_settings_path()
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["language"], "pt_BR")

        # A fresh read (simulating an app restart) must keep the persisted value
        self.i18n._loaded_path = None
        self.assertEqual(self.i18n.get_language(), "pt_BR")

    def test_unsupported_language_falls_back_to_en_us(self):
        self.assertEqual(self.i18n.set_language("xx_YY"), "en_US")
        self.assertEqual(self.i18n.get_language(), "en_US")

    def test_persisted_unknown_language_is_ignored(self):
        os.makedirs(self.config_dir, exist_ok=True)
        with open(os.path.join(self.config_dir, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"language": "klingon"}, f)
        self.i18n._loaded_path = None
        self.assertEqual(self.i18n.get_language(), "en_US")

    def test_corrupted_settings_file_does_not_raise(self):
        os.makedirs(self.config_dir, exist_ok=True)
        with open(os.path.join(self.config_dir, "settings.json"), "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.i18n._loaded_path = None
        self.assertEqual(self.i18n.get_language(), "en_US")
        # set_language must be able to recover from an unreadable file
        self.assertEqual(self.i18n.set_language("pt_BR"), "pt_BR")
        self.assertEqual(self.i18n.get_language(), "pt_BR")

    def test_translation_differs_per_language(self):
        self.assertEqual(self.i18n.tr("popup.card.state.low"), "Low Battery")
        self.i18n.set_language("pt_BR")
        self.assertEqual(self.i18n.tr("popup.card.state.low"), "Bateria baixa")
        self.assertNotEqual(
            self.i18n.tr("tray.menu.quit"),
            self.i18n.TRANSLATIONS["en_US"]["tray.menu.quit"],
        )

    def test_argument_interpolation(self):
        self.assertEqual(
            self.i18n.tr("popup.card.options_tooltip", name="G Pro"),
            "Options for G Pro",
        )
        self.i18n.set_language("pt_BR")
        self.assertEqual(
            self.i18n.tr("tray.notify.low.title", name="G Pro", pct=12),
            "G Pro — Bateria baixa (12%)",
        )

    def test_unknown_key_returns_key_and_survives_missing_kwargs(self):
        self.assertEqual(self.i18n.tr("does.not.exist"), "does.not.exist")
        # Missing interpolation kwargs must never raise inside the UI
        self.assertEqual(
            self.i18n.tr("popup.card.options_tooltip"),
            "Options for {name}",
        )

    def test_translation_tables_cover_the_same_keys(self):
        en_keys = set(self.i18n.TRANSLATIONS["en_US"])
        pt_keys = set(self.i18n.TRANSLATIONS["pt_BR"])
        self.assertEqual(en_keys, pt_keys)
        self.assertIn("menu.language", en_keys)

    def test_en_us_strings_match_original_ui_text(self):
        # Default language must render byte-identical strings to the original English UI
        self.assertEqual(self.i18n.tr("popup.card.bt_required"), "BT Req.")
        self.assertEqual(self.i18n.tr("popup.card.state.active"), "Active • Discharging")
        self.assertEqual(
            self.i18n.tr("popup.card.state.charging_eta", eta="~10 min to 100%"),
            "⚡ Charging • ~10 min to 100%",
        )
        self.assertEqual(self.i18n.tr("discovery.btn.save"), "Save Device Profile")
        self.assertEqual(self.i18n.tr("tray.status.no_device"), "No active device")
        self.assertEqual(self.i18n.tr("udev.success.title"), "Permissions Configured")

    def test_tray_device_line_is_translated(self):
        from areyoulowbattery.tray import _format_device_line

        prof = DeviceProfile(
            name="Test Mouse",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x1234, product_id=0x5678),
            protocol="compx_v1",
        )
        stat = BatteryStatus(percentage=42, is_charging=False, is_connected=True)

        self.assertEqual(_format_device_line(prof, stat), "🖱️  Test Mouse: 42%")
        self.i18n.set_language("pt_BR")
        self.assertEqual(_format_device_line(prof, stat), "🖱️  Test Mouse: 42%")
        self.assertEqual(
            _format_device_line(prof, BatteryStatus(percentage=None, is_connected=False)),
            "🖱️  Test Mouse: Desconectado (OFF)",
        )


class TestDeviceOverrides(unittest.TestCase):
    def test_rename_device_twice_updates_canonical_override(self):
        import tempfile
        from unittest.mock import patch
        from areyoulowbattery import engine

        with tempfile.TemporaryDirectory() as tmpdir:
            overrides_path = os.path.join(tmpdir, "device_overrides.json")
            with patch.object(engine, "_get_overrides_path", return_value=overrides_path), \
                 patch.object(engine, "LEGACY_NAMES_FILE", os.path.join(tmpdir, "legacy.json")):
                engine.save_custom_name("Compx 2.4G Dual Mode Mouse", "Meu mouse :)")
                engine.save_custom_name("Meu mouse :)", "Ajazz")
                overrides = engine.load_device_overrides()
                self.assertEqual(overrides["Compx 2.4G Dual Mode Mouse"]["name"], "Ajazz")
                self.assertNotIn("Meu mouse :)", overrides)


if __name__ == "__main__":
    unittest.main()
