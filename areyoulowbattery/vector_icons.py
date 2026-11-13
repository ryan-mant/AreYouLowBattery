"""
Vector icon generator for AreYouLowBattery.
Renders crisp, resolution-independent vector icons directly via QPainter,
completely eliminating missing glyphs, fontconfig discrepancies, and COLRv1 emoji bugs across platforms.
"""

from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QPainterPath, QIcon
from PySide6.QtCore import Qt, QRectF
from areyoulowbattery.models import DeviceCategory


def render_category_pixmap(category: DeviceCategory, size: int = 20, color: str = "#38bdf8") -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    s = size / 24.0
    p.scale(s, s)

    if category == DeviceCategory.MOUSE:
        p.drawRoundedRect(QRectF(5, 3, 14, 18), 7, 7)
        p.drawLine(12, 3, 12, 10)
        p.fillRect(QRectF(11, 6, 2, 4), QColor(color))
    elif category == DeviceCategory.KEYBOARD:
        p.drawRoundedRect(QRectF(3, 6, 18, 12), 2.5, 2.5)
        for x in (6, 9, 12, 15, 18):
            p.drawPoint(x, 10)
        p.drawLine(8, 14, 16, 14)
    elif category == DeviceCategory.HEADSET:
        p.drawArc(QRectF(4, 3, 16, 16), 0, 180 * 16)
        p.drawRoundedRect(QRectF(3, 11, 4, 8), 2, 2)
        p.drawRoundedRect(QRectF(17, 11, 4, 8), 2, 2)
    elif category == DeviceCategory.GAMEPAD:
        path = QPainterPath()
        path.addRoundedRect(QRectF(3, 6, 18, 12), 4, 4)
        p.drawPath(path)
        p.drawLine(7, 10, 7, 14)
        p.drawLine(5, 12, 9, 12)
        p.drawPoint(16, 11)
        p.drawPoint(18, 13)
    else:
        p.drawRoundedRect(QRectF(4, 7, 14, 10), 2, 2)
        p.fillRect(QRectF(18, 10, 2, 4), QColor(color))
        p.fillRect(QRectF(7, 9, 8, 6), QColor(color))

    p.end()
    return pix


def render_search_icon(size: int = 16, color: str = "#cbd5e1") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = size / 16.0
    p.scale(s, s)
    p.drawEllipse(QRectF(2.5, 2.5, 8.0, 8.0))
    p.drawLine(8.5, 8.5, 13.5, 13.5)
    p.end()
    return QIcon(pix)


def render_refresh_icon(size: int = 16, color: str = "#cbd5e1") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = size / 16.0
    p.scale(s, s)
    p.drawArc(QRectF(2.5, 2.5, 11, 11), 45 * 16, 270 * 16)
    p.drawLine(8, 2, 12.5, 2.5)
    p.drawLine(12.5, 2.5, 11.5, 7)
    p.end()
    return QIcon(pix)


def render_gear_icon(size: int = 16, color: str = "#cbd5e1") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = size / 16.0
    p.scale(s, s)
    p.drawEllipse(QRectF(5, 5, 6, 6))
    for angle in (0, 45, 90, 135):
        p.save()
        p.translate(8, 8)
        p.rotate(angle)
        p.drawLine(-7, 0, 7, 0)
        p.restore()
    p.end()
    return QIcon(pix)


def render_close_icon(size: int = 16, color: str = "#cbd5e1") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    s = size / 16.0
    p.scale(s, s)
    p.drawLine(4, 4, 12, 12)
    p.drawLine(12, 4, 4, 12)
    p.end()
    return QIcon(pix)
