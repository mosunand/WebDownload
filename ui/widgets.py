"""自绘通用控件:Card 玻璃容器、GlassButton 药丸按钮、IOSSwitch 开关。"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, Property, QPropertyAnimation, QRectF, Qt,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QCheckBox, QPushButton, QWidget


class Card(QWidget):
    """圆角玻璃容器:半透明底 + 顶部一道高光,模拟 iOS 玻璃面板。"""

    def __init__(self, parent=None, radius: int = 14):
        super().__init__(parent)
        self._radius = radius
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        # 底:深色半透明玻璃,不透明度足够保证文字可读
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(28, 30, 42, 165))
        grad.setColorAt(1.0, QColor(22, 24, 34, 145))
        p.fillPath(path, QBrush(grad))

        # 顶部高光条(玻璃受光边)
        hl = QLinearGradient(0, 0, self.width(), 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, 45))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        hl_pen = QPen(QBrush(hl), 1.0)
        p.setPen(hl_pen)
        p.drawLine(int(self._radius), 1, int(self.width() - self._radius), 1)

        # 细描边
        pen = QPen(QColor(255, 255, 255, 35))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


class GlassButton(QPushButton):
    """iOS 药丸按钮:全圆角 + 微渐变 + hover/pressed/disabled 态 + 按压回弹动画。"""

    def __init__(self, text: str, parent=None, primary: bool = False):
        super().__init__(text, parent)
        self._primary = primary
        self._hover = False
        self._pressed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self.setMinimumWidth(84)

        # 按压缩放:1.0 正常,按下缩到 ~0.94,松开回弹
        self._scale = 1.0
        self._scale_anim = QPropertyAnimation(self, b"pressScale", self)
        self._scale_anim.setDuration(140)
        self._scale_anim.setEasingCurve(QEasingCurve.OutCubic)

    # ---- 缩放属性(动画驱动) ----
    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float):
        self._scale = v
        self.update()

    pressScale = Property(float, _get_scale, _set_scale)

    def _animate_scale(self, target: float, duration: int, curve):
        self._scale_anim.stop()
        self._scale_anim.setDuration(duration)
        self._scale_anim.setEasingCurve(curve)
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(target)
        self._scale_anim.start()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._pressed = False
        # 鼠标移出时若还按着,也弹回
        self._animate_scale(1.0, 160, QEasingCurve.OutCubic)
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._pressed = True
        # 快速按下缩小
        self._animate_scale(0.92, 90, QEasingCurve.OutCubic)
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed:
            # 松开回弹:OutBack 会轻微过冲,模拟"弹起来"
            self._animate_scale(1.0, 260, QEasingCurve.OutBack)
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # 按压回弹:围绕中心缩放整体绘制
        if self._scale != 1.0:
            cx, cy = self.width() / 2.0, self.height() / 2.0
            p.translate(cx, cy)
            p.scale(self._scale, self._scale)
            p.translate(-cx, -cy)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = rect.height() / 2.0  # 药丸:全圆角
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        enabled = self.isEnabled()

        if self._primary:
            c_top = QColor(70, 130, 220)  # 不透明蓝色
            c_bot = QColor(50, 110, 200)
            text_color = QColor(255, 255, 255)
        else:
            c_top = QColor(55, 58, 72)  # 不透明深灰
            c_bot = QColor(42, 45, 58)
            text_color = QColor(238, 238, 240)

        if self._pressed:
            if self._primary:
                c_top = QColor(55, 110, 200)
                c_bot = QColor(40, 90, 180)
            else:
                c_top = QColor(65, 68, 82)
                c_bot = QColor(50, 53, 68)
        elif self._hover:
            if self._primary:
                c_top = QColor(85, 145, 235)
                c_bot = QColor(65, 125, 215)
            else:
                c_top = QColor(62, 66, 82)
                c_bot = QColor(48, 52, 66)

        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, c_top)
        grad.setColorAt(1.0, c_bot)

        if not enabled:
            # 禁用:整体压暗
            dim_top = QColor(c_top)
            dim_top.setAlpha(max(40, c_top.alpha() // 3))
            dim_bot = QColor(c_bot)
            dim_bot.setAlpha(max(35, c_bot.alpha() // 3))
            grad.setColorAt(0.0, dim_top)
            grad.setColorAt(1.0, dim_bot)
            text_color = QColor(255, 255, 255, 90)

        p.fillPath(path, QBrush(grad))

        # 顶部高光(玻璃)
        if enabled:
            hl = QLinearGradient(0, 0, self.width(), 0)
            hl.setColorAt(0.0, QColor(255, 255, 255, 0))
            hl.setColorAt(0.5, QColor(255, 255, 255, 90 if self._primary else 60))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(QPen(QBrush(hl), 1.0))
            inset = radius * 0.7
            p.drawLine(int(inset), 1, int(self.width() - inset), 1)

        # 描边
        edge_alpha = 120 if self._primary else 65
        if not enabled:
            edge_alpha //= 2
        pen = QPen(QColor(255, 255, 255, edge_alpha))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)

        # 文字
        p.setPen(text_color)
        font = QFont()
        font.setPointSize(10)
        if self._primary:
            font.setBold(True)
        p.setFont(font)
        p.drawText(rect, Qt.AlignCenter, self.text())
        p.end()


class IOSSwitch(QCheckBox):
    """iOS 风格滑动开关:圆角轨道 + 圆形滑块,带滑动动画。

    点击切换,滑块在轨道两端平滑移动;选中为 iOS 绿,未选中为灰色轨道。
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(30)

        # 轨道/滑块尺寸
        self._track_w = 44
        self._track_h = 26
        self._knob = 22

        # 动画进度 0.0(关) .. 1.0(开)
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.toggled.connect(self._animate)

    # ---- Qt 属性,供动画驱动 ----
    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, v: float):
        self._pos = v
        self.update()

    knobPos = Property(float, _get_pos, _set_pos)

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        fm = self.fontMetrics()
        w = self._track_w + 10 + fm.horizontalAdvance(self.text()) + 4
        h = max(self._track_h, fm.height()) + 4
        return QSize(w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        tx = 0
        ty = (self.height() - self._track_h) / 2
        track = QRectF(tx, ty, self._track_w, self._track_h)

        # 轨道颜色:按进度在灰与 iOS 绿之间插值
        off = QColor(100, 100, 110, 160)
        on = QColor(52, 199, 89)  # iOS 绿 #34c759
        r = off.red() + (on.red() - off.red()) * self._pos
        g = off.green() + (on.green() - off.green()) * self._pos
        b = off.blue() + (on.blue() - off.blue()) * self._pos
        a = off.alpha() + (on.alpha() - off.alpha()) * self._pos
        track_color = QColor(int(r), int(g), int(b), int(a))

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(track_color))
        p.drawRoundedRect(track, self._track_h / 2, self._track_h / 2)

        # 滑块(白色圆,带一点阴影感)
        pad = 2
        travel = self._track_w - self._knob - pad * 2
        kx = tx + pad + travel * self._pos
        ky = ty + (self._track_h - self._knob) / 2
        knob = QRectF(kx, ky, self._knob, self._knob)
        # 阴影
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(kx, ky + 1, self._knob, self._knob))
        # 本体
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(knob)

        # 文字
        text = self.text()
        if text:
            text_x = self._track_w + 10
            p.setPen(QColor(235, 235, 235))
            font = QFont()
            font.setPointSize(10)
            p.setFont(font)
            p.drawText(
                int(text_x), 0,
                int(self.width() - text_x), int(self.height()),
                Qt.AlignVCenter | Qt.AlignLeft, text,
            )
        p.end()

    def mouseReleaseEvent(self, e):
        # 整个控件区域都可点击切换
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.toggle()
        super().mouseReleaseEvent(e)


