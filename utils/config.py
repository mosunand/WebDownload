"""应用配置持久化(JSON):保存目录、并发数、自定义图标路径等。

配置存于项目目录下的 config.json,启动时加载,设置界面修改后写回。
"""
from __future__ import annotations

import json
import os

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
)

# 全部支持的配置项及默认值
DEFAULTS: dict = {
    "save_dir": "",        # 默认保存目录(空 = WebDownload/downloads)
    "max_workers": 6,      # 并发下载线程数
    "icon_path": "",       # 自定义窗口/任务栏图标路径(png/ico),空 = 内置默认图标
    "scroll_rounds": 8,    # 扫描时渐进滚动的轮数上限
}


def load() -> dict:
    """读取配置,缺失字段用默认值补齐。文件损坏时静默回退默认。"""
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data:
                        cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def save(cfg: dict) -> bool:
    """写回配置。返回是否成功。"""
    try:
        data = dict(DEFAULTS)
        data.update({k: v for k, v in cfg.items() if k in DEFAULTS})
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def path() -> str:
    return _CONFIG_PATH
