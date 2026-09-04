# -*- coding: utf-8 -*-
"""موتور دانلود کامل تاریخچهٔ یک چت:
- پیمایش از اولین پیام به آخرین پیام (reverse=True)
- حذف پیام‌های تکراری (dedup بر اساس id) در هر اجرا
- ادامه‌پذیری: state.json + دانلود نشدن فایل‌های موجود + min_id
- دسته‌بندی رسانه‌ها در پوشه‌های photos/videos/audio/documents/stickers
- ذخیرهٔ همهٔ پیام‌ها به‌صورت JSONL (با نام فرستنده) برای ساخت HTML
"""
import asyncio
import json
import time
from asyncio import TimeoutError as _AsyncTimeout
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from app.logger_setup import get_logger
from app.tg_client import _display_name

log = get_logger("download")

MESSAGES_FILE = "messages.jsonl"
STATE_FILE = "state.json"
CHAT_INFO_FILE = "chat_info.json"

MEDIA_DIRS = ("photos", "videos", "audio", "documents", "stickers")

MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/zip": ".zip",
}

STATE_SAVE_EVERY = 200   # هر چند پیام state ذخیره شود
WRITTEN_CAP = 10000      # حداکثر idهای نگه‌داری‌شده در state

# بهینه‌سازی سرعت: تعداد دانلود همزمان و تاخیر بین درخواست‌ها
# با پینگ 213ms، هر part یک رفت‌وبرگشت (~213ms) می‌خواهد؛ پس اتصال‌های بیشتر
# یعنی ضرب شدن سرعت (محدودیت تکی‌اتصالی v2ray دور زده می‌شود).
MAX_CONCURRENT_DOWNLOADS = 12  # 12 فایل همزمان — با cryptg (رمزگشایی C) CPU گلوگاه نیست و لینک 213ms با اتصال بیشتر اشباع می‌شود؛ FloodWait با backoff مدیریت می‌شود
ITER_WAIT_TIME = 0.15  # قبلاً 1 ثانیه بود — برای چت 50k حدود 8 دقیقه صبر الکی کم می‌شود


