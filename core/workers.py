"""QThread / QObject 包装:把扫描和下载放到后台线程,通过 Signal 回传 UI。"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QThread, Signal

from core.downloader import ConcurrentDownloader
from core.scanner import ResourceScanner, CHROME_EXE, _DEFAULT_USER_DATA
from utils.urlutils import safe_filename
from utils.stream_parser import is_stream_manifest
from datetime import datetime
from urllib.parse import urlparse
import re


def _safe_title(title_or_html: str) -> str:
    """提取标题并清理为安全文件名。接受纯标题或 HTML 内容。"""
    # 如果包含 <title 标签,先提取
    m = re.search(r"<title[^>]*>(.*?)</title>", title_or_html, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()
    else:
        title = title_or_html.strip()
    if not title:
        return ""
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    if len(title) > 80:
        title = title[:80].rstrip()
    return title


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

    def _try_merge_video(self, session_dir: str, title: str = "") -> int:
        """尝试把 video/ 子目录下的分片合并为单个 MP4,合并后删除碎片。"""
        from utils.merger import _find_ffmpeg, merge_video_files, cleanup_segments

        video_dir = os.path.join(session_dir, "video")
        if not os.path.isdir(video_dir):
            return 0

        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            self.log.emit("未找到 ffmpeg,跳过视频合并(分片已保存)")
            return 0

        all_files = os.listdir(video_dir)
        ts_files = sorted(f for f in all_files if f.endswith(".ts"))
        m4s_files = sorted(f for f in all_files if f.endswith((".m4s", ".m4v")))

        # 如果已经有 MP4 了(之前合并过),跳过
        existing_mp4 = [f for f in all_files if f.endswith(".mp4")]
        if existing_mp4:
            return 0

        # 用网页标题作为文件名,无标题则用默认名
        safe_title = _safe_title(title) if title else ""
        base_name = safe_title if safe_title else "merged"

        merged_count = 0

        # 只合并一次:按分片类型合并
        if len(ts_files) >= 2:
            seg_paths = [os.path.join(video_dir, f) for f in ts_files]
            out_name = f"{base_name}.mp4"
            out_path = os.path.join(video_dir, out_name)
            self.log.emit(f"正在合并 {len(ts_files)} 个 TS 分片 → {out_name}")
            ok = merge_video_files(seg_paths, out_path, ffmpeg)
            if ok:
                merged_count += 1
                self.log.emit(f"  ✓ {out_name} 合并成功")
            else:
                self.log.emit(f"  ⚠ TS 合并失败")

        elif len(m4s_files) >= 2:
            seg_paths = [os.path.join(video_dir, f) for f in m4s_files]
            out_name = f"{base_name}.mp4"
            out_path = os.path.join(video_dir, out_name)
            self.log.emit(f"正在合并 {len(m4s_files)} 个 M4S 分片 → {out_name}")
            ok = merge_video_files(seg_paths, out_path, ffmpeg)
            if ok:
                merged_count += 1
                self.log.emit(f"  ✓ {out_name} 合并成功")
            else:
                self.log.emit(f"  ⚠ M4S 合并失败")

        # 合并成功 → 删除分片和清单,只保留 MP4
        if merged_count > 0:
            removed = cleanup_segments(video_dir)
            if removed > 0:
                self.log.emit(f"已清理 {removed} 个临时分片文件")

        return merged_count

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

            # ========== 2. 自动合并视频分片 → 单个 MP4 ==========
            if "video" in self.selected_types and not self._stop:
                try:
                    # 优先用扫描时提取的页面标题,回退到 HTML 提取
                    title = self.resources.get("title", "")
                    if not title:
                        html_content = self.resources.get("html", "")
                        title = _safe_title(html_content) if html_content else ""
                    merged = self._try_merge_video(session_dir, title=title)
                    if merged > 0:
                        self.log.emit(f"合并完成:生成 {merged} 个 MP4 文件")
                    else:
                        self.log.emit("视频分片已保存(未合并,可能是清单格式或分片数量不足)")
                except Exception as e:
                    self.log.emit(f"合并出错: {e}")

        self.finished.emit(ok_count, fail_count)