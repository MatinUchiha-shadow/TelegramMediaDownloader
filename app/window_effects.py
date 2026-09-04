# -*- coding: utf-8 -*-
"""افکت‌های پنجره در ویندوز:
- بلور آکریلیک (Acrylic) پشت پنجره — ویندوز ۱۰ نسخهٔ ۱۸۰۳ به بالا
- در غیر این صورت بلور ساده؛ و اگر هیچ‌کدام نشد، فقط پس‌زمینهٔ نیمه‌شفاف
"""
import ctypes
import sys


def _hwnd(widget) -> int | None:
    try:
        return int(widget.winId())
    except Exception:
        return None


def enable_acrylic(hwnd: int, tint: int = 0xDC261610) -> bool:
    """فعال‌سازی بلور پشت پنجره.

    tint به‌صورت ABGR: (alpha<<24)|(blue<<16)|(green<<8)|red
    مقدار پیش‌فرض: آلفای ۲۲۰ با رنگ تیرهٔ آبی-سرمه‌ای.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:

        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t),
            ]

        user32 = ctypes.windll.user32
        SetWindowCompositionAttribute = user32.SetWindowCompositionAttribute
        SetWindowCompositionAttribute.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        SetWindowCompositionAttribute.restype = ctypes.c_int

        # ۴ = آکریلیک، ۳ = بلور ساده
        for accent_state in (4, 3):
            policy = ACCENT_POLICY()
            policy.AccentState = accent_state
            policy.AccentFlags = 2  # همراه با رنگ‌پایه
            policy.GradientColor = tint
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19  # WCA_ACCENT_POLICY
            data.Data = ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(policy)
            try:
                if SetWindowCompositionAttribute(hwnd, ctypes.byref(data)):
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False
