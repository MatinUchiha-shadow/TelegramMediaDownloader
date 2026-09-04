# -*- coding: utf-8 -*-
"""سرور وب محلی برنامه — GUI را به مرورگر می‌دهد، پایتون فقط در پیش‌زمینه.

هیچ Qt/PySide6/WebEngine در GUI نیست. این ماژول:
- فایل‌های html_gui (HTML/CSS/JS) را سرو می‌کند
- یک API JSON روی /api فراهم می‌کند (fetch از JS)
- رویدادهای زنده (پیشرفت دانلود/لاگ) را از طریق SSE ارسال می‌کند
- در مرورگر پیش‌فرض سیستم باز می‌شود که همیشه درست رندر می‌کند
"""
import asyncio
import json
import queue
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

from app import exporter
from app.android_builder import build_android_app
from app.config import load_config, save_config as _py_save_config
from app.downloader import DownloadWorker, sanitize_name, MEDIA_DIRS
from app.logger_setup import get_emitter, get_logger
from app.tg_client import fetch_dialogs, is_logged_in, send_code, sign_in

log = get_logger("server")

# فایل‌های استاتیک مجاز (فقط از پوشهٔ قالب)
STATIC_SUBDIRS = ("", "assets")
STATIC_FILES = {"", "index.html", "app.js", "style.css"}


def _gui_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "html_gui"


def _run_async(corofunc, *args, on_done=None, on_error=None):
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(corofunc(*args))
            if on_done:
                on_done(result)
        except Exception as e:
            log.exception("Async task failed")
            if on_error:
                on_error(e)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()


def _run_in_thread(fn, *args, on_done=None, on_error=None):
    def run():
        try:
            result = fn(*args)
            if on_done:
                on_done(result)
        except Exception as e:
            log.exception("Thread task failed")
            if on_error:
                on_error(e)

    threading.Thread(target=run, daemon=True).start()


def _open_folder(path: str) -> None:
    try:
        import os

        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(path)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class AppState:
    """حالت برنامه — در ترد سرور نگه داشته می‌شود."""

    def __init__(self):
        self.cfg = load_config()
        self._dialogs = []
        self.worker = None
        self.account_dir = None
        self.events = queue.Queue()  # رویدادهای ارسال‌شونده به SSE


state = AppState()


