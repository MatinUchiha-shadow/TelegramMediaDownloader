#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست جریان GUI: start → get_login_state → My Chats → لیست چتها."""
import sys, time, socketserver, http.server, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
R = Path(__file__).resolve().parent / "chats_probe_result.txt"
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
    webview.create_window("ChatsProbe", url="http://127.0.0.1:8767/index.html",
                          js_api=api, width=1000, height=680, transparent=False,
                          background_color="#161d2b")

    def probe():
        time.sleep(10)
        try:
            w = webview.windows[0]
            def js(e): return w.evaluate_js(e)

            # بعد از start، آیا loginCard مخفی شده؟ (ورود خودکار)
            loginHidden = js("document.getElementById('loginCard').style.display === 'none'")
            status1 = js("document.getElementById('status').textContent")

            # برو به My Chats
            js("document.querySelector('.nav-item[data-page=chats]').click()")
            time.sleep(12)
            count = js("document.querySelectorAll('#chatList .chat-item').length")
            first3 = js("""Array.prototype.slice.call(document.querySelectorAll('#chatList .chat-item .t'),0,3).map(function(e){return e.textContent;}).join(' | ')""")
            status2 = js("document.getElementById('status').textContent")

            R.write_text(str({
                "loginHidden": loginHidden, "status1": status1,
                "chatCount": count, "first3": first3, "status2": status2,
            }), encoding="utf-8")
            print("CHATS:", loginHidden, status1, "| count", count, "|", first3, "|", status2)
        except Exception as e:
            R.write_text("ERR " + str(e), encoding="utf-8")
            print("ERR", e)

    def done():
        time.sleep(1); webview.windows[0].destroy()

    webview.start(probe); done()


main()