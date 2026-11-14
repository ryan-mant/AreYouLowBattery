import os
import sys
import json
import time
import tempfile
import threading
import subprocess
from typing import List, Tuple, Optional

from areyoulowbattery.engine import (
    BatteryEngine,
    save_custom_name,
    save_custom_category,
    save_device_protocol,
    remove_device,
)
from areyoulowbattery.profile_loader import load_all_profiles
from areyoulowbattery.models import DeviceProfile, BatteryStatus
from areyoulowbattery.clean_env import get_clean_env

CACHE_DIR = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
CACHE_FILE = os.path.join(CACHE_DIR, "areyoulowbattery_status.json")


def _pick_color(pct: Optional[int], is_charging: bool, is_connected: bool) -> str:
    if not is_connected:
        return "#94a3b8"  # slate gray
    if is_charging:
        return "#38bdf8"  # sky blue while charging
    if pct is None:
        return "#38bdf8"
    if pct <= 20:
        return "#f87171"  # red
    if pct <= 50:
        return "#facc15"  # yellow
    return "#4ade80"      # green


def _render_tray_icon(
    pct: Optional[int],
    is_charging: bool,
    is_connected: bool,
    is_wired: bool = False,
    requires_bluetooth: bool = False,
):
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtWidgets import QSystemTrayIcon

    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    if requires_bluetooth:
        color = QColor("#38bdf8")
        label = "BT"
        font_size = 18
        span_pct = 0
    elif is_wired:
        color = QColor("#38bdf8")
        label = "🔌"
        font_size = 20
        span_pct = 100
    else:
        color = QColor(_pick_color(pct, is_charging, is_connected))
        span_pct = pct if (is_connected and pct is not None) else (100 if is_charging else 0)
        if not is_connected:
            label = "OFF"
            font_size = 16
        elif is_charging:
            label = "⚡"
            font_size = 26
        elif pct is None:
            label = "⚡"
            font_size = 26
        else:
            label = str(pct)
            font_size = 19 if pct == 100 else 22

    # Draw subtle rounded ring / progress arc around the icon
    pen = QPen(QColor("#334155"), 5)
    painter.setPen(pen)
    rect = QRectF(4, 4, size - 8, size - 8)
    painter.drawEllipse(rect)

    if span_pct > 0:
        arc_pen = QPen(color, 5)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        # Qt angles are in 1/16th of a degree; start at 90 deg (top) and go clockwise
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * (span_pct / 100.0)))

    font = QFont("Sans Serif", font_size, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor("#f8fafc"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    painter.end()
    from PySide6.QtGui import QIcon
    return QIcon(pixmap)


def _render_multi_tray_icon(devices: List[Tuple[DeviceProfile, BatteryStatus]]):
    """
    Renders a single unified icon when 2+ devices are active simultaneously:
      - Outer ring is split into N equal segments (one arc per active device),
        colored by each device's battery health/charging state.
      - Center displays a clean vector battery glyph (or ⚡ if any device is charging)
        instead of a misleading single percentage number.
    """
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QIcon
    from PySide6.QtCore import Qt, QRectF

    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    rect = QRectF(4, 4, size - 8, size - 8)
    bg_pen = QPen(QColor("#334155"), 5)
    painter.setPen(bg_pen)
    painter.drawEllipse(rect)

    n = len(devices)
    gap_deg = 18 if n <= 3 else 12
    seg_span_deg = (360.0 / n) - gap_deg

    for idx, (_, stat) in enumerate(devices):
        c = QColor(_pick_color(stat.percentage, stat.is_charging, stat.is_connected))
        arc_pen = QPen(c, 5)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        start_deg = 90.0 - idx * (360.0 / n) - (gap_deg / 2.0)
        painter.drawArc(rect, int(start_deg * 16), int(-seg_span_deg * 16))

    any_charging = any(s.is_charging for _, s in devices)
    known_pcts = [s.percentage for _, s in devices if s.percentage is not None]
    min_pct = min(known_pcts) if known_pcts else 100
    center_color = QColor(_pick_color(min_pct, any_charging, True))

    if any_charging:
        font = QFont("Sans Serif", 24, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(center_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "⚡")
    else:
        # Draw a crisp vector battery icon in the center
        batt_pen = QPen(QColor("#f8fafc"), 3)
        painter.setPen(batt_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(19, 23, 23, 18)
        painter.drawRoundedRect(body, 3, 3)
        # Positive terminal nub on the right
        painter.fillRect(QRectF(43, 27, 3.5, 10), QColor("#f8fafc"))
        # Inner charge fill
        fill_w = max(3.0, 17.0 * (min_pct / 100.0))
        painter.fillRect(QRectF(22, 26, fill_w, 12), center_color)

    painter.end()
    return QIcon(pixmap)


def _format_device_line(prof: DeviceProfile, stat: BatteryStatus) -> str:
    icon = prof.icon.strip()
    if stat.requires_bluetooth:
        return f"{icon}  {prof.name}: 2.4G (Connect via Bluetooth to monitor)"
    if stat.is_wired:
        return f"{icon}  {prof.name}: Wired USB (Continuous power)"
    if not stat.is_connected:
        return f"{icon}  {prof.name}: Disconnected (OFF)"
    eta_str = stat.format_eta()
    eta_suffix = f" ({eta_str})" if eta_str else ""
    if stat.percentage is None:
        return f"{icon}  {prof.name}: Charging via cable{eta_suffix}"
    if stat.is_charging:
        return f"{icon}  {prof.name}: {stat.percentage}% Charging{eta_suffix}"
    return f"{icon}  {prof.name}: {stat.percentage}%"


def run_tray(auto_show: bool = False):
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QInputDialog, QMessageBox
    from PySide6.QtGui import QCursor, QAction
    from PySide6.QtCore import Signal, QObject, QTimer
    from areyoulowbattery.engine import save_custom_name, save_custom_category, save_device_protocol, remove_device
    from areyoulowbattery.models import CATEGORY_ICONS, DeviceCategory

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AreYouLowBattery")

    tray = QSystemTrayIcon()
    tray.setIcon(_render_tray_icon(None, False, False))
    tray.setToolTip("AreYouLowBattery - Reading peripherals...")

    menu = QMenu()
    menu.setStyleSheet("""
        QMenu {
            background-color: #0f172a;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 6px;
            color: #f8fafc;
        }
        QMenu::item {
            background-color: transparent;
            padding: 6px 14px;
            border-radius: 4px;
            color: #cbd5e1;
            font-size: 12px;
        }
        QMenu::item:selected {
            background-color: #1e293b;
            color: #38bdf8;
        }
        QMenu::item:disabled {
            color: #94a3b8;
        }
        QMenu::separator {
            height: 1px;
            background-color: #334155;
            margin: 4px 6px;
        }
    """)
    status_action = menu.addAction("Reading battery...")
    status_action.setEnabled(False)
    sep_action = menu.addSeparator()
    find_action = menu.addAction("Find devices...")
    rename_action = menu.addAction("Rename device...")
    type_action = menu.addAction("Change device type...")
    proto_action = menu.addAction("Change device protocol...")
    remove_action = menu.addAction("Remove device...")
    refresh_action = menu.addAction("Refresh now")
    menu.addSeparator()

    autostart_action = menu.addAction("Start with system")
    autostart_action.setCheckable(True)

    def is_autostart_enabled() -> bool:
        if sys.platform == "win32":
            startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
            return os.path.exists(os.path.join(startup_dir, "AreYouLowBattery.lnk")) or os.path.exists(os.path.join(startup_dir, "AreYouLowBattery.bat"))
        else:
            service_path = os.path.expanduser("~/.config/systemd/user/areyoulowbattery.service")
            if not os.path.exists(service_path):
                return False
            try:
                res = subprocess.run(
                    ["systemctl", "--user", "is-enabled", "areyoulowbattery.service"],
                    capture_output=True, text=True, timeout=1.5, env=get_clean_env()
                )
                return res.stdout.strip() == "enabled"
            except Exception:
                return False

    autostart_action.setChecked(is_autostart_enabled())

    def toggle_autostart(checked: bool):
        if sys.platform == "win32":
            startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
            os.makedirs(startup_dir, exist_ok=True)
            bat_path = os.path.join(startup_dir, "AreYouLowBattery.bat")
            lnk_path = os.path.join(startup_dir, "AreYouLowBattery.lnk")
            if checked:
                exe_path = os.path.realpath(sys.executable)
                with open(bat_path, "w") as f:
                    if getattr(sys, "frozen", False):
                        f.write(f'@start "" "{exe_path}" --tray\n')
                    else:
                        script = os.path.abspath(sys.argv[0])
                        f.write(f'@start "" "{sys.executable}" "{script}" --tray\n')
            else:
                for target in (bat_path, lnk_path):
                    if os.path.exists(target):
                        try:
                            os.remove(target)
                        except OSError:
                            pass
        else:
            if checked:
                try:
                    subprocess.run(["systemctl", "--user", "enable", "areyoulowbattery.service"], check=True, timeout=5, env=get_clean_env())
                except Exception as e:
                    print(f"Failed to enable autostart: {e}", file=sys.stderr)
            else:
                try:
                    subprocess.run(["systemctl", "--user", "disable", "areyoulowbattery.service"], check=True, timeout=5, env=get_clean_env())
                except Exception as e:
                    print(f"Failed to disable autostart: {e}", file=sys.stderr)
        autostart_action.blockSignals(True)
        autostart_action.setChecked(is_autostart_enabled())
        autostart_action.blockSignals(False)

    autostart_action.toggled.connect(toggle_autostart)

    diag_action = menu.addAction("Export diagnostic log...")

    def handle_export_diag():
        from PySide6.QtWidgets import QMessageBox
        from areyoulowbattery.logger import export_diagnostic_report
        try:
            path = export_diagnostic_report()
            QMessageBox.information(
                None,
                "Diagnostic Log Exported",
                f"Diagnostic report saved to:\n\n{path}\n\nYou can send this file to help troubleshoot your device.",
            )
        except Exception as e:
            QMessageBox.warning(
                None,
                "Diagnostic Error",
                f"Could not generate diagnostic report:\n{e}",
            )

    diag_action.triggered.connect(handle_export_diag)

    update_action = menu.addAction("Check for updates...")
    from areyoulowbattery.updater import run_check_for_updates
    update_action.triggered.connect(lambda: run_check_for_updates(None, prompt_if_latest=True))

    uninstall_action = menu.addAction("Uninstall...")
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(menu)

    # Dedicated clean settings menu for the Dashboard gear button (excludes redundant per-card actions)
    dashboard_settings_menu = QMenu()
    dashboard_settings_menu.setStyleSheet(menu.styleSheet())
    dashboard_settings_menu.addAction(find_action)
    dashboard_settings_menu.addAction(refresh_action)
    dashboard_settings_menu.addSeparator()
    dashboard_settings_menu.addAction(autostart_action)
    dashboard_settings_menu.addAction(diag_action)
    dashboard_settings_menu.addAction(update_action)
    dashboard_settings_menu.addSeparator()
    dashboard_settings_menu.addAction(uninstall_action)
    dashboard_settings_menu.addAction(quit_action)

    tray.show()
    if sys.platform == "win32":
        tray.showMessage(
            "AreYouLowBattery",
            "Battery monitor is running in your System Tray (check the ^ arrow).",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    current_supported_devices: List[Tuple[DeviceProfile, BatteryStatus]] = []

    def prompt_rename(target_prof: Optional[DeviceProfile] = None):
        if not current_supported_devices and not target_prof:
            return
        if target_prof:
            dev_name = target_prof.name
        elif len(current_supported_devices) == 1:
            dev_name = current_supported_devices[0][0].name
        else:
            dev_names = [f"{p.icon} {p.name}" for p, _ in current_supported_devices]
            choice, ok = QInputDialog.getItem(
                None, "Rename Device", "Select device to rename:", dev_names, 0, False
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            dev_name = current_supported_devices[idx][0].name

        new_name, ok = QInputDialog.getText(
            None,
            "Rename Device",
            f"New name for '{dev_name}':",
            text=dev_name,
        )
        if ok and new_name.strip():
            save_custom_name(dev_name, new_name.strip())
            engine.profiles = load_all_profiles()
            wake_event.set()

    def prompt_change_type(target_prof: Optional[DeviceProfile] = None):
        if not current_supported_devices and not target_prof:
            return
        if target_prof:
            prof = target_prof
        elif len(current_supported_devices) == 1:
            prof = current_supported_devices[0][0]
        else:
            dev_names = [f"{p.icon} {p.name}" for p, _ in current_supported_devices]
            choice, ok = QInputDialog.getItem(
                None, "Change Device Type", "Select device:", dev_names, 0, False
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            prof = current_supported_devices[idx][0]

        type_options = [
            ("🖱️ Mouse", "mouse", "🖱️"),
            ("⌨️ Keyboard", "keyboard", "⌨️"),
            ("🎧 Headset", "headset", "🎧"),
            ("🎮 Gamepad", "gamepad", "🎮"),
            ("🔋 Other", "other", "🔋"),
        ]
        labels = [item[0] for item in type_options]
        current_idx = 0
        for i, item in enumerate(type_options):
            if item[1] == prof.category.value:
                current_idx = i
                break

        choice, ok = QInputDialog.getItem(
            None,
            "Change Device Type",
            f"Select new type for '{prof.name}':",
            labels,
            current_idx,
            False,
        )
        if ok and choice:
            for lbl, cat, ico in type_options:
                if lbl == choice:
                    save_custom_category(prof.name, cat, ico)
                    engine.profiles = load_all_profiles()
                    wake_event.set()
                    break

    def prompt_change_protocol(target_prof: Optional[DeviceProfile] = None):
        if not current_supported_devices and not target_prof:
            return
        if target_prof:
            prof = target_prof
        elif len(current_supported_devices) == 1:
            prof = current_supported_devices[0][0]
        else:
            dev_names = [f"{p.icon} {p.name}" for p, _ in current_supported_devices]
            choice, ok = QInputDialog.getItem(
                None, "Change Protocol", "Select device:", dev_names, 0, False
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            prof = current_supported_devices[idx][0]

        modes = [
            ("2.4G CompX / Beken (Ajazz, Delux, Pulsar, Keychron)", "compx_v1", None),
            ("2.4G Nordic 4K/8K RF (VXE, ATK, Scyrox, Lamzu)", "nordic_v1", None),
            ("2.4G Logitech Lightspeed & Bolt (G Pro, G502, G915)", "hidpp_v2", None),
            ("2.4G Logitech HID++ 1.0 (Legacy Nano Receiver M185/M220)", "hidpp_v1", None),
            ("2.4G Razer HyperSpeed (Viper, DeathAdder, Basilisk)", "razer_v1", None),
            ("2.4G SteelSeries (Aerox, Rival, Arctis, Nova)", "steelseries_v1", None),
            ("2.4G Corsair Slipstream (Dark Core, Virtuoso, HS80)", "corsair_v1", None),
            ("2.4G HyperX Wireless (Cloud Flight/II/Alpha, Pulsefire)", "hyperx_v1", None),
            ("2.4G Wireless Headset (Actions Semi / Baseus)", "actions_v1", None),
            ("2.4G Standard USB HID Battery (Generic 0x85)", "generic_hid", None),
            ("2.4G Dongle (Requires Bluetooth for battery)", "compx_v1", {"requires_bluetooth": True}),
            ("Wired USB (Continuous power, no battery alerts)", "compx_v1", {"is_wired": True}),
        ]
        labels = [m[0] for m in modes]
        current_idx = 0
        for i, m in enumerate(modes):
            if m[1] == prof.protocol:
                current_idx = i
                break

        choice, ok = QInputDialog.getItem(
            None,
            "Change Protocol",
            f"Select new protocol for '{prof.name}':",
            labels,
            current_idx,
            False,
        )
        if ok and choice:
            for lbl, proto_id, cfg in modes:
                if lbl == choice:
                    save_device_protocol(prof.name, proto_id, cfg)
                    engine.profiles = load_all_profiles()
                    wake_event.set()
                    break

    def prompt_remove_device(target_prof: Optional[DeviceProfile] = None):
        if not current_supported_devices and not target_prof:
            return
        if target_prof:
            prof = target_prof
        elif len(current_supported_devices) == 1:
            prof = current_supported_devices[0][0]
        else:
            dev_names = [f"{p.icon} {p.name}" for p, _ in current_supported_devices]
            choice, ok = QInputDialog.getItem(
                None, "Remove Device", "Select device to remove:", dev_names, 0, False
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            prof = current_supported_devices[idx][0]

        reply = QMessageBox.question(
            None,
            "Remove Device",
            f"Are you sure you want to remove '{prof.name}' from the battery monitor?\n\nThis will hide the device and delete any custom profile created for it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            remove_device(
                prof.name,
                prof.match.vendor_id,
                prof.match.product_id,
                getattr(prof.match, "product_ids", None),
            )
            engine.profiles = load_all_profiles()
            engine._offline_devices.pop(prof.name, None)
            engine._recent_queries.pop(prof.name, None)
            wake_event.set()

    rename_action.triggered.connect(lambda: prompt_rename())
    type_action.triggered.connect(lambda: prompt_change_type())
    proto_action.triggered.connect(lambda: prompt_change_protocol())
    remove_action.triggered.connect(lambda: prompt_remove_device())

    def prompt_uninstall():
        from PySide6.QtWidgets import QMessageBox
        import subprocess, shutil, glob
        reply = QMessageBox.question(
            None,
            "Uninstall AreYouLowBattery",
            "Are you sure you want to completely uninstall AreYouLowBattery?\n\nThis will stop and remove the background service, delete the binary and clean up all configuration files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if sys.platform == "win32":
                startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
                for target_name in ("AreYouLowBattery.bat", "AreYouLowBattery.lnk"):
                    fpath = os.path.join(startup_dir, target_name)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                config_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "areyoulowbattery")
                if os.path.exists(config_dir):
                    shutil.rmtree(config_dir, ignore_errors=True)
                for f in glob.glob(os.path.join(CACHE_DIR, "areyoulowbattery*")):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                app.quit()
                return

            clean_env = get_clean_env()
            subprocess.run(["systemctl", "--user", "stop", "areyoulowbattery.service"], check=False, env=clean_env)
            subprocess.run(["systemctl", "--user", "disable", "areyoulowbattery.service"], check=False, env=clean_env)
            service_path = os.path.expanduser("~/.config/systemd/user/areyoulowbattery.service")
            if os.path.exists(service_path):
                try:
                    os.remove(service_path)
                except OSError:
                    pass
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, env=clean_env)
            target_bin = os.path.expanduser("~/.local/bin/areyoulowbattery")
            if os.path.exists(target_bin):
                try:
                    os.remove(target_bin)
                except OSError:
                    pass
            config_dir = os.path.expanduser("~/.config/areyoulowbattery")
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir, ignore_errors=True)
            for f in glob.glob(os.path.join(CACHE_DIR, "areyoulowbattery*")):
                try:
                    os.remove(f)
                except OSError:
                    pass
            app.quit()

    uninstall_action.triggered.connect(prompt_uninstall)

    stop_event = threading.Event()
    wake_event = threading.Event()
    force_refresh = False

    def trigger_force_refresh():
        nonlocal force_refresh
        force_refresh = True
        wake_event.set()

    def handle_open_discovery():
        was_visible = popup.isVisible() if 'popup' in locals() else False
        from areyoulowbattery.discovery_dialog import DeviceDiscoveryDialog
        from areyoulowbattery.profile_loader import load_all_profiles

        def on_saved():
            engine.profiles = load_all_profiles()
            wake_event.set()

        dlg = DeviceDiscoveryDialog(
            profiles=engine.profiles,
            on_profile_created=on_saved,
            parent=popup if 'popup' in locals() and popup.isVisible() else None,
        )
        dlg.exec()
        if was_visible:
            QTimer.singleShot(100, popup.show_centered_or_tray)

    find_action.triggered.connect(handle_open_discovery)

    def handle_device_action(action: str, prof: DeviceProfile):
        was_visible = popup.isVisible()
        if action == "change_protocol":
            prompt_change_protocol(prof)
        elif action == "rename":
            prompt_rename(prof)
        elif action == "change_type":
            prompt_change_type(prof)
        elif action == "remove":
            prompt_remove_device(prof)

        if was_visible:
            QTimer.singleShot(100, popup.show_centered_or_tray)

    from areyoulowbattery.popup import BatteryPopup
    popup = BatteryPopup(
        on_refresh=trigger_force_refresh,
        settings_menu=dashboard_settings_menu,
        context_menu=menu,
        on_open_discovery=handle_open_discovery,
        on_device_action=handle_device_action,
    )

    if auto_show:
        trigger_force_refresh()
        QTimer.singleShot(250, popup.show_centered_or_tray)

    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            trigger_force_refresh()
            popup.toggle_at_cursor()

    tray.activated.connect(on_tray_activated)

    class Updater(QObject):
        updated = Signal(object)
        auto_detected = Signal(object)  # AutoDetectEvent

    updater = Updater()
    pending_identify_click = {"active": False}
    engine = BatteryEngine()
    dynamic_actions = []
    # Tracks notification levels per device: key = profile.name, value = set of triggered thresholds (e.g. {15, 5})
    notified_thresholds: dict[str, set[int]] = {}

    def is_fullscreen_or_game_running() -> bool:
        """
        Detects if a competitive game (CS2, Dota 2, Apex, etc.) is running.
        Prevents popping notifications that could cause stutter or distraction during matches.
        """
        game_signatures = {
            "cs2", "csgo_linux64", "dota2", "steam_app_",
            "valorant.exe", "overwatch.exe", "r5apex.exe",
            "pubg.exe", "fortnite.exe"
        }
        my_pid = os.getpid()
        if sys.platform != "win32":
            try:
                for pid_str in os.listdir("/proc"):
                    if not pid_str.isdigit() or int(pid_str) == my_pid:
                        continue
                    try:
                        exe_name = os.path.basename(os.readlink(f"/proc/{pid_str}/exe")).lower()
                        if exe_name in game_signatures or any(sig in exe_name for sig in ("cs2", "dota2", "steam_app")):
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            # On Windows, Focus Assist / Game Bar normally silences notifications automatically,
            # but we can check foreground window state if needed.
            pass
        return False

    def _play_alert_sound(critical: bool = False):
        """
        Plays a non-blocking, lightweight system audio cue in the background.
        Never creates a window or touches graphics/focus, making it 100% safe during fullscreen games.
        """
        if sys.platform == "win32":
            try:
                import winsound
                flag = winsound.MB_ICONHAND if critical else winsound.MB_ICONEXCLAMATION
                winsound.MessageBeep(flag)
            except Exception:
                pass
        else:
            sound_id = "battery-caution" if critical else "battery-low"
            fallback_files = [
                f"/usr/share/sounds/ocean/stereo/{sound_id}.oga",
                "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
                "/usr/share/sounds/freedesktop/stereo/bell.oga",
            ]
            clean_env = get_clean_env()
            for snd in fallback_files:
                if os.path.exists(snd):
                    for player in ("pw-play", "paplay"):
                        try:
                            subprocess.Popen(
                                [player, snd],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                env=clean_env,
                            )
                            return
                        except Exception:
                            continue
            try:
                subprocess.Popen(
                    ["canberra-gtk-play", "-i", sound_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=clean_env,
                )
            except Exception:
                pass

    def check_battery_notifications(supported_devices: List[Tuple[DeviceProfile, BatteryStatus]]):
        for prof, stat in supported_devices:
            if (
                not stat.is_connected
                or stat.percentage is None
                or stat.is_wired
                or stat.requires_bluetooth
            ):
                continue

            # If device is charging or above 20%, reset triggered notification flags
            if stat.is_charging or stat.percentage > 20:
                if prof.name in notified_thresholds:
                    notified_thresholds[prof.name].clear()
                continue

            sent_levels = notified_thresholds.setdefault(prof.name, set())
            in_game = is_fullscreen_or_game_running()

            # Critical Battery: <= 5%
            if stat.percentage <= 5 and 5 not in sent_levels:
                sent_levels.add(5)
                sent_levels.add(15)  # Suppress 15% if it drops straight to <= 5%
                _play_alert_sound(critical=True)
                if not in_game:
                    tray.showMessage(
                        f"{prof.name} — Critical Battery ({stat.percentage}%)",
                        "Battery is critically low. Connect the charger to avoid sudden power off.",
                        QSystemTrayIcon.MessageIcon.Critical,
                        6000
                    )
            # Low Battery: <= 15%
            elif stat.percentage <= 15 and 15 not in sent_levels and 5 not in sent_levels:
                sent_levels.add(15)
                _play_alert_sound(critical=False)
                if not in_game:
                    tray.showMessage(
                        f"{prof.name} — Low Battery ({stat.percentage}%)",
                        "Battery level is low. Consider charging soon.",
                        QSystemTrayIcon.MessageIcon.Warning,
                        4500
                    )

    def write_cache(results: List[Tuple[DeviceProfile, BatteryStatus]]):
        tmp_file = CACHE_FILE + ".tmp"
        cached_data = []
        for profile, status in results:
            cached_data.append({
                "name": profile.name,
                "category": profile.category.value,
                "icon": profile.icon,
                "protocol": profile.protocol,
                "percentage": status.percentage,
                "is_charging": status.is_charging,
                "is_connected": status.is_connected,
                "is_wired": status.is_wired,
                "requires_bluetooth": status.requires_bluetooth,
                "supported": status.supported,
                "eta_seconds": status.eta_seconds,
                "details": status.details,
                "timestamp": time.time(),
            })
        try:
            with open(tmp_file, "w") as f:
                json.dump(cached_data, f)
            if sys.platform != "win32":
                try:
                    os.chmod(tmp_file, 0o600)
                except OSError:
                    pass
            os.replace(tmp_file, CACHE_FILE)
            if sys.platform != "win32":
                try:
                    os.chmod(CACHE_FILE, 0o600)
                except OSError:
                    pass
        except Exception:
            pass

    def hotplug_watcher():
        """
        Watches for USB HID / power_supply hotplug events (plugging/unplugging cable or dongle)
        and immediately wakes the polling worker without waiting for the 10s routine interval.
        """
        from areyoulowbattery.transport import get_hid_topology_signature

        if sys.platform != "win32":
            try:
                proc = subprocess.Popen(
                    [
                        "udevadm", "monitor", "--udev",
                        "--subsystem-match=hidraw",
                        "--subsystem-match=power_supply",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    env=get_clean_env(),
                )
                for line in proc.stdout:
                    if stop_event.is_set():
                        break
                    if any(act in line for act in (" add ", " remove ", " change ")):
                        # Brief debounce so udev permissions settle on new nodes
                        time.sleep(0.25)
                        trigger_force_refresh()
                proc.terminate()
                return
            except Exception:
                pass

        # Fallback (Windows or Linux without udevadm): compare lightweight topology signature
        last_sig = get_hid_topology_signature()
        while not stop_event.is_set():
            time.sleep(1.5)
            cur_sig = get_hid_topology_signature()
            if cur_sig != last_sig:
                last_sig = cur_sig
                time.sleep(0.2)
                trigger_force_refresh()

    def worker():
        nonlocal force_refresh
        from areyoulowbattery.autodetect import AutoDetector
        from areyoulowbattery.profile_loader import load_all_profiles
        detector = AutoDetector()
        first_run = True
        while not stop_event.is_set():
            try:
                is_force = force_refresh
                force_refresh = False

                # Zero-config: on app start and on every hotplug/refresh, identify brand-new
                # peripherals (once per model) and set them up without any user action.
                if is_force or first_run:
                    first_run = False
                    try:
                        events = detector.run(engine.profiles)
                        if any(e.kind == "profiled" for e in events):
                            engine.profiles = load_all_profiles()
                        for ev in events:
                            updater.auto_detected.emit(ev)
                    except Exception as e:
                        print(f"Auto-detect error: {e}", file=sys.stderr, flush=True)

                results = engine.poll_all_devices(force=is_force)
                write_cache(results)
                updater.updated.emit(results)
            except Exception as e:
                print(f"Tray worker error: {e}", file=sys.stderr, flush=True)
            wake_event.wait(timeout=10.0)
            wake_event.clear()

    def on_updated(results: List[Tuple[DeviceProfile, BatteryStatus]]):
        nonlocal current_supported_devices, dynamic_actions
        supported = [(p, s) for p, s in results if s.supported]
        current_supported_devices = supported
        popup.update_devices(supported)

        if not supported:
            if not menu.isVisible():
                for act in dynamic_actions:
                    menu.removeAction(act)
                dynamic_actions.clear()
            tray.setIcon(_render_tray_icon(None, False, False))
            tray.setToolTip("AreYouLowBattery: No supported device active")
            status_action.setVisible(True)
            status_action.setText("No active device")
            rename_action.setEnabled(False)
            type_action.setEnabled(False)
            proto_action.setEnabled(False)
            remove_action.setEnabled(False)
            return

        rename_action.setEnabled(True)
        type_action.setEnabled(True)
        proto_action.setEnabled(True)
        remove_action.setEnabled(True)
        status_action.setVisible(False)

        # Prefer active battery devices over wired or bluetooth-required for the tray icon
        connected = [(p, s) for p, s in supported if s.is_connected]
        batt_connected = [
            (p, s) for p, s in connected
            if not s.is_wired and not s.requires_bluetooth and s.percentage is not None
        ]
        if len(batt_connected) >= 2:
            tray.setIcon(_render_multi_tray_icon(batt_connected))
        elif batt_connected:
            p, s = batt_connected[0]
            tray.setIcon(_render_tray_icon(s.percentage, s.is_charging, s.is_connected))
        elif any(s.is_wired for _, s in connected):
            tray.setIcon(_render_tray_icon(100, is_charging=False, is_connected=True, is_wired=True))
        elif any(s.requires_bluetooth for _, s in connected):
            tray.setIcon(_render_tray_icon(None, is_charging=False, is_connected=True, requires_bluetooth=True))
        else:
            primary_prof, primary_stat = connected[0] if connected else supported[0]
            tray.setIcon(_render_tray_icon(
                primary_stat.percentage,
                primary_stat.is_charging,
                primary_stat.is_connected,
                is_wired=primary_stat.is_wired,
                requires_bluetooth=primary_stat.requires_bluetooth,
            ))

        tooltip_lines = [_format_device_line(prof, stat) for prof, stat in supported]
        tray.setToolTip("\n".join(tooltip_lines))

        # Check thresholds and trigger native system alerts if needed (with hysteresis protection)
        check_battery_notifications(supported)

        # Do not rebuild or touch the menu if the user currently has it open!
        if menu.isVisible():
            return

        for act in dynamic_actions:
            menu.removeAction(act)
        dynamic_actions.clear()

        for line in tooltip_lines:
            act = QAction(line, menu)
            act.setEnabled(False)
            menu.insertAction(sep_action, act)
            dynamic_actions.append(act)

    updater.updated.connect(on_updated)

    def on_auto_detected(ev):
        pending_identify_click["active"] = ev.kind == "unrecognized"
        tray.showMessage(
            ev.title, ev.message, QSystemTrayIcon.MessageIcon.Information, 8000
        )
        if ev.kind == "profiled":
            wake_event.set()

    def on_message_clicked():
        # Only the "unrecognized device" notification opens the identification assistant.
        if pending_identify_click["active"]:
            pending_identify_click["active"] = False
            handle_open_discovery()

    updater.auto_detected.connect(on_auto_detected)
    tray.messageClicked.connect(on_message_clicked)
    refresh_action.triggered.connect(trigger_force_refresh)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    hotplug_thread = threading.Thread(target=hotplug_watcher, daemon=True)
    hotplug_thread.start()

    try:
        sys.exit(app.exec())
    finally:
        stop_event.set()
        wake_event.set()
