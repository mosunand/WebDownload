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
import logging

from utils.urlutils import get_ext

logger = logging.getLogger(__name__)

# Windows 隐藏 ffmpeg 命令行窗口
_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

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


def _run_ffmpeg(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """执行 ffmpeg 命令,隐藏窗口,返回结果。"""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def merge_video_files(
    file_paths: list[str],
    output_path: str,
    ffmpeg_path: str | None = None,
) -> bool:
    """把一组视频分片文件合并为单个 MP4。"""
    if not file_paths:
        return False

    ffmpeg = ffmpeg_path or _find_ffmpeg()
    if not ffmpeg:
        return False

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


def merge_by_manifest(
    manifest_path: str,
    output_path: str,
    ffmpeg_path: str | None = None,
) -> bool:
    """用 ffmpeg 读取清单文件合并。清单失败时回退到 concat demuxer。"""
    ffmpeg = ffmpeg_path or _find_ffmpeg()
    if not ffmpeg or not os.path.isfile(manifest_path):
        return False

    ext = get_ext(manifest_path).lower()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [ffmpeg, "-y"]
    if ext == ".m3u8":
        cmd += [
            "-protocol_whitelist", "file,pipe,concat",
            "-i", manifest_path,
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            output_path,
        ]
    elif ext == ".mpd":
        cmd += ["-i", manifest_path, "-c", "copy", output_path]
    else:
        return False

    result = _run_ffmpeg(cmd, timeout=300)
    if result.returncode == 0:
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0

    # 清单合并失败 → 回退到分片 concat
    manifest_dir = os.path.dirname(manifest_path)
    seg_files = sorted(
        os.path.join(manifest_dir, f)
        for f in os.listdir(manifest_dir)
        if f.endswith((".ts", ".m4s", ".m4v"))
    )
    if seg_files:
        return merge_video_files(seg_files, output_path, ffmpeg)
    return False


def select_best_manifest(video_dir: str) -> str | None:
    """从 video/ 目录中选出最佳清单:优先选子清单(非 master),最多分片的优先。

    解决 master m3u8 被展开成多个子清单后重复合并的问题。
    """
    all_files = os.listdir(video_dir)
    m3u8_files = [f for f in all_files if f.endswith(".m3u8")]
    mpd_files = [f for f in all_files if f.endswith(".mpd")]
    manifests = m3u8_files + mpd_files
    if not manifests:
        return None

    ts_count = len([f for f in all_files if f.endswith(".ts")])
    m4s_count = len([f for f in all_files if f.endswith((".m4s", ".m4v"))])
    has_segments = ts_count > 0 or m4s_count > 0

    if not has_segments:
        # 没有分片文件,不需要合并
        return None

    if len(manifests) == 1:
        return os.path.join(video_dir, manifests[0])

    # 多个清单:如果有 TS 分片,直接用 concat,不需要清单
    # 如果有 M4S 分片,也需要用 concat
    # 只有在没有任何分片但有清单时才用清单
    return None  # 交给分片合并


def cleanup_segments(video_dir: str, merged_mp4: str | None = None) -> int:
    """合并成功后删除分片文件(TS/M4S)和清单文件,只保留 MP4。

    Returns:
        删除的文件数
    """
    if not os.path.isdir(video_dir):
        return 0

    removed = 0
    keep_exts = {".mp4", ".mp3", ".wav", ".aac", ".flac"}  # 保留的格式

    for f in os.listdir(video_dir):
        fp = os.path.join(video_dir, f)
        if not os.path.isfile(fp):
            continue
        ext = get_ext(f).lower()
        # 删除: TS/M4S/M4V 分片 + m3u8/mpd 清单 + concat.txt 临时文件
        if ext in (".ts", ".m4s", ".m4v", ".m3u8", ".mpd") or f.endswith(".concat.txt"):
            try:
                os.remove(fp)
                removed += 1
            except OSError:
                pass

    return removed


# ─────────────── 内部实现 ───────────────

def _concat_ts(segments: list[str], output: str, ffmpeg: str) -> bool:
    """合并 .ts 分片:用 concat demuxer。"""
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
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            output,
        ]
        result = _run_ffmpeg(cmd, timeout=300)
        return result.returncode == 0 and os.path.isfile(output) and os.path.getsize(output) > 0
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass


def _concat_fmp4(segments: list[str], output: str, ffmpeg: str) -> bool:
    """合并 fMP4 (.m4s) 分片。"""
    init_segs = [s for s in segments if "init" in os.path.basename(s).lower()]
    media_segs = [s for s in segments if s not in init_segs]
    ordered = init_segs + media_segs

    list_file = output + ".concat.txt"
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for seg in ordered:
                safe = seg.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output,
        ]
        result = _run_ffmpeg(cmd, timeout=600)
        return result.returncode == 0 and os.path.isfile(output) and os.path.getsize(output) > 0
    finally:
        try:
            os.remove(list_file)
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
