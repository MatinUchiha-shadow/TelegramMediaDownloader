#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پروب: آیا WebEngine روی دسکتاپ واقعی محتوا را رندر می‌کند؟
با grab خود Chromium (عالی‌وار، بدون اتکا به قابلیت عکس‌برداری ویندوز).
استفاده: python render_probe.py [--soft]
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

USE_SOFT = "--soft" in sys.argv
if USE_SOFT:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from app.web_app import WebMainWindow  # noqa: E402

app = QApplication(sys.argv)
w = WebMainWindow()
w.resize(1000, 650)
w.show()


def probe():
    # گوی Chromium را بگیر
    pm = w.view.grab()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "probe_" + ("soft" if USE_SOFT else "hw") + ".png")
    pm.save(out)
    # رنگ مرکزی (پیکسل وسط) پوینت
    from PySide6.QtGui import QColor
    img = pm.toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    print(f"GRABBED {pm.width()}x{pm.height()} center={c.name()} saved={out}")
    # میانگین روشنایی کل: سفید=پوسته خالی
    total = 0
    count = 0
    for x in range(0, img.width(), 40):
        for y in range(0, img.height(), 40):
            pc = img.pixelColor(x, y)
            total += pc.red() + pc.green() + pc.blue()
            count += 1
    brightness = total / (count * 3)
    print(f"AVG_BRIGHTNESS={brightness:.0f} (سفید ~250 ، تیره ~40)")
    w.close()
    app.quit()


QTimer.singleShot(5000, probe)
QTimer.singleShot(20000, lambda: (print("TIMEOUT"), app.quit()))
app.exec()