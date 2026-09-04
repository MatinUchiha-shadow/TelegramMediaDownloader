#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست کامل جریان ورود: شماره → Send Code → Verify با کد اشتباه.
انتظار: دکمهٔ Verify ظاهر شود و پیام «کد اشتباه است» بیاید (نه خطای hash)."""
import sys, time, socketserver, http.server, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
R = Path(__file__).resolve().parent / "flow_probe_result.txt"
GUI = Path(__file__).resolve().parent / "webview_gui"


def start_server():
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw): super().__init__(*a, directory=str(GUI), **kw)
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 8767), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    setup_logging(APP_DIR / "logs")
    import webview, webview_backend
    start_server()
    api = webview_backend.Api()
    webview.create_window("FlowProbe", url="http://127.0.0.1:8767/index.html",
                          js_api=api, width=1000, height=680, transparent=False,
                          background_color="#161d2b")

    def probe():
        time.sleep(10)
        try:
            w = webview.windows[0]
            def js(e): return w.evaluate_js(e)

            # 1) send code
            js("document.getElementById('phone').value='09990001111'")
            js("document.getElementById('sendCodeBtn').click()")
            time.sleep(10)
            step1 = {
                "msg": js("document.getElementById('loginMsg').textContent"),
                "verifyVisible": js("document.getElementById('verifyBtn').style.display"),
                "codeEnabled": js("!document.getElementById('code').disabled"),
            }

            # 2) enter wrong code and verify
            js("document.getElementById('code').value='00000'")
            js("document.getElementById('verifyBtn').click()")
            time.sleep(10)
            step2 = {
                "msg": js("document.getElementById('loginMsg').textContent"),
                "passwordEnabled": js("!document.getElementById('password').disabled"),
                "status": js("document.getElementById('status').textContent"),
            }

            R.write_text(str({"step1": step1, "step2": step2}), encoding="utf-8")
            print("FLOW:", step1, step2)
        except Exception as e:
            R.write_text("ERR " + str(e), encoding="utf-8")
            print("ERR", e)

    def done():
        time.sleep(1); webview.windows[0].destroy()

    webview.start(probe); done()


main()