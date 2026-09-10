"""QThread / QObject 包装:把扫描和下载放到后台线程,通过 Signal 回传 UI。"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QThread, Signal

from core.downloader import ConcurrentDownloader
from core.scanner import ResourceScanner, CHROME_EXE, _DEFAULT_USER_DATA
from utils.urlutils import safe_filename, natural_key
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
        # URL → 实际保存路径(下载回调时记录)。
        # 分片文件名可能与播放顺序无关(冲突加序号/无数字名),
        # 合并时靠这个映射按清单顺序还原,而不是靠文件名排序。
        self._url_to_path: dict[str, str] = {}
        # 扫描阶段解析出的 {清单URL: 有序分片URL列表},合并顺序的权威来源
        self._stream_playlists: dict[str, list[str]] = {
            str(m): list(segs)
            for m, segs in (resources.get("stream_playlists") or {}).items()
        }

    def stop(self):
        self._stop = True
        self._downloader.stop()
        # 正在运行的 ffmpeg 合并也一并取消,避免后台残留长任务
        try:
            from utils.merger import cancel_pending_merge
            cancel_pending_merge()
        except Exception:
            pass

    def _try_merge_video(self, session_dir: str, title: str = "") -> int:
        """把 video/ 子目录下的分片合并为 MP4,合并后删除碎片。

        顺序策略(修复合并后画面顺序错乱的问题):
        1. 优先按清单(m3u8/mpd)里的播放顺序拼接 —— 通过下载时记录的
           URL→本地路径映射还原顺序,与文件名无关
        2. 没有清单信息的散分片,按文件名自然排序(seg-2 排在 seg-10 前),
           并按扩展名分组,避免不同来源的分片混在一起
        3. 多个清单各合并成独立的 MP4,不互相混拼
        """
        from utils.merger import _find_ffmpeg, merge_video_files

        video_dir = os.path.join(session_dir, "video")
        if not os.path.isdir(video_dir):
            return 0

        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            self.log.emit("未找到 ffmpeg,跳过视频合并(分片已保存)")
            return 0

        all_files = os.listdir(video_dir)

        # 用网页标题作为文件名,无标题则用默认名
        safe_title = _safe_title(title) if title else ""
        base_name = safe_title if safe_title else "merged"

        # ── 1. 按清单顺序制定合并计划(每个清单一个 MP4) ──
        plans: list[list[str]] = []
        claimed: set[str] = set()

        for seg_urls in self._stream_playlists.values():
            seg_paths: list[str] = []
            for u in seg_urls:
                p = self._url_to_path.get(u)
                if not p or p in claimed or not os.path.isfile(p):
                    continue
                if os.path.splitext(p)[1].lower() in (".m3u8", ".mpd"):
                    continue  # 清单本身不是分片
                seg_paths.append(p)
            if len(seg_paths) >= 2:
                claimed.update(seg_paths)
                plans.append(seg_paths)

        # ── 2. 清单没覆盖的散分片:按扩展名分组 + 自然排序 ──
        def group_leftovers(exts: tuple[str, ...], include_init_mp4: bool = False) -> list[str]:
            files = []
            for f in all_files:
                fp = os.path.join(video_dir, f)
                if fp in claimed:
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext in exts or (include_init_mp4 and ext == ".mp4" and "init" in f.lower()):
                    files.append(fp)
            return sorted(files, key=lambda p: natural_key(os.path.basename(p)))

        ts_left = group_leftovers((".ts",), include_init_mp4=False)
        m4s_left = group_leftovers((".m4s", ".m4v"), include_init_mp4=True)
        if len(ts_left) >= 2:
            plans.append(ts_left)
        if len(m4s_left) >= 2:
            plans.append(m4s_left)

        # ── 3. 执行合并 ──
        merged_count = 0
        merged_paths: list[str] = []
        multi = len(plans) > 1
        used_names: set[str] = set(all_files)
        for idx, seg_paths in enumerate(plans, 1):
            out_name = f"{base_name}_{idx}.mp4" if multi else f"{base_name}.mp4"
            # 输出名撞上页面直接下载的文件时加后缀,不覆盖(ffmpeg -y 会覆盖)
            stem, ext = os.path.splitext(out_name)
            i = 1
            while out_name in used_names:
                out_name = f"{stem}_{i}{ext}"
                i += 1
            used_names.add(out_name)
            out_path = os.path.join(video_dir, out_name)
            self.log.emit(f"正在按播放顺序合并 {len(seg_paths)} 个分片 → {out_name}")
            if merge_video_files(seg_paths, out_path, ffmpeg):
                merged_count += 1
                merged_paths.extend(seg_paths)
                self.log.emit(f"  ✓ {out_name} 合并成功")
            else:
                self.log.emit(f"  ⚠ {out_name} 合并失败")

        # ── 4. 清理:只删已成功合并的分片;全部成功时连清单一起删 ──
        if merged_count > 0:
            to_remove = set(merged_paths)
            if merged_count == len(plans):
                for f in all_files:
                    if f.lower().endswith((".m3u8", ".mpd")) or f.endswith(".concat.txt"):
                        to_remove.add(os.path.join(video_dir, f))
            removed = 0
            for p in to_remove:
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
            if removed:
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
                    if url and save_path:
                        self._url_to_path[url] = save_path
                    if ok:
                        ok_count += 1
                    else:
                        fail_count += 1
                    done[0] += 1
                    name = os.path.basename(save_path) if save_path else "?"
                    self.total_progress.emit(done[0], total, name)

                # 计数与进度都在 on_file_done 回调里完成,返回值不需要
                self._downloader.download_all(
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