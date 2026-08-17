"""Playwright 资源扫描器:加载页面、提取分类资源 URL。

用本地已装的 Chromium(executable_path 直指),真浏览器渲染后再扫描,
能拿到 JS 动态加载的资源 + 懒加载图片 + 背景图。

支持持久化用户数据目录(Cookies/登录态保留),可扫需要登录的页面。
"""
from __future__ import annotations

import os
import re
import threading
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from utils.urlutils import classify, normalize_url, is_data_url

import os

# 从 core/scanner.py 往上退两级 → 项目根目录 (WebDownload/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 定位到 Tools/chromium-1140/chrome-win/chrome.exe
CHROME_EXE = os.path.join(
    _ROOT,
    "Tools\ms-playwright",
    "chromium-1140",
    "chrome-win",
    "chrome.exe"
)

# 默认持久化用户数据目录(保留 Cookies / 登录态)
_DEFAULT_USER_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "userdata"
)

# 在浏览器里跑的提取脚本:返回 DOM 中所有资源 URL
_EXTRACT_JS = r"""
() => {
    const out = { images: [], audio: [], video: [], css: [], js: [] };
    const abs = (u) => { try { return new URL(u, document.baseURI).href; } catch(e){ return ''; } };

    // 图片:<img> src / currentSrc / srcset / data-src(常见懒加载占位)
    document.querySelectorAll('img').forEach(img => {
        if (img.src) out.images.push(abs(img.src));
        if (img.currentSrc) out.images.push(abs(img.currentSrc));
        // 懒加载常见占位属性
        ['data-src','data-original','data-lazy-src','data-url','data-echo'].forEach(k => {
            const v = img.getAttribute(k);
            if (v) out.images.push(abs(v));
        });
        if (img.srcset) {
            img.srcset.split(',').forEach(s => {
                const u = s.trim().split(' ')[0];
                if (u) out.images.push(abs(u));
            });
        }
    });

    // 内联 style 背景图
    document.querySelectorAll('[style]').forEach(el => {
        const s = el.getAttribute('style') || '';
        const re = /url\(["']?([^"')]+)["']?\)/g;
        let m;
        while ((m = re.exec(s)) !== null) {
            if (m[1]) out.images.push(abs(m[1]));
        }
    });

    // 计算样式背景图(CSS 类定义的背景,不只是内联)
    // 性能:只查常见容器标签 + 限制数量,避免超大页面卡顿
    try {
        const cand = document.querySelectorAll(
            'div,section,header,footer,main,aside,article,li,a,span,figure'
        );
        const limit = Math.min(cand.length, 1500);
        for (let i = 0; i < limit; i++) {
            const bg = getComputedStyle(cand[i]).backgroundImage;
            if (bg && bg !== 'none' && bg.indexOf('url(') !== -1) {
                const re = /url\(["']?([^"')]+)["']?\)/g;
                let m;
                while ((m = re.exec(bg)) !== null) {
                    if (m[1]) out.images.push(abs(m[1]));
                }
            }
        }
    } catch(e) {}

    // <picture><source srcset>
    document.querySelectorAll('picture source[srcset]').forEach(s => {
        (s.getAttribute('srcset') || '').split(',').forEach(c => {
            const u = c.trim().split(' ')[0];
            if (u) out.images.push(abs(u));
        });
    });

    // 音频
    document.querySelectorAll('audio').forEach(a => {
        if (a.src) out.audio.push(abs(a.src));
    });
    document.querySelectorAll('audio source[src]').forEach(s => {
        out.audio.push(abs(s.getAttribute('src')));
    });
    // 视频
    document.querySelectorAll('video').forEach(v => {
        if (v.src) out.video.push(abs(v.src));
        if (v.poster) out.images.push(abs(v.poster));
    });
    document.querySelectorAll('video source[src]').forEach(s => {
        out.video.push(abs(s.getAttribute('src')));
    });

    // CSS / JS
    document.querySelectorAll('link[rel~="stylesheet"][href]').forEach(l => {
        out.css.push(abs(l.getAttribute('href')));
    });
    document.querySelectorAll('script[src]').forEach(s => {
        out.js.push(abs(s.getAttribute('src')));
    });

    // <a> 链接:只补抓扩展名明确是音/视频的(由 Python 侧 classify 二次归类)
    document.querySelectorAll('a[href]').forEach(a => {
        out.audio.push(abs(a.getAttribute('href')));
    });

    for (const k in out) out[k] = out[k].filter(Boolean);
    return out;
}
"""


