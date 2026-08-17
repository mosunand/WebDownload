"""主窗口:无边框 + iOS 风渐变玻璃背景 + 标题栏 + 全部布局与信号连接。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QVBoxLayout, QWidget,
)

try:
    from ctypes import windll  # 仅 Windows 存在
    myappid = 'com.webdownload.app.v1'  # 用你应用的唯一标识
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except ImportError:
    pass

from core.workers import DownloadWorker, ScanWorker, LoginWorker
from ui.settings import SettingsDialog
from ui.styles import QSS
from ui.titlebar import TitleBar
from ui.widgets import Card, IOSSwitch, GlassButton, DragHandle
from utils import glass
from utils import config as app_config
from utils.icon import get_app_icon

# 资源类型 -> 中文名 + 子目录名
TYPE_META = {
    "images": ("图片", "images"),
    "audio": ("音频", "audio"),
    "video": ("视频", "video"),
    "css": ("样式表", "css"),
    "js": ("脚本", "js"),
    "html": ("网页HTML", "html"),
}

_BG_RADIUS = 16.0


class MainWindow(QWidget):
    scanned = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(800, 700)
        self.setMinimumSize(660, 620)

        # 配置
        self._cfg = app_config.load()

        # DWM 毛玻璃是否已成功应用(决定 paintEvent 是否绘制背景填充)
        self._glass_applied = False

        # 记录普通几何,用于最大化/还原
        self._normal_geometry = None

        # 后台线程引用(关闭时需清理)
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._dl_thread: QThread | None = None
        self._dl_worker: DownloadWorker | None = None
        self._login_thread: QThread | None = None
        self._login_worker: LoginWorker | None = None

        # 扫描结果
        self._resources: dict = {}
        # 手动选过的保存目录(优先级高于配置默认)
        self._save_dir_override: str = ""

        self._build_ui()
        self.setStyleSheet(QSS)
        self._refresh_dir_label()
        self._set_downloading_state(False)
        self._set_scanning_state(False)
        self._update_counts()

    # ---------- 有效保存目录 ----------
    def _effective_save_dir(self) -> str:
        if self._save_dir_override:
            return self._save_dir_override
        cfg_dir = self._cfg.get("save_dir", "").strip()
        if cfg_dir:
            return cfg_dir
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "downloads",
        )

    def _refresh_dir_label(self):
        d = self._effective_save_dir()
        self.dir_label.setText(f"保存到: {d}")

    # ---------- UI 构建 ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        # 标题栏(带设置回调)
        self.titlebar = TitleBar(self, on_settings=self._open_settings)
        root.addWidget(self.titlebar)

        # 可见拖动把手(标题栏下方,提示用户此处可拖动)
        self.drag_handle = DragHandle(self)
        root.addWidget(self.drag_handle)

        # 输入区 Card
        input_card = Card(self)
        input_lay = QVBoxLayout(input_card)
        input_lay.setContentsMargins(18, 16, 18, 16)
        input_lay.setSpacing(10)

        hint = QLabel("输入要扫描的网址", input_card)
        hint.setObjectName("hintLabel")
        input_lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.url_edit = QLineEdit(input_card)
        self.url_edit.setPlaceholderText("https://example.com ...")
        self.url_edit.setMinimumHeight(36)
        self.url_edit.returnPressed.connect(self._on_scan)
        row.addWidget(self.url_edit, 1)

        self.btn_scan = GlassButton("扫描资源", input_card, primary=True)
        self.btn_scan.clicked.connect(self._on_scan)
        row.addWidget(self.btn_scan)

        self.btn_login = GlassButton("登录浏览器", input_card)
        self.btn_login.setToolTip("需要登录的网站:先点这里打开浏览器登录,再扫描")
        self.btn_login.clicked.connect(self._on_login)
        row.addWidget(self.btn_login)
        input_lay.addLayout(row)
        root.addWidget(input_card)

        # 类型勾选区 Card
        type_card = Card(self)
        type_lay = QVBoxLayout(type_card)
        type_lay.setContentsMargins(18, 16, 18, 16)
        type_lay.setSpacing(12)

        type_hint = QLabel("选择要下载的资源类型", type_card)
        type_hint.setObjectName("hintLabel")
        type_lay.addWidget(type_hint)

        self.checks: dict[str, IOSSwitch] = {}
        self.count_labels: dict[str, QLabel] = {}
        grid = QHBoxLayout()
        grid.setSpacing(24)
        col1 = QVBoxLayout()
        col1.setSpacing(10)
        col2 = QVBoxLayout()
        col2.setSpacing(10)

        keys = list(TYPE_META.keys())
        half = (len(keys) + 1) // 2
        for i, key in enumerate(keys):
            name, _sub = TYPE_META[key]
            wrap = QHBoxLayout()
            wrap.setSpacing(8)
            cb = IOSSwitch(name, type_card)
            cb.toggled.connect(self._update_counts)
            self.checks[key] = cb
            cnt = QLabel("0", type_card)
            cnt.setObjectName("countLabel")
            self.count_labels[key] = cnt
            wrap.addWidget(cb)
            wrap.addStretch()
            wrap.addWidget(cnt)
            (col1 if i < half else col2).addLayout(wrap)

        grid.addLayout(col1)
        grid.addLayout(col2)
        type_lay.addLayout(grid)
        root.addWidget(type_card)

        # 操作区 Card
        op_card = Card(self)
        op_lay = QVBoxLayout(op_card)
        op_lay.setContentsMargins(18, 16, 18, 16)
        op_lay.setSpacing(10)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.btn_dir = GlassButton("更改保存目录", op_card)
        self.btn_dir.clicked.connect(self._choose_dir)
        dir_row.addWidget(self.btn_dir)
        self.dir_label = QLabel("", op_card)
        self.dir_label.setObjectName("statusLabel")
        self.dir_label.setWordWrap(True)
        dir_row.addWidget(self.dir_label, 1)
        op_lay.addLayout(dir_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_download = GlassButton("开始下载", op_card, primary=True)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_cancel = GlassButton("取消", op_card)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_download)
        btn_row.addWidget(self.btn_cancel)
        op_lay.addLayout(btn_row)
        root.addWidget(op_card)

        # 进度区
        prog_card = Card(self)
        prog_lay = QVBoxLayout(prog_card)
        prog_lay.setContentsMargins(18, 16, 18, 16)
        prog_lay.setSpacing(8)

        self.progress = QProgressBar(prog_card)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        prog_lay.addWidget(self.progress)

        self.status_label = QLabel("就绪。输入网址后点击「扫描资源」。", prog_card)
        self.status_label.setObjectName("statusLabel")
        prog_lay.addWidget(self.status_label)
        root.addWidget(prog_card)

        # 底部信息栏:左侧提示 + 右侧版权/邮箱
        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 0)
        tip = QLabel("Playwright 扫描 · httpx 并发下载", self)
        tip.setObjectName("footerLabel")
        footer.addWidget(tip)
        footer.addStretch()
        copy = QLabel("© 2026 moshuai · moshuai1013@outlook.com", self)
        copy.setObjectName("footerLabel")
        footer.addWidget(copy)
        root.addLayout(footer)

    # ---------- iOS 风渐变玻璃背景 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, _BG_RADIUS, _BG_RADIUS)

        if not self._glass_applied:
            # 毛玻璃未生效:自绘极低 alpha 渐变作为半透明后备
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QColor(30, 34, 48, 14))
            grad.setColorAt(0.5, QColor(22, 24, 34, 10))
            grad.setColorAt(1.0, QColor(16, 18, 26, 12))
            p.fillPath(path, QBrush(grad))

        # 顶部高光(玻璃受光)
        hl = QLinearGradient(0, 0, self.width(), 0)
        hl.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, 60))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(hl), 1.0))
        p.drawLine(int(_BG_RADIUS), 1, int(self.width() - _BG_RADIUS), 1)

        # 边缘细描边
        pen = QPen(QColor(255, 255, 255, 30))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        p.end()

    def showEvent(self, e):
        super().showEvent(e)
        # 延迟 100ms 确保窗口完全创建后再应用模糊
        # 去掉 WS_EX_LAYERED + DWM 模糊必须在窗口 fully created 后才有效
        QTimer.singleShot(100, self._apply_glass_delayed)

    def _apply_glass_delayed(self):
        try:
            # 更低 alpha 让 DWM 毛玻璃效果更明显
            ok = glass.apply_glass(int(self.winId()), color=(20, 22, 30, 100))
            if ok:
                self._glass_applied = True
                # 告诉 Qt 不要再自动填充窗口背景,让 DWM 模糊完全透出来
                self.setAttribute(Qt.WA_NoSystemBackground, True)
                self.setAttribute(Qt.WA_OpaquePaintEvent, False)
                pal = self.palette()
                pal.setBrush(self.backgroundRole(), QBrush(QColor(0, 0, 0, 0)))
                self.setPalette(pal)
                self.update()
        except Exception:
            pass

    # ---------- 最大化 / 还原(避开任务栏) ----------
    def toggle_maximize(self):
        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
            self._normal_geometry = None
        else:
            self._normal_geometry = self.geometry()
            screen = self.screen()
            if screen is not None:
                self.setGeometry(screen.availableGeometry())

    def is_maximized(self) -> bool:
        return self._normal_geometry is not None

    # ---------- 设置 ----------
    def _open_settings(self):
        dlg = SettingsDialog(self._cfg, self)
        dlg.applied.connect(self._on_settings_applied)
        dlg.exec()

    def _on_settings_applied(self, new_cfg: dict):
        self._cfg = dict(new_cfg)
        # 配置改动:刷新图标、保存目录显示
        self._apply_icon()
        self._refresh_dir_label()
        self.status_label.setText("设置已保存。")

    # ---------- 扫描 ----------
    def _normalized_url(self) -> str:
        url = self.url_edit.text().strip()
        if url and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
            self.url_edit.setText(url)
        return url

    def _on_scan(self):
        url = self._normalized_url()
        if not url:
            self.status_label.setText("请先输入网址。")
            return

        self._set_scanning_state(True)
        self.status_label.setText("正在扫描,请稍候...")

        self._scan_thread = QThread()
        self._scan_worker = ScanWorker(url)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.log.connect(self.status_label.setText)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)

        self._scan_thread.start()

    def _on_scan_finished(self, result: dict):
        self._resources = result
        self._set_scanning_state(False)
        self._update_counts()
        total = sum(len(v) for k, v in result.items() if k != "html")
        html_len = len(result.get("html", ""))
        self.status_label.setText(
            f"扫描完成:共 {total} 个资源"
            + (f",HTML {html_len} 字符" if html_len else "")
        )

    def _on_scan_error(self, msg: str):
        self._set_scanning_state(False)
        self.status_label.setText(msg)

    def _set_scanning_state(self, scanning: bool):
        self.btn_scan.setEnabled(not scanning)
        self.btn_scan.setText("扫描中..." if scanning else "扫描资源")
        self.url_edit.setEnabled(not scanning)

    # ---------- 登录浏览器 ----------
    def _on_login(self):
        url = self._normalized_url() or "https://www.baidu.com"
        self.status_label.setText("已打开浏览器,登录完成后关闭窗口即可...")

        self._login_thread = QThread()
        self._login_worker = LoginWorker(url)
        self._login_worker.moveToThread(self._login_thread)

        self._login_thread.started.connect(self._login_worker.run)
        self._login_worker.log.connect(self.status_label.setText)
        self._login_worker.finished.connect(self._on_login_finished)
        self._login_worker.error.connect(self._on_login_finished)
        self._login_worker.finished.connect(self._login_thread.quit)
        self._login_worker.error.connect(self._login_thread.quit)
        self._login_thread.finished.connect(self._login_worker.deleteLater)
        self._login_thread.finished.connect(self._login_thread.deleteLater)

        self._login_thread.start()

    def _on_login_finished(self, *_):
        self.status_label.setText("浏览器已关闭,登录态已保存。现在可以扫描了。")

    # ---------- 下载 ----------
    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录",
                                             self._effective_save_dir())
        if d:
            self._save_dir_override = d
            self._refresh_dir_label()

    def _on_download(self):
        selected = [k for k, cb in self.checks.items() if cb.isChecked()]
        if not selected:
            self.status_label.setText("请至少打开一种资源类型的开关。")
            return
        if not self._resources:
            self.status_label.setText("请先扫描资源。")
            return

        save_dir = self._effective_save_dir()
        os.makedirs(save_dir, exist_ok=True)

        self._set_downloading_state(True)
        self.progress.setValue(0)
        self.status_label.setText("准备下载...")

        max_workers = int(self._cfg.get("max_workers", 6) or 6)

        self._dl_thread = QThread()
        self._dl_worker = DownloadWorker(
            self._resources, selected, save_dir,
            webaddr=self._normalized_url(),   # ← 加这行
            max_workers=max_workers
        )
        self._dl_worker.moveToThread(self._dl_thread)

        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.log.connect(self.status_label.setText)
        self._dl_worker.total_progress.connect(self._on_total_progress)
        self._dl_worker.finished.connect(self._on_download_finished)
        self._dl_worker.error.connect(self._on_download_error)
        self._dl_worker.finished.connect(self._dl_thread.quit)
        self._dl_worker.error.connect(self._dl_thread.quit)
        self._dl_thread.finished.connect(self._dl_worker.deleteLater)
        self._dl_thread.finished.connect(self._dl_thread.deleteLater)

        self._dl_thread.start()

    def _on_total_progress(self, done: int, total: int, name: str):
        pct = int(done / total * 100) if total else 0
        self.progress.setValue(pct)
        self.status_label.setText(f"已下载 {done}/{total} — {name}")

    def _on_download_finished(self, ok: int, fail: int):
        self._set_downloading_state(False)
        self.progress.setValue(100)
        self.status_label.setText(f"完成:成功 {ok},失败 {fail}")

    def _on_download_error(self, msg: str):
        self._set_downloading_state(False)
        self.status_label.setText(msg)

    def _on_cancel(self):
        if self._dl_worker:
            self._dl_worker.stop()
            self.status_label.setText("正在取消...")

    def _set_downloading_state(self, downloading: bool):
        self.btn_download.setEnabled(not downloading)
        self.btn_scan.setEnabled(not downloading)
        self.btn_cancel.setEnabled(downloading)

    # ---------- 勾选 / 计数 ----------
    def _update_counts(self):
        for key, cnt_label in self.count_labels.items():
            n = len(self._resources.get(key, [])) if key != "html" else (
                1 if self._resources.get("html") else 0
            )
            cnt_label.setText(str(n))

    # ---------- 关闭清理 ----------
    def closeEvent(self, e):
        for worker, thread in (
            (self._scan_worker, self._scan_thread),
            (self._dl_worker, self._dl_thread),
            (self._login_worker, self._login_thread),
        ):
            if worker is not None and hasattr(worker, "stop"):
                try:
                    worker.stop()
                except Exception:
                    pass
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(3000)
        super().closeEvent(e)
