"""Windows 毛玻璃效果封装(可选增强)。

核心思路:
  Qt WA_TranslucentBackground + FramelessWindowHint → 窗口带 WS_EX_LAYERED。
  DWM 的 Acrylic/BlurBehind API 不支持分层窗口,所以必须在窗口创建后:
    1. 用 win32gui 去掉 WS_EX_LAYERED
    2. 再调 DwmExtendFrameIntoClientArea(-1) + DwmEnableBlurBehindWindow
  失败时静默回退到 paintEvent 自绘半透明色块。
仅在 Windows 平台有效。
"""
from __future__ import annotations

import ctypes
import sys


def _is_windows() -> bool:
    return sys.platform == "win32"


# =====================================================================
#  1. 去掉 WS_EX_LAYERED (让 DWM 能接管合成)
# =====================================================================

WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20


def remove_layered_flag(hwnd: int) -> bool:
    """去掉窗口扩展样式的 WS_EX_LAYERED 标志。

    Qt 的 WA_TranslucentBackground + FramelessWindowHint 会自动加上这个标志,
    导致 DWM Acrylic/BlurBehind 完全无效。去掉后 DWM 才能对窗口做模糊。
    返回是否成功。
    """
    if not _is_windows() or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long

        style = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            user32.SetWindowLongW(
                ctypes.c_void_p(hwnd), GWL_EXSTYLE, style & ~WS_EX_LAYERED
            )
            return True
        return False  # 本来就没有,不需要操作
    except Exception:
        return False


# =====================================================================
#  2. DwmExtendFrameIntoClientArea (-1,-1,-1,-1)
# =====================================================================

class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def apply_frame_glass(hwnd: int) -> bool:
    """把玻璃帧扩展到整个客户区。

    去掉 WS_EX_LAYERED 之后,这个调用通常就能让窗口背景变模糊。
    """
    if not _is_windows() or not hwnd:
        return False
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        margins = _MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_MARGINS)
        ]
        dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_int
        hr = dwmapi.DwmExtendFrameIntoClientArea(
            ctypes.c_void_p(hwnd), ctypes.byref(margins)
        )
        return hr == 0
    except Exception:
        return False


# =====================================================================
#  3. DwmEnableBlurBehindWindow (备选)
# =====================================================================

class _DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = [
        ("dwFlags", ctypes.c_uint),
        ("fEnable", ctypes.c_int),
        ("hRgnBlur", ctypes.c_void_p),
        ("fTransitionOnMaximized", ctypes.c_int),
    ]


DWM_BB_ENABLE = 0x1
DWM_BB_TRANSITIONONMAXIMIZED = 0x4


def apply_blur_behind(hwnd: int) -> bool:
    """给整个窗口启用 Aero 模糊。"""
    if not _is_windows() or not hwnd:
        return False
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        bb = _DWM_BLURBEHIND()
        bb.dwFlags = DWM_BB_ENABLE | DWM_BB_TRANSITIONONMAXIMIZED
        bb.fEnable = 1
        bb.hRgnBlur = None
        bb.fTransitionOnMaximized = 1
        dwmapi.DwmEnableBlurBehindWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p
        ]
        dwmapi.DwmEnableBlurBehindWindow.restype = ctypes.c_int
        hr = dwmapi.DwmEnableBlurBehindWindow(
            ctypes.c_void_p(hwnd), ctypes.byref(bb)
        )
        return hr == 0
    except Exception:
        return False


# =====================================================================
#  4. SetWindowCompositionAttribute (Acrylic, 候选)
# =====================================================================

ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENTPOLICY = 19


class _ACCENTPOLICY(ctypes.Structure):
    _fields_ = [
        ("nAccentState", ctypes.c_int),
        ("nFlags", ctypes.c_int),
        ("nColor", ctypes.c_uint),
        ("nAnimationId", ctypes.c_int),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("nAttribute", ctypes.c_int),
        ("pData", ctypes.c_void_p),
        ("ulDataSize", ctypes.c_ulong),
    ]


def apply_acrylic(hwnd: int, color=(30, 32, 42, 150)) -> bool:
    """Acrylic 模糊(仅 Windows 10 1903+,部分版本有效)。"""
    if not _is_windows() or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        accent = _ACCENTPOLICY()
        accent.nAccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.nFlags = 0
        accent.nAnimationId = 0
        r, g, b, a = color
        accent.nColor = (a << 24) | (b << 16) | (g << 8) | r
        data = _WINCOMPATTRDATA()
        data.nAttribute = WCA_ACCENTPOLICY
        data.pData = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.ulDataSize = ctypes.sizeof(accent)
        user32.SetWindowCompositionAttribute.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p
        ]
        user32.SetWindowCompositionAttribute.restype = ctypes.c_int
        ok = user32.SetWindowCompositionAttribute(
            ctypes.c_void_p(hwnd), ctypes.byref(data)
        )
        return bool(ok)
    except Exception:
        return False


# =====================================================================
#  统一入口
# =====================================================================

def apply_glass(hwnd: int, color=(30, 32, 42, 150)) -> bool:
    """对无边框窗口启用真实模糊背景。

    关键步骤:先去掉 WS_EX_LAYERED,再调 DWM API。
    优先级:Acrylic > FrameGlass > BlurBehind。
    失败时调用方依靠低 alpha paintEvent 自绘保持半透明(无模糊)。
    """
    # 第一步:去掉 WS_EX_LAYERED(这是 DWM 模糊生效的前提)
    remove_layered_flag(hwnd)

    # 第二步:尝试各种模糊 API
    if apply_acrylic(hwnd, color):
        return True
    if apply_frame_glass(hwnd):
        return True
    if apply_blur_behind(hwnd):
        return True
    return False
