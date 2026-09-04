#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
URL="http://127.0.0.1:8767/index.html"
R=Path(__file__).resolve().parent/"apitype_result.txt"
def main():
    setup_logging(APP_DIR/"logs")
    import webview, webview_backend
    webview.create_window("ApiType", url=URL, js_api=webview_backend.Api(), width=600, height=400, transparent=False, background_color="#161d2b")
    def probe():
        time.sleep(4)
        try:
            w=webview.windows[0]
            js=("(function(){var a=window.pywebview.api;"+
                "var out={};[" + ','.join("'" + m + "'" for m in ['set_phone','send_code','login','browse_channel','export_all','choose_save_dir','logout']) + "].forEach(function(k){ out[k]=typeof a[k];});"+
                "return JSON.stringify(out);})()")
            r=w.evaluate_js(js)
            R.write_text(str(r),encoding="utf-8"); print("TYPES:",r)
        except Exception as e:
            R.write_text("ERR "+str(e),encoding="utf-8"); print("ERR",e)
    def done():
        time.sleep(1); webview.windows[0].destroy()
    webview.start(probe); done()
main()
