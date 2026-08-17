"""httpx 并发下载器:共享连接池、流式下载、进度节流回调、可取消。"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


class ConcurrentDownloader:
    """对一组 URL 并发流式下载,实时回调进度。

    所有任务共享一个 httpx.Client(连接池),避免每文件重建 TCP/TLS。
    进度回调按时间节流,避免刷屏 Signal 拖慢 UI。
    """

    def __init__(self, max_workers: int = 6, timeout: float = 60.0,
                 progress_interval: float = 0.12):
        self.max_workers = max_workers
        self.timeout = timeout
        self.progress_interval = progress_interval  # 单文件进度回调最小间隔(秒)
        self._cancels: dict[str, threading.Event] = {}
        self._global_stop = threading.Event()

    def stop(self) -> None:
        """请求全局取消所有下载。"""
        self._global_stop.set()
        for ev in self._cancels.values():
            ev.set()

    def _download_one(
        self,
        client: httpx.Client,
        url: str,
        save_path: str,
        on_progress=None,
    ) -> bool:
        """下载单个文件(流式,复用连接池)。返回是否成功。"""
        if self._global_stop.is_set():
            return False
        cancel = threading.Event()
        self._cancels[url] = cancel

        try:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return False
                total = int(resp.headers.get("content-length", 0))
                done = 0
                last_emit = 0.0
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if cancel.is_set() or self._global_stop.is_set():
                            f.close()
                            try:
                                os.remove(save_path)
                            except OSError:
                                pass
                            return False
                        f.write(chunk)
                        done += len(chunk)
                        # 节流:距上次回调超过间隔才发,最后一次必发
                        if on_progress:
                            now = time.monotonic()
                            if (now - last_emit) >= self.progress_interval:
                                last_emit = now
                                on_progress(done, total)
                if on_progress:
                    on_progress(done, total)
            return True
        except Exception:
            try:
                if os.path.exists(save_path):
                    os.remove(save_path)
            except OSError:
                pass
            return False
        finally:
            self._cancels.pop(url, None)

    def download_all(
        self,
        urls: list[str],
        base_dir: str,
        type_key: str,
        base_url: str,
        make_filename=None,
        on_file_progress=None,
        on_file_done=None,
    ) -> tuple[int, int]:
        """并发下载一组 URL 到 base_dir/type_key/ 子目录。

        返回 (成功数, 失败数)。
        on_file_progress(url, done, total) :单文件字节进度(已节流)
        on_file_done(url, ok, save_path)   :单文件完成
        """
        from utils.urlutils import safe_filename

        sub_dir = os.path.join(base_dir, type_key)
        os.makedirs(sub_dir, exist_ok=True)

        # 预先分配不冲突的文件名
        assigned: list[tuple[str, str]] = []
        used: set[str] = set()
        for u in urls:
            if self._global_stop.is_set():
                break
            name = make_filename(u) if make_filename else safe_filename(u)
            base, ext = os.path.splitext(name)
            candidate = name
            i = 1
            while candidate in used or os.path.exists(os.path.join(sub_dir, candidate)):
                candidate = f"{base}_{i}{ext}"
                i += 1
            used.add(candidate)
            assigned.append((u, os.path.join(sub_dir, candidate)))

        ok_count = 0
        fail_count = 0

        if not assigned:
            return 0, 0

        # 共享连接池:浏览器 UA + 连接复用 + 合理上限
        limits = httpx.Limits(
            max_connections=self.max_workers * 2,
            max_keepalive_connections=self.max_workers,
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        }

        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            limits=limits,
            headers=headers,
            http2=False,
        ) as client:

            def task(item):
                url, path = item
                self._download_one(
                    client, url, path,
                    on_progress=(
                        (lambda d, t, _u=url: on_file_progress(_u, d, t))
                        if on_file_progress else None
                    ),
                )
                return url, path

            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {pool.submit(task, it): it for it in assigned}
                for fut in as_completed(futures):
                    if self._global_stop.is_set():
                        break
                    try:
                        url, path = fut.result()
                        ok = os.path.exists(path) and os.path.getsize(path) > 0
                        if ok:
                            ok_count += 1
                        else:
                            fail_count += 1
                        if on_file_done:
                            on_file_done(url, ok, path)
                    except Exception:
                        fail_count += 1
                        if on_file_done:
                            on_file_done(None, False, "")

        return ok_count, fail_count
