"""M3U8 / MPD 流媒体清单解析器。

从 HLS(.m3u8) 和 DASH(.mpd) 清单中提取分片(TS/M4S) URL,
支持多码率自适应(自动选最高分辨率)、AES-128 密钥标记。
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 公共常量
# ──────────────────────────────────────────────
TIMEOUT = 30.0
MAX_SEGMENTS = 5000  # 单个清单最多解析的分片数,防止恶意文件


# ──────────────────────────────────────────────
# M3U8 解析
# ──────────────────────────────────────────────

class M3U8Segment:
    """单个 TS 分片信息。"""
    __slots__ = ("url", "duration", "key_url", "key_iv")
    def __init__(self, url: str, duration: float = 0.0,
                 key_url: str | None = None, key_iv: str | None = None):
        self.url = url
        self.duration = duration
        self.key_url = key_url
        self.key_iv = key_iv


class M3U8Playlist:
    """解析后的 M3U8 媒体清单。"""
    __slots__ = ("segments", "target_duration", "version", "is_master")
    def __init__(self):
        self.segments: list[M3U8Segment] = []
        self.target_duration: float = 0.0
        self.version: int = 3
        self.is_master: bool = False


def _resolve(base_url: str, href: str) -> str:
    """安全地拼接 URL。"""
    if not href:
        return ""
    if href.startswith(("http://", "https://", "data:")):
        return href
    # 去掉 fragment
    href = href.split("#")[0]
    return urljoin(base_url, href)


def parse_m3u8(content: str, base_url: str) -> M3U8Playlist:
    """解析 M3U8 文本内容,返回媒体分片列表。

    Args:
        content: M3U8 文件内容(UTF-8 文本)
        base_url: 用于拼接相对路径的基准 URL

    Returns:
        M3U8Playlist 对象
    """
    playlist = M3U8Playlist()
    lines = content.splitlines()

    current_key_url: str | None = None
    current_key_iv: str | None = None
    current_duration: float = 0.0
    segment_count = 0
    # 主清单的码率变体表:(带宽, 分辨率像素数, 子清单 URL)
    variants: list[tuple[int, int, str]] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 跳过空行/注释
        if not line or line.startswith("#EXTM3U"):
            i += 1
            continue

        # 主清单标记:包含多个码率流,先收集,循环结束后只解析最高码率的那条
        # (如果全解析,不同码率的分片会混进同一列表,合并时顺序错乱)
        if line.startswith("#EXT-X-STREAM-INF"):
            playlist.is_master = True
            attrs = _parse_attrs(line)
            bandwidth = _safe_int(attrs.get("BANDWIDTH") or attrs.get("AVERAGE-BANDWIDTH"))
            resolution = 0
            res_str = attrs.get("RESOLUTION", "")
            if res_str:
                try:
                    w, h = res_str.lower().split("x", 1)
                    resolution = int(w) * int(h)
                except ValueError:
                    resolution = 0
            # 下一行就是子清单 URL
            i += 1
            if i < len(lines) and not lines[i].strip().startswith("#"):
                child_url = _resolve(base_url, lines[i].strip())
                if child_url:
                    variants.append((bandwidth, resolution, child_url))
            i += 1
            continue

        # 目标时长
        if line.startswith("#EXT-X-TARGETDURATION"):
            m = re.search(r"(\d+(?:\.\d+)?)", line)
            if m:
                playlist.target_duration = float(m.group(1))
            i += 1
            continue

        # 版本
        if line.startswith("#EXT-X-VERSION"):
            m = re.search(r"(\d+)", line)
            if m:
                playlist.version = int(m.group(1))
            i += 1
            continue

        # AES-128 密钥
        if line.startswith("#EXT-X-KEY"):
            attrs = _parse_attrs(line)
            method = attrs.get("METHOD", "NONE")
            if method.upper() == "AES-128":
                current_key_url = _resolve(base_url, attrs.get("URI", ""))
                current_key_iv = attrs.get("IV")
            else:
                current_key_url = None
                current_key_iv = None
            i += 1
            continue

        # EXT-X-MAP: fMP4 HLS 的初始化段(moov 头)。
        # 它出现在所属分片之前,按遇到顺序追加即可保证排在最前
        if line.startswith("#EXT-X-MAP"):
            attrs = _parse_attrs(line)
            init_url = _resolve(base_url, attrs.get("URI", ""))
            if init_url:
                playlist.segments.append(M3U8Segment(url=init_url, duration=0.0))
                segment_count += 1
            i += 1
            continue

        # 分片信息
        if line.startswith("#EXTINF"):
            # 提取时长
            m = re.match(r"#EXTINF:\s*([\d.]+)", line)
            if m:
                current_duration = float(m.group(1))
            else:
                current_duration = 0.0
            # 下一行是分片 URL
            i += 1
            if i < len(lines) and not lines[i].strip().startswith("#"):
                seg_url = _resolve(base_url, lines[i].strip())
                if seg_url:
                    playlist.segments.append(M3U8Segment(
                        url=seg_url,
                        duration=current_duration,
                        key_url=current_key_url,
                        key_iv=current_key_iv,
                    ))
                    segment_count += 1
                    if segment_count >= MAX_SEGMENTS:
                        break
            i += 1
            continue

        # 字节范围偏移(EXT-X-BYTERANGE) — 紧随 EXTINF 或直接跟分片 URL
        if line.startswith("#EXT-X-BYTERANGE"):
            # 下一行是分片 URL
            i += 1
            if i < len(lines) and not lines[i].strip().startswith("#"):
                seg_url = _resolve(base_url, lines[i].strip())
                if seg_url:
                    playlist.segments.append(M3U8Segment(
                        url=seg_url,
                        duration=current_duration,
                        key_url=current_key_url,
                        key_iv=current_key_iv,
                    ))
                    segment_count += 1
                    if segment_count >= MAX_SEGMENTS:
                        break
            i += 1
            continue

        # 分片 URL 直接出现(无 EXTINF 前缀,在低版本中可能)
        if not line.startswith("#") and line:
            seg_url = _resolve(base_url, line)
            if seg_url:
                playlist.segments.append(M3U8Segment(
                    url=seg_url,
                    duration=current_duration,
                    key_url=current_key_url,
                    key_iv=current_key_iv,
                ))
                segment_count += 1
                if segment_count >= MAX_SEGMENTS:
                    break

        # 其他标签: #EXT-X-ENDLIST, #EXT-X-DISCONTINUITY 等 — 忽略
        i += 1

    # 主清单:只解析最高码率(带宽优先,分辨率兜底)的那一个变体。
    # 从高到低依次尝试,某个变体下载失败或没有分片时降级到下一档。
    if variants:
        variants.sort(key=lambda v: (v[0], v[1]), reverse=True)
        for _, _, child_url in variants:
            child_content = _fetch_text(child_url)
            if not child_content:
                continue
            child = parse_m3u8(child_content, child_url)
            if not child.segments:
                continue
            if child.target_duration:
                playlist.target_duration = child.target_duration
            remaining = MAX_SEGMENTS - len(playlist.segments)
            if remaining > 0:
                playlist.segments.extend(child.segments[:remaining])
            break

    return playlist


def _parse_attrs(line: str) -> dict[str, str]:
    """解析 M3U8 标签属性行,如 ``#EXT-X-KEY:METHOD=AES-128,URI="..."``"""
    attrs = {}
    # 去掉标签名,保留属性部分
    idx = line.find(":")
    if idx == -1:
        return attrs
    rest = line[idx + 1:]

    # 简单解析:引号内值保持原样,逗号分隔
    buf = []
    in_quote = False
    for ch in rest:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch == ',' and not in_quote:
            buf.append('\x00')  # 用 \x00 作为临时分隔符
        else:
            buf.append(ch)
    parts = ''.join(buf).split('\x00')

    for part in parts:
        part = part.strip()
        if '=' in part:
            key, val = part.split('=', 1)
            key = key.strip()
            val = val.strip().strip('"')
            attrs[key] = val
    return attrs


