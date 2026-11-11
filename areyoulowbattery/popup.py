from typing import List, Tuple, Callable, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QApplication, QMenu
)
from PySide6.QtCore import Qt, QPoint, QEvent, QRectF
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QColor, QPainterPath

from areyoulowbattery.models import DeviceProfile, BatteryStatus


def _pick_accent_color(
    pct: Optional[int],
    is_charging: bool,
    is_connected: bool,
    is_wired: bool = False,
    requires_bluetooth: bool = False,
) -> str:
    if requires_bluetooth:
        return "#38bdf8"  # informational sky blue
    if is_wired:
        return "#38bdf8"  # continuous USB power
    if not is_connected:
        return "#64748b"  # muted slate
    if is_charging:
        return "#38bdf8"  # sky blue
    if pct is None:
        return "#38bdf8"
    if pct <= 15:
        return "#f87171"  # red
    if pct <= 40:
        return "#facc15"  # yellow
    return "#4ade80"      # green


class RoundedBatteryBar(QWidget):
    """Custom antialiased pill-shaped progress bar for crisp rounded corners on all themes."""

    def __init__(self, value: int, color_hex: str, parent=None):
        super().__init__(parent)
        self._value = max(0, min(100, value))
        self._color = QColor(color_hex)
        self._bg_color = QColor("#0f172a")
        self.setFixedHeight(8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        radius = h / 2.0

        track_path = QPainterPath()
        track_path.addRoundedRect(QRectF(0.0, 0.0, w, h), radius, radius)
        painter.fillPath(track_path, self._bg_color)

        if self._value > 0:
            fill_w = max(h, w * (self._value / 100.0))
            painter.setClipPath(track_path)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(QRectF(0.0, 0.0, fill_w, h), radius, radius)
            painter.fillPath(fill_path, self._color)
        painter.end()


class DeviceCard(QFrame):
    """A sleek card widget displaying a single peripheral's battery telemetry."""

    def __init__(self, profile: DeviceProfile, status: BatteryStatus, parent=None):
        super().__init__(parent)
        self.setObjectName("deviceCard")
        accent = _pick_accent_color(
            status.percentage,
            status.is_charging,
            status.is_connected,
            is_wired=status.is_wired,
            requires_bluetooth=status.requires_bluetooth,
        )

        self.setStyleSheet(f"""
            QFrame#deviceCard {{
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                color: #f8fafc;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Top row: Icon + Name on left, Status / Percentage badge on right
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        name_lbl = QLabel(f"{profile.icon}  {profile.name}")
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #f1f5f9;")
        top_row.addWidget(name_lbl, 1)

        if status.requires_bluetooth:
            pct_text = "BT Req."
            badge_style = "font-size: 11px; font-weight: 700; color: #38bdf8; background-color: #0f172a; padding: 2px 7px; border-radius: 4px;"
        elif status.is_wired:
            pct_text = "🔌 Wired"
            badge_style = "font-size: 11px; font-weight: 700; color: #38bdf8; background-color: #0f172a; padding: 2px 7px; border-radius: 4px;"
        elif not status.is_connected:
            pct_text = "OFF"
            badge_style = f"font-size: 15px; font-weight: 700; color: {accent};"
        elif status.percentage is not None:
            pct_text = f"{status.percentage}%" + (" ⚡" if status.is_charging else "")
            badge_style = f"font-size: 15px; font-weight: 700; color: {accent};"
        else:
            pct_text = "⚡"
            badge_style = f"font-size: 15px; font-weight: 700; color: {accent};"

        pct_lbl = QLabel(pct_text)
        pct_lbl.setStyleSheet(badge_style)
        pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(pct_lbl)

        layout.addLayout(top_row)

        # Middle row: Pill-shaped progress bar (uniform across all cards)
        if status.requires_bluetooth:
            bar = RoundedBatteryBar(0, "#38bdf8", self)
            layout.addWidget(bar)
        elif status.is_wired:
            bar = RoundedBatteryBar(100, accent, self)
            layout.addWidget(bar)
        else:
            if not status.is_connected:
                bar_val = 0
            elif status.percentage is not None:
                bar_val = max(0, min(100, status.percentage))
            else:
                bar_val = 100 if status.is_charging else 0
            bar = RoundedBatteryBar(bar_val, accent, self)
            layout.addWidget(bar)

        # Bottom row: Status text on left, Protocol/Mode on right
        bot_row = QHBoxLayout()
        bot_row.setSpacing(6)

        if status.requires_bluetooth:
            state_str = "Connect via Bluetooth to monitor"
        elif status.is_wired:
            state_str = "Wired device • Continuous power"
        elif not status.is_connected:
            state_str = "Disconnected / Deep Sleep"
        elif status.is_charging:
            eta_str = status.format_eta()
            if status.percentage is not None and status.percentage >= 100:
                state_str = "⚡ Fully Charged"
            elif eta_str:
                state_str = f"⚡ Charging • {eta_str}"
            else:
                state_str = "⚡ Charging via cable/dock"
        else:
            if status.percentage is not None and status.percentage <= 5:
                state_str = "Critical Battery — Charge now!"
            elif status.percentage is not None and status.percentage <= 15:
                state_str = "Low Battery"
            else:
                state_str = "Active • Discharging"

        state_lbl = QLabel(state_str)
        state_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        bot_row.addWidget(state_lbl, 1)

        proto_map = {
            "compx_v1": "2.4G / USB",
            "nordic_v1": "4K/8K RF",
            "hidpp_v2": "Lightspeed",
            "razer_v1": "HyperSpeed",
            "steelseries_v1": "SteelSeries",
            "corsair_v1": "Slipstream",
            "hyperx_v1": "HyperX",
            "sysfs_power_supply": "System / BT",
            "bluetooth": "Bluetooth",
            "actions_v1": "2.4G Dongle",
            "generic_hid": "Standard HID",
        }
        if status.requires_bluetooth:
            proto_badge = "2.4G Dongle"
        elif status.is_wired:
            proto_badge = "Wired USB"
        else:
            proto_badge = proto_map.get(profile.protocol, profile.protocol)

        proto_lbl = QLabel(proto_badge)
        proto_lbl.setStyleSheet(
            "font-size: 10px; color: #64748b; background-color: #0f172a; "
            "padding: 2px 6px; border-radius: 4px;"
        )
        bot_row.addWidget(proto_lbl)

        layout.addLayout(bot_row)


class BatteryPopup(QWidget):
    """
    Lightweight, zero-background-cost flyout dashboard shown on tray left-click.
    Uses Qt.Popup so clicking anywhere outside dismisses it natively.
    """

    def __init__(
        self,
        on_refresh: Callable[[], None],
        context_menu: QMenu,
        on_open_discovery: Optional[Callable[[], None]] = None,
    ):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._on_refresh = on_refresh
        self._context_menu = context_menu
        self._on_open_discovery = on_open_discovery
        self._devices: List[Tuple[DeviceProfile, BatteryStatus]] = []
        self._last_updated_ts: float = 0.0

        self.setFixedWidth(350)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame(self)
        self.container.setObjectName("popupContainer")
        self.container.setStyleSheet("""
            QFrame#popupContainer {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 14px;
            }
            QPushButton#iconBtn {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#iconBtn:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)
        outer_layout.addWidget(self.container)

        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setContentsMargins(14, 14, 14, 12)
        self.main_layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        header.setSpacing(6)

        title = QLabel("AreYouLowBattery")
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f8fafc; border: none;")
        header.addWidget(title, 1)

        self.find_btn = QPushButton("🔍")
        self.find_btn.setObjectName("iconBtn")
        self.find_btn.setToolTip("Find & configure new devices")
        self.find_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.find_btn.clicked.connect(self._open_discovery)
        header.addWidget(self.find_btn)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("iconBtn")
        self.refresh_btn.setToolTip("Refresh battery now")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._handle_refresh)
        header.addWidget(self.refresh_btn)

        self.menu_btn = QPushButton("⚙")
        self.menu_btn.setObjectName("iconBtn")
        self.menu_btn.setToolTip("Options & Settings")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.clicked.connect(self._open_settings_menu)
        header.addWidget(self.menu_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("iconBtn")
        self.close_btn.setToolTip("Close")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)

        self.main_layout.addLayout(header)

        # Cards area
        self.cards_container = QWidget(self.container)
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.main_layout.addWidget(self.cards_container)

        # Footer
        self.footer_lbl = QLabel("Click ⚙ for device settings & autostart")
        self.footer_lbl.setStyleSheet("font-size: 10px; color: #64748b; border: none;")
        self.footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.footer_lbl)

    def _handle_refresh(self):
        self.footer_lbl.setText("Refreshing telemetry...")
        self._on_refresh()

    def _open_discovery(self):
        self.hide()
        if self._on_open_discovery:
            self._on_open_discovery()

    def _open_settings_menu(self):
        btn_pos = self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height() + 4))
        self._context_menu.popup(btn_pos)

    def update_devices(self, devices: List[Tuple[DeviceProfile, BatteryStatus]]):
        self._devices = devices
        # Zero background overhead: only rebuild widgets if the popup is currently open!
        if self.isVisible():
            self._rebuild_cards()

    def _rebuild_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._devices:
            empty_box = QFrame(self.cards_container)
            empty_box.setStyleSheet("""
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 16px;
            """)
            eb_layout = QVBoxLayout(empty_box)
            eb_layout.setSpacing(10)
            empty_lbl = QLabel("No supported wireless peripheral detected.")
            empty_lbl.setStyleSheet("font-size: 12px; color: #94a3b8; border: none;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            eb_layout.addWidget(empty_lbl)

            find_btn = QPushButton("🔍 Find New Devices")
            find_btn.setObjectName("iconBtn")
            find_btn.setStyleSheet("""
                background-color: #0284c7;
                color: #ffffff;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 6px;
                border: none;
            """)
            find_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            find_btn.clicked.connect(self._open_discovery)
            eb_layout.addWidget(find_btn, 0, Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(empty_box)
        else:
            # Show active battery peripherals first, then wired, then bluetooth-required, then disconnected
            def _sort_key(item):
                prof, stat = item
                if not stat.is_connected:
                    return (4, prof.name)
                if stat.requires_bluetooth:
                    return (3, prof.name)
                if stat.is_wired:
                    return (2, prof.name)
                return (1, prof.name)

            sorted_devs = sorted(self._devices, key=_sort_key)
            for prof, stat in sorted_devs:
                self.cards_layout.addWidget(DeviceCard(prof, stat, self.cards_container))

        self.footer_lbl.setText("Right-click tray icon or click ⚙ for options")
        self.adjustSize()

    def toggle_at_cursor(self):
        if self.isVisible():
            self.hide()
            return

        self._rebuild_cards()
        self.adjustSize()

        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = self.width()
            h = self.height()

            # Center horizontally on cursor, clamp inside available screen bounds
            x = max(avail.left() + 8, min(cursor_pos.x() - w // 2, avail.right() - w - 8))

            # If cursor is in the bottom half of the screen (bottom taskbar), place popup above cursor
            if cursor_pos.y() > avail.center().y():
                y = max(avail.top() + 8, cursor_pos.y() - h - 12)
            else:
                y = min(avail.bottom() - h - 8, cursor_pos.y() + 12)

            self.move(x, y)
        else:
            self.move(cursor_pos)

        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if not self._context_menu.isVisible():
                self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            wh = self.windowHandle()
            if wh is not None:
                try:
                    wh.startSystemMove()
                except Exception:
                    pass
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and getattr(self, "_drag_offset", None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
