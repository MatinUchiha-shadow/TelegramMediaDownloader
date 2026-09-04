# -*- coding: utf-8 -*-
"""مدیریت تنظیمات برنامه — ذخیره در پوشهٔ AppData کاربر."""
import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "TelegramMediaDownloader"
CONFIG_FILE = APP_DIR / "config.json"
SESSION_DIR = APP_DIR / "sessions"
EXPORTS_ROOT = Path.home() / "Desktop" / "TelegramMediaDownloader Exports"

# نکته امنیتی: هیچ کلید API اینجا هاردکد نیست. هر کاربر باید از
# my.telegram.org کلید خودش را بگیرد و در بخش API برنامه وارد کند.
DEFAULT_CONFIG = {
    "api_id": "",
    "api_hash": "",
    "phone": "",
    "export_root": str(EXPORTS_ROOT),
    "music_root": "",
    "proxy_host": "127.0.0.1",
    "proxy_port": "10808",  # پورت‌ واقعی v2rayN/xray (SOCKS5)
}


def require_api(cfg: dict) -> None:
    """اگر api_id/api_hash وارد نشده باشد، خطای فارسی واضح می‌دهد."""
    if not str(cfg.get("api_id") or "").strip() or not str(cfg.get("api_hash") or "").strip():
        raise RuntimeError(
            "api_id و api_hash وارد نشده است؛ از my.telegram.org بگیرید و در بخش API وارد کنید."
        )

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