# ──────────────────────────────────────────────
# MPD (DASH) 解析
# ──────────────────────────────────────────────

class MPDSegment:
    """单个 M4S 分片信息。"""
    __slots__ = ("url", "start_number", "duration")
    def __init__(self, url: str, start_number: int = 0, duration: float = 0.0):
        self.url = url
        self.start_number = start_number
        self.duration = duration


class MPDPlaylist:
    """解析后的 MPD 媒体清单。"""
    __slots__ = ("segments", "min_buffer_time", "availability_start")
    def __init__(self):
        self.segments: list[MPDSegment] = []
        self.min_buffer_time: float = 2.0
        self.availability_start: str = ""


def parse_mpd(content: str, base_url: str) -> MPDPlaylist:
    """解析 MPD XML 内容,提取 M4S 分片 URL。

    Args:
        content: MPD XML 文本
        base_url: 基准 URL 用于拼接

    Returns:
        MPDPlaylist 对象
    """
    playlist = MPDPlaylist()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.warning("MPD XML 解析失败: %s", e)
        return playlist

    # 命名空间处理 — DASH 通常使用 urn:mpeg:dash:schema:mpd:2011
    ns = _resolve_mpd_ns(root.tag)
    if ns:
        ET.register_namespace("", ns)

    # 取最小缓冲时间
    mbt = root.get("minBufferTime")
    if mbt:
        playlist.min_buffer_time = _parse_duration(mbt)

    # 便利函数:给标签加命名空间前缀(必须定义在所有使用点之前,
    # 原代码把 def tag 放在了使用它的 Period 兜底循环之后,会触发 NameError)
    def tag(name: str) -> str:
        return f"{{{ns}}}{name}" if ns else name

    # 取媒体演示总时长(秒),用于在无 SegmentTimeline 时估算分片数量
    mpd_duration = 0.0
    dur_attr = root.get("mediaPresentationDuration") or root.get("minimumUpdatePeriod")
    if dur_attr:
        mpd_duration = _parse_duration(dur_attr)
    # 兜底:从 Period 的 duration 属性取
    if mpd_duration <= 0:
        for period in root.findall(f".//{tag('Period')}"):
            pd = period.get("duration")
            if pd:
                mpd_duration = _parse_duration(pd)
                break

    # 收集所有 (AdaptationSet, Representation) 组合,优先选视频
    def _is_video_pair(aset_el: ET.Element, rep_el: ET.Element) -> bool:
        for el in (aset_el, rep_el):
            if "video" in (el.get("mimeType") or ""):
                return True
        # mimeType 可能只在兄弟 Representation 上
        return any(
            "video" in (r.get("mimeType") or "")
            for r in aset_el.findall(tag("Representation"))
        )

    pairs = [
        (aset_el, rep_el)
        for aset_el in root.findall(f".//{tag('AdaptationSet')}")
        for rep_el in aset_el.findall(tag("Representation"))
    ]
    video_pairs = [pr for pr in pairs if _is_video_pair(*pr)] or pairs
    if not video_pairs:
        return playlist

    # 只取全局带宽最高的那一个 Representation:
    # 多个 AdaptationSet / Representation 是同一内容的不同码率或编码,
    # 全部解析会让不同码率的分片交叉,合并后顺序错乱
    best_aset, best_rep = max(video_pairs, key=lambda pr: _safe_int(pr[1].get("bandwidth")))

    _resolve_mpd_representation(best_rep, best_aset, base_url, playlist, mpd_duration)

    return playlist


