#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست دود رابط کاربری (بدون نمایش پنجره)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import MainWindow  # noqa: E402

app = QApplication(sys.argv)
w = MainWindow()
w.show()
for page in ("chats", "download", "android", "log", "login", "chats"):
    w._goto(page)
app.processEvents()
assert w.stack.count() == 5
print("UI smoke test OK — pages:", w.stack.count())
w.close()
