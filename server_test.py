#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست محلی سرور: آیا HTML و API پاسخ می‌دهند؟ (بدون بازکردن مرورگر)"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    from app.web_server import start_server

    start_server(port=8756, open_browser=False)
    time.sleep(1.5)
    base = "http://127.0.0.1:8756"

    # 1) HTML
    st, html = get(base + "/index.html")
    print("HTML:", st, "has_title=", "Telegram Downloader" in html)

    # 2) CSS
    st, css = get(base + "/style.css")
    print("CSS:", st, "len=", len(css))

    # 3) JS
    st, js = get(base + "/app.js")
    print("JS:", st, "len=", len(js))

    # 4) config GET
    st, cfg = get(base + "/api/config")
    cfg = json.loads(cfg)
    print("CONFIG:", st, "ok=", cfg.get("ok"), "phone=", cfg.get("result", {}).get("phone"))

    # 5) save config POST
    st, r = post(base + "/api/config", {"api_id": "", "api_hash": "", "phone": "09929184925",
                                        "proxy_host": "127.0.0.1", "proxy_port": "1080"})
    print("SAVE_CONFIG:", st, "ok=", r.get("ok"))

    # 6) logged_in POST (starts async, should return ok immediately)
    st, r = post(base + "/api/logged_in", {})
    print("LOGGED_IN:", st, "ok=", r.get("ok"), "result=", r.get("result"))

    print("SERVER_TEST_DONE")


if __name__ == "__main__":
    main()