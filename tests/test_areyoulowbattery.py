import os
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


if __name__ == "__main__":
    unittest.main()
