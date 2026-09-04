#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backend پایتون برای پنجرهٔ pywebview.
بدون Qt — فقط telethon + دانلود + خروجی. GUI شیشه‌ای است.
"""
import asyncio
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import load_config, save_config, session_path
from app.tg_client import send_code, sign_in, fetch_dialogs, is_logged_in, normalize_phone
from app.logger_setup import get_logger

log = get_logger("backend")

# قفل برای پروندهٔ session (SQLite) — فقط یک کلاینت در لحظه
# به session دسترسی دارد تا «database is locked» رخ ندهد.
_session_lock = threading.Lock()


def _run_async(corofunc, *args, on_done=None, on_error=None):
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(corofunc(*args))
            if on_done:
                on_done(result)
        except Exception as e:
            log.exception("async task failed")
            if on_error:
                on_error(e)
        finally:
            loop.close()

    threading.Thread(target=run, daemon=True).start()


def _friendly_login_error(e) -> str:
    """تبدیل خطاهای ورود تلگرام به پیام فارسی کوتاه."""
    name = type(e).__name__
    if name == "PhoneCodeInvalidError":
        return "کد واردشده اشتباه است. دوباره تلاش کنید."
    if name == "PhoneCodeExpiredError":
        return "کد منقضی شده است. دوباره Send Code بزنید."
    if name == "FloodWaitError":
        return "تلگرام محدودیت گذاشته — چند دقیقه صبر کنید و دوباره تلاش کنید."
    if name == "PasswordHashInvalidError":
        return "رمز دومرحله‌ای اشتباه است."
    if name == "PhoneNumberUnoccupiedError":
        return "این شماره در تلگرام ثبت نشده است."
    if name in ("ApiIdInvalidError", "AuthKeyUnregisteredError"):
        return "api_id/api_hash معتبر نیست — از تب API مقادیر را بررسی کنید."
    if "connect" in name.lower() or "Timeout" in name or "Network" in name:
        return "اتصال به تلگرام برقرار نشد — اینترنت/پروکسی را بررسی کنید."
    return str(e)[:200]


class Api:
    """متدهایی که از JS (pywebview.api.X) صدا زده می‌شوند."""

    def __init__(self):
        self.cfg = load_config()
        self._phone_code_hash = ""
        self._building = False
        self._build_progress = {"state": "idle"}
        self._build_result = None

    # ---------------- ورود ----------------
    def set_phone(self, phone):
        self.cfg["phone"] = normalize_phone(phone)
        save_config(self.cfg)
        return True

    def send_code(self, phone):
        done = threading.Event()
        holder = {}

        def ok(hash_value):
            # hash از send_code می‌آید و برای sign_in لازم است
            self._phone_code_hash = hash_value or ""
            holder["r"] = "sent"
            done.set()

        def err(e):
            holder["r"] = {"error": str(e)}
            done.set()

        _run_async(send_code, self.cfg, normalize_phone(phone), on_done=ok, on_error=err)
        # مهم: صبر می‌کنیم تا عملی real تمام شود؛ اگر تمام نشد خطای صادقانه گزارش می‌دهیم.
        if not done.wait(timeout=60):
            return {"error": "تلگرام جواب نداد (زمان‌بیش از ۶۰ ثانیه). اتصال/پروکسی/اینترنت را بررسی کنید."}
        return holder.get("r", {"error": "ارسال نامعلوم؛ دوباره تلاش کنید."})

    def login(self, phone, code, password):
        done = threading.Event()
        holder = {}

        def ok(name):
            holder["name"] = name
            done.set()

        def err(e):
            args = getattr(e, "args", ())
            holder["error"] = args[0] if args and args[0] == "2FA" else _friendly_login_error(e)
            done.set()

        _run_async(
            sign_in, self.cfg, normalize_phone(phone), code.strip(),
            (password or "").strip() or None,
            self._phone_code_hash,
            on_done=ok, on_error=err,
        )
        if not done.wait(timeout=90):
            return {"error": "ورود جواب نداد (زمان‌بیش از ۹۰ ثانیه). اتصال را بررسی کنید."}
        if "error" in holder:
            return {"error": holder["error"]}
        return holder.get("name", "")

    def get_login_state(self):
        """بررسی اینکه نشست ذخیره‌شده هنوز معتبر است (برای ورود خودکار)."""
        done = threading.Event()
        holder = {}

        def ok(is_auth):
            holder["logged_in"] = bool(is_auth)
            holder["phone"] = self.cfg.get("phone", "")
            done.set()

        def err(e):
            holder["logged_in"] = False
            holder["phone"] = self.cfg.get("phone", "")
            holder["error"] = str(e)[:200]
            done.set()

        _run_async(is_logged_in, self.cfg, on_done=ok, on_error=err)
        if not done.wait(timeout=30):
            return {"logged_in": False, "phone": self.cfg.get("phone", "")}
        return holder

    def logout(self):
        # حذف نشست
        try:
            sp = session_path()
            for suffix in (".session", ".session-journal"):
                p = Path(str(sp) + suffix)
                if p.exists():
                    p.unlink()
        except Exception:
            pass
        return True

    # ---------------- تنظیمات ----------------
    def get_config(self):
        # تازه از روی دیسک می‌خوانیم تا آخرین تغییرات دیده شود
        import json
        from app.config import CONFIG_FILE
        try:
            if CONFIG_FILE.exists():
                c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                return {
                    "api_id": c.get("api_id", ""),
                    "api_hash": c.get("api_hash", ""),
                    "proxy_host": c.get("proxy_host", ""),
                    "proxy_port": c.get("proxy_port", ""),
                }
        except Exception:
            pass
        return {
            "api_id": self.cfg.get("api_id", ""),
            "api_hash": self.cfg.get("api_hash", ""),
            "proxy_host": self.cfg.get("proxy_host", ""),
            "proxy_port": self.cfg.get("proxy_port", ""),
        }

    def set_api_config(self, api_id, api_hash, proxy_host, proxy_port):
        if (api_id or "").strip():
            self.cfg["api_id"] = api_id.strip()
        if (api_hash or "").strip():
            self.cfg["api_hash"] = api_hash.strip()
        self.cfg["proxy_host"] = (proxy_host or "127.0.0.1").strip()
        self.cfg["proxy_port"] = str(proxy_port or "10808").strip()
        save_config(self.cfg)
        return True

    # ---------------- چت/Channel ----------------
    def get_dialogs(self):
        """لیست واقعی چت‌ها/گروه‌ها/کانال‌ها (JSON-safe)."""
        import time as _time

        # اگر سشن لحظه‌ای قفل باشد (دانلود همزمان در حال اجراست)، تا ۳ بار
        # با فاصله تلاش می‌کند به‌جای اینکه فوری خطا بدهد.
        holder = {"error": "دریافت چت‌ها جواب نداد — اتصال را بررسی کنید."}
        for attempt in range(3):
            done = threading.Event()
            holder = {}

            def ok(dialogs):
                # entity ها قابل JSON نیستند؛ فقط فیلدهای ساده برمی‌گردانیم
                holder["dialogs"] = [
                    {
                        "id": d.get("id"),
                        "title": d.get("title", ""),
                        "type": d.get("type", "unknown"),
                        "unread": d.get("unread", 0),
                    }
                    for d in dialogs
                ]
                holder["self_name"] = dialogs[0].get("self_name", "") if dialogs else ""
                done.set()

            def ok_empty():
                holder["dialogs"] = []
                holder["self_name"] = ""
                done.set()

            def err(e):
                holder["error"] = _friendly_login_error(e) if e else "خطا"
                done.set()

            _run_async(fetch_dialogs, self.cfg, on_done=ok, on_error=err)
            if not done.wait(timeout=60):
                return {"error": "دریافت چت‌ها جواب نداد — اتصال را بررسی کنید."}
            if "error" in holder and "database is locked" in str(holder["error"]) and attempt < 2:
                log.info("get_dialogs: session locked — retry %d/3", attempt + 2)
                _time.sleep(2.5)
                continue
            return holder
        return holder

    def browse_channel(self, username):
        # در این نسخهٔ ساده: همان لیست چت‌ها را برمی‌گرداند
        return self.get_dialogs()

    # ---- ساخت اپ اندروید (پس‌زمینه + پیشرفت) ----
    def start_build(self, chat_id, include_media=True):
        """دانلود کامل چت + ساخت اپ اندروید را در پس‌زمینه شروع می‌کند.
        فوراً برمی‌گردد؛ پیشرفت را با get_build_progress می‌خوانند.
        include_media=False یعنی فقط متن/پیام‌ها (رد رسانه) — برای اینترنت کند
        که دانلود فایل‌ها طول می‌کشد.
        """
        chat_id = int(chat_id)
        if getattr(self, "_building", False):
            return {"error": "یک ساخت در حال اجراست؛ ابتدا تمام شود."}
        self._building = True
        self._include_media = bool(include_media)
        self._build_progress = {"state": "starting", "done": 0, "total": 0, "label": "در حال شروع…"}
        self._build_result = None
        # مبنای سرعت‌سنج: حجم پوشه خروجی در شروع (نمونه‌برداری تنبل در get_build_progress)
        self._scan_b0 = None
        self._scan_t0 = 0.0
        self._scan_t = 0.0
        self._scan_mb = 0.0
        self._scan_rate = 0.0

        def update(step, d, tot):
            if step == "repair":
                lbl = f"ترمیم رسانه‌های جاافتاده {d} از {tot}" if tot else "ترمیم رسانه‌ها…"
            else:
                lbl = f"دانلود {d} از {tot} پیام" if tot else "در حال دانلود…"
            self._build_progress = {"state": "downloading", "done": int(d or 0), "total": int(tot or 0), "label": lbl}

        def ok(_r):
            self._build_progress = {"state": "building", "done": 0, "total": 0, "label": "ساخت اپ اندروید…"}
            self._build_result = _r
            self._build_progress = {"state": "done", "done": 0, "total": 0, "label": "تمام شد."}
            self._building = False

        def err(e):
            self._build_result = {"error": _friendly_login_error(e) if hasattr(e, "args") else str(e)}
            self._build_progress = {"state": "error", "done": 0, "total": 0, "label": "خطا."}
            self._building = False

        _run_async(self._build_job, chat_id, self._include_media, update, on_done=ok, on_error=err)
        return {"started": True}

    def get_build_progress(self):
        base = dict(getattr(self, "_build_progress", {"state": "idle"}))
        # سرعت لحظه‌ای دانلود (MB دانلودشده و میانگین MB/s از شروع) — نمونه‌برداری
        # حجم پوشه خروجی حداکثر هر 4 ثانیه تا روی ترد UI فشار نیاید.
        try:
            if base.get("state") == "downloading":
                import time as _t
                import os as _os
                now = _t.time()
                if now - getattr(self, "_scan_t", 0) >= 4:
                    from app.config import EXPORTS_ROOT as _ER
                    total = 0
                    try:
                        for _dp, _dn, _fn in _os.walk(str(_ER)):
                            for _f in _fn:
                                try:
                                    total += _os.path.getsize(_os.path.join(_dp, _f))
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    if getattr(self, "_scan_b0", None) is None:
                        self._scan_b0, self._scan_t0 = total, now
                    dt = max(1.0, now - getattr(self, "_scan_t0", now))
                    self._scan_mb = round((total - self._scan_b0) / 1048576, 1)
                    self._scan_rate = round((total - self._scan_b0) / dt / 1048576, 2)
                    self._scan_t = now
                base["mb"] = getattr(self, "_scan_mb", 0.0)
                base["rate"] = getattr(self, "_scan_rate", 0.0)
        except Exception:
            pass
        return base

    def get_build_result(self):
        return self._build_result

    def get_logs(self, n=300):
        """آخر n خط لاگ برنامه — برای صفحه Logs داخل EXE (تشخیص FloodWait/خطا/سرعت)."""
        try:
            from app.config import APP_DIR
            p = APP_DIR / "logs" / "app.log"
            if not p.exists():
                return {"lines": []}
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            try:
                n = max(50, min(2000, int(n or 300)))
            except (TypeError, ValueError):
                n = 300
            return {"lines": lines[-n:]}
        except Exception as e:
            return {"error": str(e)[:200]}

    async def _build_job(self, chat_id, include_media, update):
        """همهٔ مراحل: یافتن چت → دانلود کامل → HTML → پروژهٔ اندروید."""
        from app.config import EXPORTS_ROOT
        from app.android_builder import build_android_app
        from app.exporter import generate_index, generate_chat_page, ensure_assets
        from app.downloader import export_chat_async, sanitize_name
        from app.tg_client import _client

        # فقط عنوان چت را بگیر — entity را داخل export_chat_async
        # با کلاینت جدید بازسازی می‌کنیم تا «۰ پیام» رخ ندهد.
        with _session_lock:
            title = "chat"
            ent_type = "channel"
            c = _client(self.cfg, None)
            try:
                await c.connect()
                ent = await c.get_entity(int(chat_id))
                title = getattr(ent, "title", None) or getattr(ent, "first_name", "") or "chat"
                ent_type = "channel" if getattr(ent, "broadcast", False) else "group"
            finally:
                try:
                    await c.disconnect()
                except Exception:
                    pass
        dialog = {"id": int(chat_id), "title": title, "type": ent_type, "entity": None}

        export_root = EXPORTS_ROOT
        export_root.mkdir(parents=True, exist_ok=True)
        ensure_assets(export_root)

        # حالت افزایشی: داده قبلی (پیام‌ها + رسانه‌ها) نگه داشته می‌شود و فقط
        # پیام‌های جدید دانلود می‌شوند — با اینترنت محدود، از اول شروع نمی‌شود.
        try:
            _chat_dir_tmp = export_root / "chats" / sanitize_name(title)
            _msg_tmp = _chat_dir_tmp / "messages.jsonl"
            _old_n = 0
            if _msg_tmp.exists():
                with open(_msg_tmp, encoding="utf-8") as _fh:
                    for _ln in _fh:
                        if _ln.strip():
                            _old_n += 1
            if _old_n:
                log.info("%s پیام از قبل موجود است — ادامه از همان‌جا", _old_n)
        except Exception as e:
            log.warning("خواندن داده قبلی ناموفق بود: %s", e)

        stats = await export_chat_async(self.cfg, dialog, export_root,
                                        options={"media": bool(include_media), "text": True},
                                        progress=update)

        self._build_progress = {"state": "building", "done": 0, "total": 0, "label": "ساخت صفحات HTML…"}
        chat_dir = export_root / "chats" / sanitize_name(title)
        generate_chat_page(chat_dir, export_root)
        generate_index(export_root)

        # خروجی تک‌کانال: فقط همین چت داخل اپ/APK می‌رود — کانال‌های قبلی
        # (که در پوشهٔ خروجی مشترک جمع شده‌اند) دیگر ظاهر نمی‌شوند؛
        # نام اپ هم = عنوان کانال می‌شود.
        from app.android_builder import build_single_chat

        def _phase(lbl):
            self._build_progress = {"state": "building", "done": 0, "total": 0, "label": lbl}

        _phase("آماده‌سازی ساخت APK…")
        out_dir = EXPORTS_ROOT.parent / "android_builds"
        result = build_single_chat(export_root, title, out_dir, progress=_phase)
        result["stats"] = stats
        return result

    def build_android_for_chat(self, chat_id):
        """دانلود کامل چت (از اول تا آخر) + خروجی HTML + ساخت پروژهٔ اندروید
        با applicationId یکتا. این عملیات طولانی است؛ تا تمام شدن صبر می‌کنیم.
        برمی‌گرداند {ok, stats, project_name, zip_path} یا {error}.
        """
        import json as _json
        from app.config import EXPORTS_ROOT, CONFIG_FILE
        from app.exporter import generate_index, generate_chat_page, ensure_assets
        from app.downloader import export_chat_async, CHAT_INFO_FILE, sanitize_name

        done = threading.Event()
        holder = {}

        def progress(step, done_n, total_n):
            # فقط برای لاگ — گزارش زندهٔ واقعی به GUI بعداً
            if total_n and done_n % 100 == 0:
                log.info("android: %s %s/%s", step, done_n, total_n)

        async def _run():
            from app.tg_client import _client

            # فقط عنوان چت را بگیر — entity را داخل export_chat_async
            # با کلاینت جدید بازسازی می‌کنیم تا «۰ پیام» رخ ندهد.
            title = "chat"
            c = _client(self.cfg, None)
            try:
                await c.connect()
                ent = await c.get_entity(int(chat_id))
                title = getattr(ent, "title", None) or getattr(ent, "first_name", "") or "chat"
            finally:
                await c.disconnect()
            dialog = {"id": int(chat_id), "title": title,
                      "type": "channel" if getattr(ent, "broadcast", False) else "chat",
                      "entity": None}

            export_root = EXPORTS_ROOT
            export_root.mkdir(parents=True, exist_ok=True)
            ensure_assets(export_root)

            # ۱) دانلود افزایشی (از اولین به آخرین؛ داده قبلی حفظ می‌شود)
            stats = await export_chat_async(self.cfg, dialog, export_root,
                                            options={"media": True, "text": True},
                                            progress=progress)
            holder["stats"] = stats

            # ۲) ساخت صفحات HTML
            chat_dir = export_root / "chats" / sanitize_name(title)
            generate_chat_page(chat_dir, export_root)
            generate_index(export_root)

            # ۳) فقط همین چت داخل اپ می‌رود + نام اپ = عنوان چت
            from app.android_builder import build_single_chat

            res = build_single_chat(export_root, title, EXPORTS_ROOT.parent / "android_builds")
            holder["project_name"] = res.get("project_name", "")
            holder["zip"] = res.get("zip", "")

        def ok(_r):
            holder["ok"] = True
            done.set()

        def err(e):
            holder["error"] = _friendly_login_error(e) if hasattr(e, "args") else str(e)
            done.set()

        _run_async(_run, on_done=ok, on_error=err)
        # دانلود کل یک چت می‌تواند خیلی طول بکشد؛ تا ۳۰ دقیقه صبر می‌کنیم
        if not done.wait(timeout=1800):
            return {"error": "ساخت اپ زمان‌بیش از ۳۰ دقیقه طول کشید — دوباره تلاش کنید."}
        return holder

    def export_all(self):
        return {"error": "First select a chat from My Chats to export."}

    def open_folder(self):
        from app.config import EXPORTS_ROOT

        try:
            import os

            os.startfile(str(EXPORTS_ROOT))
            return True
        except Exception:
            return False

    def choose_save_dir(self):
        return str(Path.home() / "Desktop" / "Telegram Downloads")

    # ---------------- اتصال به شبکه (پروکسی) ----------------
    def set_proxy(self, host, port):
        self.cfg["proxy_host"] = host
        self.cfg["proxy_port"] = str(port)
        save_config(self.cfg)
        return True