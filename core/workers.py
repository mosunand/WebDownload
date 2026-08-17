"""QThread / QObject 包装:把扫描和下载放到后台线程,通过 Signal 回传 UI。"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QThread, Signal

from core.downloader import ConcurrentDownloader
from core.scanner import ResourceScanner, CHROME_EXE, _DEFAULT_USER_DATA
from utils.urlutils import safe_filename
from datetime import datetime
from urllib.parse import urlparse


class ScanWorker(QObject):
    """扫描 worker:在后台线程跑 Playwright 扫描。"""

    finished = Signal(dict)   # {images/audio/video/css/js/html}
    error = Signal(str)
    log = Signal(str)          # 给状态栏的日志

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.log.emit("正在启动浏览器并加载页面...")
            scanner = ResourceScanner()
            result = scanner.scan(self.url)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"扫描失败: {e}")


class LoginWorker(QObject):
    """打开一个带界面的持久化浏览器,让用户手动登录。

    登录态写入 _DEFAULT_USER_DATA,之后扫描(同一 user_data_dir)即可带 Cookies。
    用户关闭浏览器窗口后结束。
    """

    finished = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            from playwright.sync_api import sync_playwright

            os.makedirs(_DEFAULT_USER_DATA, exist_ok=True)
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=_DEFAULT_USER_DATA,
                    headless=False,  # 有界面,方便登录
                    executable_path=CHROME_EXE,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    ),
                    ignore_https_errors=True,
                    viewport={"width": 1280, "height": 860},
                )
                page = context.pages[0] if context.pages else context.new_page()
                self.log.emit("浏览器已打开,请登录后关闭窗口...")
                try:
                    page.goto(self.url, wait_until="commit", timeout=60000)
                except Exception:
                    pass
                # 阻塞直到用户关闭浏览器(最后一个页面被关掉)
                try:
                    context.wait_for_event("close", timeout=0)
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
            self.finished.emit()
        except Exception as e:
            self.error.emit(f"登录浏览器出错: {e}")


class DownloadWorker(QObject):
    """下载 worker:在后台线程并发下载选中类型的资源。"""

    file_started = Signal(str)                  # 文件名
    file_progress = Signal(str, int, int)        # url, done_bytes, total_bytes
    total_progress = Signal(int, int, str)       # done, total, 当前文件名
    finished = Signal(int, int)                  # ok, fail
    error = Signal(str)
    log = Signal(str)

    def __init__(self, resources: dict, selected_types: list[str], save_dir: str,
                 webaddr: str, max_workers: int = 6):
        super().__init__()
        self.resources = resources
        self.selected_types = selected_types
        self.save_dir = save_dir
        self.webaddr = webaddr
        self._stop = False
        self._downloader = ConcurrentDownloader(max_workers=max_workers)

    def stop(self):
        self._stop = True
        self._downloader.stop()

    def run(self):
        # ========== 1. 构建 时间+域名 的会话目录 ==========
        domain = urlparse(self.webaddr).netloc
        if not domain:
            domain = self.webaddr.replace("https://", "").replace("http://", "").strip("/")

        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        session_dir = os.path.join(self.save_dir, f"{timestamp}{domain}")
        os.makedirs(session_dir, exist_ok=True)
        # ================================================

        # 收集所有要下载的 (type_key, url) 列表
        jobs: list[tuple[str, str]] = []
        html_content = self.resources.get("html", "")

        for t in self.selected_types:
            if t == "html":
                if html_content:
                    jobs.append(("html", "__HTML_CONTENT__"))
            else:
                urls = self.resources.get(t, [])
                for u in urls:
                    jobs.append((t, u))

        total = len(jobs)
        if total == 0:
            self.log.emit("没有可下载的资源")
            self.finished.emit(0, 0)
            return

        done = [0]
        ok_count = 0
        fail_count = 0

        def make_filename(u):
            return safe_filename(u)

        try:
            for t in self.selected_types:
                if self._stop:
                    break
                if t == "html":
                    if not html_content:
                        continue
                    # HTML 直接写到 session_dir/html/
                    sub_dir = os.path.join(session_dir, "html")
                    os.makedirs(sub_dir, exist_ok=True)
                    path = os.path.join(sub_dir, "page.html")
                    i = 1
                    while os.path.exists(path):
                        path = os.path.join(sub_dir, f"page_{i}.html")
                        i += 1
                    try:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(html_content)
                        ok_count += 1
                        self.file_started.emit("page.html")
                        done[0] += 1
                        self.total_progress.emit(done[0], total, "page.html")
                    except Exception:
                        fail_count += 1
                        done[0] += 1
                        self.total_progress.emit(done[0], total, "page.html")
                    continue

                urls = self.resources.get(t, [])
                if not urls:
                    continue

                self.log.emit(f"开始下载 {t}:共 {len(urls)} 个文件...")

                def on_file_progress(url, d, total_bytes):
                    self.file_progress.emit(url, d, total_bytes)

                def on_file_done(url, ok, save_path):
                    nonlocal ok_count, fail_count
                    if ok:
                        ok_count += 1
                    else:
                        fail_count += 1
                    done[0] += 1
                    name = os.path.basename(save_path) if save_path else "?"
                    self.total_progress.emit(done[0], total, name)

                ok, fail = self._downloader.download_all(
                    urls=urls,
                    base_dir=session_dir,   # ← 关键：用 session_dir 代替 save_dir
                    type_key=t,
                    base_url="",
                    make_filename=make_filename,
                    on_file_progress=on_file_progress,
                    on_file_done=on_file_done,
                )
        except Exception as e:
            self.error.emit(f"下载出错: {e}")
            self.finished.emit(ok_count, fail_count)
            return

        if self._stop:
            self.log.emit("已取消下载")
        else:
            self.log.emit(f"下载完成:成功 {ok_count},失败 {fail_count}")
        self.finished.emit(ok_count, fail_count)