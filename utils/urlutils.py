"""URL 规范化与资源分类工具。"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

# 各类资源扩展名表(小写,不含点)
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".tif", ".tiff", ".avif", ".jfif",
}
AUDIO_EXTS = {
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".aac", ".opus",
    ".wma", ".weba",
}
VIDEO_EXTS = {
    ".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".ogv", ".wmv",
    ".flv", ".3gp", ".ts", ".m3u8",
}
CSS_EXTS = {"css"}
JS_EXTS = {"js", "mjs", "cjs"}

# content-type 主类型 -> 资源类别
_CONTENT_TYPE_MAP = {
    "image": "images",
    "audio": "audio",
    "video": "video",
    "text/css": "css",
    "javascript": "js",
    "ecmascript": "js",
}


def normalize_url(base: str, href: str) -> str:
    """把相对/绝对 href 合并到 base,去 fragment 与空白。返回 '' 表示无效。"""
    if not href:
        return ""
    href = href.strip()
    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    if href.startswith("data:"):
        return href  # data: URL 原样返回,调用方自行过滤
    try:
        joined = urljoin(base, href)
        parsed = urlparse(joined)
        # 去掉 fragment
        cleaned = parsed._replace(fragment="")
        return urlunparse(cleaned)
    except Exception:
        return ""


def is_data_url(url: str) -> bool:
    return url.lower().startswith("data:")


def get_ext(url: str) -> str:
    """从 URL 路径取扩展名(小写,不含点)。查询串里的 ext 不算。"""
    try:
        path = urlparse(url).path
        if "." in path:
            return path.rsplit(".", 1)[-1].lower()
    except Exception:
        pass
    return ""


def classify(url: str, content_type: str | None = None) -> str | None:
    """按扩展名/content-type 判定资源类别。

    返回 'images' | 'audio' | 'video' | 'css' | 'js' | None。
    content-type 优先,其次扩展名。
    """
    # content-type 优先
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        # 精确匹配 text/css、application/javascript 等
        if ct in _CONTENT_TYPE_MAP:
            return _CONTENT_TYPE_MAP[ct]
        # 主类型匹配 image/* audio/* video/*
        if "/" in ct:
            main = ct.split("/", 1)[0]
            if main in ("image", "audio", "video"):
                return _CONTENT_TYPE_MAP[main]

    # 扩展名兜底
    ext = get_ext(url)
    if ext in IMAGE_EXTS:
        return "images"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in CSS_EXTS:
        return "css"
    if ext in JS_EXTS:
        return "js"
    return None


def safe_filename(url: str, fallback: str = "file") -> str:
    """从 URL 推导一个安全的本地文件名。"""
    try:
        parsed = urlparse(url)
        name = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
        if not name:
            name = fallback
        # 去掉非法字符
        name = "".join(c for c in name if c not in '<>:"/\\|?*')
        if not name:
            name = fallback
        return name
    except Exception:
        return fallback


def unique_path(directory: str, filename: str) -> str:
    """在 directory 下生成不冲突的路径,冲突时加序号。"""
    import os

    if not filename:
        filename = "file"
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{i}{ext}")
        i += 1
    return candidate