class Handler(BaseHTTPRequestHandler):
    server_version = "TelegramDownloader/1.0"

    # ---------- ابزار ----------
    def _log(self):
        pass  # خاموش کردن لاگ دسترسی پیش‌فرض

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _reply_async(self, req_id, on_result, on_error=None):
        """ارسال پاسخ ناهمگام به‌صورت رویداد؛ چون پایان درخواست HTTP جدا از پاسخ است،
        از مدل ساده استفاده می‌کنیم: متد async خودش رویداد 'reply' می‌فرستد."""

    def _push(self, evt: dict):
        try:
            state.events.put_nowait(json.dumps(evt, ensure_ascii=False))
        except Exception:
            pass

    # ---------- GET: استاتیک و SSE ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/events":
            self._handle_sse()
            return

        if path.startswith("/api/"):
            self._route_api_get(path)
            return

        self._serve_static(path)

    def _serve_static(self, path):
        gui = _gui_dir()
        if path in ("/", "/index.html"):
            target = gui / "index.html"
        elif path == "/app.js":
            target = gui / "app.js"
        elif path == "/style.css":
            target = gui / "style.css"
        else:
            self.send_error(404)
            return
        if not target.exists():
            self.send_error(404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    line = state.events.get(timeout=1.0)
                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ---------- API: POST ----------
    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_json()
        method = (parsed.path or "").rsplit("/", 1)[-1]
        self._route_api_post(method, body)

    # ---------- مسیرهای GET API ----------
    def _route_api_get(self, path):
        if path == "/api/config":
            self._send_json({
                "ok": True,
                "result": {
                    "phone": state.cfg.get("phone", ""),
                    "proxy_host": state.cfg.get("proxy_host", ""),
                    "proxy_port": state.cfg.get("proxy_port", ""),
                    "export_root": state.cfg.get("export_root", ""),
                    "music_root": state.cfg.get("music_root", ""),
                    "logged_in": False,
                },
            })
            return
        if path == "/api/android_info":
            self._send_json({"ok": True, "result": str(state.account_dir) if state.account_dir else None})
            return
        self._send_json({"ok": False, "error": "not found"}, 404)

    # ---------- مسیرهای POST API ----------
    def _route_api_post(self, method, body):
        handlers = {
            "config": self._api_save_config,
            "send_code": self._api_send_code,
            "login": self._api_login,
            "logged_in": self._api_logged_in,
            "list_chats": self._api_list_chats,
            "start_download": self._api_start_download,
            "stop_download": self._api_stop_download,
            "choose_dir": self._api_choose_dir,
            "open_account_dir": self._api_open_account_dir,
            "make_export": self._api_make_export,
            "build_android": self._api_build_android,
            "open_android_out": self._api_open_android_out,
            "music_choose_dir": self._api_music_choose_dir,
            "music_list": self._api_music_list,
        }
        h = handlers.get(method)
        if h is None:
            self._send_json({"ok": False, "error": f"روش ناشناخته: {method}"}, 404)
            return
        try:
            h(body)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)})

    # POST — پاسخ‌های فوری (همگام)
    def _api_save_config(self, body):
        api_id = body.get("api_id", "")
        api_hash = body.get("api_hash", "")
        if (api_id or "").strip():
            state.cfg["api_id"] = api_id.strip()
        if (api_hash or "").strip():
            state.cfg["api_hash"] = api_hash.strip()
        if (body.get("phone") or "").strip():
            state.cfg["phone"] = body["phone"].strip()
        if (body.get("proxy_host") or "").strip():
            state.cfg["proxy_host"] = body["proxy_host"].strip()
        if (body.get("proxy_port") or "").strip():
            state.cfg["proxy_port"] = body["proxy_port"].strip()
        _py_save_config(state.cfg)
        self._send_json({"ok": True, "result": True})

    def _api_stop_download(self, body):
        if state.worker:
            state.worker.stop()
        self._send_json({"ok": True, "result": True})

    def _api_logged_in(self, body):
        def done(ok):
            self._push({"type": "login_check", "ok": bool(ok)})

        _run_async(is_logged_in, state.cfg, on_done=done)
        self._send_json({"ok": True, "result": "ok"})

    def _api_choose_dir(self, body):
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askdirectory(initialdir=state.cfg.get("export_root", ""))
        root.destroy()
        if p:
            state.cfg["export_root"] = p
        _py_save_config(state.cfg)
        self._send_json({"ok": True, "result": p})

    def _api_music_choose_dir(self, body):
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askdirectory(initialdir=state.cfg.get("music_root") or state.cfg.get("export_root", ""))
        root.destroy()
        if p:
            state.cfg["music_root"] = p
            _py_save_config(state.cfg)
        self._send_json({"ok": True, "result": p})

    def _api_open_account_dir(self, body):
        if state.account_dir:
            _open_folder(str(state.account_dir))
        self._send_json({"ok": True, "result": True})

    def _api_open_android_out(self, body):
        if state.account_dir:
            _open_folder(str(state.account_dir.parent))
        self._send_json({"ok": True, "result": True})

    # POST — پاسخ‌های فوری که کار ناهمگام را شروع می‌کنند
    def _api_send_code(self, body):
        phone = body.get("phone", "")
        self._run_async_push(phone, send_code, "کد ارسال شد — کد را وارد و «ورود» را بزنید.")
        self._send_json({"ok": True, "result": "sent"})

    def _api_login(self, body):
        phone = body.get("phone", "")
        code = body.get("code", "")
        password = body.get("password", "")
        self._run_async_push(phone, sign_in, "login_ok", code, password, is_login=True)
        self._send_json({"ok": True, "result": "ok"})

    def _api_list_chats(self, body):
        _run_async(
            fetch_dialogs, state.cfg,
            on_done=lambda dialogs: self._on_chats(dialogs),
            on_error=lambda e: self._push({"type": "status", "text": "❌ " + str(e), "kind": "err"}),
        )
        self._send_json({"ok": True, "result": "ok"})

    def _api_start_download(self, body):
        chat = body.get("chat")
        opts = body.get("options", {})
        dir_root = body.get("dir", "") or ""
        entry = next((d for d in state._dialogs if str(d["id"]) == str(chat.get("id"))), None)
        if entry is None:
            self._send_json({"ok": False, "error": "چت انتخاب‌شده یافت نشد؛ دوباره چت‌ها را بارگذاری کنید."})
            return
        export_root = Path(dir_root or state.cfg.get("export_root") or "")
        if not export_root:
            export_root = Path.home() / "Desktop"
        account = sanitize_name(entry.get("self_name") or "account") + "_export"
        state.account_dir = export_root / account
        state.account_dir.mkdir(parents=True, exist_ok=True)
        chat_dir = state.account_dir / exporter.CHATS_DIR / sanitize_name(entry["title"])

        if state.worker and state.worker.isRunning():
            self._send_json({"ok": False, "error": "هم‌اکنون دانلودی در جریان است."})
            return

        worker = DownloadWorker(state.cfg, entry, chat_dir, opts, None)
        worker.progress.connect(
            lambda k, d, t, p, lbl: self._push(
                {"type": "dl_progress", "progress": {"done": d, "total": t, "pct": p, "label": lbl}}
            )
        )
        worker.file_progress.connect(
            lambda k, p, lbl: self._push({"type": "dl_progress", "filePct": p, "fileLabel": lbl})
        )
        worker.status.connect(lambda k, m: self._push({"type": "dl_status", "text": m}))
        worker.finished.connect(lambda k, s: self._on_download_finished(s))
        worker.failed.connect(lambda k, e: self._push({"type": "dl_done", "text": "❌ " + e, "isErr": True}))
        worker.start()
        state.worker = worker
        self._send_json({"ok": True, "result": True})

    def _api_make_export(self, body):
        _run_in_thread(
            self._make_export_work,
            on_done=lambda res: self._push({"type": "dl_done", "text": res, "isErr": False}),
            on_error=lambda e: self._push({"type": "dl_done", "text": "❌ " + str(e), "isErr": True}),
        )
        self._send_json({"ok": True, "result": True})

    def _api_build_android(self, body):
        if not state.account_dir:
            self._send_json({"ok": False, "error": "اول باید خروجی ساخته شود."})
            return
        chat = body.get("chat") or {}
        chat_id = chat.get("id")
        title = (chat.get("title") or "").strip()

        def work():
            # ─── مرحله ۱: پاک‌سازی state قدیمی + دانلود کامل از اول ───
            self._push({"type": "dl_status", "text": "پاک‌سازی دادهٔ قدیمی «" + title + "» …"})
            try:
                self._clear_chat_data(chat_id, title)
            except Exception as e:
                log.warning("پاک‌سازی دادهٔ قدیمی ناموفق بود: %s", e)

            self._push({"type": "dl_status", "text": "دانلود کامل «" + title + "» از اول …"})
            try:
                self._incremental_download(chat_id, title)
            except Exception as e:
                log.warning("دانلود قبل از ساخت اندروید ناموفق بود: %s", e)
                # حتی اگر دانلود نشد، با دادهٔ موجود ادامه بده

            # ─── مرحله ۲: بازسازی HTML ───
            self._push({"type": "dl_status", "text": "بازسازی خروجی HTML …"})
            try:
                cd = state.account_dir / exporter.CHATS_DIR
                chat_dir = cd / sanitize_name(title)
                if chat_dir.exists():
                    exporter.generate_chat_page(chat_dir, state.account_dir)
            except Exception as e:
                log.warning("بازسازی HTML ناموفق بود: %s", e)

            # ─── مرحله ۳: ساخت اپ اندروید ───
            self._push({"type": "dl_status", "text": "ساخت پروژهٔ اندروید …"})
            from app.android_builder import build_single_chat
            res = build_single_chat(state.account_dir, title, state.account_dir.parent)
            return res.get("apk") or res.get("project_name") or ""

        _run_in_thread(
            work,
            on_done=lambda res: self._push({"type": "android_ok", "project": res}),
            on_error=lambda e: self._push({"type": "android_fail", "error": str(e)}),
        )
        self._send_json({"ok": True, "result": True})

    def _clear_chat_data(self, chat_id, title):
        """پاک‌سازی کامل داده‌های یک چت (state.json + messages.jsonl) تا دانلود از اول انجام شود.
        فایل‌های رسانه (عکس/ویدیو/صوت) حفظ می‌شوند چون حجم زیادی دارند
        و دوباره دانلودشان وقت‌گیر است.
        """
        import json as _json
        from app.downloader import MESSAGES_FILE, STATE_FILE, sanitize_name as _sn

        entry = None
        for d in state._dialogs:
            if str(d.get("id")) == str(chat_id):
                entry = d
                break
        if entry is None:
            return

        chat_dir = state.account_dir / exporter.CHATS_DIR / _sn(entry["title"])
        if not chat_dir.exists():
            return

        # حذف state.json (checkpoint آخرین id)
        state_file = chat_dir / STATE_FILE
        if state_file.exists():
            try:
                state_file.unlink()
                log.info("state.json حذف شد: %s", state_file)
            except OSError as e:
                log.warning("خطا در حذف state.json: %s", e)

        # حذف messages.jsonl (شروع تمیز)
        msg_file = chat_dir / MESSAGES_FILE
        if msg_file.exists():
            try:
                msg_file.unlink()
                log.info("messages.jsonl حذف شد: %s", msg_file)
            except OSError as e:
                log.warning("خطا در حذف messages.jsonl: %s", e)

        log.info("دادهٔ چت «%s» پاک‌سازی شد — دانلود از اول انجام می‌شود", title)

    def _incremental_download(self, chat_id, title):
        """دانلود پیام‌های یک چت (بدون دانلود فایل رسانه).
        اگر state.json وجود داشته باشد فقط پیام‌های جدید دانلود می‌شوند؛
        در غیر این صورت همهٔ پیام‌ها از اول دانلود می‌شوند.
        """
        import json as _json
        from app.downloader import MESSAGES_FILE, STATE_FILE, sanitize_name as _sn
        from app.tg_client import _display_name

        # پیدا کردن entry چت از لیست dialogs
        entry = None
        for d in state._dialogs:
            if str(d.get("id")) == str(chat_id):
                entry = d
                break
        if entry is None:
            return

        chat_dir = state.account_dir / exporter.CHATS_DIR / _sn(entry["title"])
        chat_dir.mkdir(parents=True, exist_ok=True)

        # خواندن state قبلی
        state_file = chat_dir / STATE_FILE
        saved = {}
        if state_file.exists():
            try:
                saved = _json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        last_id = saved.get("last_id", 0)

        # خواندن idهای موجود
        existing_ids: set[int] = set()
        msg_file = chat_dir / MESSAGES_FILE
        if msg_file.exists():
            with open(msg_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = _json.loads(line)
                        mid = rec.get("id")
                        if mid is not None:
                            existing_ids.add(int(mid))
                    except Exception:
                        pass

        # اتصال به تلگرام
        from app.tg_client import _client
        import asyncio

        async def _do():
            client = _client(state.cfg, None)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    return
                entity = entry.get("entity")
                if entity is None:
                    return

                # دانلود پیام‌های جدید (از last_id به بعد)
                kwargs = dict(reverse=True, wait_time=1)
                if last_id:
                    kwargs["min_id"] = last_id
                try:
                    iterator = client.iter_messages(entity, **kwargs)
                except TypeError:
                    kwargs.pop("min_id", None)
                    iterator = client.iter_messages(entity, **kwargs)

                new_count = 0
                fh = open(msg_file, "a", encoding="utf-8")
                try:
                    async for msg in iterator:
                        if msg is None:
                            continue
                        if msg.id in existing_ids:
                            continue
                        existing_ids.add(msg.id)

                        service = msg.action is not None
                        text = (msg.text or msg.message or "").strip() if not service else ""
                        reply_id = None
                        rt = getattr(msg, "reply_to", None)
                        if rt is not None:
                            reply_id = getattr(rt, "reply_to_msg_id", None) or getattr(msg, "reply_to_msg_id", None)

                        media_type = None
                        media_name = None
                        media_size = 0
                        media = getattr(msg, "media", None)
                        if media is not None:
                            from app.downloader import classify_document, _media_type_name
                            from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
                            if isinstance(media, MessageMediaPhoto):
                                media_type = "photo"
                                media_name = "photo.jpg"
                                try:
                                    media_size = media.photo.size if media.photo else 0
                                except Exception:
                                    media_size = 0
                            elif isinstance(media, MessageMediaDocument):
                                doc = media.document
                                if doc is not None:
                                    folder, fname = classify_document(doc)
                                    media_type = _media_type_name(folder)
                                    media_name = fname
                                    media_size = getattr(doc, "size", 0) or 0

                        sender_name = ""
                        if msg.sender_id is not None:
                            try:
                                ent = await client.get_entity(msg.sender_id)
                                sender_name = _display_name(ent)
                            except Exception:
                                sender_name = str(msg.sender_id)

                        rec = {
                            "id": msg.id,
                            "date": msg.date.astimezone().isoformat() if getattr(msg, "date", None) else "",
                            "sender_id": msg.sender_id,
                            "sender_name": sender_name,
                            "out": bool(getattr(msg, "out", False)),
                            "text": text,
                            "service": service,
                            "reply_to": reply_id,
                            "media_type": media_type,
                            "media_name": media_name,
                            "media_size": media_size,
                            "media": None,
                        }
                        fh.write(_json.dumps(rec, ensure_ascii=False) + "\n")
                        new_count += 1
                        last_id = max(last_id, msg.id)
                finally:
                    fh.close()

                # ذخیرهٔ state
                if new_count > 0:
                    try:
                        state_data = {"last_id": last_id, "count": len(existing_ids)}
                        state_file.write_text(_json.dumps(state_data, ensure_ascii=False),
                                              encoding="utf-8")
                    except Exception:
                        pass

                if new_count > 0:
                    log.info("%s پیام جدید برای «%s» دانلود شد", new_count, title)
            finally:
                await client.disconnect()

        # اجرای async در یک event loop جدید
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_do())
        finally:
            loop.close()

    def _api_music_list(self, body):
        root = (body.get("root") or "").strip()
        if not root:
            root = str(state.cfg.get("music_root") or "")
        _run_in_thread(
            lambda: _scan_audio_str(Path(root)),
            on_done=lambda songs: self._push({"type": "music_list", "songs": json.dumps(songs, ensure_ascii=False)}),
            on_error=lambda e: self._push({"type": "status", "text": "❌ " + str(e), "kind": "err"}),
        )
        self._send_json({"ok": True, "result": True})

    # ---------- توابع کمکی ناهمگام ----------
    def _run_async_push(self, phone, func, ok_msg, *extra, is_login=False):
        def done(res):
            if is_login:
                self._push({"type": "login_ok", "name": res})
            else:
                self._push({"type": "status", "text": ok_msg, "kind": "ok"})

        def err(e):
            if is_login:
                args = getattr(e, "args", ())
                msg = args[0] if args and args[0] == "2FA" else str(e)
                self._push({"type": "login_fail", "err": msg})
            else:
                self._push({"type": "login_fail", "err": str(e)})

        _run_async(func, state.cfg, phone, *extra, on_done=done, on_error=err)

    def _on_chats(self, dialogs):
        state._dialogs = dialogs
        payload = [
            {"id": d["id"], "title": d["title"], "type": d.get("type", ""), "unread": d.get("unread", 0)}
            for d in dialogs
        ]
        self._push({"type": "chats_loaded", "chats": json.dumps(payload, ensure_ascii=False)})

    def _on_download_finished(self, stats):
        total = stats.get("total") or 0
        done = stats.get("count") or 0
        txt = (
            f"✅ {done} از {total} پیام · {stats.get('media', 0)} فایل دانلود شد "
            f"({stats.get('skipped_media', 0)} تکراری حذف)"
        )
        self._push({"type": "dl_done", "text": txt, "isErr": False})
        self._make_export_async()

    def _make_export_work(self):
        if not state.account_dir:
            return "هنوز خروجی‌ای وجود ندارد."
        exporter.ensure_assets(state.account_dir)
        n = 0
        cd = state.account_dir / exporter.CHATS_DIR
        if cd.exists():
            for sub in sorted(cd.iterdir()):
                if sub.is_dir():
                    exporter.generate_chat_page(sub, state.account_dir)
                    n += 1
        exporter.generate_index(state.account_dir)
        return f"خروجی HTML برای {n} چت ساخته شد ✅"

    def _make_export_async(self):
        _run_in_thread(
            self._make_export_work,
            on_done=lambda res: self._push({"type": "dl_done", "text": res, "isErr": False}),
            on_error=lambda e: self._push({"type": "dl_done", "text": "❌ " + str(e), "isErr": True}),
        )


