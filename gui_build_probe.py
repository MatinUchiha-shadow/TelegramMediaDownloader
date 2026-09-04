#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, socketserver, http.server, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
R = Path(__file__).resolve().parent / "gui_build_probe.txt"
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
    webview.create_window("GuiBuild", url="http://127.0.0.1:8767/index.html",
                          js_api=api, width=1000, height=680, transparent=False,
                          background_color="#161d2b")
    def probe():
        time.sleep(10)
        try:
            w = webview.windows[0]
            def js(e): return w.evaluate_js(e)
            js("document.querySelector('.nav-item[data-page=chats]').click()")
            time.sleep(25)
            # روی دکمهٔ Android اولین چتِ «درآمد دلاری» کلیک کن (توسط title پیدا می‌کنیم)
            clicked = js("""(function(){
              var items=document.querySelectorAll('#chatList .chat-item');
              for(var i=0;i<items.length;i++){
                var t=items[i].querySelector('.t').textContent||'';
                if(t.indexOf('درآمد')!==-1){ items[i].querySelector('.chat-dl').click(); return items[i].id||items[i].querySelector('.t').textContent; }
              } return null;})()""")
            # یک لحظه صبر کن بعد وضعیت پیام را بخوان (پیشرفت یا انجام)
            time.sleep(25)
            out = {
                "clicked": clicked,
                "msg": js("document.getElementById('chatsMsg').textContent"),
                "msgClass": js("document.getElementById('chatsMsg').className"),
                "status": js("document.getElementById('status').textContent"),
            }
            R.write_text(str(out), encoding="utf-8"); print("GUI-BUILD:", out)
        except Exception as e:
            R.write_text("ERR " + str(e), encoding="utf-8"); print("ERR", e)
    def done():
        time.sleep(1); webview.windows[0].destroy()
    webview.start(probe); done()

main()