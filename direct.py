#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
URL="http://127.0.0.1:8767/index.html"
R=Path(__file__).resolve().parent/"direct_result.txt"
def main():
    setup_logging(APP_DIR/"logs")
    import webview, webview_backend
    api=webview_backend.Api()
    webview.create_window("Direct", url=URL, js_api=api, width=1000, height=680, transparent=False, background_color="#161d2b")
    def probe():
        time.sleep(6)
        try:
            w=webview.windows[0]
            t0=w.evaluate_js("typeof window.pywebview.api.set_phone")
            # فراخوانی مستقیم و گرفتن نتیجه (باید Promise باشد یا مقدار)
            r=w.evaluate_js("window.pywebview.api.set_phone('09929184925') ")
            t1=w.evaluate_js("typeof window.pywebview.api.set_phone")
            state="t0="+str(t0)+" | direct="+repr(r)+" | t1="+str(t1)
            R.write_text(state,encoding="utf-8"); print(state)
        except Exception as e:
            R.write_text("ERR "+str(e),encoding="utf-8"); print("ERR",e)
    def done():
        time.sleep(1); webview.windows[0].destroy()
    webview.start(probe); done()
main()
