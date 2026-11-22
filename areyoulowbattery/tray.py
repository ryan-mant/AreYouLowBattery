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
from areyoulowbattery.i18n import SUPPORTED_LANGUAGES, get_language, set_language, tr

def _get_cache_dir() -> str:
    xdg_rt = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_rt and os.path.isdir(xdg_rt):
        return xdg_rt
    return "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()


CACHE_DIR = _get_cache_dir()
CACHE_FILE = os.path.join(CACHE_DIR, f"areyoulowbattery_status_{os.getuid() if hasattr(os, 'getuid') else 'user'}.json")


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
        return tr("tray.line.bluetooth", icon=icon, name=prof.name)
    if stat.is_wired:
        return tr("tray.line.wired", icon=icon, name=prof.name)
    if not stat.is_connected:
        return tr("tray.line.disconnected", icon=icon, name=prof.name)
    eta_str = stat.format_eta()
    eta_suffix = f" ({eta_str})" if eta_str else ""
    if stat.percentage is None:
        return tr("tray.line.charging_unknown", icon=icon, name=prof.name, eta=eta_suffix)
    if stat.is_charging:
        return tr("tray.line.charging", icon=icon, name=prof.name, pct=stat.percentage, eta=eta_suffix)
    return tr("tray.line.percentage", icon=icon, name=prof.name, pct=stat.percentage)


def _ensure_linux_desktop_entry():
    """
    On Linux / Wayland, compositors (KWin, Mutter) display a generic 'W' fallback icon
    unless an app_id desktop entry matching app.desktopFileName exists in ~/.local/share/applications/.
    This installs the icon and .desktop entry automatically on app startup.
    """
    if sys.platform == "win32":
        return
    try:
        from areyoulowbattery.profile_loader import get_resource_dir
        import shutil

        # 1. Install icon into ~/.local/share/icons/hicolor/256x256/apps/areyoulowbattery.png
        icon_dir = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps")
        os.makedirs(icon_dir, exist_ok=True)
        dest_icon = os.path.join(icon_dir, "areyoulowbattery.png")

        src_icon = os.path.join(get_resource_dir(), "assets", "icon.png")
        if os.path.exists(src_icon) and not os.path.exists(dest_icon):
            try:
                shutil.copy2(src_icon, dest_icon)
            except Exception:
                pass

        # 2. Install desktop entry into ~/.local/share/applications/areyoulowbattery.desktop
        apps_dir = os.path.expanduser("~/.local/share/applications")
        os.makedirs(apps_dir, exist_ok=True)
        desktop_file = os.path.join(apps_dir, "areyoulowbattery.desktop")

        exe_path = os.path.realpath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
        if not getattr(sys, "frozen", False):
            exec_cmd = f'"{sys.executable}" "{exe_path}" --tray'
        else:
            exec_cmd = f'"{exe_path}" --tray'

        desktop_content = (
            "[Desktop Entry]\n"
            "Name=AreYouLowBattery\n"
            "Comment=Wireless Peripheral Battery Monitor & System Tray\n"
            f"Exec={exec_cmd}\n"
            "Icon=areyoulowbattery\n"
            "Terminal=false\n"
            "Type=Application\n"
            "Categories=Utility;HardwareSettings;\n"
            "StartupNotify=false\n"
            "StartupWMClass=areyoulowbattery\n"
        )

        if not os.path.exists(desktop_file):
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write(desktop_content)
    except Exception:
        pass


def add_game_mode_actions(menu):
    status = menu.addAction(tr("tray.menu.game_mode_active"))
    status.setEnabled(False)
    status.setVisible(False)
    pause = menu.addAction(tr("tray.menu.pause_polling"))
    pause.setCheckable(True)
    return status, pause


