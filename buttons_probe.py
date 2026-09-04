#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کلیک روی همهٔ دکمه‌های رابط واقعی با سرور داخلی و ثبت پیام/وضعیت هرکدام."""
import sys, time, socketserver, http.server, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import APP_DIR
from app.logger_setup import setup_logging
R = Path(__file__).resolve().parent / "buttons_probe_result.txt"
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
    webview.create_window("ButtonsProbe", url="http://127.0.0.1:8767/index.html",
                          js_api=api, width=1000, height=680, transparent=False,
                          background_color="#161d2b")

    def probe():
        time.sleep(8)
        try:
            w = webview.windows[0]
            def js(e): return w.evaluate_js(e)
            ready = js("!!document.getElementById('phone') && !!document.getElementById('sendCodeBtn')")
            out = {'ready': ready}
            if not ready:
                out['err'] = js("document.documentElement.outerHTML.slice(0,200)")
                R.write_text(str(out), encoding='utf-8'); print('NOT READY', out); return

            out["nav"] = js("""(function(){
              var ids=[];
              document.querySelectorAll('.nav-item[data-page]').forEach(function(b){
                b.click(); ids.push(b.dataset.page+':'+document.getElementById('pageTitle').textContent);
              }); return ids.join('|'); })()""")

            js("document.getElementById('phone').value=''; document.getElementById('sendCodeBtn').click()"); time.sleep(1)
            out["send_empty"] = js("document.getElementById('loginMsg').textContent")

            js("document.getElementById('phone').value='09929184925'; document.getElementById('sendCodeBtn').click()"); time.sleep(6)
            out["send_phone"] = js("document.getElementById('loginMsg').textContent")

            js("document.getElementById('channel').value=''; document.getElementById('browseBtn').click()"); time.sleep(1)
            out["browse_empty"] = js("document.getElementById('status').textContent")

            js("document.getElementById('channel').value='@test'; document.getElementById('browseBtn').click()"); time.sleep(1)
            out["browse_set"] = js("document.getElementById('status').textContent")

            js("document.getElementById('exportBtn').click()"); time.sleep(1)
            out["export"] = js("document.getElementById('status').textContent")

            js("document.getElementById('allBtn').click()")
            out["all_val"] = js("document.getElementById('channel').value")

            js("document.getElementById('settingsBtn').click()"); time.sleep(0.5)
            out["settings"] = js("document.getElementById('status').textContent")

            js("document.getElementById('phone').value='0'; document.getElementById('logoutBtn').click()"); time.sleep(1)
            out["logout"] = js("document.getElementById('loginMsg').textContent")

            R.write_text(str(out), encoding="utf-8")
            print("BUTTONS:", out)
        except Exception as e:
            R.write_text("ERR " + str(e), encoding="utf-8")
            print("ERR", e)

    def done():
        time.sleep(1); webview.windows[0].destroy()

    webview.start(probe); done()


main()