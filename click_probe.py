#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کل برنامهٔ واقعی را با رابط واقعی لود می‌کند، شماره می‌گذارد،
روی Send Code کلیک می‌کند و نتیجه‌ای که JS نمایش می‌دهد را می‌خواند."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import APP_DIR
from app.logger_setup import setup_logging

URL = "http://127.0.0.1:8767/index.html"
RESULT_FILE = Path(__file__).resolve().parent / "click_probe_result.txt"


def main():
    setup_logging(APP_DIR / "logs")
    import webview
    import webview_backend

    api = webview_backend.Api()
    webview.create_window(
        "TelegramMediaClickTest",
        url=URL,
        js_api=api,
        width=1000,
        height=680,
        transparent=False,
        background_color="#161d2b",
    )

    def probe():
        time.sleep(3)
        try:
            w = webview.windows[0]
            # بررسی دسترسی بریج
            bridge = w.evaluate_js("typeof window.pywebview + '/' + typeof window.pywebview.api")
            # شماره را بگذار و کلیک کن
            w.evaluate_js("document.getElementById('phone').value='09990001111'")
            w.evaluate_js("document.getElementById('sendCodeBtn').click()")
            # چند ثانیه بعد نتیجه را بخوان
            time.sleep(8)
            state = w.evaluate_js(
                "JSON.stringify({"
                "bridge: '" + bridge + "',"
                "msg: document.getElementById('loginMsg').textContent,"
                "msgClass: document.getElementById('loginMsg').className,"
                "btnDisabled: document.getElementById('sendCodeBtn').disabled,"
                "codeDisabled: document.getElementById('code').disabled,"
                "phoneVal: document.getElementById('phone').value"
                "})"
            )
            RESULT_FILE.write_text(str(state), encoding="utf-8")
            print("STATE:", state)
        except Exception as e:
            RESULT_FILE.write_text("ERR " + str(e), encoding="utf-8")
            print("ERR", e)

    def sec_state():
        time.sleep(2)
        webview.windows[0].destroy()

    webview.start(probe)
    sec_state()


if __name__ == "__main__":
    main()