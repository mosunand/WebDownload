"""应用图标管理模块。

功能:
  - 支持传入 .ico / .png / .jpg 路径
  - 兼容 PyInstaller / Nuitka 打包后的资源路径
  - 找不到自定义图标时，自动回退到程序生成的 iOS 风默认图标
  - 提供 Windows 任务栏图标修复辅助函数 (AUMID)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)

from utils.config import load as load_config


# ── 打包兼容: 资源路径解析 ──────────────────────────────────────
def _resource_path(*parts: str) -> str:
    """获取资源文件的绝对路径，兼容开发环境和打包后环境。"""
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        # icon.py -> utils/ -> 项目根目录 (WebDownload/)
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


# ── 默认图标绘制 ───────────────────────────────────────────────
def _make_default_pixmap(size: int = 256) -> QPixmap:
    """程序化生成 iOS 风默认图标: 蓝紫渐变圆角方块 + 白色下载箭头。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    s = float(size)
    rect = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    radius = s * 0.24

    # 主渐变: 左上亮蓝 -> 右下靛紫
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#5e9cf5"))
    grad.setColorAt(0.5, QColor("#4dabf7"))
    grad.setColorAt(1.0, QColor("#7b6cf0"))
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.fillPath(path, QBrush(grad))

    # 顶部高光(玻璃感)
    hl = QLinearGradient(
        rect.topLeft(),
        QPointF(rect.left(), rect.top() + rect.height() * 0.5),
    )
    hl.setColorAt(0.0, QColor(255, 255, 255, 70))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    hl_path = QPainterPath()
    hl_path.addRoundedRect(
        QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.5),
        radius,
        radius,
    )
    p.fillPath(hl_path, QBrush(hl))

    # 下载箭头: 圆头粗线
    pen = QPen(QColor(255, 255, 255, 240))
    pen.setWidthF(s * 0.085)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)

    cx = s * 0.5
    p.drawLine(QPointF(cx, s * 0.28), QPointF(cx, s * 0.60))
    p.drawLine(QPointF(s * 0.34, s * 0.47), QPointF(cx, s * 0.62))
    p.drawLine(QPointF(s * 0.66, s * 0.47), QPointF(cx, s * 0.62))
    p.drawLine(QPointF(s * 0.30, s * 0.74), QPointF(s * 0.70, s * 0.74))

    p.end()
    return pm


def _make_default_icon() -> QIcon:
    """生成多尺寸默认图标，适配任务栏/标题栏/托盘各场景。"""
    ic = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(_make_default_pixmap(sz))
    return ic


# ── 图标加载 ───────────────────────────────────────────────────
def _load_icon_from(path_str: str | None) -> QIcon | None:
    """从给定路径加载图标，失败返回 None。"""
    if not path_str:
        return None
    try:
        path = Path(path_str).expanduser().resolve()
        if path.exists():
            ic = QIcon(str(path))
            if not ic.isNull():
                return ic
    except Exception:
        pass
    return None


# ── 核心接口 ───────────────────────────────────────────────────
def get_app_icon(
        custom_path: str | None = None,
        cfg: dict | None = None,
) -> QIcon:
    """获取应用图标。

    查找优先级:
      1. 传入的 custom_path 参数 (最高优先级)
      2. config.json 里的 icon_path
      3. 项目根目录 icon.ico / icon.png / icon.jpg
      4. 程序生成的默认图标 (保底)

    Args:
        custom_path: 用户指定的图标文件路径，支持相对/绝对路径
        cfg: 已加载的配置字典，为 None 时会自动加载
    """
    # 1. 传入的参数 (最高优先级)
    if custom_path:
        # 先按原样尝试，失败再用 resource_path 解析
        ic = _load_icon_from(custom_path)
        if ic is not None:
            return ic
        # 尝试用打包兼容路径解析
        ic = _load_icon_from(_resource_path(custom_path))
        if ic is not None:
            return ic

    # 2. 配置文件
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}

    config_path = cfg.get("icon_path", "")
    if config_path:
        ic = _load_icon_from(config_path)
        if ic is not None:
            return ic
        # 打包后 config 里的路径可能是相对路径，尝试解析
        ic = _load_icon_from(_resource_path(config_path))
        if ic is not None:
            return ic

    # 3. 项目根目录常规文件名
    for name in ("icon.ico", "icon.png", "icon.jpg"):
        ic = _load_icon_from(_resource_path(name))
        if ic is not None:
            return ic

    # 4. 默认生成
    return _make_default_icon()


def default_pixmap(size: int = 256) -> QPixmap:
    """暴露给设置界面做"恢复默认"预览。"""
    return _make_default_pixmap(size)


# ── Windows 任务栏图标修复 ─────────────────────────────────────
def fix_windows_taskbar_icon(app_id: str = "com.webdownload.app.v1") -> None:
    """修复 Windows 任务栏显示 Python 默认图标的问题。

    必须在 QApplication 创建**之前**调用！

    Args:
        app_id: 应用唯一标识，建议格式: com.公司名.应用名.版本
    """
    try:
        from ctypes import windll
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (ImportError, AttributeError):
        pass  # 非 Windows 平台，静默跳过


def setup_app_icons(
        app,
        window,
        custom_path: str | None = None,
        cfg: dict | None = None,
) -> QIcon:
    """一键设置应用级和窗口级图标，返回实际使用的 QIcon。"""
    icon = get_app_icon(custom_path=custom_path, cfg=cfg)
    app.setWindowIcon(icon)
    window.setWindowIcon(icon)

    # 同步到自定义标题栏（如果存在）
    if hasattr(window, 'titlebar') and hasattr(window.titlebar, 'set_icon'):
        window.titlebar.set_icon(icon)

    return icon