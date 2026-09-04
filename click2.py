#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
URL="http://127.0.0.1:8767/index.html"
R=Path(__file__).resolve().parent/"click2_result.txt"
def main():
    setup_logging(APP_DIR/"logs")
    import webview, webview_backend
    api=webview_backend.Api()
    webview.create_window("ClickTest2", url=URL, js_api=api, width=1000, height=680, transparent=False, background_color="#161d2b")
    def probe():
        time.sleep(6)
        try:
            w=webview.windows[0]
            # قبل از کلیک، مستقیم تست کن متد الان function است یا نه
            before=w.evaluate_js("typeof window.pywebview.api.set_phone")
            w.evaluate_js("document.getElementById('phone').value='09990001111'")
            w.evaluate_js("document.getElementById('sendCodeBtn').click()")
            time.sleep(7)
            state=w.evaluate_js("JSON.stringify({before:'" + str(before) + "',msg:document.getElementById('loginMsg').textContent,msgClass:document.getElementById('loginMsg').className})")
            R.write_text(str(state),encoding="utf-8"); print("STATE:",state)
        except Exception as e:
            R.write_text("ERR "+str(e),encoding="utf-8"); print("ERR",e)
    def done():
        time.sleep(1); webview.windows[0].destroy()
    webview.start(probe); done()
main()
