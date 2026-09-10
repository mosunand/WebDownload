"""视频分片合并工具:用 ffmpeg 把 HLS(.m3u8) / DASH(.mpd) 分片合并为单个 MP4。

自动查找系统中的 ffmpeg,依次尝试:
1. PATH 中的 ffmpeg
2. 项目内置 Tools/ 下的 ffmpeg
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time
import logging

from utils.urlutils import get_ext

logger = logging.getLogger(__name__)

# Windows 隐藏 ffmpeg 命令行窗口
_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

# 取消事件:下载被取消/窗口被关闭时置位,正在运行的 ffmpeg 会被 kill
_MERGE_CANCEL = threading.Event()

# ffmpeg 搜索路径(项目内置)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANDIDATE_PATHS = [
    os.path.join(_ROOT, "Tools", "ffmpeg", "bin", "ffmpeg.exe"),
    os.path.join(_ROOT, "Tools", "ffmpeg", "ffmpeg.exe"),
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
]


def _find_ffmpeg() -> str | None:
    """在 PATH 和常见位置中查找 ffmpeg。"""
    path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if path:
        return path
    for p in _CANDIDATE_PATHS:
        if os.path.isfile(p):
            return p
    for drive in ("C:", "D:", "E:", "F:"):
        for base in ("Tools", "Program Files", "Program Files (x86)"):
            top = os.path.join(drive + "\\", base)
            if not os.path.isdir(top):
                continue
            for d in os.listdir(top):
                if "ffmpeg" in d.lower():
                    candidate = os.path.join(top, d, "bin", "ffmpeg.exe")
                    if os.path.isfile(candidate):
                        return candidate
    return None


def cancel_pending_merge() -> None:
    """请求取消正在进行的合并(kill 运行中的 ffmpeg)。"""
    _MERGE_CANCEL.set()


def _run_ffmpeg(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """执行 ffmpeg 命令,可被取消事件中断,超时/取消时 kill 进程。

    输出重定向到 DEVNULL:本工具只关心退出码,而 ffmpeg 会持续向
    stderr 写进度,用管道的话长合并可能把管道写满导致卡死。
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if _MERGE_CANCEL.is_set():
            proc.kill()
            break
        if time.monotonic() >= deadline:
            proc.kill()
            break
        time.sleep(0.2)
    proc.wait()
    rc = proc.returncode if proc.returncode is not None else 1
    return subprocess.CompletedProcess(cmd, returncode=rc)


def merge_video_files(
    file_paths: list[str],
    output_path: str,
    ffmpeg_path: str | None = None,
) -> bool:
    """把一组视频分片文件合并为单个 MP4。

    注意:file_paths 的顺序即拼接顺序,调用方必须保证它就是播放顺序。
    """
    if not file_paths:
        return False

    ffmpeg = ffmpeg_path or _find_ffmpeg()
    if not ffmpeg:
        return False

    # 新一轮合并前清掉上一轮可能残留的取消标记
    _MERGE_CANCEL.clear()

    ext = get_ext(file_paths[0]).lower()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        if ext == ".ts":
            return _concat_ts(file_paths, output_path, ffmpeg)
        elif ext in (".m4s", ".mp4", ".m4v"):
            return _concat_fmp4(file_paths, output_path, ffmpeg)
        else:
            return _concat_generic(file_paths, output_path, ffmpeg)
    except Exception as e:
        logger.error("合并失败: %s", e)
        return False


# ─────────────── 内部实现 ───────────────

def _concat_ts(segments: list[str], output: str, ffmpeg: str) -> bool:
    """合并 .ts 分片:用 concat demuxer。"""
    list_file = output + ".concat.txt"
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for seg in segments:
                safe = seg.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        base_cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
        ]
        # aac_adtstoasc 仅对 AAC 音轨有效;MP3/AC3 等 TS 用它会报错,
        # 带 bsf 失败时去掉再试一次
        for extra in (["-bsf:a", "aac_adtstoasc"], []):
            result = _run_ffmpeg(base_cmd + extra + [output], timeout=300)
            if result.returncode == 0 and os.path.isfile(output) and os.path.getsize(output) > 0:
                return True
        return False
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass


def _concat_fmp4(segments: list[str], output: str, ffmpeg: str) -> bool:
    """合并 fMP4 (.m4s) 分片:init 段 + 媒体段按序二进制拼接,再重封装为 MP4。

    不用 concat demuxer:单个 .m4s 缺少独立的文件头,ffmpeg 探测不了;
    二进制拼接(init 的 moov + 各段的 moof/mdat)后就是一个合法的
    fMP4 流,用 -c copy 重封装即可。
    """
    tmp = output + ".concat.mp4"
    try:
        with open(tmp, "wb") as out:
            for seg in segments:
                with open(seg, "rb") as f:
                    shutil.copyfileobj(f, out, 1024 * 1024)

        cmd = [ffmpeg, "-y", "-i", tmp, "-c", "copy", output]
        result = _run_ffmpeg(cmd, timeout=600)
        return result.returncode == 0 and os.path.isfile(output) and os.path.getsize(output) > 0
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _concat_generic(segments: list[str], output: str, ffmpeg: str) -> bool:
    """通用合并:尝试 concat demuxer。"""
    list_file = output + ".concat.txt"
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for seg in segments:
                safe = seg.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output,
        ]
        result = _run_ffmpeg(cmd, timeout=300)
        return result.returncode == 0 and os.path.isfile(output) and os.path.getsize(output) > 0
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass
