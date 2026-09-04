# -*- coding: utf-8 -*-
"""رابط کاربری به‌همراه قالب HTML/CSS/JS در یک WebView (با QWebChannel).

کل GUI در html_gui/ ساخته شده و این ماژول:
- قالب را لود می‌کند (هم از حالت منبع، هم از داخل EXE/PyInstaller)
- یک شیء Bridge در QWebChannel ثبت می‌کند تا JS بتواند توابع پایتون را صدا بزند
- رویدادهای پیشرفت دانلود/لاگ را به JS می‌فرستد

پروتکل بریج:
  JS →  bridge.request(JSON {id, method, args})
  پاسخ همگام:        بلافاصله با notify → {type:"reply", id, ok, result}
  پاسخ ناهمگام:      متدهای ASYNC با reply(...) جواب می‌دهند
  رویداد زنده:       notify → {type: dl_progress|dl_status|dl_done|log|status}
"""
import asyncio
import json
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow

from app import exporter
from app.android_builder import build_single_chat
from app.config import load_config, save_config as _py_save_config
from app.downloader import MEDIA_DIRS, DownloadWorker, sanitize_name
from app.logger_setup import get_emitter, get_logger
from app.tg_client import fetch_dialogs, is_logged_in, send_code, sign_in

log = get_logger("web")

# متدهایی که پاسخشان بعداً (ناهمگام) می‌آید — signature: handler(*params, reply=fn)
ASYNC_METHODS = {"is_logged_in", "send_code", "login", "list_chats", "make_export", "build_android", "music_list"}

