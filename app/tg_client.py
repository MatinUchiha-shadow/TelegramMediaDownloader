# -*- coding: utf-8 -*-
"""توابع ناهمگام تلگرام (Telethon):
ورود با شماره موبایل، کد، رمز دومرحله‌ای، و دریافت لیست چت‌ها.
هر تابع یک کلاینت مستقل با همان session می‌سازد تا در GUI ساده بماند.
"""
import asyncio
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.types import Channel, Chat, User

from app.logger_setup import get_logger

log = get_logger("tg")

# مقاومت سشن SQLite در برابر دسترسی همزمان: وقتی وسط دانلود، لیست چت‌ها هم
# گرفته می‌شود، دو کانکشن همزمان به telegram.session می‌زنند و SQLite فوری
# خطای «database is locked» می‌داد. با busy_timeout به‌جای خطای فوری، تا
# ۱۵ ثانیه صبر می‌کند (نوبتی). این پچ process-wide است و همه کلاینت‌ها را
# پوشش می‌دهد.
try:
    from telethon.sessions.sqlite import SQLiteSession as _SQLiteSession

    _orig_sqlite_cursor = _SQLiteSession._cursor

    def _cursor_with_busy_timeout(self):
        cur = _orig_sqlite_cursor(self)
        try:
            cur.execute("PRAGMA busy_timeout=15000")
        except Exception:
            pass
        return cur

    _SQLiteSession._cursor = _cursor_with_busy_timeout
except Exception:
    pass

# خطاهای قابل انتظار هنگام ورود → پیام فارسی مناسب
LOGIN_ERRORS = {
    PhoneCodeInvalidError: "کد واردشده اشتباه است. دوباره تلاش کنید.",
    PhoneCodeExpiredError: "کد منقضی شده است. یک کد جدید درخواست کنید.",
    PasswordHashInvalidError: "رمز دومرحله‌ای اشتباه است.",
}


def _proxy(cfg: dict):
    from app.config import proxy_tuple

    return proxy_tuple(cfg)


def _client(cfg: dict, session: Path) -> TelegramClient:
    from app.config import session_path

    return TelegramClient(
        str(session_path() if session is None else session),
        int(cfg["api_id"]),
        cfg["api_hash"],
        proxy=_proxy(cfg),
        connection_retries=5,
        retry_delay=1,
        device_model="TelegramMediaDownloader",
        app_version="1.0.0",
        system_version="Windows 10",
    )


async def _handle_flood(e: FloodWaitError) -> None:
    seconds = int(getattr(e, "seconds", 10))
    log.warning("FloodWait: %s ثانیه صبر می‌کنیم", seconds)
    await asyncio.sleep(min(seconds, 300))


def normalize_phone(phone: str) -> str:
    """تبدیل شماره به فرمت بین‌المللی:
    09929184925 → +989929184925
    +989929184925 → بدون تغییر
    """
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("00"):
        p = "+" + p[2:]
    elif p.startswith("+0"):
        p = "+" + p[2:]
    if not p.startswith("+"):
        if p.startswith("0") and len(p) >= 10 and p[1] == "9":
            p = "+98" + p[1:]  # 0992... → +98992...
        elif p.startswith("9") and len(p) == 10:
            p = "+98" + p  # 9929184925 → +989929184925
        else:
            p = "+" + p
    return p


async def send_code(cfg: dict, phone: str) -> str:
    """ارسال کد ورود به شمارهٔ داده‌شده و برگرداندن phone_code_hash.
    فقط connect + send_code_request (نه start() — چون start() از کاربر input می‌خواهد).
    hash لازم است تا sign_in بعدی با همان درخواست کد جفت شود.
    """
    phone = normalize_phone(phone)
    client = _client(cfg, None)
    try:
        await client.connect()
        while True:
            try:
                result = await client.send_code_request(phone)
                return getattr(result, "phone_code_hash", "")
            except FloodWaitError as e:
                await _handle_flood(e)
    finally:
        await client.disconnect()


