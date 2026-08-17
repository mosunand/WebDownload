"""WebDownload 资源爬虫 GUI 入口。

启动一个无边框、iOS 风渐变玻璃的主窗口,
用 Playwright 扫描网页资源并用 httpx 并发下载。
"""
from __future__ import annotations
from utils.icon import setup_app_icons

import os
import sys

# 把项目根目录加入 sys.path,保证 ui/core/utils 可作为顶层包导入
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.window import MainWindow
from utils.icon import get_app_icon


def main():
    # 高 DPI 适配(PySide6 6.11 默认已开启高 DPI,这里显式设置缩放策略)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("WebDownload")

    # 任务栏/窗口图标:自定义或程序生成的默认图标,窗口创建前设置才生效于任务栏
    #app.setWindowIcon(get_app_icon())
    #app.setWindowIcon(setup_app_icons(app, window, custom_path="./icon/logo.ico"))


    win = MainWindow()
    setup_app_icons(app, win, custom_path="./icon/logo.ico")

    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