def sanitize_name(name: str, max_len: int = 80) -> str:
    """نام امن برای پوشه/فایل (ویندوز)."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in name).strip().strip(".")
    out = out.replace(" ", "_")
    return out[:max_len] or "untitled"


def classify_document(doc) -> tuple[str, str]:
    """(پوشهٔ مقصد، نام فایل) برای یک سند تلگرام."""
    attrs = doc.attributes
    mime = doc.mime_type or ""
    filename = None
    video_attr = None
    audio_attr = None
    for a in attrs:
        if isinstance(a, DocumentAttributeFilename) and a.file_name:
            filename = a.file_name
        elif isinstance(a, DocumentAttributeVideo):
            video_attr = a
        elif isinstance(a, DocumentAttributeAudio):
            audio_attr = a
    is_sticker = any(isinstance(a, DocumentAttributeSticker) for a in attrs)
    is_animated = any(isinstance(a, DocumentAttributeAnimated) for a in attrs)

    if is_sticker:
        return "stickers", filename or "sticker.webp"
    if is_animated:
        return "videos", filename or "animation.mp4"
    if video_attr is not None:
        return "videos", filename or "video.mp4"
    if audio_attr is not None:
        if audio_attr.voice:
            return "audio", filename or "voice.ogg"
        return "audio", filename or "audio.mp3"
    if mime.startswith("image"):
        return "photos", filename or "image.jpg"
    return "documents", filename or "file.bin"


def _media_type_name(folder: str) -> str:
    return {"photos": "photo", "videos": "video", "audio": "audio",
            "stickers": "sticker", "documents": "document"}.get(folder, "document")


def _ext_for(filename: str, mime: str) -> str:
    p = Path(filename)
    if p.suffix and len(p.suffix) <= 5:
        return p.suffix
    return MIME_EXT.get(mime, "")


class DownloadWorker(QThread):
    """دانلود کامل یک چت در یک ترد جداگانه."""

    progress = Signal(str, int, int, float, str)   # chat_key, done, total, pct, label (پیشرفت پیام)
    file_progress = Signal(str, float, str)        # chat_key, pct, label (پیشرفت فایل جاری)
    file_done = Signal(str, str)                   # chat_key, rel_path
    status = Signal(str, str)                      # chat_key, message
    finished = Signal(str, dict)                   # chat_key, stats
    failed = Signal(str, str)                      # chat_key, error

    def __init__(self, cfg: dict, dialog: dict, chat_dir: Path, options: dict, session: Path):
        super().__init__()
        self.cfg = cfg
        self.dialog = dialog
        self.chat_dir = chat_dir
        self.options = options
        self.session = session
        self.key = str(dialog["id"])
        self._stop = False
        self._names: dict[int, str] = {}
        self._last_emit = 0.0

    # ------- کنترل از بیرون (تنظیم flag؛ تحت GIL امن است) -------
    def stop(self) -> None:
        self._stop = True

    # ------- اجرا -------
    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("Download failed")
            self.failed.emit(self.key, str(e))

    # ------- هسته -------
    async def _main(self) -> None:
        from app.config import require_api, session_path

        require_api(self.cfg)
        client = TelegramClient(
            str(self.session or session_path()),
            int(self.cfg["api_id"]),
            self.cfg["api_hash"],
            proxy=self._proxy(),
            connection_retries=5,
            retry_delay=1,
            device_model="TelegramMediaDownloader",
            app_version="1.0.0",
        )
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("نشست معتبر نیست؛ ابتدا وارد شوید.")

        entity = self.dialog["entity"]
        title = self.dialog["title"]
        self.status.emit(self.key, f"شروع دانلود «{title}» …")

        total = 0
        try:
            total = int((await client.get_messages(entity, limit=0)).total or 0)
        except Exception:
            pass

        state = self._load_state()
        last_id = state.get("last_id", 0)
        written_ids = set(state.get("written_ids", []) or [])
        count = state.get("count", 0)
        last_processed_id = last_id  # آخرین id پردازش‌شده در همین اجرا

        self.chat_dir.mkdir(parents=True, exist_ok=True)
        for d in MEDIA_DIRS:
            (self.chat_dir / d).mkdir(exist_ok=True)

        fh = open(self.chat_dir / MESSAGES_FILE, "a", encoding="utf-8")
        seen: set[int] = set(written_ids)
        stats = {
            "messages": 0,
            "media": 0,
            "skipped_media": 0,
            "bytes": 0,
            "first_date": None,
            "last_date": None,
            "stopped": False,
        }

        try:
            kwargs = dict(reverse=True, wait_time=ITER_WAIT_TIME)
            if last_id:
                kwargs["min_id"] = last_id
            try:
                iterator = client.iter_messages(entity, **kwargs)
            except TypeError:
                # اگر نسخهٔ telethon از min_id پشتیبانی نکند، بدون آن ادامه می‌دهیم
                kwargs.pop("min_id", None)
                iterator = client.iter_messages(entity, **kwargs)
            async for msg in iterator:
                if self._stop:
                    stats["stopped"] = True
                    break
                if msg is None or msg.id in seen:
                    continue
                seen.add(msg.id)
                last_processed_id = msg.id

                rec = await self._build_record(client, msg)
                stats["messages"] += 1
                stats["first_date"] = stats["first_date"] or rec["date"]
                stats["last_date"] = rec["date"]

                if self.options.get("media") and rec["media_type"]:
                    rel, ok, size, skipped = await self._download_media(client, msg, rec)
                    rec["media"] = rel
                    if ok:
                        stats["media"] += 1
                        stats["bytes"] += size
                        self.file_done.emit(self.key, rel)
                        if skipped:
                            stats["skipped_media"] += 1
                    else:
                        rec["media"] = None

                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1

                if count % STATE_SAVE_EVERY == 0:
                    self._save_state(state, last_id=last_processed_id, count=count, written=seen)
                    self._emit_progress(count, total)

            fh.flush()
        finally:
            fh.close()

        self._save_state(state, last_id=last_processed_id, count=count, written=seen)
        stats["count"] = count
        stats["total"] = total
        stats["chat_title"] = title
        stats["self_id"] = self.dialog.get("self_id")
        stats["self_name"] = self.dialog.get("self_name", "")

        self._write_chat_info(stats)

        self._emit_progress(count, total, force=True)
        if stats["stopped"]:
            self.status.emit(self.key, "دانلود متوقف شد (بعداً می‌توانید ادامه دهید).")
        else:
            self.status.emit(self.key, "دانلود کامل شد ✅")
        self.finished.emit(self.key, stats)

    def _proxy(self):
        from app.config import proxy_tuple

        return proxy_tuple(self.cfg)

    # ------- نام فرستنده (با کش) -------
    async def _name_for(self, client: TelegramClient, sender_id) -> str:
        if sender_id is None:
            return ""
        if sender_id in self._names:
            return self._names[sender_id]
        name = str(sender_id)
        try:
            ent = await client.get_entity(sender_id)
            name = _display_name(ent)
        except Exception:
            pass
        self._names[sender_id] = name
        return name

    # ------- رکورد پیام -------
    async def _build_record(self, client: TelegramClient, msg) -> dict:
        service = msg.action is not None
        text = (msg.text or msg.message or "").strip() if not service else ""
        if not self.options.get("text", True):
            text = ""
        reply_id = None
        rt = getattr(msg, "reply_to", None)
        if rt is not None:
            reply_id = getattr(rt, "reply_to_msg_id", None) or getattr(msg, "reply_to_msg_id", None)

        media_type = None
        media_name = None
        media_size = 0
        media = getattr(msg, "media", None)
        if media is not None:
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

        sender_name = await self._name_for(client, msg.sender_id)

        return {
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

    # ------- دانلود فایل -------
    async def _download_media(self, client: TelegramClient, msg, rec: dict) -> tuple[str | None, bool, int, bool]:
        media = getattr(msg, "media", None)
        if media is None:
            return None, False, 0, False
        try:
            if isinstance(media, MessageMediaPhoto):
                folder = "photos"
                fname = f"{msg.id:06d}_{sanitize_name(rec['media_name'] or 'photo.jpg')}"
            elif isinstance(media, MessageMediaDocument):
                doc = media.document
                folder, orig = classify_document(doc)
                ext = _ext_for(orig, doc.mime_type or "")
                base = sanitize_name(orig)
                if not Path(orig).suffix and ext:
                    base += ext
                fname = f"{msg.id:06d}_{base}"
            else:
                return None, False, 0, False
        except Exception:
            return None, False, 0, False

        rel = f"{folder}/{fname}"
        target = self.chat_dir / rel
        size = int(rec["media_size"] or 0)

        # فایل از قبل دانلود شده با همان اندازه؟ → رد شو (ادامهٔ دانلود)
        if target.exists() and (size == 0 or target.stat().st_size == size):
            return rel, True, size, True

        # فایل ناقص از قبل هست؟ حذفش کن
        if target.exists() and size > 0 and target.stat().st_size < size:
            target.unlink(missing_ok=True)

        # حداکثر ۳ تلاش برای دانلود هر فایل
        for attempt in range(3):
            try:
                await client.download_media(
                    msg,
                    file=str(target),
                    progress_callback=self._file_cb(rec["id"]),
                )
                final_size = target.stat().st_size if target.exists() else size
                return rel, True, final_size, False
            except FloodWaitError as e:
                secs = int(getattr(e, "seconds", 30))
                log.warning("FloodWait هنگام دانلود: %s ثانیه", secs)
                self.status.emit(self.key, f"محدودیت تلگرام — {secs} ثانیه صبر…")
                await asyncio.sleep(min(secs, 300))
                # بعد از FloodWait دوباره تلاش کن
                continue
            except RPCError as e:
                log.warning("خطا در دانلود رسانه (id=%s, تلاش %s/3): %s",
                            rec["id"], attempt + 1, e)
                target.unlink(missing_ok=True)
                await asyncio.sleep(2 * (attempt + 1))
            except Exception as e:
                log.warning("خطای غیرمنتظره در دانلود (id=%s, تلاش %s/3): %s",
                            rec["id"], attempt + 1, e)
                target.unlink(missing_ok=True)
                await asyncio.sleep(2 * (attempt + 1))
        log.error("رسانهٔ id=%s بعد از ۳ تلاش دانلود نشد", rec["id"])
        return rel, False, 0, False

    def _file_cb(self, msg_id: int):
        def cb(received: int, total: int) -> None:
            now = time.monotonic()
            if now - self._last_emit < 0.15:
                return
            self._last_emit = now
            pct = (received / total * 100) if total else 0.0
            self.file_progress.emit(self.key, pct, f"دانلود فایل پیام {msg_id} … {pct:.0f}%")

        return cb

    # ------- state / chat_info -------
    def _load_state(self) -> dict:
        p = self.chat_dir / STATE_FILE
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: dict, last_id: int, count: int, written: set) -> None:
        ids = list(written)[-WRITTEN_CAP:]
        state.update({"last_id": last_id, "count": count, "written_ids": ids})
        try:
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            (self.chat_dir / STATE_FILE).write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def _write_chat_info(self, stats: dict) -> None:
        info = {
            "id": self.dialog["id"],
            "title": self.dialog["title"],
            "type": self.dialog.get("type", ""),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "message_count": stats["count"],
            "media_count": stats["media"],
            "first_date": stats.get("first_date"),
            "last_date": stats.get("last_date"),
            "self_id": self.dialog.get("self_id"),
            "self_name": self.dialog.get("self_name", ""),
        }
        try:
            (self.chat_dir / CHAT_INFO_FILE).write_text(
                json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _emit_progress(self, done: int, total: int, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_emit < 0.2:
            return
        self._last_emit = now
        pct = (done / total * 100) if total else 0.0
        self.progress.emit(self.key, done, total, pct, f"{done} از {total} پیام")


# ---------------------------------------------------------------------------
# ترمیم رسانه‌های جاافتاده (مثلاً رکوردهای media=None از دوره‌ای که دانلود
# رسانه خطا می‌داد): بدون دانلود دوبارهٔ همه‌چیز، فقط همان پیام‌ها گرفته و
# فایلشان دانلود و رکوردشان در messages.jsonl اصلاح می‌شود.
# ---------------------------------------------------------------------------
def find_broken_media(chat_dir: Path) -> list[dict]:
    """رکوردهایی که media_type دارند ولی فایلشان روی دیسک نیست."""
    broken: list[dict] = []
    p = chat_dir / MESSAGES_FILE
    if not p.exists():
        return broken
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return broken
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not rec.get("media_type"):
            continue
        rel = rec.get("media")
        if rel and (chat_dir / rel).exists():
            continue
        broken.append(rec)
    return broken


def rewrite_media_fields(chat_dir: Path, updates: dict[int, str]) -> int:
    """به‌روزرسانی فیلد media رکوردها در messages.jsonl. برمی‌گرداند تعداد اصلاح‌شده."""
    if not updates:
        return 0
    p = chat_dir / MESSAGES_FILE
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0
    n = 0
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except Exception:
            out.append(line)
            continue
        try:
            mid = int(rec.get("id"))
        except (TypeError, ValueError):
            out.append(line)
            continue
        if mid in updates:
            rec["media"] = updates[mid]
            n += 1
        out.append(json.dumps(rec, ensure_ascii=False))
    try:
        tmp = p.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(p)
    except Exception:
        return 0
    return n


# ---------------------------------------------------------------------------
# نسخهٔ async خالص (بدون Qt) — برای backend پنجرهٔ pywebview
# ---------------------------------------------------------------------------
async def export_chat_async(cfg: dict, dialog: dict, export_root: Path,
                            options: dict | None = None,
                            progress=None) -> dict:
    """دانلود کامل یک چت از اولین پیام تا آخرین + ساخت خروجی HTML.
    برمی‌گرداند آمار دانلود. progress(step: str, done: int, total: int) اختیاری است.
    """
    from telethon import TelegramClient
    from app.config import require_api, session_path, proxy_tuple

    require_api(cfg)
    options = options or {}
    chat_dir = export_root / "chats" / sanitize_name(dialog["title"])
    chat_dir.mkdir(parents=True, exist_ok=True)
    for d in MEDIA_DIRS:
        (chat_dir / d).mkdir(exist_ok=True)

    client = TelegramClient(
        str(session_path()), int(cfg["api_id"]), cfg["api_hash"],
        proxy=proxy_tuple(cfg), connection_retries=5, retry_delay=1,
        device_model="TelegramMediaDownloader", app_version="1.0.0",
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("نشست معتبر نیست؛ ابتدا وارد شوید.")

        # بازسازی entity با کلاینت جدید — entity از کلاینت قطع‌شدهٔ قبلی
        # باعث می‌شود iter_messages هیچ پیامی برنگرداند.
        entity = dialog["entity"]
        try:
            entity = await client.get_entity(int(dialog["id"]))
        except Exception:
            pass  # اگر نشد، همان entity قبلی را امتحان می‌کنیم

        total = 0
        try:
            total = int((await client.get_messages(entity, limit=0)).total or 0)
        except Exception:
            pass

        # state ذخیره از قبل — تا پیام‌های دانلودشده دوباره دانلود نشوند.
        # حالت افزایشی (resume): messages.jsonl و state.json نگه داشته می‌شوند و فقط
        # پیام‌های جدید گرفته می‌شوند؛ رسانه‌های موجود روی دیسک هم دوباره دانلود نمی‌شوند.
        existing = set()
        _old_first_date = None
        _old_last_date = None
        if (chat_dir / MESSAGES_FILE).exists():
            for line in (chat_dir / MESSAGES_FILE).read_text(encoding="utf-8").splitlines():
                try:
                    _r = json.loads(line)
                    if _r.get("id") is not None:
                        existing.add(_r.get("id"))
                    # فایل به ترتیب زمانی است (قدیم→جدید) — اول و آخر را نگه دار
                    if _r.get("date"):
                        if _old_first_date is None:
                            _old_first_date = _r["date"]
                        _old_last_date = _r["date"]
                except Exception:
                    pass

        async def _reconnect():
            """قطع و وصل دوبارهٔ کلاینت — بعد از «Server closed the connection»
            که باعث «wrong session ID» و گیرکردن می‌شود."""
            try:
                await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(1)
            try:
                await client.connect()
            except Exception as e:
                log.warning("reconnect failed: %s", e)

        # نام فرستنده‌ها: حلقه داغ هرگز منتظر شبکه نمی‌ماند. برای هر فرستنده ناشناس
        # فقط یک تسک مشترک ساخته می‌شود (_ensure_name_task) و رکوردها موقع فلاش —
        # همزمان با دانلود رسانه‌ها — نام را برمی‌دارند (_backfill_names). قبلاً هر
        # فرستنده جدید یک RTT سریالی (~0.5s با پروکسی) وسط حلقه بود و شمارنده/بایت‌ها
        # را قفل می‌کرد.
        names: dict[int, str] = {}
        pending_names: dict[int, asyncio.Task] = {}

        async def _fetch_name(sender_id) -> str:
            n = str(sender_id)
            try:
                # سقف 10 ثانیه — یک فرستنده خراب/حذف‌شده نباید چیزی را قفل کند
                ent = await asyncio.wait_for(client.get_entity(sender_id), timeout=10)
                n = _display_name(ent)
            except Exception:
                pass
            names[sender_id] = n
            return n

        def _ensure_name_task(sender_id) -> None:
            if sender_id is None or sender_id in names or sender_id in pending_names:
                return
            pending_names[sender_id] = asyncio.create_task(_fetch_name(sender_id))

        async def _backfill_names() -> None:
            need = [pending_names[rec.get("sender_id")]
                    for rec, _, _ in buffer
                    if rec.get("sender_id") is not None
                    and rec.get("sender_id") not in names
                    and rec.get("sender_id") in pending_names]
            if need:
                await asyncio.gather(*need, return_exceptions=True)
            for rec, _, _ in buffer:
                sid = rec.get("sender_id")
                if sid is not None:
                    rec["sender_name"] = names.get(sid, str(sid))

        # شمارش از داده قبلی شروع می‌شود تا پیشرفت و chat_info درست باشند
        # (در ادامه، پیام‌های تکراری دوباره شمرده نمی‌شوند)
        stats = {"messages": len(existing), "media": 0, "bytes": 0,
                 "first_date": _old_first_date, "last_date": _old_last_date}
        # state برای ادامه‌پذیری — ذخیرهٔ min_id هر چند پیام
        state_file = chat_dir / STATE_FILE
        saved_state = {}
        if state_file.exists():
            try:
                saved_state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        last_id = saved_state.get("last_id", 0)
        fh = open(chat_dir / MESSAGES_FILE, "a", encoding="utf-8")
        try:
            # دانلود از اولین پیام به آخرین (reverse=True = قدیمی→جدید)
            # min_id باعث می‌شود پیام‌های قبلاً دانلودشده دوباره پردازش نشوند
            kwargs = dict(reverse=True, wait_time=ITER_WAIT_TIME)
            if last_id:
                kwargs["min_id"] = last_id
            try:
                iterator = client.iter_messages(entity, **kwargs)
            except TypeError:
                kwargs.pop("min_id", None)
                iterator = client.iter_messages(entity, **kwargs)

            # — دانلود موازی: پیام‌ها را دسته‌ای جمع می‌کنیم و رسانه‌ها را با هم دانلود می‌کنیم —
            # این باعث می‌شود با اینترنت پرسرعت و پینگ 213ms، سرعت ~4-5 برابر شود
            # ولی همهٔ فایل‌ها (voice/image/video/document/sticker) همچنان کامل دانلود می‌شوند
            sem = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
            buffer: list[tuple[dict, object | None, object]] = []  # (rec, task|None, msg)
            BATCH_FLUSH = 24  # هر 24 پیام یا وقتی 5 رسانه جمع شد، با هم فلاش کن
            queued = len(existing)  # از داده قبلی شروع کن تا شمارنده به عقب برنگردد

            async def _bounded_dl(m, r):
                async with sem:
                    # بدون reconnect دستی: کلاینت بین 5 دانلود موازی مشترک است و
                    # disconnect وسط کار، بقیه دانلودهای سالم را هم می‌کشد.
                    # تلاش‌های مجدد با backoff + reconnect خودکار telethon کافی است.
                    return await _download_media_async(client, m, r, chat_dir, reconnect=None)

            async def _flush_buffer():
                nonlocal last_id
                if not buffer:
                    return
                # نام فرستنده‌ها همزمان با دانلود رسانه‌ها آماده می‌شود (بدون معطلی سریالی)
                backfill = asyncio.create_task(_backfill_names())
                # تفکیک: کدام‌ها رسانه دارند
                tasks = [t for _, t, _ in buffer if t is not None]
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    await backfill
                    ri = 0
                    for idx, (rec, task, msg_obj) in enumerate(buffer):
                        if task is not None:
                            res = results[ri]
                            ri += 1
                            if isinstance(res, Exception):
                                log.warning("دانلود موازی خطا id=%s: %s", rec["id"], res)
                                rec["media"] = None
                            else:
                                rec["media"] = res
                                if res:
                                    stats["media"] += 1
                                    stats["bytes"] += int(rec.get("media_size") or 0)
                        # نوشتن
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        existing.add(rec["id"])
                        stats["messages"] += 1
                        stats["first_date"] = stats["first_date"] or rec["date"]
                        stats["last_date"] = rec["date"]
                        last_id = max(last_id, rec["id"])
                        if progress:
                            progress("downloading", stats["messages"], total)
                else:
                    await backfill
                    for rec, _, _ in buffer:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        existing.add(rec["id"])
                        stats["messages"] += 1
                        stats["first_date"] = stats["first_date"] or rec["date"]
                        stats["last_date"] = rec["date"]
                        last_id = max(last_id, rec["id"])
                        if progress:
                            progress("downloading", stats["messages"], total)
                # فلاش و ذخیره state
                if stats["messages"] % 100 < len(buffer):
                    fh.flush()
                    try:
                        state_data = {"last_id": last_id, "count": stats["messages"]}
                        state_file.write_text(json.dumps(state_data, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                buffer.clear()

            async for msg in iterator:
                if msg is None:
                    continue
                if msg.id in existing:
                    # پیام قدیمی — قبلاً شمرده شده (stats از len(existing) شروع شد)،
                    # فقط اگر buffer پر است فلاش کن و رد شو (بدون دانلود مجدد).
                    if len(buffer) >= BATCH_FLUSH:
                        await _flush_buffer()
                    continue
                service = msg.action is not None
                text = (msg.text or msg.message or "").strip() if not service else ""
                media_type = None
                media_name = None
                media_size = 0
                media = getattr(msg, "media", None)
                if media is not None:
                    if isinstance(media, MessageMediaPhoto):
                        media_type, media_name = "photo", "photo.jpg"
                        try:
                            media_size = media.photo.size if media.photo else 0
                        except Exception:
                            media_size = 0
                    elif isinstance(media, MessageMediaDocument):
                        doc = media.document
                        if doc is not None:
                            folder, fname = classify_document(doc)
                            media_type = _media_type_name(folder)
                            media_name, media_size = fname, getattr(doc, "size", 0) or 0

                # نام را همزمان در پس‌زمینه بگیر؛ مقدار نهایی موقع فلاش پر می‌شود
                _ensure_name_task(msg.sender_id)
                sender_name = names.get(msg.sender_id, "")
                rec = {
                    "id": msg.id,
                    "date": msg.date.astimezone().isoformat() if getattr(msg, "date", None) else "",
                    "sender_id": msg.sender_id,
                    "sender_name": sender_name,
                    "out": bool(getattr(msg, "out", False)),
                    "text": text,
                    "service": service,
                    "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
                    "media_type": media_type,
                    "media_name": media_name,
                    "media_size": media_size,
                    "media": None,
                }

                # اگر رسانه دارد و باید دانلود شود → تسک موازی بساز (await نکن)
                if options.get("media", True) and media_type:
                    task = asyncio.create_task(_bounded_dl(msg, rec))
                    buffer.append((rec, task, msg))
                else:
                    buffer.append((rec, None, msg))

                # وقتی buffer پر شد، فلاش کن (دانلودهای موازی اجرا می‌شوند)
                pending_media = sum(1 for _, t, _ in buffer if t is not None)
                queued += 1
                # پیشرفت زنده با شمارش پیام‌های خوانده‌شده — حتی وقتی رسانه‌ها
                # هنوز در حال دانلودند، عدد روی صفحه جلو می‌رود و «گیر کرده» به نظر نمی‌رسد
                if progress:
                    progress("downloading", queued, total)
                if len(buffer) >= BATCH_FLUSH or pending_media >= MAX_CONCURRENT_DOWNLOADS:
                    await _flush_buffer()
            # فلاش باقی‌مانده
            await _flush_buffer()
            # ذخیرهٔ state نهایی
            try:
                state_data = {"last_id": last_id, "count": stats["messages"]}
                state_file.write_text(json.dumps(state_data, ensure_ascii=False),
                                      encoding="utf-8")
            except Exception:
                pass
        finally:
            fh.close()

        # — ترمیم رسانه‌های جاافتاده (رکورد media_typeدار ولی بدون فایل) —
        # بدون دانلود دوبارهٔ پیام‌ها؛ فقط همان پیام‌ها از تلگرام گرفته می‌شوند.
        if options.get("media", True):
            try:
                broken = find_broken_media(chat_dir)
            except Exception:
                broken = []
            if broken:
                log.info("ترمیم %s رسانه جاافتاده…", len(broken))
                by_id = {int(r["id"]): r for r in broken if r.get("id") is not None}
                ids = list(by_id)
                repaired: dict[int, str] = {}
                sem_r = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

                async def _repair_dl(m, r):
                    async with sem_r:
                        return await _download_media_async(client, m, r, chat_dir, reconnect=None)

                done_n = 0
                for i in range(0, len(ids), 50):
                    chunk_ids = ids[i:i + 50]
                    try:
                        msgs = await client.get_messages(entity, ids=list(chunk_ids))
                    except Exception as e:
                        log.warning("repair: get_messages ناموفق: %s", str(e)[:100])
                        continue
                    if not msgs:
                        continue
                    if not isinstance(msgs, list):
                        msgs = [msgs]
                    jobs = []
                    for m in msgs:
                        if m is None:
                            continue
                        old = by_id.get(int(getattr(m, "id", -1)))
                        if old is None:
                            continue
                        stub = {"id": m.id, "media_name": old.get("media_name"),
                                "media_size": old.get("media_size")}
                        jobs.append((m, stub, asyncio.create_task(_repair_dl(m, stub))))
                    if not jobs:
                        continue
                    res = await asyncio.gather(*[t for _, _, t in jobs], return_exceptions=True)
                    for (m, stub, _), r in zip(jobs, res):
                        done_n += 1
                        if isinstance(r, Exception) or not r:
                            continue
                        repaired[int(m.id)] = r
                        stats["media"] += 1
                        try:
                            stats["bytes"] += int(by_id[int(m.id)].get("media_size") or 0)
                        except Exception:
                            pass
                    if progress:
                        progress("repair", done_n, len(broken))
                if repaired:
                    n_fixed = rewrite_media_fields(chat_dir, repaired)
                    log.info("ترمیم کامل شد: %s رسانه برگشت", n_fixed)

        # chat_info برای exporter
        info = {
            "id": dialog["id"], "title": dialog["title"], "type": dialog.get("type", ""),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "message_count": stats["messages"], "media_count": stats["media"],
            "first_date": stats.get("first_date"), "last_date": stats.get("last_date"),
            "self_id": dialog.get("self_id"), "self_name": dialog.get("self_name", ""),
        }
        (chat_dir / CHAT_INFO_FILE).write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

        stats["total"] = total
        stats["chat_title"] = dialog["title"]
        return stats
    finally:
        await client.disconnect()


async def _download_media_async(client, msg, rec: dict, chat_dir: Path,
                                reconnect=None) -> str | None:
    """دانلود یک رسانه و برگرداندن مسیر نسبی (یا None).
    reconnect: اختیاری است؛ async callable که کلاینت را دوباره وصل می‌کند.
    اگر فایل نیمه‌کاره ماند (اتصال قطع شد) برداشته و دوباره از اول دانلود می‌شود.
    """
    media = getattr(msg, "media", None)
    if media is None:
        return None
    try:
        if isinstance(media, MessageMediaPhoto):
            folder = "photos"
            fname = f"{msg.id:06d}_{sanitize_name(rec['media_name'] or 'photo.jpg')}"
        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            folder, orig = classify_document(doc)
            ext = _ext_for(orig, doc.mime_type or "")
            base = sanitize_name(orig)
            if not Path(orig).suffix and ext:
                base += ext
            fname = f"{msg.id:06d}_{base}"
        else:
            return None
    except Exception:
        return None

    rel = f"{folder}/{fname}"
    target = chat_dir / rel
    size = int(rec["media_size"] or 0)
    if target.exists() and (size == 0 or target.stat().st_size == size):
        return rel

    # فایل‌های بسیار بزرگ از طریق فیلترشکن/پروکسی عملاً دانلود نمی‌شوند و
    # کل چت را روی خودشان گیر می‌اندازند؛ ردشان می‌کنیم تا بقیه ادامه یابد.
    MAX_MEDIA_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
    if size > MAX_MEDIA_SIZE:
        log.warning("رسانهٔ id=%s با حجم %sMB بیش از حد مجاز است — رد شد",
                    rec["id"], round(size / 1024 / 1024))
        return None

    # چند تلاش با فاصله، هر تلاش با سقف زمانی تا یک فایل گیر، کل چت را نکشد.
    # فرمول جدید: 30 ثانیه پایه + حجم/(500KB/s) با سقف 180 ثانیه.
    # با اینترنت پرسرعت، فایل 10MB حدود 50 ثانیه وقت دارد؛ اگر از آن کندتر بود
    # (یعنی عملاً گیر کرده) رد می‌شود تا 6331 پیام دیگر معطل نمانند.
    # فرمول قبلی تا 300 ثانیه × 4 تلاش ≈ 20 دقیقه برای یک فایل صبر می‌کرد!
    FILE_TIMEOUT = (max(45, min(180, 30 + int(size / (500 * 1024)))) if size > 0 else 45)

    for attempt in range(4):  # ۴ تلاش به جای ۳
        try:
            # اگر فایل ناقص از قبل هست، حذفش کن تا از اول دانلود شود
            if target.exists() and size > 0 and target.stat().st_size < size:
                target.unlink(missing_ok=True)
            # نکته: download_media در Telethon 1.44 پارامتر part_size_kb ندارد (فقط
            # download_file سطح‌پایین دارد) — پاس دادنش TypeError می‌دهد و همه رسانه‌ها
            # می‌پرند! خود Telethon به‌صورت خودکار سایز مناسب می‌گذارد
            # (get_appropriated_part_size: ‏128KB تا 100MB ‏/ 256KB تا 750MB ‏/ 512KB بالاتر).
            task = asyncio.ensure_future(client.download_media(msg, file=str(target)))
            await asyncio.wait_for(task, timeout=FILE_TIMEOUT)
            if not target.exists() or target.stat().st_size == 0:
                target.unlink(missing_ok=True)
                raise ConnectionError("empty download")
            return rel
        except _AsyncTimeout:
            log.warning("دانلود رسانهٔ id=%s از %s ثانیه بیشتر طول کشید (تلاش %s) — دوباره تلاش…",
                        rec["id"], FILE_TIMEOUT, attempt + 1)
            target.unlink(missing_ok=True)
            if reconnect and attempt < 2:
                try:
                    await reconnect()
                except Exception:
                    pass
            await asyncio.sleep(2 * (attempt + 1))
        except FloodWaitError as e:
            secs = int(getattr(e, "seconds", 30))
            log.warning("FloodWait هنگام دانلود: %s ثانیه", secs)
            await asyncio.sleep(min(secs, 300))
            continue  # بعد از FloodWait دوباره تلاش کن
        except Exception as e:
            log.warning("خطا در دانلود رسانه (id=%s, تلاش %s/%s): %s",
                        rec["id"], attempt + 1, 4, str(e)[:120])
            target.unlink(missing_ok=True)
            if reconnect:
                try:
                    await reconnect()
                except Exception:
                    pass
            await asyncio.sleep(3 * (attempt + 1))
    return None