async def sign_in(cfg: dict, phone: str, code: str, password: str | None = None,
                  phone_code_hash: str = "") -> str:
    """ورود با کد (و در صورت نیاز رمز دومرحله‌ای). برمی‌گرداند نام کاربر.
    phone_code_hash از send_code می‌آید؛ بدون آن تلگرام خطای
    «You also need to provide a phone_code_hash» می‌دهد.
    """
    phone = normalize_phone(phone)
    client = _client(cfg, None)
    try:
        await client.connect()
        try:
            if phone_code_hash:
                await client.sign_in(phone=phone, code=code.strip(),
                                     phone_code_hash=phone_code_hash)
            else:
                await client.sign_in(phone=phone, code=code.strip())
        except SessionPasswordNeededError:
            if not password:
                raise _NeedsPassword("2FA")
            try:
                await client.sign_in(password=password)
            except FloodWaitError as e:
                await _handle_flood(e)
                raise
        except FloodWaitError as e:
            await _handle_flood(e)
            raise
        me = await client.get_me()
        return _display_name(me) or str(me.id)
    finally:
        await client.disconnect()


class _NeedsPassword(Exception):
    """برای اعلام نیاز به رمز دومرحله‌ای (به‌جای خطای telethon در GUI)."""


async def is_logged_in(cfg: dict) -> bool:
    client = _client(cfg, None)
    try:
        await client.connect()
        return bool(await client.is_user_authorized())
    except Exception:
        return False
    finally:
        await client.disconnect()


def _display_name(entity) -> str:
    if isinstance(entity, User):
        return " ".join(
            p for p in (getattr(entity, "first_name", "") or "", getattr(entity, "last_name", "") or "") if p
        ) or str(getattr(entity, "id", ""))
    return getattr(entity, "title", "") or str(getattr(entity, "id", ""))


async def fetch_dialogs(cfg: dict) -> list[dict]:
    """دریافت همهٔ چت‌ها/گروه‌ها/کانال‌ها. هر آیتم شامل entity است
    تا بعداً برای دانلود همان شیء استفاده شود.
    حذف تکراری‌ها: وقتی یک گروه به سوپرگروپ ارتقا پیدا می‌کند،
    هم Chat قدیمی و هم Channel جدید در لیست ظاهر می‌شوند —
    فقط نسخهٔ فعال (Channel) را نگه می‌داریم.
    """
    client = _client(cfg, None)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("نشست معتبر نیست؛ ابتدا وارد شوید.")
        me = await client.get_me()

        # ۱) دریافت همهٔ dialogها
        raw = []
        async for d in client.iter_dialogs():
            entity = d.entity
            if isinstance(entity, User):
                dtype = "user"
            elif isinstance(entity, Channel):
                dtype = "channel" if entity.broadcast else "group"
            elif isinstance(entity, Chat):
                dtype = "group"
            else:
                dtype = "unknown"
            raw.append({
                "id": d.id,
                "title": d.name or "بدون نام",
                "type": dtype,
                "unread": getattr(d, "unread_count", 0) or 0,
                "date": d.date.isoformat() if getattr(d, "date", None) else "",
                "entity": entity,
                "self_id": me.id,
                "self_name": _display_name(me),
            })

        # ۲) حذف تکراری‌ها — اگر یک Channel (سوپرگروپ) به Chat قدیمی اشاره
        #    کند (migrated_from_chat_id)، Chat قدیمی را حذف می‌کنیم.
        migrated_chat_ids: set[int] = set()
        for item in raw:
            ent = item["entity"]
            if isinstance(ent, Channel):
                mcid = getattr(ent, "migrated_from_chat_id", None)
                if mcid is not None:
                    migrated_chat_ids.add(mcid)

        dialogs = [item for item in raw if item["id"] not in migrated_chat_ids]

        # ۳) حذف تکراری بر اساس id (محافظت اضافی)
        seen_ids: set[int] = set()
        unique: list[dict] = []
        for item in dialogs:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                unique.append(item)

        # ۴) حذف تکراری بر اساس عنوان — اگر دو چت عنوان یکسانی
        #    دارند، نسخهٔ Channel (سوپرگروپ) را نگه می‌داریم چون فعال‌تر است.
        from collections import defaultdict
        by_title: dict[str, list[dict]] = defaultdict(list)
        for item in unique:
            by_title[item["title"]].append(item)

        final: list[dict] = []
        for title_key, items in by_title.items():
            if len(items) == 1:
                final.append(items[0])
                continue
            # اولویت: channel > group > user
            priority = {"channel": 0, "group": 1, "user": 2, "unknown": 3}
            items.sort(key=lambda x: priority.get(x["type"], 9))
            final.append(items[0])

        return final
    finally:
        await client.disconnect()
