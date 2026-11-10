from typing import List, Tuple, Callable, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QApplication, QMenu
)
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QCursor, QGuiApplication

from areyoulowbattery.models import DeviceProfile, BatteryStatus


def _pick_accent_color(pct: Optional[int], is_charging: bool, is_connected: bool) -> str:
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


class DeviceCard(QFrame):
    """A sleek card widget displaying a single peripheral's battery telemetry."""

    def __init__(self, profile: DeviceProfile, status: BatteryStatus, parent=None):
        super().__init__(parent)
        self.setObjectName("deviceCard")
        accent = _pick_accent_color(status.percentage, status.is_charging, status.is_connected)

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
            QProgressBar {{
                background-color: #0f172a;
                border: none;
                border-radius: 4px;
                height: 8px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Top row: Icon + Name on left, Percentage badge on right
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        name_lbl = QLabel(f"{profile.icon}  {profile.name}")
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #f1f5f9;")
        top_row.addWidget(name_lbl, 1)

        if not status.is_connected:
            pct_text = "OFF"
        elif status.percentage is not None:
            pct_text = f"{status.percentage}%" + (" ⚡" if status.is_charging else "")
        else:
            pct_text = "⚡"

        pct_lbl = QLabel(pct_text)
        pct_lbl.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {accent};")
        pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(pct_lbl)

        layout.addLayout(top_row)

        # Middle row: Progress bar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(7)
        if not status.is_connected:
            bar.setValue(0)
        elif status.percentage is not None:
            bar.setValue(max(0, min(100, status.percentage)))
        else:
            bar.setValue(100 if status.is_charging else 0)
        layout.addWidget(bar)

        # Bottom row: Status text on left, Protocol/Mode on right
        bot_row = QHBoxLayout()
        bot_row.setSpacing(6)

        if not status.is_connected:
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
            "sysfs_power_supply": "System / BT",
        }
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
        self._devices: List[Tuple[DeviceProfile, BatteryStatus]] = []
        self._last_updated_ts: float = 0.0

        self.setFixedWidth(330)

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
            empty = QLabel("No supported wireless peripheral detected.")
            empty.setStyleSheet(
                "font-size: 12px; color: #94a3b8; background-color: #1e293b; "
                "border: 1px solid #334155; border-radius: 10px; padding: 18px;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(empty)
        else:
            # Show connected devices first
            sorted_devs = sorted(self._devices, key=lambda item: (not item[1].is_connected, item[0].name))
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