class ResourceScanner:
    """扫描一个 URL 的全部资源,按类别返回。"""

    def __init__(
        self,
        chrome_exe: str = CHROME_EXE,
        timeout_ms: int = 90000,
        user_data_dir: str | None = None,
        scroll_rounds: int = 8,
    ):
        self.chrome_exe = chrome_exe
        self.timeout_ms = timeout_ms
        self.user_data_dir = user_data_dir or _DEFAULT_USER_DATA
        self.scroll_rounds = scroll_rounds

    # ---- 内部:渐进滚动,触发懒加载/无限滚动 ----
    def _auto_scroll(self, page):
        """分多段滚到底,每段等一下,给懒加载/无限滚动留时间。"""
        try:
            page.evaluate(
                """() => {
                    window.__wd_stop = false;
                    let last = 0, stable = 0;
                    const timer = setInterval(() => {
                        window.scrollBy(0, Math.max(400, window.innerHeight * 0.8));
                        const h = document.body.scrollHeight;
                        const y = window.scrollY + window.innerHeight;
                        if (y >= h - 4) {
                            if (h === last) { stable++; } else { stable = 0; last = h; }
                        }
                        if (stable >= 2 || window.__wd_stop) {
                            clearInterval(timer);
                            window.scrollTo(0, document.body.scrollHeight);
                        }
                    }, 500);
                }"""
            )
            # 等滚动循环自己停(稳定 2 次)或超时
            page.wait_for_function(
                "() => (window.scrollY + window.innerHeight) >= (document.body.scrollHeight - 8)",
                timeout=min(self.timeout_ms, 30000),
            )
        except Exception:
            pass
        finally:
            try:
                page.evaluate("() => { window.__wd_stop = true; }")
            except Exception:
                pass

    def scan(self, url: str) -> dict:
        """扫描 url,返回 dict:
        {
          'images': [url,...], 'audio': [...], 'video': [...],
          'css': [...], 'js': [...],
          'html': <渲染后的 outerHTML 字符串>,
        }
        """
        result = {"images": [], "audio": [], "video": [], "css": [], "js": [], "html": ""}

        os.makedirs(self.user_data_dir, exist_ok=True)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=True,
                executable_path=self.chrome_exe,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
                viewport={"width": 1366, "height": 900},
                accept_downloads=False,
            )
            page = context.pages[0] if context.pages else context.new_page()

            # 网络响应监听:补抓 DOM 里没有的资源(懒加载/动态/背景图/XHR 媒体)
            seen_net: set[str] = set()

            def on_response(response):
                try:
                    u = response.url
                    if not u or is_data_url(u):
                        return
                    ct = response.headers.get("content-type", "")
                    cat = classify(u, ct)
                    if cat and cat != "html" and u not in seen_net:
                        seen_net.add(u)
                        result.setdefault(cat, []).append(u)
                except Exception:
                    pass

            page.on("response", on_response)

            # 1) 先 commit,尽快建立文档
            try:
                page.goto(url, wait_until="commit", timeout=self.timeout_ms)
            except Exception:
                pass

            # 2) 等 DOM ready
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass

            # 3) 等网络空闲(动态资源、懒加载首批)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            # 4) 渐进滚动,触发懒加载/无限滚动
            self._auto_scroll(page)
            try:
                page.wait_for_timeout(1200)
            except Exception:
                pass

            # 5) DOM 提取(含计算样式背景图、懒加载占位属性)
            try:
                dom_res = page.evaluate(_EXTRACT_JS)
            except Exception:
                dom_res = {"images": [], "audio": [], "video": [], "css": [], "js": []}

            # 6) 渲染后的 HTML
            try:
                result["html"] = page.content()
            except Exception:
                result["html"] = ""

            try:
                context.close()
            except Exception:
                pass

        # ---- 合并:网络拦截(已按 content-type 分类) + DOM 提取 ----
        merged: dict[str, set[str]] = {
            "images": set(), "audio": set(), "video": set(),
            "css": set(), "js": set(),
        }
        for cat in ("images", "audio", "video", "css", "js"):
            for u in result.get(cat, []):
                nu = normalize_url(url, u)
                if nu and not is_data_url(nu):
                    merged[cat].add(nu)

        for raw_cat, urls in dom_res.items():
            for u in urls:
                if not u or is_data_url(u):
                    continue
                nu = normalize_url(url, u)
                if not nu:
                    continue
                if raw_cat in ("audio", "video"):
                    # <a> 链接只有扩展名匹配才保留,丢弃页面内链
                    cat = classify(nu)
                    if cat in ("audio", "video"):
                        merged[cat].add(nu)
                else:
                    cat = classify(nu) or raw_cat
                    if cat in merged:
                        merged[cat].add(nu)

        for cat in merged:
            result[cat] = sorted(merged[cat])

        return result
