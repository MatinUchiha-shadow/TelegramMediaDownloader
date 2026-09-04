# -*- coding: utf-8 -*-
"""راه‌اندازی لاگ: فایل + کنسول + پل به رابط کاربری (Qt signal)."""
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal

APP_LOGGER = "app"


class LogEmitter(QObject):
    """سیگنالی که هر خط لاگ را به UI می‌فرستد."""
    message = Signal(str)


_emitter = LogEmitter()


def get_emitter() -> LogEmitter:
    return _emitter


class QtLogHandler(logging.Handler):
    """Handler که خطوط لاگ را از طریق سیگنال به UI می‌فرستد."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _emitter.message.emit(msg)
        except Exception:
            pass


def setup_logging(log_dir: Path) -> None:
    # کنسول ویندوز (cp1252) نمی‌تواند فارسی چاپ کند؛ به UTF-8 تغییر می‌دهیم.
    # در EXE پنجره‌ای (console=False) sys.stdout/stderr برابر None است — اگر بی‌احتیاط
    # هندلر کنسول اضافه شود، اولین log.info فارسی با UnicodeEncodeError/AttributeError
    # از داخل logging می‌پرد بیرون و تسک در حال اجرا (مثل ساخت APK) را می‌کشد و
    # نتیجه گم می‌شود (UI برای همیشه «در حال کار» می‌ماند). پس فقط وقتی کنسول
    # واقعاً قابل‌نوشتن است اضافه‌اش می‌کنیم.
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:
        pass

    try:
        _out = sys.stdout
        if _out is not None and getattr(_out, "write", None) is not None:
            console = logging.StreamHandler(_out)
            console.setFormatter(fmt)
            root.addHandler(console)
    except Exception:
        pass

    try:
        qt_handler = QtLogHandler()
        qt_handler.setFormatter(fmt)
        root.addHandler(qt_handler)
    except Exception:
        pass


def get_logger(name: str = APP_LOGGER) -> logging.Logger:
    return logging.getLogger(name)
