#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""راه‌انداز پنجرهٔ مستقل با pywebview (WebView2) + تم تیرهٔ شیشه‌ای.
HTML از طریق یک سرور HTTP محلی سرو می‌شود (WebView2 به file:// درست لود نمی‌کند).
بدون مرورگر، بدون Qt، بدون صفحهٔ سفید.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import APP_DIR
from app.logger_setup import setup_logging


def _start_server(gui_dir):
    import http.server
    import socketserver

    PORT = 8767

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(gui_dir), **kw)

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    setup_logging(APP_DIR / "logs")

    # در هنگام باندل (PyInstaller) پوشهٔ webview_gui در _MEIPASS است
    gui_dir = Path(__file__).resolve().parent / "webview_gui"
    if getattr(sys, "frozen", False):
        gui_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "webview_gui"

    from webview_backend import Api

    import webview

    # شروع سرور محلی برای سرو HTML/CSS/JS
    _start_server(gui_dir)
    url = "http://127.0.0.1:8767/index.html"

    api = Api()

    # پنجرهٔ مات با پس‌زمینهٔ تیرهٔ CSS.
    # transparent=True روی WebView2 کار نمی‌کند و صفحه را سفید/سیاه می‌کند؛
    # پس مات می‌گذاریم و پس‌زمینهٔ تیره هم در HTML تضمین شده.
    window = webview.create_window(
        "Telegram Media Downloader",
        url=url,
        js_api=api,
        width=1000,
        height=680,
        min_size=(820, 540),
        transparent=False,
        frameless=False,  # عنوان‌بار استاندارد ویندوز
        background_color="#161d2b",
    )

    webview.start()


if __name__ == "__main__":
    main()