# پسوندهای صوتی قابل پخش در پلیر موزیک
AUDIO_EXTS = {".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".flac", ".wma", ".webm"}


def _gui_dir() -> Path:
    """پوشهٔ html_gui — هم در حالت منبع و هم داخل EXE."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "html_gui"


def _run_async(corofunc, *args, on_done=None, on_error=None):
    """اجرای coroutine در یک ترد جداگانه."""

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
    """اجرای یک تابع همگام سنگین در ترد جداگانه."""

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


def _scan_audio(root: Path) -> list:
    """جستجوی همهٔ فایل‌های صوتی زیر یک پوشه (مثل آهنگ‌های دانلودشده)."""
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
            rel = p.relative_to(root)
        except (OSError, ValueError):
            continue
        # نام چت: پوشه‌ای که زیرپوشهٔ رسانه (audio و …) داخل آن است
        chat = str(rel.parts[0]) if len(rel.parts) > 1 else ""
        for i, part in enumerate(rel.parts[:-1]):
            if part in MEDIA_DIRS and i > 0:
                chat = str(rel.parts[i - 1])
                break
        songs.append(
            {
                "path": str(p),
                "name": p.stem,
                "ext": p.suffix.lower().lstrip("."),
                "chat": chat,
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
        )
    songs.sort(key=lambda s: s["mtime"], reverse=True)
    return songs


def _open_folder(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", str(path)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class Bridge(QObject):
    """شیء QWebChannel که از JS صدا زده می‌شود."""

    notify = Signal(str)

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.cfg = load_config()
        self._dialogs = []
        self.worker = None
        self.account_dir = None

    # ---------------- پروتکل پایه ----------------
    @Slot(str)
    def request(self, payload_json: str) -> None:
        try:
            payload = json.loads(payload_json)
        except Exception:
            return
        rid = payload.get("id")
        method = payload.get("method")
        params = payload.get("args", [])
        handler = getattr(self, "api_" + method, None)
        if handler is None:
            self._respond(rid, False, f"روش ناشناخته: {method}")
            return
        try:
            if method in ASYNC_METHODS:
                handler(*params, reply=lambda ok, res, _rid=rid: self._respond(_rid, ok, res))
            else:
                self._respond(rid, True, handler(*params))
        except Exception as e:
            log.exception("API error %s", method)
            self._respond(rid, False, str(e))

    def _respond(self, rid, ok: bool, result) -> None:
        self.notify.emit(json.dumps({"type": "reply", "id": rid, "ok": ok, "result": result}))

    def emit_evt(self, evt: dict) -> None:
        self.notify.emit(json.dumps(evt))

    # ---------------- API: تنظیمات ----------------
    def api_get_config(self):
        return json.dumps({
            "api_id": self.cfg.get("api_id", ""),
            "api_hash": self.cfg.get("api_hash", ""),
            "phone": self.cfg.get("phone", ""),
            "proxy_host": self.cfg.get("proxy_host", ""),
            "proxy_port": self.cfg.get("proxy_port", ""),
            "export_root": self.cfg.get("export_root", ""),
            "music_root": self.cfg.get("music_root", ""),
        }, ensure_ascii=False)

    def api_save_config(self, api_id, api_hash, phone, proxy_host="", proxy_port=""):
        # اگر فیلد خالی رسید، مقدل پیش‌فرض (که از config پر شده) حفظ می‌شود
        if (api_id or "").strip():
            self.cfg["api_id"] = (api_id or "").strip()
        if (api_hash or "").strip():
            self.cfg["api_hash"] = (api_hash or "").strip()
        self.cfg["phone"] = (phone or "").strip()
        if (proxy_host or "").strip():
            self.cfg["proxy_host"] = (proxy_host or "").strip()
        if (proxy_port or "").strip():
            self.cfg["proxy_port"] = (proxy_port or "").strip()
        _py_save_config(self.cfg)
        return True

    # ---------------- API: ورود ----------------
    def api_is_logged_in(self, reply):
        def done(ok):
            reply(True, bool(ok))

        def err(e):
            reply(False, str(e))

        _run_async(is_logged_in, self.cfg, on_done=done, on_error=err)

    def api_send_code(self, phone, reply):
        def done(_):
            reply(True, "sent")

        def err(e):
            reply(False, str(e))

        _run_async(send_code, self.cfg, phone, on_done=done, on_error=err)

    def api_login(self, phone, code, password, reply):
        def done(name):
            reply(True, name)

        def err(e):
            args = getattr(e, "args", ())
            msg = args[0] if args and args[0] == "2FA" else str(e)
            reply(False, msg)

        _run_async(sign_in, self.cfg, phone, code, password or None, on_done=done, on_error=err)

    # ---------------- API: موزیک ----------------
    def api_music_list(self, root, reply):
        root = (root or "").strip()
        if not root:
            # پیش‌فرض: آخرین خروجی دانلودشده
            root = str(self.account_dir) if self.account_dir else str(self.cfg.get("export_root") or "")

        def done(songs):
            reply(True, json.dumps(songs, ensure_ascii=False))

        def err(e):
            reply(False, str(e))

        _run_in_thread(lambda: _scan_audio(Path(root)), on_done=done, on_error=err)

    def api_music_choose_dir(self):
        p = QFileDialog.getExistingDirectory(
            self.main,
            "پوشهٔ موزیک (فایل‌های MP3 و …)",
            self.cfg.get("music_root") or self.cfg.get("export_root") or "",
        )
        if p:
            self.cfg["music_root"] = p
            _py_save_config(self.cfg)
        return p

    # ---------------- API: چت‌ها ----------------
    def api_list_chats(self, reply):
        def done(dialogs):
            self._dialogs = dialogs
            payload = [
                {
                    "id": d["id"],
                    "title": d["title"],
                    "type": d["type"],
                    "unread": d.get("unread", 0),
                }
                for d in dialogs
            ]
            reply(True, json.dumps(payload, ensure_ascii=False))

        def err(e):
            reply(False, str(e))

        _run_async(fetch_dialogs, self.cfg, on_done=done, on_error=err)

    # ---------------- API: دانلود ----------------
    def api_start_download(self, chat_json, options_json, dir_root):
        chat = json.loads(chat_json)
        opts = json.loads(options_json)
        entry = next((d for d in self._dialogs if str(d["id"]) == str(chat.get("id"))), None)
        if entry is None:
            raise RuntimeError("چت انتخاب‌شده یافت نشد؛ دوباره چت‌ها را بارگذاری کنید.")
        export_root = Path(dir_root or self.cfg.get("export_root") or "")
        if not export_root:
            export_root = Path.home() / "Desktop"
        account = sanitize_name(entry.get("self_name") or str(entry.get("self_id", "account"))) + "_export"
        self.account_dir = export_root / account
        self.account_dir.mkdir(parents=True, exist_ok=True)
        chat_dir = self.account_dir / exporter.CHATS_DIR / sanitize_name(entry["title"])

        if self.worker and self.worker.isRunning():
            raise RuntimeError("هم‌اکنون دانلودی در جریان است.")

        self.worker = DownloadWorker(self.cfg, entry, chat_dir, opts, None)
        self.worker.progress.connect(
            lambda k, d, t, p, lbl: self.emit_evt(
                {"type": "dl_progress", "progress": {"done": d, "total": t, "pct": p, "label": lbl}}
            )
        )
        self.worker.file_progress.connect(
            lambda k, p, lbl: self.emit_evt({"type": "dl_progress", "filePct": p, "fileLabel": lbl})
        )
        self.worker.status.connect(lambda k, m: self.emit_evt({"type": "dl_status", "text": m}))
        self.worker.finished.connect(self._download_finished)
        self.worker.failed.connect(
            lambda k, e: self.emit_evt({"type": "dl_done", "text": "❌ " + e, "isErr": True})
        )
        self.worker.start()
        return True

    def _download_finished(self, key, stats):
        total = stats.get("total") or 0
        done = stats.get("count") or 0
        txt = (
            f"✅ {done} از {total} پیام · {stats.get('media', 0)} فایل دانلود شد "
            f"({stats.get('skipped_media', 0)} تکراری حذف)"
        )
        self.emit_evt({"type": "dl_done", "text": txt, "isErr": False})
        # ساخت خودکار خروجی HTML
        self._make_export_async()

    def api_stop_download(self):
        if self.worker:
            self.worker.stop()
        return True

    def api_choose_dir(self):
        p = QFileDialog.getExistingDirectory(self.main, "پوشهٔ خروجی", self.cfg.get("export_root", ""))
        if p:
            self.cfg["export_root"] = p
            _py_save_config(self.cfg)
        return p

    def api_open_account_dir(self):
        if self.account_dir:
            _open_folder(str(self.account_dir))
        return True

    # ---------------- API: خروجی HTML ----------------
    def _make_export_work(self):
        if not self.account_dir:
            return "هنوز خروجی‌ای وجود ندارد."
        exporter.ensure_assets(self.account_dir)
        n = 0
        cd = self.account_dir / exporter.CHATS_DIR
        if cd.exists():
            for sub in sorted(cd.iterdir()):
                if sub.is_dir():
                    exporter.generate_chat_page(sub, self.account_dir)
                    n += 1
        exporter.generate_index(self.account_dir)
        return f"خروجی HTML برای {n} چت ساخته شد ✅"

    def api_make_export(self, reply):
        self.emit_evt({"type": "dl_status", "text": "در حال ساخت خروجی HTML…"})
        _run_in_thread(
            self._make_export_work,
            on_done=lambda res: reply(True, res),
            on_error=lambda e: reply(False, str(e)),
        )

    def _make_export_async(self):
        _run_in_thread(
            self._make_export_work,
            on_done=lambda res: self.emit_evt({"type": "dl_done", "text": res, "isErr": False}),
            on_error=lambda e: self.emit_evt({"type": "dl_done", "text": "❌ " + str(e), "isErr": True}),
        )

    # ---------------- API: اندروید ----------------
    def api_android_info(self):
        return str(self.account_dir) if self.account_dir else None

    def api_build_android(self, reply):
        if not self.account_dir:
            reply(False, "اول باید خروجی ساخته شود.")
            return

        def work():
            res = build_single_chat(self.account_dir, "", self.account_dir.parent)
            return res.get("apk") or res.get("project_name") or ""

        _run_in_thread(
            work,
            on_done=lambda res: reply(True, str(res)),
            on_error=lambda e: reply(False, str(e)),
        )

    def api_open_android_out(self):
        if self.account_dir:
            _open_folder(str(self.account_dir.parent))
        return True


# --------------------------------------------------------------------------
# پنجرهٔ اصلی — WebView (پنجرهٔ استاندارد ویندوز، بدون باگ جابه‌جایی)
# --------------------------------------------------------------------------
class WebMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Media Downloader — آرشیو تلگرام")
        self.resize(1080, 700)
        self.setMinimumSize(860, 560)

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)

        self.channel = QWebChannel(self.view)
        self.bridge = Bridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        url = QUrl.fromLocalFile(str((_gui_dir() / "index.html").resolve()))
        self.view.load(url)

        # لاگ زنده به صفحهٔ لاگ
        get_emitter().message.connect(
            lambda line: self.bridge.emit_evt({"type": "log", "text": line})
        )

    def closeEvent(self, e) -> None:
        if self.bridge.worker:
            self.bridge.worker.stop()
        super().closeEvent(e)
