import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from areyoulowbattery.discovery import DiscoveredDevice
from areyoulowbattery.discovery_dialog import DeviceConfigCard, DeviceDiscoveryDialog
from areyoulowbattery.engine import (
    BatteryEngine,
    load_ignored_devices,
    remove_device,
    save_device_override,
)
from areyoulowbattery.models import BatteryStatus, DeviceCategory, DeviceMatch, DeviceProfile
from areyoulowbattery.popup import BatteryPopup, DeviceCard


def _get_qapp():
    return QApplication.instance() or QApplication(["test", "-platform", "offscreen"])


class TestFrontendButtonsAndFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_qapp()

    def test_popup_header_and_empty_state_buttons(self):
        on_refresh = MagicMock()
        on_open_discovery = MagicMock()
        popup = BatteryPopup(
            on_refresh=on_refresh,
            settings_menu=QMenu(),
            on_open_discovery=on_open_discovery,
        )
        try:
            popup.show()
            popup.update_devices([])
            self.app.processEvents()

            popup.find_btn.click()
            self.assertEqual(on_open_discovery.call_count, 1)

            popup.refresh_btn.click()
            self.assertEqual(on_refresh.call_count, 1)

            # Empty state also renders a dedicated Find Devices button
            from PySide6.QtWidgets import QPushButton
            header_btns = {popup.find_btn, popup.refresh_btn, popup.menu_btn, popup.close_btn}
            empty_find_btns = [b for b in popup.findChildren(QPushButton) if b not in header_btns]
            self.assertGreaterEqual(len(empty_find_btns), 1)
            empty_find_btns[0].click()
            self.assertEqual(on_open_discovery.call_count, 2)

            popup.show()
            self.app.processEvents()
            popup.close_btn.click()
            self.app.processEvents()
            self.assertFalse(popup.isVisible())
        finally:
            popup.close()
            popup.deleteLater()

    def test_device_card_more_menu_actions(self):
        actions_triggered = []
        prof = DeviceProfile(
            name="ATK A9Air",
            category=DeviceCategory.MOUSE,
            icon="🖱️",
            match=DeviceMatch(vendor_id=0x373B, product_id=0x11D9, interface_number=1),
            protocol="nordic_v1",
        )
        status = BatteryStatus(percentage=85, is_connected=True, is_charging=False)
        card = DeviceCard(
            prof,
            status,
            on_action=lambda act, p: actions_triggered.append((act, p.name)),
        )
        try:
            for idx in range(4):
                class _FakeCardMenu:
                    def __init__(self, _parent=None):
                        self.actions = []

                    def setStyleSheet(self, _css):
                        pass

                    def addAction(self, text):
                        act = object()
                        self.actions.append(act)
                        return act

                    def addSeparator(self):
                        pass

                    def exec(self, _pos):
                        return self.actions[idx]

                with patch("areyoulowbattery.popup.QMenu", _FakeCardMenu):
                    card.btn_more.click()

            self.assertEqual(
                actions_triggered,
                [
                    ("change_protocol", "ATK A9Air"),
                    ("rename", "ATK A9Air"),
                    ("change_type", "ATK A9Air"),
                    ("remove", "ATK A9Air"),
                ],
            )
        finally:
            card.close()
            card.deleteLater()

    def test_discovery_test_protocol_and_save_buttons(self):
        tmp_dir = tempfile.mkdtemp()
        on_saved = MagicMock()
        dev = DiscoveredDevice(
            name="Compx Wireless mouse 8k dongle-L",
            vendor_id=0x373B,
            product_id=0x11D9,
            interface_number=1,
            dev_path="/dev/hidraw6",
            suggested_category=DeviceCategory.MOUSE,
            suggested_icon="🖱️",
        )
        try:
            with patch("areyoulowbattery.engine._get_config_dir", return_value=tmp_dir), \
                 patch("areyoulowbattery.discovery.get_user_profiles_dir", return_value=os.path.join(tmp_dir, "profiles")):
                card = DeviceConfigCard(dev, on_saved_callback=on_saved)
                try:
                    with patch("areyoulowbattery.discovery_dialog.time.sleep"), \
                         patch("areyoulowbattery.discovery_dialog.probe_device_protocol", return_value=("nordic_v1", 85)):
                        card.btn_test.click()
                        self.app.processEvents()

                    self.assertEqual(card.cmb_mode.currentData(), "nordic_v1")
                    self.assertIn("85%", card.test_status_lbl.text())

                    card.btn_save.click()
                    self.app.processEvents()
                    self.assertFalse(card.btn_save.isEnabled())
                    self.assertEqual(on_saved.call_count, 1)
                finally:
                    card.close()
                    card.deleteLater()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_remove_find_devices_test_protocol_and_restore_end_to_end(self):
        """
        Regression test for the full Remove -> Find Devices -> Test Protocol -> Restore flow
        when the device has a custom name override in device_overrides.json.
        """
        tmp_dir = tempfile.mkdtemp()
        dev = DiscoveredDevice(
            name="Compx Wireless mouse 8k dongle-L",
            vendor_id=0x373B,
            product_id=0x11D9,
            interface_number=1,
            dev_path="/dev/hidraw6",
            suggested_category=DeviceCategory.MOUSE,
            suggested_icon="🖱️",
        )
        try:
            with patch("areyoulowbattery.engine._get_config_dir", return_value=tmp_dir), \
                 patch("areyoulowbattery.discovery.get_user_profiles_dir", return_value=os.path.join(tmp_dir, "profiles")):
                # 1. User renames device to "ATK A9Air" and then removes it from dashboard
                save_device_override("Compx Wireless mouse 8k dongle-L", name="ATK A9Air")
                remove_device("ATK A9Air", 0x373B, 0x11D9)
                self.assertIn("ATK A9Air", load_ignored_devices())

                # 2. User opens Find Devices -> removed device is shown with Restore button
                on_device_saved = MagicMock()
                with patch("areyoulowbattery.discovery_dialog.scan_unmapped_devices", return_value=[dev]), \
                     patch("areyoulowbattery.udev_installer.are_udev_rules_installed", return_value=True):
                    dlg = DeviceDiscoveryDialog(profiles=[], on_profile_created=on_device_saved)
                    try:
                        cards = dlg.scroll_content.findChildren(DeviceConfigCard)
                        self.assertEqual(len(cards), 1)
                        card = cards[0]
                        self.assertTrue(card.is_ignored)

                        # 3. User clicks Test Protocol -> selects nordic_v1
                        with patch("areyoulowbattery.discovery_dialog.time.sleep"), \
                             patch("areyoulowbattery.discovery_dialog.probe_device_protocol", return_value=("nordic_v1", 85)):
                            card.btn_test.click()
                            self.app.processEvents()
                        self.assertEqual(card.cmb_mode.currentData(), "nordic_v1")

                        # 4. User clicks Restore -> un-ignores BOTH raw name and renamed override
                        card.btn_save.click()
                        self.app.processEvents()
                        self.assertEqual(on_device_saved.call_count, 1)
                        self.assertNotIn("ATK A9Air", load_ignored_devices())
                        self.assertNotIn("373b:11d9", load_ignored_devices())

                        # 5. Device is no longer ignored so dashboard/discovery treat it as active
                        from areyoulowbattery.discovery import is_device_ignored
                        self.assertFalse(is_device_ignored("ATK A9Air", 0x373B, 0x11D9))
                    finally:
                        dlg.close()
                        dlg.deleteLater()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_discovery_dialog_rescan_and_done_buttons(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            with patch("areyoulowbattery.engine._get_config_dir", return_value=tmp_dir), \
                 patch("areyoulowbattery.discovery.get_user_profiles_dir", return_value=os.path.join(tmp_dir, "profiles")), \
                 patch("areyoulowbattery.discovery_dialog.scan_unmapped_devices", return_value=[]) as mock_scan, \
                 patch("areyoulowbattery.udev_installer.are_udev_rules_installed", return_value=True):
                dlg = DeviceDiscoveryDialog(profiles=[], on_profile_created=MagicMock())
                try:
                    self.assertEqual(mock_scan.call_count, 1)
                    dlg.btn_rescan.click()
                    self.app.processEvents()
                    self.assertEqual(mock_scan.call_count, 2)

                    done_btns = [
                        b for b in dlg.findChildren(type(dlg.btn_rescan))
                        if b.objectName() == "closeBtn"
                    ]
                    self.assertEqual(len(done_btns), 1)
                    done_btns[0].click()
                    self.app.processEvents()
                    self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
                finally:
                    dlg.close()
                    dlg.deleteLater()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
