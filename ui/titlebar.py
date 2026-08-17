"""自定义无边框窗口标题栏:应用图标 + 系统原生拖动 + 设置/关闭等按钮。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class _TitleButton(QPushButton):
    """标题栏单按钮,自绘 hover(关闭按钮 hover 变红)。"""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind  # 'min' / 'max' / 'close' / 'settings'
        self._hover = False
        self._pressed = False
        self.setFixedSize(42, 36)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._pressed = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        if self._hover:
            if self._kind == "close":
                color = QColor(232, 17, 35)         # #e11123
            else:
                color = QColor(255, 255, 255, 30)
            p.fillRect(self.rect(), color)
            if self._pressed:
                if self._kind == "close":
                    p.fillRect(self.rect(), QColor(180, 10, 25))
                else:
                    p.fillRect(self.rect(), QColor(255, 255, 255, 45))

        pen = QPen(QColor(235, 235, 235), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)

        cx = self.width() / 2
        cy = self.height() / 2
        s = 6
        if self._kind == "close":  # X
            p.drawLine(int(cx - s), int(cy - s), int(cx + s), int(cy + s))
            p.drawLine(int(cx + s), int(cy - s), int(cx - s), int(cy + s))
        elif self._kind == "min":  # 横线
            p.drawLine(int(cx - s), int(cy), int(cx + s), int(cy))
        elif self._kind == "max":  # 方框
            p.setBrush(Qt.NoBrush)
            p.drawRect(int(cx - s), int(cy - s), int(2 * s), int(2 * s))
        elif self._kind == "settings":  # 齿轮:实体圆 + 齿 + 中心孔
            import math
            from PySide6.QtCore import QPointF, QRectF
            color = QColor(235, 235, 235)
            # 外圈实体(齿轮本体)
            body_pen = QPen(color, 1.8)
            body_pen.setCapStyle(Qt.RoundCap)
            p.setPen(body_pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - 5.5, cy - 5.5, 11.0, 11.0))
            # 6个矩形齿(从外圈向外延伸)
            tooth_pen = QPen(color, 2.0)
            tooth_pen.setCapStyle(Qt.FlatCap)
            p.setPen(tooth_pen)
            for i in range(6):
                a = (2 * math.pi * i) / 6
                # 齿根在外圈上(r=5.5),齿尖在r=8.0
                p.drawLine(
                    QPointF(cx + 5.5 * math.cos(a), cy + 5.5 * math.sin(a)),
                    QPointF(cx + 8.0 * math.cos(a), cy + 8.0 * math.sin(a)),
                )
            # 中心小圆孔(齿轮轴孔)
            p.setPen(QPen(color, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - 1.8, cy - 1.8, 3.6, 3.6))
        p.end()


class TitleBar(QWidget):
    """自定义标题栏:应用图标 + 标题 + 系统原生拖动 + 右侧控制按钮。"""

    def __init__(self, parent=None, on_settings=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self._on_settings = on_settings

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        # 应用图标
        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(20, 20)
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._icon_label.setStyleSheet("background:transparent;")
        layout.addWidget(self._icon_label)
        layout.addSpacing(8)

        self._title_label = QPushButton("WebDownload 资源爬虫", self)
        self._title_label.setFlat(True)
        self._title_label.setCursor(Qt.ArrowCursor)
        self._title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._title_label.setStyleSheet(
            "QPushButton{background:transparent;color:rgba(255,255,255,215);"
            "border:none;font-size:13px;font-weight:600;}"
        )
        layout.addWidget(self._title_label)
        layout.addStretch()

        if on_settings is not None:
            self.btn_settings = _TitleButton("settings", self)
            self.btn_settings.setToolTip("设置")
            self.btn_settings.clicked.connect(self._open_settings)
            layout.addWidget(self.btn_settings)

        self.btn_min = _TitleButton("min", self)
        self.btn_max = _TitleButton("max", self)
        self.btn_close = _TitleButton("close", self)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

        self.btn_max.clicked.connect(self._toggle_maximize)
        self.btn_min.clicked.connect(self._minimize)
        self.btn_close.clicked.connect(self._close)

    # ---- 图标 ----
    def set_icon(self, icon):
        pm = icon.pixmap(20, 20)
        self._icon_label.setPixmap(pm)

    # ---- 窗口控制 ----
    def _open_settings(self):
        if self._on_settings:
            self._on_settings()

    def _toggle_maximize(self):
        win = self.window()
        if hasattr(win, "toggle_maximize"):
            win.toggle_maximize()
        elif win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()

    def _minimize(self):
        self.window().showMinimized()

    def _close(self):
        self.window().close()

    # ---- 系统原生拖动:交给 OS 处理,流畅且支持贴边吸附 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle_maximize()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)
