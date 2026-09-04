#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست pywebview: پنجره را باز می‌کند و بعد از لود، DOM را با JS می‌خواند."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import APP_DIR
from app.logger_setup import setup_logging

URL = "http://127.0.0.1:8767/index.html"
RESULT_FILE = Path(__file__).resolve().parent / "dom_check.txt"


def main():
    setup_logging(APP_DIR / "logs")
    import webview
    import webview_backend

    def probe():
        time.sleep(3)
        try:
            js = (
                "JSON.stringify({"
                "title: document.title,"
                "bgIsDark: getComputedStyle(document.body).backgroundColor,"
                "cards: document.querySelectorAll('.card').length,"
                "sidebar: !!document.querySelector('.sidebar'),"
                "navItems: document.querySelectorAll('.nav-item').length,"
                "hasPhone: !!document.getElementById('phone'),"
                "hasChannel: !!document.getElementById('channel'),"
                "status: document.getElementById('status').textContent"
                "})"
            )
            w = webview.windows[0]
            res = w.evaluate_js(js)
            RESULT_FILE.write_text(str(res), encoding="utf-8")
            print("DOM:", res)
        except Exception as e:
            RESULT_FILE.write_text("ERR " + str(e), encoding="utf-8")
            print("ERR", e)

    def done():
        time.sleep(1)
        webview.windows[0].destroy()

    api = webview_backend.Api()
    webview.create_window(
        "TelegramMediaTest",
        url=URL,
        js_api=api,
        width=1000,
        height=680,
        min_size=(820, 540),
        transparent=False,
        background_color="#131a26",
    )
    # بعد از لود کامل در thread اصلی اجرا می‌شود سپس پنجره بسته می‌شود
    webview.start(probe)
    done()


if __name__ == "__main__":
    main()