def run_tray(auto_show: bool = False):
    from PySide6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu, QInputDialog, QMessageBox,
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox
    )
    from PySide6.QtGui import QCursor, QAction
    from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize
    from areyoulowbattery.engine import save_custom_name, save_custom_category, save_device_protocol, remove_device
    from areyoulowbattery.models import CATEGORY_ICONS, DeviceCategory
    from areyoulowbattery.vector_icons import get_app_icon, render_category_icon

    _ensure_linux_desktop_entry()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AreYouLowBattery")
    app.setDesktopFileName("areyoulowbattery")
    app.setWindowIcon(get_app_icon())

    tray = QSystemTrayIcon()
    popup = None
    tray.setIcon(_render_tray_icon(None, False, False))
    tray.setToolTip(tr("tray.tooltip.reading"))

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
    language_menus = []

    def apply_language(code: str):
        """Switches the active language and re-renders every translated surface."""
        set_language(code)
        retranslate_menus()
        if popup is not None:
            popup.retranslate_ui()

    def register_language_menu(parent_menu):
        submenu = parent_menu.addMenu(tr("menu.language"))
        entries = {}
        for code, label in SUPPORTED_LANGUAGES:
            act = submenu.addAction(label)
            act.setCheckable(True)
            act.setChecked(get_language() == code)
            act.triggered.connect(lambda _checked=False, c=code: apply_language(c))
            entries[code] = act
        language_menus.append((submenu, entries))
        return submenu

    status_action = menu.addAction(tr("tray.status.reading"))
    status_action.setEnabled(False)
    sep_action = menu.addSeparator()
    find_action = menu.addAction(tr("tray.menu.find"))
    rename_action = menu.addAction(tr("tray.menu.rename"))
    type_action = menu.addAction(tr("tray.menu.change_type"))
    proto_action = menu.addAction(tr("tray.menu.change_protocol"))
    remove_action = menu.addAction(tr("tray.menu.remove"))
    refresh_action = menu.addAction(tr("tray.menu.refresh"))
    game_mode_status, pause_action = add_game_mode_actions(menu)
    menu.addSeparator()
    register_language_menu(menu)
    menu.addSeparator()

    autostart_action = menu.addAction(tr("tray.menu.autostart"))
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

    diag_action = menu.addAction(tr("tray.menu.diagnostics"))

    def handle_export_diag():
        from PySide6.QtWidgets import QMessageBox
        from areyoulowbattery.logger import export_diagnostic_report
        was_visible = popup is not None and popup.isVisible()
        if was_visible:
            popup.hide()
            QApplication.processEvents()
        try:
            path = export_diagnostic_report()
            QMessageBox.information(
                None,
                tr("tray.dialog.diag.title"),
                tr("tray.dialog.diag.body", path=path),
            )
        except Exception as e:
            QMessageBox.warning(
                None,
                tr("tray.dialog.diag_error.title"),
                tr("tray.dialog.diag_error.body", e=e),
            )
        finally:
            if was_visible:
                QTimer.singleShot(100, popup.show_centered_or_tray)

    diag_action.triggered.connect(handle_export_diag)

    update_action = menu.addAction(tr("tray.menu.updates"))
    from areyoulowbattery.updater import run_check_for_updates
    update_action.triggered.connect(lambda: run_check_for_updates(None, prompt_if_latest=True))

    uninstall_action = menu.addAction(tr("tray.menu.uninstall"))
    quit_action = menu.addAction(tr("tray.menu.quit"))
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(menu)

    # Dedicated clean settings menu for the Dashboard gear button (excludes redundant per-card actions)
    dashboard_settings_menu = QMenu()
    dashboard_settings_menu.setStyleSheet(menu.styleSheet())
    dashboard_settings_menu.addAction(find_action)
    dashboard_settings_menu.addAction(refresh_action)
    dashboard_settings_menu.addAction(game_mode_status)
    dashboard_settings_menu.addAction(pause_action)
    dashboard_settings_menu.addSeparator()
    register_language_menu(dashboard_settings_menu)
    dashboard_settings_menu.addSeparator()

    if sys.platform.startswith("linux"):
        udev_action = menu.addAction(tr("tray.menu.udev"))
        from areyoulowbattery.udev_installer import install_udev_rules
        udev_action.triggered.connect(lambda: install_udev_rules(None))
        dashboard_settings_menu.addAction(udev_action)

    dashboard_settings_menu.addAction(autostart_action)
    dashboard_settings_menu.addAction(diag_action)
    dashboard_settings_menu.addAction(update_action)
    dashboard_settings_menu.addSeparator()
    dashboard_settings_menu.addAction(uninstall_action)
    dashboard_settings_menu.addAction(quit_action)

    def retranslate_menus():
        """Re-applies the translated labels to every menu entry and the tray tooltip."""
        status_action.setText(
            tr("tray.status.no_device") if not current_supported_devices else tr("tray.status.reading")
        )
        find_action.setText(tr("tray.menu.find"))
        rename_action.setText(tr("tray.menu.rename"))
        type_action.setText(tr("tray.menu.change_type"))
        proto_action.setText(tr("tray.menu.change_protocol"))
        remove_action.setText(tr("tray.menu.remove"))
        refresh_action.setText(tr("tray.menu.refresh"))
        game_mode_status.setText(tr("tray.menu.game_mode_active"))
        pause_action.setText(tr("tray.menu.pause_polling"))
        autostart_action.setText(tr("tray.menu.autostart"))
        diag_action.setText(tr("tray.menu.diagnostics"))
        update_action.setText(tr("tray.menu.updates"))
        uninstall_action.setText(tr("tray.menu.uninstall"))
        quit_action.setText(tr("tray.menu.quit"))
        if sys.platform.startswith("linux"):
            udev_action.setText(tr("tray.menu.udev"))
        for submenu, entries in language_menus:
            submenu.setTitle(tr("menu.language"))
            for code, act in entries.items():
                act.setChecked(get_language() == code)
        if current_supported_devices:
            lines = [_format_device_line(prof, stat) for prof, stat in current_supported_devices]
            tray.setToolTip("\n".join(lines))
            for act, line in zip(dynamic_actions, lines):
                act.setText(line)
        else:
            tray.setToolTip(tr("tray.tooltip.no_device"))

    tray.show()
    if sys.platform == "win32":
        tray.showMessage(
            "AreYouLowBattery",
            tr("tray.notify.tray_started"),
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
                None,
                tr("tray.dialog.rename.title"),
                tr("tray.dialog.rename.select_prompt"),
                dev_names,
                0,
                False,
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            dev_name = current_supported_devices[idx][0].name

        new_name, ok = QInputDialog.getText(
            None,
            tr("tray.dialog.rename.title"),
            tr("tray.dialog.rename.new_name", name=dev_name),
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
            dev_dialog = QDialog()
            dev_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            dev_dialog.setWindowTitle(tr("tray.dialog.select_device.title"))
            dev_dialog.setWindowIcon(get_app_icon())
            dev_dialog.setFixedWidth(350)
            dev_dialog.setStyleSheet("""
                QDialog { background-color: #0f172a; color: #f8fafc; }
                QLabel { color: #f8fafc; font-size: 12px; }
                QComboBox { background-color: #1e293b; border: 1px solid #475569; border-radius: 6px; color: #f8fafc; padding: 6px; font-size: 12px; }
                QComboBox QAbstractItemView { background-color: #1e293b; color: #f8fafc; selection-background-color: #334155; }
                QPushButton#okBtn { background-color: #0284c7; color: #fff; border: none; border-radius: 6px; padding: 6px 14px; font-weight: 600; font-size: 12px; }
                QPushButton#cancelBtn { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 6px; padding: 6px 14px; font-size: 12px; }
            """)
            d_lay = QVBoxLayout(dev_dialog)
            d_lay.setContentsMargins(16, 16, 16, 16)
            d_lay.setSpacing(12)
            d_lay.addWidget(QLabel(tr("tray.dialog.select_device.change_type")))
            dev_cmb = QComboBox()
            dev_cmb.setIconSize(QSize(18, 18))
            for p, _ in current_supported_devices:
                dev_cmb.addItem(render_category_icon(p.category, size=18, color="#38bdf8"), p.name, p)
            d_lay.addWidget(dev_cmb)
            d_btns = QHBoxLayout()
            d_btns.addStretch(1)
            b_c = QPushButton(tr("common.cancel"))
            b_c.setObjectName("cancelBtn")
            b_c.clicked.connect(dev_dialog.reject)
            d_btns.addWidget(b_c)
            b_ok = QPushButton(tr("common.next"))
            b_ok.setObjectName("okBtn")
            b_ok.clicked.connect(dev_dialog.accept)
            d_btns.addWidget(b_ok)
            d_lay.addLayout(d_btns)
            if dev_dialog.exec() != QDialog.DialogCode.Accepted:
                return
            prof = dev_cmb.currentData()

        type_dialog = QDialog()
        type_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        type_dialog.setWindowTitle(tr("tray.dialog.change_type.title"))
        type_dialog.setWindowIcon(get_app_icon())
        type_dialog.setFixedWidth(360)
        type_dialog.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
            }
            QLabel {
                color: #f8fafc;
                font-size: 12px;
            }
            QComboBox {
                background-color: #1e293b;
                border: 1px solid #475569;
                border-radius: 6px;
                color: #f8fafc;
                padding: 6px 8px;
                font-size: 12px;
            }
            QComboBox:focus {
                border: 1px solid #38bdf8;
            }
            QComboBox QAbstractItemView {
                background-color: #1e293b;
                color: #f8fafc;
                selection-background-color: #334155;
                border: 1px solid #475569;
            }
            QPushButton#saveBtn {
                background-color: #0284c7;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton#saveBtn:hover {
                background-color: #0369a1;
            }
            QPushButton#cancelBtn {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton#cancelBtn:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)

        t_lay = QVBoxLayout(type_dialog)
        t_lay.setContentsMargins(18, 18, 18, 18)
        t_lay.setSpacing(14)

        desc = QLabel(tr("tray.dialog.change_type.prompt", name=prof.name))
        desc.setWordWrap(True)
        t_lay.addWidget(desc)

        cmb_cat = QComboBox()
        cmb_cat.setIconSize(QSize(18, 18))
        cats = [
            (tr("discovery.category.mouse"), DeviceCategory.MOUSE, "🖱️"),
            (tr("discovery.category.keyboard"), DeviceCategory.KEYBOARD, "⌨️"),
            (tr("discovery.category.headset"), DeviceCategory.HEADSET, "🎧"),
            (tr("discovery.category.gamepad"), DeviceCategory.GAMEPAD, "🎮"),
            (tr("discovery.category.other"), DeviceCategory.OTHER, "🔋"),
        ]
        curr_idx = 0
        for i, (name, cat_enum, emoji) in enumerate(cats):
            ico = render_category_icon(cat_enum, size=18, color="#38bdf8")
            cmb_cat.addItem(ico, name, (cat_enum.value, emoji))
            if cat_enum == prof.category:
                curr_idx = i
        cmb_cat.setCurrentIndex(curr_idx)
        t_lay.addWidget(cmb_cat)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.setObjectName("cancelBtn")
        btn_cancel.clicked.connect(type_dialog.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton(tr("common.save"))
        btn_save.setObjectName("saveBtn")
        btn_save.clicked.connect(type_dialog.accept)
        btn_row.addWidget(btn_save)
        t_lay.addLayout(btn_row)

        if type_dialog.exec() == QDialog.DialogCode.Accepted:
            cat_val, ico = cmb_cat.currentData()
            save_custom_category(prof.name, cat_val, ico)
            engine.profiles = load_all_profiles()
            wake_event.set()

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
                None,
                tr("tray.dialog.change_protocol.title"),
                tr("tray.dialog.change_protocol.select_device"),
                dev_names,
                0,
                False,
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            prof = current_supported_devices[idx][0]

        modes = [
            (tr("discovery.mode.compx_v1"), "compx_v1", None),
            (tr("discovery.mode.yjx_v1"), "yjx_v1", None),
            (tr("discovery.mode.gamesir_v1"), "gamesir_v1", None),
            (tr("discovery.mode.nordic_v1"), "nordic_v1", None),
            (tr("discovery.mode.hidpp_v2"), "hidpp_v2", None),
            (tr("discovery.mode.hidpp_v1"), "hidpp_v1", None),
            (tr("discovery.mode.razer_v1"), "razer_v1", None),
            (tr("discovery.mode.steelseries_v1"), "steelseries_v1", None),
            (tr("discovery.mode.corsair_v1"), "corsair_v1", None),
            (tr("discovery.mode.hyperx_v1"), "hyperx_v1", None),
            (tr("discovery.mode.actions_v1"), "actions_v1", None),
            (tr("discovery.mode.generic_hid"), "generic_hid", None),
            (tr("discovery.mode.requires_bluetooth"), "compx_v1", {"requires_bluetooth": True}),
            (tr("discovery.mode.is_wired"), "compx_v1", {"is_wired": True}),
        ]
        labels = [m[0] for m in modes]
        current_idx = 0
        for i, m in enumerate(modes):
            if m[1] == prof.protocol:
                current_idx = i
                break

        choice, ok = QInputDialog.getItem(
            None,
            tr("tray.dialog.change_protocol.title"),
            tr("tray.dialog.change_protocol.prompt", name=prof.name),
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
                None,
                tr("tray.dialog.remove.title"),
                tr("tray.dialog.remove.select_device"),
                dev_names,
                0,
                False,
            )
            if not ok or not choice:
                return
            idx = dev_names.index(choice)
            prof = current_supported_devices[idx][0]

        reply = QMessageBox.question(
            None,
            tr("tray.dialog.remove.title"),
            tr("tray.dialog.remove.confirm", name=prof.name),
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
            tr("tray.dialog.uninstall.title"),
            tr("tray.dialog.uninstall.confirm"),
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
    pause_polling = threading.Event()
    force_refresh = False

    def trigger_force_refresh():
        nonlocal force_refresh
        if pause_polling.is_set():
            return
        force_refresh = True
        wake_event.set()

    def show_game_mode(active: bool):
        game_mode_status.setVisible(active)
        refresh_action.setEnabled(not active)

    def set_polling_paused(paused: bool):
        if paused:
            pause_polling.set()
            show_game_mode(True)
        else:
            pause_polling.clear()
        wake_event.set()

    pause_action.toggled.connect(set_polling_paused)

    def handle_open_discovery():
        was_visible = popup is not None and popup.isVisible()
        if was_visible:
            popup.hide()
            QApplication.processEvents()
        from areyoulowbattery.discovery_dialog import DeviceDiscoveryDialog
        from areyoulowbattery.profile_loader import load_all_profiles

        def on_saved():
            engine.profiles = load_all_profiles()
            wake_event.set()

        dlg = DeviceDiscoveryDialog(
            profiles=engine.profiles,
            on_profile_created=on_saved,
            parent=None,
        )
        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        if was_visible:
            QTimer.singleShot(100, popup.show_centered_or_tray)

    find_action.triggered.connect(handle_open_discovery)

    def handle_device_action(action: str, prof: DeviceProfile):
        was_visible = popup.isVisible()
        if was_visible:
            popup.hide()
            QApplication.processEvents()
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
        updated = Signal(object, bool)
        auto_detected = Signal(object)  # AutoDetectEvent

    updater = Updater()
    pending_identify_click = {"active": False}
    engine = BatteryEngine()
    dynamic_actions = []
    # Tracks notification levels per device: key = profile.name, value = set of triggered thresholds (e.g. {15, 5})
    notified_thresholds: dict[str, set[int]] = {}
    def is_fullscreen_or_game_running(ttl: float = 15.0) -> bool:
        """Game Mode detection shared with the daemon/CLI (see areyoulowbattery.gamemode)."""
        from areyoulowbattery.gamemode import is_game_active
        return pause_polling.is_set() or is_game_active(ttl)

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
                        tr("tray.notify.critical.title", name=prof.name, pct=stat.percentage),
                        tr("tray.notify.critical.body"),
                        QSystemTrayIcon.MessageIcon.Critical,
                        6000
                    )
            # Low Battery: <= 15%
            elif stat.percentage <= 15 and 15 not in sent_levels and 5 not in sent_levels:
                sent_levels.add(15)
                _play_alert_sound(critical=False)
                if not in_game:
                    tray.showMessage(
                        tr("tray.notify.low.title", name=prof.name, pct=stat.percentage),
                        tr("tray.notify.low.body"),
                        QSystemTrayIcon.MessageIcon.Warning,
                        4500
                    )

    def write_cache(results: List[Tuple[DeviceProfile, BatteryStatus]]):
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
        tmp_file = None
        try:
            cache_dir = os.path.dirname(CACHE_FILE) or CACHE_DIR
            fd, tmp_file = tempfile.mkstemp(prefix=".areyoulowbattery_", suffix=".tmp", dir=cache_dir)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cached_data, f)
            if sys.platform != "win32":
                try:
                    os.chmod(tmp_file, 0o600)
                except OSError:
                    pass
            os.replace(tmp_file, CACHE_FILE)
            tmp_file = None
            if sys.platform != "win32":
                try:
                    os.chmod(CACHE_FILE, 0o600)
                except OSError:
                    pass
        except Exception:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
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
                        if is_fullscreen_or_game_running():
                            # Debounce longer in-game so USB bus renegotiations don't trigger wakeups
                            time.sleep(2.0)
                        else:
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
            time.sleep(5.0 if is_fullscreen_or_game_running() else 1.5)
            cur_sig = get_hid_topology_signature()
            if cur_sig != last_sig:
                last_sig = cur_sig
                time.sleep(1.0 if is_fullscreen_or_game_running() else 0.2)
                trigger_force_refresh()

    def worker():
        nonlocal force_refresh
        from areyoulowbattery.autodetect import AutoDetector
        from areyoulowbattery.profile_loader import load_all_profiles
        detector = AutoDetector()
        first_run = True
        while not stop_event.is_set():
            in_game = False
            try:
                is_force = force_refresh
                force_refresh = False
                in_game = is_fullscreen_or_game_running()
                if in_game:
                    is_force = False

                # Zero-config: on app start and on every hotplug/refresh, identify brand-new
                # peripherals (once per model) and set them up without any user action.
                # Skip automatic probing during competitive games to avoid background CPU/USB load!
                if (is_force or first_run) and not in_game:
                    first_run = False
                    try:
                        events = detector.run(engine.profiles)
                        if any(e.kind == "profiled" for e in events):
                            engine.profiles = load_all_profiles()
                        for ev in events:
                            updater.auto_detected.emit(ev)
                    except Exception as e:
                        print(f"Auto-detect error: {e}", file=sys.stderr, flush=True)

                results = engine.poll_all_devices(force=is_force, in_game=in_game)
                write_cache(results)
                updater.updated.emit(results, in_game)
            except Exception as e:
                print(f"Tray worker error: {e}", file=sys.stderr, flush=True)
            # In Game Mode, relax polling to 120s to ensure zero interference with competitive gameplay.
            # In regular desktop mode, default to 10s.
            wake_event.wait(timeout=120.0 if in_game else 10.0)
            wake_event.clear()

    last_ui_sig = object()

    def on_updated(results: List[Tuple[DeviceProfile, BatteryStatus]], in_game: bool):
        nonlocal current_supported_devices, dynamic_actions, last_ui_sig
        show_game_mode(in_game or pause_polling.is_set())
        supported = [(p, s) for p, s in results if s.supported]
        current_supported_devices = supported
        popup.update_devices(supported)

        ui_sig = tuple(
            (
                p.name, p.icon, s.percentage, s.is_charging,
                s.is_connected, s.is_wired, s.requires_bluetooth,
            )
            for p, s in supported
        )
        if ui_sig == last_ui_sig:
            if supported:
                check_battery_notifications(supported)
            return
        last_ui_sig = ui_sig

        if not supported:
            if not menu.isVisible():
                for act in dynamic_actions:
                    menu.removeAction(act)
                dynamic_actions.clear()
            tray.setIcon(_render_tray_icon(None, False, False))
            tray.setToolTip(tr("tray.tooltip.no_device"))
            status_action.setVisible(True)
            status_action.setText(tr("tray.status.no_device"))
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
            last_ui_sig = object()
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
