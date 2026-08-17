"""设置对话框:保存目录 / 并发数 / 自定义图标,无边框玻璃风。

改动写入 config.json,并立即通过回调应用到主窗口。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout, QWidget,
)

from ui.widgets import Card, GlassButton
from utils import config as app_config
from utils import glass
from utils.icon import get_app_icon, default_pixmap


class SettingsDialog(QDialog):
    """设置对话框。保存后通过 applied 信号把新配置发出去。"""

    applied = Signal(dict)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = dict(cfg)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedWidth(520)

        self._build_ui()
        self._load_into_widgets()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 标题
        title_row = QHBoxLayout()
        title = QLabel("设置", self)
        title.setObjectName("dialogTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.btn_close = GlassButton("✕", self)
        self.btn_close.setFixedSize(34, 34)
        self.btn_close.clicked.connect(self.reject)
        title_row.addWidget(self.btn_close)
        root.addLayout(title_row)

        # 内容卡片
        card = Card(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)

        # 保存目录
        lay.addWidget(self._hint("默认保存目录"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_edit = QLineEdit(card)
        self.dir_edit.setPlaceholderText("留空 = 程序目录/downloads")
        dir_row.addWidget(self.dir_edit, 1)
        self.btn_browse = GlassButton("浏览", card)
        self.btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.btn_browse)
        lay.addLayout(dir_row)

        # 并发数
        lay.addWidget(self._hint("同时下载数量(并发线程)"))
        self.workers_spin = QSpinBox(card)
        self.workers_spin.setRange(1, 32)
        self.workers_spin.setMinimumHeight(34)
        lay.addWidget(self.workers_spin)

        # 自定义图标
        lay.addWidget(self._hint("自定义图标(png / ico,留空用默认)"))
        icon_row = QHBoxLayout()
        icon_row.setSpacing(10)
        self.icon_preview = QLabel(card)
        self.icon_preview.setFixedSize(48, 48)
        self.icon_preview.setStyleSheet("background:transparent;")
        icon_row.addWidget(self.icon_preview)

        icon_btns = QVBoxLayout()
        icon_btns.setSpacing(6)
        icon_path_row = QHBoxLayout()
        icon_path_row.setSpacing(8)
        self.icon_edit = QLineEdit(card)
        self.icon_edit.setPlaceholderText("选择图片文件...")
        self.icon_edit.textChanged.connect(self._refresh_icon_preview)
        icon_path_row.addWidget(self.icon_edit, 1)
        self.btn_icon = GlassButton("选择", card)
        self.btn_icon.clicked.connect(self._browse_icon)
        icon_path_row.addWidget(self.btn_icon)
        icon_btns.addLayout(icon_path_row)

        self.btn_default_icon = GlassButton("恢复默认图标", card)
        self.btn_default_icon.clicked.connect(self._reset_icon)
        icon_btns.addWidget(self.btn_default_icon)
        icon_row.addLayout(icon_btns, 1)
        lay.addLayout(icon_row)

        root.addWidget(card)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        self.btn_cancel = GlassButton("取消", self)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = GlassButton("保存", self, primary=True)
        self.btn_save.setMinimumWidth(100)
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

    def _hint(self, text: str) -> QLabel:
        lb = QLabel(text, self)
        lb.setObjectName("hintLabel")
        return lb

    # ---------- 数据 <-> 控件 ----------
    def _load_into_widgets(self):
        self.dir_edit.setText(self._cfg.get("save_dir", ""))
        self.workers_spin.setValue(int(self._cfg.get("max_workers", 6) or 6))
        self.icon_edit.setText(self._cfg.get("icon_path", ""))
        self._refresh_icon_preview()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择默认保存目录",
                                             self.dir_edit.text() or "")
        if d:
            self.dir_edit.setText(d)

    def _browse_icon(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择图标", "",
            "图片文件 (*.png *.ico *.jpg *.jpeg *.bmp);;所有文件 (*)"
        )
        if f:
            self.icon_edit.setText(f)

    def _reset_icon(self):
        self.icon_edit.setText("")
        self._refresh_icon_preview()

    def _refresh_icon_preview(self):
        path_str = self.icon_edit.text().strip()
        if path_str and os.path.exists(path_str):
            from PySide6.QtGui import QIcon
            pm = QIcon(path_str).pixmap(48, 48)
            if pm.isNull():
                pm = default_pixmap(48)
        else:
            pm = default_pixmap(48)
        self.icon_preview.setPixmap(pm)

    # ---------- 保存 ----------
    def _on_save(self):
        new_cfg = dict(self._cfg)
        new_cfg["save_dir"] = self.dir_edit.text().strip()
        new_cfg["max_workers"] = int(self.workers_spin.value())
        new_cfg["icon_path"] = self.icon_edit.text().strip()

        if app_config.save(new_cfg):
            self.applied.emit(new_cfg)
            self.accept()
        else:
            # 写入失败也关闭,但不崩溃
            self.reject()

    # ---------- 玻璃背景 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        # 比主窗口略实一点,保证设置项可读
        p.fillPath(path, QColor(26, 26, 32, 175))
        pen = QPen(QColor(255, 255, 255, 36))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        p.end()

    def showEvent(self, e):
        super().showEvent(e)
        try:
            glass.apply_glass(int(self.winId()), color=(26, 26, 32, 210))
        except Exception:
            pass
