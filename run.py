#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""نقطهٔ ورود برنامه — اجرا با: python run.py
GUI کاملاً HTML است و در مرورگر سیستم باز می‌شود؛ پایتون فقط در پیش‌زمینه.
"""
import atexit
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import APP_DIR  # noqa: E402
from app.logger_setup import setup_logging  # noqa: E402
from app.web_server import start_server  # noqa: E402

# برای اینکه مرورگر ویندوز کنسول را باز نکند و رندر در همه‌جا درست باشد
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def main() -> int:
    setup_logging(APP_DIR / "logs")

    port = 8756
    server = start_server(port=port, open_browser=True)

    # منتظر بمان تا برنامه بسته شود (تست آفلاین: Ctrl+C)
    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())