#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اسکرین‌شات از رابط کاربری (بدون نمایش پنجره)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import MainWindow  # noqa: E402

app = QApplication(sys.argv)
w = MainWindow()
w.resize(1080, 700)
w.show()

for page in ("chats", "download", "android", "log", "login"):
    w._goto(page)
    app.processEvents()

w._goto("login")
app.processEvents()

pix = w.grab()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_screenshot.png")
pix.save(out)
print("saved", pix.width(), "x", pix.height())
w.close()
