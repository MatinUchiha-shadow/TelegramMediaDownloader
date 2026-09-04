#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class Api:
    def set_phone(self, phone):
        return {"ok": True, "phone": phone}

    async def send_code(self, phone):
        return {"ok": True, "phone": phone}

    def plain_value(self):
        return 42


def main():
    import webview

    RESULT = Path(__file__).resolve().parent / "api_probe_result.txt"

    def probe():
        time.sleep(4)
        try:
            js = ("JSON.stringify({" +
                  "setPhoneType: typeof pywebview.api.set_phone," +
                  "setPhoneResult: pywebview.api.set_phone('09990001111')," +
                  "plain: pywebview.api.plain_value()," +
                  "sendCodeType: typeof pywebview.api.send_code," +
                  "sendCodeIsPromise: (pywebview.api.send_code('x') instanceof Promise)" +
                  "})")
            res = webview.windows[0].evaluate_js(js)
            RESULT.write_text(str(res), encoding="utf-8")
            print("RESULT:", res)
        except Exception as e:
            RESULT.write_text("ERR " + str(e), encoding="utf-8")
            print("ERR", e)

    def done():
        time.sleep(1)
        webview.windows[0].destroy()

    webview.create_window(
        "ApiProbe",
        html="<html><body>probe</body></html>",
        js_api=Api(),
        width=500,
        height=300,
    )
    webview.start(probe)
    done()


if __name__ == "__main__":
    main()