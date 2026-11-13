import os
import json
import unittest
from unittest.mock import patch, MagicMock

from areyoulowbattery.models import DeviceProfile, DeviceMatch, DeviceCategory
from areyoulowbattery.profile_loader import load_all_profiles
from areyoulowbattery.handlers import HANDLER_REGISTRY, get_handler
from areyoulowbattery.handlers.compx import CompXHandler
from areyoulowbattery.handlers.nordic import NordicHandler
from areyoulowbattery.handlers.hidpp import LogitechHidppHandler
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
            # MUST retain direct hardware telemetry (15%) rather than stale Windows GATT cache (95%)
            self.assertEqual(s.percentage, 15)

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


if __name__ == "__main__":
    unittest.main()