def _scan_audio_str(root: Path) -> list:
    AUDIO_EXTS = {".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".flac", ".wma", ".webm"}
    songs = []
    if not root or not root.exists() or not root.is_dir():
        return songs
    try:
        paths = list(root.rglob("*"))
    except (PermissionError, OSError):
        return songs
    for p in paths:
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        chat = ""
        try:
            rel = p.relative_to(root).parts
            if len(rel) > 1 and rel[-2] in MEDIA_DIRS:
                chat = rel[-3] if len(rel) > 2 else ""
        except Exception:
            rel = []
        songs.append({"path": str(p), "name": p.stem, "ext": p.suffix.lower().lstrip("."), "chat": chat, "size": st.st_size, "mtime": st.st_mtime})
    songs.sort(key=lambda s: s["mtime"], reverse=True)
    return songs


def start_server(port: int = 8756, open_browser: bool = True) -> ThreadingHTTPServer:
    """راه‌اندازی سرور و بازکردن مرورگر."""

    def run():
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            log.info("سرور روی http://127.0.0.1:%s شروع شد", port)
            url = f"http://127.0.0.1:{port}/index.html"
            if open_browser:
                threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            httpd.serve_forever()
        except Exception as e:
            log.exception("Server failed")
            print(f"ERROR: {e}")
            input("برای بستن Enter بزنید")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t