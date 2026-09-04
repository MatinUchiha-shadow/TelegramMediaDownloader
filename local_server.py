#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""سرور HTTP محلی برای سرو فایل‌های webview_gui (برای WebView2).
پورت ثابت 8767. فقط loopback.
"""
import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "webview_gui"
PORT = 8767


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):
        pass


def main():
    handler = Handler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()