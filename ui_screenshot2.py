#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""گرفتن تصویر پنجرهٔ واقعی (با فونت‌های ویندوز) — اجرا روی دسکتاپ."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import MainWindow  # noqa: E402

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
app.setStyle("Fusion")

w = MainWindow()
w.resize(1080, 700)
w.show()

def snap():
    pix = w.grab()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_real.png")
    pix.save(out)
    print("saved", pix.width(), "x", pix.height())
    w.close()
    app.quit()

QTimer.singleShot(2500, snap)
app.exec()