def _safe_int(value, default: int = 0) -> int:
    """安全转 int,失败返回 default。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _expand_media_tpl(tpl: str, rep_id: str, bandwidth: str,
                      seg_num: int, time_val: int) -> str:
    """替换 SegmentTemplate 中的 $Number$ / $RepresentationID$ / $Bandwidth$ / $Time$ 变量。"""
    s = tpl.replace("$RepresentationID$", rep_id)
    s = s.replace("$Bandwidth$", bandwidth)
    s = s.replace("$Number$", str(seg_num))
    s = s.replace("$Time$", str(time_val))
    # 带格式的数字变量,如 $Number%05d$
    return re.sub(r"\$Number%(\d+)d\$", lambda m: str(seg_num).zfill(int(m.group(1))), s)


def _resolve_mpd_representation(
    rep: ET.Element,
    aset: ET.Element,
    base_url: str,
    playlist: MPDPlaylist,
    mpd_duration: float = 0.0,
):
    """解析单个 Representation 的分片集合。

    SegmentTemplate / SegmentList 可能挂在 Representation 上,
    也可能从父级 AdaptationSet 继承,两级都找。
    """
    ns = _resolve_mpd_ns(rep.tag)

    def tag(name: str) -> str:
        return f"{{{ns}}}{name}" if ns else name

    seg_template = rep.find(tag("SegmentTemplate"))
    if seg_template is None:
        seg_template = aset.find(tag("SegmentTemplate"))
    if seg_template is not None:
        _resolve_mpd_template(seg_template, rep, aset, base_url, playlist, mpd_duration)
        return

    seg_list = rep.find(tag("SegmentList"))
    if seg_list is None:
        seg_list = aset.find(tag("SegmentList"))
    if seg_list is not None:
        _resolve_mpd_segment_list(seg_list, rep, base_url, playlist)
        return

    seg_timeline = rep.find(tag("SegmentTimeline"))
    if seg_timeline is None:
        seg_timeline = aset.find(tag("SegmentTimeline"))
    if seg_timeline is not None:
        _resolve_mpd_timeline(seg_timeline, rep, aset, base_url, playlist)
        return

    # 如果都没有,尝试直接取 BaseURL
    base_url_el = rep.find(tag("BaseURL"))
    if base_url_el is None:
        base_url_el = aset.find(tag("BaseURL"))
    if base_url_el is not None and base_url_el.text:
        url = _resolve(base_url, base_url_el.text.strip())
        if url:
            playlist.segments.append(MPDSegment(url=url))


def _resolve_mpd_ns(tag: str) -> str:
    """从根标签中提取命名空间。"""
    m = re.match(r"\{(.+?)\}", tag)
    return m.group(1) if m else ""


def _resolve_mpd_template(
    template: ET.Element,
    rep: ET.Element,
    aset: ET.Element,
    base_url: str,
    playlist: MPDPlaylist,
    mpd_duration: float = 0.0,
):
    """解析 SegmentTemplate,展开分片 URL(含初始化分片)。"""
    start_number = _safe_int(template.get("startNumber"), 1) or 1
    duration = _safe_int(template.get("duration"))  # 在 timescale 下的单位
    timescale = _safe_int(template.get("timescale"), 1) or 1
    media_tpl = template.get("media", "")

    rep_id = rep.get("id", "")
    bandwidth = rep.get("bandwidth", "0")

    # 检查 SegmentTimeline 子元素(精确的时间点列表,可能在 rep 或 aset 上)
    ns = _resolve_mpd_ns(rep.tag)
    seg_timeline_tag = f"{{{ns}}}SegmentTimeline" if ns else "SegmentTimeline"
    timeline = rep.find(seg_timeline_tag)
    if timeline is None:
        timeline = aset.find(seg_timeline_tag)
    if timeline is not None:
        _resolve_mpd_timeline(timeline, rep, aset, base_url, playlist)
        return

    # 如果没有分片总数标记,默认拉取一个合理的数量
    total = 0
    total_str = template.get("endNumber", "")
    if total_str:
        total = _safe_int(total_str) - start_number + 1
    elif duration > 0 and mpd_duration > 0:
        # 从 mediaPresentationDuration 推算:总时长 / 单分片时长(秒) + 1 容错
        import math
        total = int(math.ceil(mpd_duration * timescale / duration)) + 1
        total = min(total, MAX_SEGMENTS)
    else:
        total = 1

    # 初始化分片(fMP4 的 moov 头,缺了它合并出的 MP4 无法播放)
    init_tpl = template.get("initialization", "")
    if init_tpl:
        url = _resolve(base_url, _expand_media_tpl(init_tpl, rep_id, bandwidth, start_number, 0))
        if url:
            playlist.segments.append(MPDSegment(url=url))

    for i in range(min(total, MAX_SEGMENTS)):
        seg_num = start_number + i
        time_val = (seg_num - start_number) * duration
        url = _resolve(base_url, _expand_media_tpl(media_tpl, rep_id, bandwidth, seg_num, time_val))
        if url:
            playlist.segments.append(MPDSegment(
                url=url,
                start_number=seg_num,
                duration=duration / timescale if timescale else 0,
            ))


def _resolve_mpd_segment_list(
    seg_list: ET.Element,
    rep: ET.Element,
    base_url: str,
    playlist: MPDPlaylist,
):
    """解析 SegmentList,提取分片 URL。"""
    ns = _resolve_mpd_ns(rep.tag)
    def tag(name: str) -> str:
        return f"{{{ns}}}{name}" if ns else name

    # 初始化分片
    init_el = seg_list.find(tag("Initialization"))
    if init_el is not None:
        src = init_el.get("sourceURL", "")
        if src:
            url = _resolve(base_url, src)
            if url:
                playlist.segments.append(MPDSegment(url=url))

    for seg_url in seg_list.findall(tag("SegmentURL")):
        media = seg_url.get("media", "")
        if media:
            url = _resolve(base_url, media)
            if url:
                playlist.segments.append(MPDSegment(url=url))


def _resolve_mpd_timeline(
    timeline: ET.Element,
    rep: ET.Element,
    aset: ET.Element,
    base_url: str,
    playlist: MPDPlaylist,
):
    """解析 SegmentTimeline,按时间顺序提取分片 URL。"""
    ns = _resolve_mpd_ns(rep.tag)

    def tag(name: str) -> str:
        return f"{{{ns}}}{name}" if ns else name

    # SegmentTemplate 可能在 rep 上,也可能从父级 aset 继承
    template = rep.find(tag("SegmentTemplate"))
    if template is None:
        template = aset.find(tag("SegmentTemplate"))
    if template is None:
        return

    start_number = _safe_int(template.get("startNumber"), 1) or 1
    timescale = _safe_int(template.get("timescale"), 1) or 1
    media_tpl = template.get("media", "")

    rep_id = rep.get("id", "")
    bandwidth = rep.get("bandwidth", "0")
    seg_num = start_number
    current_time = 0

    # 初始化分片
    init_tpl = template.get("initialization", "")
    if init_tpl:
        url = _resolve(base_url, _expand_media_tpl(init_tpl, rep_id, bandwidth, seg_num, 0))
        if url:
            playlist.segments.append(MPDSegment(url=url))

    for s_elem in timeline.findall(tag("S")):
        d = _safe_int(s_elem.get("d"))  # 单分片时长(timescale 单位)
        r = _safe_int(s_elem.get("r"))  # 重复次数
        t = s_elem.get("t")

        if t is not None:
            current_time = _safe_int(t)

        for _ in range(min(r + 1, MAX_SEGMENTS)):
            url = _resolve(
                base_url,
                _expand_media_tpl(media_tpl, rep_id, bandwidth, seg_num, current_time),
            )
            if url:
                playlist.segments.append(MPDSegment(
                    url=url,
                    start_number=seg_num,
                    duration=d / timescale if timescale else 0,
                ))

            seg_num += 1
            current_time += d

            if len(playlist.segments) >= MAX_SEGMENTS:
                return


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def _parse_duration(dur_str: str) -> float:
    """解析 ISO 8601 时长 PT1H2M3.5S → 秒。"""
    if not dur_str:
        return 0.0
    dur_str = dur_str.upper().removeprefix("P").removeprefix("T")
    total = 0.0
    # 匹配数字+单位
    pattern = re.findall(r"([\d.]+)([HMS])", dur_str)
    for val, unit in pattern:
        val_f = float(val)
        if unit == "H":
            total += val_f * 3600
        elif unit == "M":
            total += val_f * 60
        elif unit == "S":
            total += val_f
    return total


def _fetch_text(url: str, timeout: float = TIMEOUT) -> str | None:
    """用 httpx 下载文本内容。"""
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
            },
        ) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        logger.debug("下载失败 %s: %s", url, e)
    return None


def parse_stream_manifest(url: str) -> list[str]:
    """自动检测清单类型(M3U8/MPD),下载并解析,返回分片 URL 列表。

    这是对外的主要接口,供 scanner.py 调用。

    Args:
        url: 清单文件 URL (.m3u8 或 .mpd)

    Returns:
        解析出的分片 URL 列表,解析失败返回空列表
    """
    lower = url.lower()
    content = _fetch_text(url)
    if not content:
        return []

    if ".m3u8" in lower:
        playlist = parse_m3u8(content, url)
        if playlist.is_master and not playlist.segments:
            # 主清单但没解析出分片,可能是需要额外处理
            logger.info("M3U8 主清单未解析出分片: %s", url)
        return [seg.url for seg in playlist.segments]

    if ".mpd" in lower:
        playlist = parse_mpd(content, url)
        return [seg.url for seg in playlist.segments]

    # 尝试通过 content-type 嗅探
    if content.strip().startswith("#EXTM3U"):
        playlist = parse_m3u8(content, url)
        return [seg.url for seg in playlist.segments]

    if content.strip().startswith("<?xml") or "<MPD" in content:
        playlist = parse_mpd(content, url)
        return [seg.url for seg in playlist.segments]

    return []


def is_stream_manifest(url: str) -> bool:
    """判断一个 URL 是否可能是流媒体清单(M3U8/MPD)。"""
    lower = url.lower()
    return lower.endswith(".m3u8") or lower.endswith(".mpd")