# 兼容旧引用:FlatCheckBox 保留为 IOSSwitch 的别名(若别处仍在 import)
FlatCheckBox = IOSSwitch


class DragHandle(QWidget):
    """可见的窗口拖动把手:一条圆角小横杠 + 提示文字,按住即可拖动窗口。

    用系统原生 startSystemMove,拖动流畅。hover 时把手变亮提示可拖。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("按住这里拖动窗口")
        self._hover = False
        self._dragging = False

    def enterEvent(self, e):
        self._hover = True
        self.setCursor(Qt.OpenHandCursor)
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        if not self._dragging:
            self.unsetCursor()
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor if self._hover else Qt.ArrowCursor)
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # 中央小横杠(iOS 页面指示把手风格)
        bar_w, bar_h = 44, 5
        bx = (self.width() - bar_w) / 2
        by = (self.height() - bar_h) / 2 - 1
        alpha = 110 if (self._hover or self._dragging) else 55
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, alpha))
        p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), bar_h / 2, bar_h / 2)

        # hover 时显示提示文字
        if self._hover or self._dragging:
            font = QFont()
            font.setPointSize(8)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 100))
            p.drawText(
                QRectF(0, 0, bx - 8, self.height()),
                Qt.AlignVCenter | Qt.AlignRight, "拖",
            )
        p.end()
