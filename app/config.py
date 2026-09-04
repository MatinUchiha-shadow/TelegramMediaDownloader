# -*- coding: utf-8 -*-
"""مدیریت تنظیمات برنامه — ذخیره در پوشهٔ AppData کاربر."""
import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "TelegramMediaDownloader"
CONFIG_FILE = APP_DIR / "config.json"
SESSION_DIR = APP_DIR / "sessions"
EXPORTS_ROOT = Path.home() / "Desktop" / "TelegramMediaDownloader Exports"

DEFAULT_CONFIG = {
    "api_id": "2040",
    "api_hash": "b18441a1ff607e10a989891a5462e627",
    "phone": "",
    "export_root": str(EXPORTS_ROOT),
    "music_root": "",
    "proxy_host": "127.0.0.1",
    "proxy_port": "10808",  # پورت‌ واقعی v2rayN/xray (SOCKS5)
}

_loaded = None


def load_config() -> dict:
    """خواندن تنظیمات (با کش)."""
    global _loaded
    if _loaded is None:
        cfg = dict(DEFAULT_CONFIG)
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                cfg.update({k: v for k, v in data.items() if k in cfg})
        except Exception:
            pass
        # اگر کاربر api_id ذخیره نکرده است، جفت عمومی پیش‌فرض را پر می‌کنیم
        if not (cfg.get("api_id") or "").strip():
            cfg["api_id"] = DEFAULT_CONFIG["api_id"]
        if not (cfg.get("api_hash") or "").strip():
            cfg["api_hash"] = DEFAULT_CONFIG["api_hash"]
        if not (cfg.get("proxy_host") or "").strip():
            cfg["proxy_host"] = DEFAULT_CONFIG.get("proxy_host", "")
        if not (cfg.get("proxy_port") or "").strip():
            cfg["proxy_port"] = DEFAULT_CONFIG.get("proxy_port", "")
        _loaded = cfg
    return _loaded


def save_config(cfg: dict) -> None:
    """ذخیرهٔ تنظیمات."""
    global _loaded
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _loaded = cfg
    except Exception:
        pass


def session_path() -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / "telegram.session"


def proxy_tuple(cfg: dict):
    """ساخت tuple پروکسی برای Telethon (فقط در صورت پر بودن فیلدها)."""
    host = (cfg.get("proxy_host") or "").strip()
    port = (cfg.get("proxy_port") or "").strip()
    if host and port:
        try:
            return ("socks5", host, int(port))
        except ValueError:
            return None
    return None
