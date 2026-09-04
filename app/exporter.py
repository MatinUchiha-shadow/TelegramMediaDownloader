# -*- coding: utf-8 -*-
"""ساخت خروجی HTML به سبک خروجی دسکتاپ تلگرام:
- index.html (لیست چت‌ها)
- chats/<نام چت>/index.html (تاریخچه با حباب‌ها، تفکیک روز، رسانه)
- پشتیبانی از RTL برای فارسی و LTR برای انگلیسی (unicode-bidi: plaintext)
- تاریخ شمسی (جلالی) با jdatetime
- حذف پیام‌های تکراری بر اساس id (لایهٔ آخر دفاعی)

نکتهٔ مهم (عملکرد و حافظه — برای کانال/گروه‌های سنگین):
صفحهٔ هر چت دیگر با یک رشتهٔ غول‌آسا در رم ساخته نمی‌شود و دادهٔ پیام‌ها هم
همه داخل صفحه قرار نمی‌گیرد. پیام‌ها به‌صورت «رکورد کوتاه» در فایل‌های chunk
جدا (chats/<چت>/data/c*.js) نوشته می‌شوند و مرورگر/اندروید (app.js) فقط
chunk های نزدیک به جای اسکرول را لود می‌کند — یعنی:
  * فقط ~۱۰ پیام بالا و ~۱۲ پیام پایینِ پیامِ در حال مشاهده در DOM است
  * فایل‌های رسانه هم فقط همان محدوده لود می‌شوند (عکس‌ها lazy هستند)
  * ویدیو و ویس اصلاً پیش‌لود نمی‌شوند؛ فقط با کلیک روی دکمهٔ پخش لود می‌شوند
پس رم گوشی یک‌دفعه پر نمی‌شود و کانال/گروه خیلی سنگین هم لگ/کرش نمی‌کند.
جستجو (تدریجی روی chunk های لودشده)، پخش یک‌تای صدا، پخش خودکار وویس بعدی،
سرعت پخش، اولین/آخرین پیام، ذخیرهٔ جای اسکرول و زوم عکس هم در همان app.js است.
"""
import html
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import jdatetime

# فعال‌سازی نام‌ها و ارقام فارسی در تاریخ شمسی (jdatetime 6+)
try:
    jdatetime.set_locale(jdatetime.FA_LOCALE)
except Exception:
    pass

from app.downloader import CHAT_INFO_FILE, MESSAGES_FILE, sanitize_name
from app.logger_setup import get_logger

log = get_logger("export")

CHATS_DIR = "chats"
ASSETS_DIR = "assets"

# پالت رنگ نام فرستنده‌ها (مثل تلگرام)
SENDER_COLORS = [
    "#ef6c00", "#e53935", "#d81b60", "#8e24aa", "#5e35b1", "#3949ab",
    "#1e88e5", "#00897b", "#43a047", "#7cb342", "#fdd835", "#ff8f00",
]

_RTL_RE = re.compile(r"[\u0590-\u08ff\u0600-\u06ff\ufb1d-\ufdff\ufe70-\ufefc]")

# وویس‌های تلگرام معمولاً ogg/opus هستند
VOICE_EXTS = (".ogg", ".oga", ".opus")

# تعداد پیام در هر فایل chunk — کم است تا لود تدریجی سبک بماند
CHUNK_SIZE = 250

# کاراکترهای base36 برای بسته‌بندی فشردهٔ تخمین ارتفاع پیام‌ها
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def sender_color(sender_id) -> str:
    try:
        return SENDER_COLORS[abs(int(sender_id)) % len(SENDER_COLORS)]
    except Exception:
        return SENDER_COLORS[0]


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa_digits(s: str) -> str:
    return s.translate(_FA_DIGITS)


def format_jalali(iso: str) -> str:
    """تبدیل ISO → «شنبه ۲۳ مرداد ۱۴۰۳»."""
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return iso[:10]
    try:
        jd = jdatetime.date.fromgregorian(date=dt.date())
        return _fa_digits(f"{jd.strftime('%A')} {jd.day} {jd.strftime('%B')} {jd.year}")
    except Exception:
        return dt.date().isoformat()


def format_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%H:%M")
    except Exception:
        return ""


def format_size(n: int) -> str:
    try:
        n = int(n or 0)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def load_chat_info(chat_dir: Path) -> dict | None:
    try:
        return json.loads((chat_dir / CHAT_INFO_FILE).read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_records(chat_dir: Path):
    """خواندن رکوردهای پیام با حذف idهای تکراری و مرتب‌سازی بر اساس id.
    اگر دانلود وسط کار قطع شده و دوباره ادامه یافته باشد،
    پیام‌ها ممکن است به ترتیب زمانی نباشند → مرتب‌سازی تضمین می‌کند
    که همیشه از اولین پیام تا آخرین پیام نمایش داده شوند.
    """
    seen: set[int] = set()
    records: list[dict] = []
    p = chat_dir / MESSAGES_FILE
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            mid = rec.get("id")
            if mid is None or mid in seen:
                continue
            seen.add(mid)
            records.append(rec)
    # مرتب‌سازی بر اساس id (تضمین ترتیب زمانی)
    records.sort(key=lambda r: int(r.get("id") or 0))
    for rec in records:
        yield rec


def _sanitize_script(s: str) -> str:
    """جلوگیری از بسته شدن زودهنگام تگ <script> با محتوای کاربر."""
    return s.replace("</script", "<\\/script").replace("<!--", "<\\!--").replace("]]>", "]]\\>")


def _voice_from_rel(rel: str) -> bool:
    """وویس بودن از پسوند فایل صوتی تشخیص داده می‌شود."""
    return rel.lower().endswith(VOICE_EXTS)


# --------------------------------------------------------------------------
# رکورد کوتاه پیام (داخل chunk ها) + تخمین ارتفاع
# --------------------------------------------------------------------------
def _pack_hint(hint: int) -> str:
    """بسته‌بندی تخمین ارتفاع به دو کاراکتر base36 (مقدار ۳۰ تا ۳۰۰)."""
    v = max(0, min(300, int(hint or 0))) - 30
    return _B36[v // 36] + _B36[v % 36]


def _height_hint_rec(r: dict) -> int:
    """تخمین ارتفاع ردیف از روی رکورد کوتاه (برای اسکرول قبل از اندازه‌گیری)."""
    if r.get("svc"):
        return 34
    reply_extra = 55 if r.get("rp") else 0  # reply preview block (generous estimate)
    M = 10  # margin-bottom allowance
    mt = r.get("mt")
    if mt == "photo":
        return 300 + reply_extra + M
    if mt == "video":
        return 260 + reply_extra + M
    if mt == "audio":
        return 86 + reply_extra + M
    if mt == "sticker":
        return 150 + reply_extra + M
    if mt == "document":
        return 70 + reply_extra + M
    n = len(r.get("t") or "")
    if n > 400:
        return 170 + reply_extra + M
    if n > 180:
        return 120 + reply_extra + M
    if n > 80:
        return 95 + reply_extra + M
    return 78 + reply_extra + M


def _record_for(rec: dict, id_map: dict | None = None) -> dict | None:
    """تبدیل رکورد پیام به رکورد کوتاه برای داخل chunk.
    HTML ردیف سمت مرورگر ساخته می‌شود (app.js) تا حجم داده پایین بماند.
    اگر reply_to دارد، پیش‌نمایش reply (نام/متن/نوع رسانه) هم همینجا ذخیره می‌شود
    تا در اپ حتی اگر chunk مقصد هنوز لود نشده، پیش‌نمایش درست نشان داده شود
    و نیازی به جستجوی همه chunk ها نباشد.
    """
    try:
        mid = int(rec.get("id"))
    except (TypeError, ValueError):
        return None
    r: dict = {
        "i": mid,
        "d": rec.get("date") or "",
        "out": 1 if rec.get("out") else 0,
        "svc": 1 if rec.get("service") else 0,
        "t": rec.get("text") or "",
    }
    rt = rec.get("reply_to")
    if rt is not None:
        try:
            r["rp"] = int(rt)
        except Exception:
            pass
        # پیش‌نمایش reply — اگر id_map داریم (برای اینکه نیازی به لود chunk مقصد نباشد)
        if id_map is not None:
            try:
                target = id_map.get(int(rt))
                if target:
                    tsn = (target.get("sender_name") or "").strip()
                    if tsn:
                        r["rs"] = tsn[:24]
                    tsi = target.get("sender_id")
                    if tsi is not None:
                        try:
                            r["rsi"] = int(tsi)
                        except Exception:
                            pass
                    tt = (target.get("text") or "").strip().replace("\n", " ").replace("\r", " ")[:80]
                    if tt:
                        r["rt"] = tt
                    tmt = target.get("media_type")
                    if tmt:
                        r["rm"] = tmt
            except Exception:
                pass
    sid = rec.get("sender_id")
    if sid is not None:
        r["sid"] = sid
    sn = rec.get("sender_name") or ""
    if sn:
        r["sn"] = sn
    media = rec.get("media")
    mt = rec.get("media_type")
    if media:
        r["mt"] = mt or "document"
        r["m"] = media.replace("\\", "/")
        if mt == "audio" and _voice_from_rel(media.replace("\\", "/")):
            r["v"] = 1
    return r


# --------------------------------------------------------------------------
# صفحهٔ یک چت — نگارش جریان‌ی + chunk بندی (بدون ساخت رشتهٔ غول‌آسا در رم)
# --------------------------------------------------------------------------
def generate_chat_page(chat_dir: Path, export_root: Path) -> dict:
    info = load_chat_info(chat_dir) or {}
    title = info.get("title", chat_dir.name)
    out = chat_dir / "index.html"
    back = "../../index.html"

    media_count = 0
    text_count = 0
    msg_count = 0
    first_date = last_date = None
    seen_days: set[str] = set()

    data_dir = chat_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # پاک‌سازی chunk های قدیمی (مثلاً از خروجی قبلی با تعداد/سایز متفاوت)
    for old in data_dir.glob("c*.js"):
        try:
            old.unlink()
        except OSError:
            pass

    chunk_idx = 0
    current_chunk: list = []
    est_parts: list[str] = []

    def flush_chunk() -> None:
        nonlocal chunk_idx, current_chunk
        if not current_chunk:
            return
        fname = f"c{chunk_idx:05d}.js"
        body = (
            "window.__tg_chunk("
            + str(chunk_idx)
            + ","
            + json.dumps(current_chunk, ensure_ascii=False)
            + ");\n"
        )
        (data_dir / fname).write_text(_sanitize_script(body), encoding="utf-8")
        chunk_idx += 1
        current_chunk = []

    def push_entry(entry: dict, hint: int) -> None:
        current_chunk.append(entry)
        est_parts.append(_pack_hint(hint))
        if len(current_chunk) >= CHUNK_SIZE:
            flush_chunk()

    fh = open(out, "w", encoding="utf-8")
    try:
        fh.write(HEAD_TEMPLATE.format(title=escape(title), back=back))

        # برای پیش‌نمایش reply، یک بار همه رکوردها را جمع کن (تا تصویر reply به عکس هم درست نشان داده شود حتی اگر chunk مقصد هنوز لود نشده)
        all_recs = list(iter_records(chat_dir))
        id_map = {}
        for _r in all_recs:
            try:
                _id = int(_r.get("id"))
                id_map[_id] = _r
            except Exception:
                pass

        for rec in all_recs:
            iso = rec.get("date") or ""
            if iso:
                day = format_jalali(iso)
                if day not in seen_days:
                    seen_days.add(day)
                    push_entry({"dy": day}, 44)
                first_date = first_date or iso
                last_date = iso

            media = rec.get("media")
            media_type = rec.get("media_type")
            text = rec.get("text") or ""
            if media:
                media_count += 1
            elif text:
                text_count += 1

            entry = _record_for(rec, id_map)
            if entry is None:
                continue
            msg_count += 1
            push_entry(entry, _height_hint_rec(entry))

        flush_chunk()

        meta = {
            "title": title,
            "count": msg_count,
            "media": media_count,
            "text": text_count,
        }
        chunk_meta = {
            "size": CHUNK_SIZE,
            "count": chunk_idx,
            "url": "data/c",
            "est": "".join(est_parts),
        }
        fh.write("\n<script id=\"chat-data\">\n")
        fh.write("window.CHAT_META = " + json.dumps(meta, ensure_ascii=False) + ";\n")
        fh.write("window.CHUNK_META = " + json.dumps(chunk_meta, ensure_ascii=False) + ";\n")
        fh.write("</script>\n")
        fh.write(FOOT_TEMPLATE)
    finally:
        fh.close()

    return {
        "title": title,
        "messages": msg_count,
        "media": media_count,
        "first_date": first_date,
        "last_date": last_date,
    }


def _count_messages(chat_dir: Path) -> int:
    info = load_chat_info(chat_dir)
    if info and info.get("message_count"):
        return int(info["message_count"])
    n = 0
    for _ in iter_records(chat_dir):
        n += 1
    return n


# --------------------------------------------------------------------------
# index.html — لیست چت‌ها
# --------------------------------------------------------------------------
def generate_index(export_root: Path) -> list[dict]:
    chats_dir = export_root / CHATS_DIR
    chats = []
    if chats_dir.exists():
        for sub in sorted(chats_dir.iterdir()):
            if not sub.is_dir():
                continue
            info = load_chat_info(sub)
            if not info:
                continue
            msgs = _count_messages(sub)
            chats.append(
                {
                    "title": info.get("title", sub.name),
                    "href": f"{CHATS_DIR}/{sub.name}/index.html",
                    "count": msgs,
                    "color": sender_color(info.get("id")),
                }
            )

    cards = []
    for c in chats:
        cards.append(
            f'<a class="chat-card" href="{escape(c["href"])}">'
            f'<div class="avatar" style="background:{c["color"]}">{escape(initial(c["title"]))}</div>'
            f'<div class="meta"><div class="name">{escape(c["title"])}</div>'
            f'<div class="sub">{c["count"]} پیام</div></div>'
            f'</a>'
        )

    page = INDEX_TEMPLATE.format(
        total=len(chats),
        cards="\n".join(cards) or '<div class="empty">هنوز چتی خروجی نگرفته است.</div>',
    )
    (export_root / "index.html").write_text(page, encoding="utf-8")
    return chats


def initial(title: str) -> str:
    t = (title or "").strip()
    return t[0] if t else "؟"


def ensure_assets(export_root: Path) -> None:
    assets = export_root / ASSETS_DIR
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "style.css").write_text(CSS, encoding="utf-8")
    (assets / "app.js").write_text(JS, encoding="utf-8")


# --------------------------------------------------------------------------
# خروجی تک‌کانال برای ساخت اپ اندروید (فقط همان کانال در اپ ظاهر می‌شود)
# --------------------------------------------------------------------------
def _hardlink_or_copy_tree(src: Path, dst: Path) -> None:
    """کپی درخت — با hard link (سریع، بدون مصرف دوبارهٔ دیسک) و fallback به کپی واقعی."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        s = src / item.name
        d = dst / item.name
        if s.is_dir():
            _hardlink_or_copy_tree(s, d)
        elif s.is_file():
            try:
                os_link(s, d)
            except OSError:
                try:
                    shutil.copy2(s, d)
                except OSError:
                    pass


def os_link(src: Path, dst: Path) -> None:
    import os

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    os.link(str(src), str(dst))


def make_single_chat_export(account_root: Path, chat_title: str) -> Path:
    """از پوشهٔ حساب، فقط یک چت را به‌صورت خروجی مستقل می‌سازد (برای APK).
    برمی‌گرداند پوشهٔ جدید که فقط همان کانال/گروه را دارد. تمیزکردنش با caller.
    """
    chat_name = sanitize_name(chat_title)
    src_chat = account_root / CHATS_DIR / chat_name
    if not src_chat.exists():
        # جستجوی نرم: اگر عنوان فاصله/نویسهٔ دیگری داشت
        matches = []
        cd = account_root / CHATS_DIR
        if cd.exists():
            for sub in cd.iterdir():
                if sub.is_dir() and load_chat_info(sub).get("title") == chat_title:
                    matches.append(sub)
        if len(matches) == 1:
            src_chat = matches[0]
            chat_name = src_chat.name
        elif len(matches) == 0 and chat_title.strip() == "":
            # بدون انتخاب: اگر فقط یک چت وجود دارد، همان را بردار
            all_chats = [s for s in cd.iterdir() if s.is_dir()] if cd and cd.exists() else []
            if len(all_chats) == 1:
                src_chat = all_chats[0]
                chat_name = src_chat.name
                info = load_chat_info(src_chat) or {}
                chat_title = info.get("title", src_chat.name)
            else:
                raise RuntimeError("چتی انتخاب نشده است.")
        else:
            raise RuntimeError(f"چت «{chat_title}» در خروجی پیدا نشد.")

    root = Path(tempfile.mkdtemp(prefix="tg_single_"))
    ensure_assets(root)
    dst_chat = root / CHATS_DIR / chat_name
    _hardlink_or_copy_tree(src_chat, dst_chat)
    # اجرای دوبارهٔ صفحه با موتور جدید (دادهٔ تعبیه‌شدهٔ تازه)
    generate_chat_page(dst_chat, root)
    # index.html → ریدایرکت مستقیم به همین یک چت
    (root / "index.html").write_text(
        SINGLE_INDEX_TEMPLATE.format(title=escape(chat_title), href=f"{CHATS_DIR}/{chat_name}/index.html"),
        encoding="utf-8",
    )
    return root


# --------------------------------------------------------------------------
# قالب‌ها
# --------------------------------------------------------------------------
INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>آرشیو تلگرام</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="top">
  <h1>آرشیو تلگرام</h1>
  <span class="sub">{total} چت</span>
  <input id="search" type="search" placeholder="جستجوی چت…">
</header>
<main id="chat-list">
{cards}
</main>
<script src="assets/app.js"></script>
</body>
</html>
"""

HEAD_TEMPLATE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{title} — آرشیو تلگرام</title>
<link rel="stylesheet" href="../../assets/style.css">
</head>
<body>
<header class="top chat-top">
  <a class="back" href="{back}" title="بازگشت">‹</a>
  <h1>{title}</h1>
  <span class="sub" id="posInfo"></span>
  <div class="header-actions">
    <button id="btnFirst" class="jump" title="اولین پیام">⏮ اولین</button>
    <button id="btnLast" class="jump" title="آخرین پیام">آخرین ⏭</button>
    <button id="btnSpeed" class="jump" title="سرعت پخش صدا/ویدیو">۱×</button>
  </div>
  <input id="search" type="search" placeholder="جستجو در پیام‌ها…">
</header>
<main id="history">
  <div id="padTop"></div>
  <div id="msgView"></div>
  <div id="padBottom"></div>
</main>
<div id="searchPanel" class="hidden"></div>
<!-- پخش‌کنندهٔ مشترک ویس/صوت: با لود تدریجی (preload=none) تا چیزی از قبل لود نشود -->
<audio id="player" preload="none"></audio>
<div id="lightbox" class="hidden">
  <div id="lbStage"><img id="lbImg" alt=""></div>
  <div id="lbTools">
    <button id="lbZoomOut" title="کوچک‌کردن">−</button>
    <span id="lbZoomVal">100%</span>
    <button id="lbZoomIn" title="بزرگ‌کردن">+</button>
    <button id="lbFit" title="اندازهٔ اصلی">⌖</button>
    <button id="lbClose" title="بستن">✕</button>
  </div>
</div>
"""

FOOT_TEMPLATE = """<script src="../../assets/app.js"></script>
</body>
</html>
"""

SINGLE_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{title}</title>
<script>location.replace('{href}');</script>
</head>
<body>
<p style="padding:40px;text-align:center;font-family:sans-serif">
  در حال باز کردن… <br><a href="{href}" style="color:#3390ec">ورود به «{title}»</a>
</p>
</body>
</html>
"""

CSS = """/* آرشیو تلگرام — تم تیره */
:root {
  --bg: #0e1621;
  --panel: #17212b;
  --bubble-in: #182533;
  --bubble-out: #2b5278;
  --text: #e6edf3;
  --muted: #8a98a5;
  --accent: #3390ec;
  --border: #232e3c;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
html {
  /* جلوگیری از زوم دابل‌تپ/پینچ روی پیام‌ها */
  touch-action: manipulation;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}
body {
  background: var(--bg); color: var(--text);
  font-family: "Segoe UI", Vazirmatn, Tahoma, sans-serif;
  min-height: 100vh;
  padding-top: 56px; /* فاصله برای هدر ثابت */
}
.top {
  position: fixed; top: 0; left: 0; right: 0; z-index: 20;
  background: var(--panel); border-bottom: 1px solid var(--border);
  padding: 12px 16px; display: flex; align-items: center; gap: 12px;
  flex-wrap: wrap;
}
.top h1 { font-size: 18px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 30vw; }
.top .sub { color: var(--muted); font-size: 12px; white-space: nowrap; }
.header-actions { display: flex; gap: 6px; -webkit-user-select: none; user-select: none; }
.jump {
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: 16px; padding: 6px 12px; font-size: 12.5px; cursor: pointer;
  white-space: nowrap;
}
.jump:active { background: var(--accent); color: #fff; }
.top input {
  margin-inline-start: auto; background: var(--bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 20px; padding: 8px 14px;
  min-width: 140px; width: 200px; outline: none;
}
.top input:focus { border-color: var(--accent); }
.back {
  color: var(--accent); font-size: 30px; text-decoration: none; line-height: 1;
  padding-inline-end: 4px; user-select: none;
}
/* تاریخچه */
#history { max-width: 760px; margin: 0 auto; padding: 0 14px 40px; position: relative; }
#padTop, #padBottom { width: 100%; }
.day { text-align: center; margin: 16px 0 8px; }
.day span {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 20px; padding: 4px 13px; font-size: 12px; color: var(--muted);
}
.row { display: flex; margin-bottom: 6px; justify-content: flex-start; }
.row.mine { justify-content: flex-end; }
.bubble {
  max-width: 86%; background: var(--bubble-in); border-radius: 14px 14px 14px 4px;
  padding: 7px 11px 5px; position: relative; line-height: 1.55;
  font-size: 14.5px; overflow-wrap: break-word;
}
.row.mine .bubble { background: var(--bubble-out); border-radius: 14px 14px 4px 14px; }
.bubble .from { display: block; font-size: 12.5px; font-weight: 700; margin-bottom: 2px; }
.bubble .text { unicode-bidi: plaintext; white-space: pre-wrap; }
.bubble .text a { color: var(--accent); }
.bubble .time {
  float: inline-end; color: var(--muted); font-size: 11px;
  margin-inline-start: 8px; margin-top: 6px;
}
/* reply preview — خط بالای پیام */
.reply-ref {
  display: flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,.04); border-radius: 6px;
  padding: 4px 8px; margin-bottom: 4px; cursor: pointer;
  border-inline-start: 3px solid var(--accent);
  max-height: 48px; overflow: hidden;
}
.row.mine .reply-ref { background: rgba(0,0,0,.15); }
.reply-ref .rr-name {
  font-size: 11.5px; font-weight: 700; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 90px; flex: none;
}
.reply-ref .rr-text {
  font-size: 12px; color: var(--muted); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0;
  unicode-bidi: plaintext;
}
.reply-ref:active { background: rgba(255,235,59,.20); }
.bubble .photo img { max-width: 100%; max-height: 340px; width: auto; height: auto; object-fit: contain; border-radius: 8px; display: block; margin-top: 4px; cursor: zoom-in; }
.bubble .sticker { width: 130px; }
.bubble .media { max-width: 100%; border-radius: 8px; margin-top: 4px; display: block; }
.bubble>.media { width: 100%; }
.bubble .doc { color: var(--accent); text-decoration: none; display: inline-block; margin-top: 4px; }
.service-row { justify-content: center; }
.bubble.service { background: transparent; border: none; color: var(--muted); font-size: 13px; padding: 2px 0; }
/* index */
#chat-list { max-width: 760px; margin: 24px auto; padding: 0 16px; display: flex; flex-direction: column; gap: 10px; }
.chat-card {
  display: flex; align-items: center; gap: 14px; text-decoration: none;
  background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  padding: 12px 16px; color: var(--text); transition: background .15s;
}
.chat-card:hover { background: #1d2936; }
.avatar {
  width: 46px; height: 46px; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: 700; color: #fff;
}
.chat-card .name { font-size: 15px; font-weight: 600; }
.chat-card .sub { color: var(--muted); font-size: 12.5px; margin-top: 2px; }
.empty { text-align: center; color: var(--muted); padding: 40px 0; }
/* جستجو */
#searchPanel {
  position: fixed; top: 60px; left: 0; right: 0; margin: 0 auto;
  max-width: 720px; background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; z-index: 40; max-height: 70vh; overflow-y: auto;
}
#searchPanel .sr-head { padding: 10px 14px; color: var(--muted); font-size: 12px; border-bottom: 1px solid var(--border); }
.sr-item {
  padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer;
  display: block; text-decoration: none; color: var(--text);
}
.sr-item:hover { background: #1d2936; }
.sr-item .sr-snip { font-size: 13.5px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.sr-item .sr-meta { color: var(--muted); font-size: 11.5px; margin-top: 3px; }
.sr-none { padding: 16px; color: var(--muted); text-align: center; }
/* ویس/صوت — پخش‌کنندهٔ سفارشی (رفع باگ پخش‌کنندهٔ پیش‌فرض اندروید) */
.voice {
  display: flex; align-items: center; gap: 8px;
  background: rgba(255,255,255,.06); border-radius: 14px;
  padding: 6px 10px; margin-top: 4px;
  min-width: 180px; max-width: 100%;
  -webkit-user-select: none; user-select: none;
}
.row.mine .voice { background: rgba(0,0,0,.18); }
.vplay {
  width: 34px; height: 34px; flex: none; border-radius: 50%;
  border: none; background: var(--accent); color: #fff;
  font-size: 13px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  padding: 0;
}
.vplay:active { transform: scale(.94); }
.vseek {
  flex: 1; min-width: 60px; height: 30px;
  -webkit-appearance: none; appearance: none;
  background: transparent; cursor: pointer;
  outline: none;
}
.vseek::-webkit-slider-runnable-track {
  height: 4px; border-radius: 2px;
  background: rgba(255,255,255,.25);
}
.vseek::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--accent); margin-top: -5px;
  transition: transform .1s;
}
.vseek:active::-webkit-slider-thumb { transform: scale(1.3); }
.vseek::-moz-range-track {
  height: 4px; border-radius: 2px;
  background: rgba(255,255,255,.25);
}
.vseek::-moz-range-thumb {
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--accent); border: none;
}
.vseek::-moz-range-progress {
  background: var(--accent);
  border-radius: 2px;
  height: 4px;
}
.voice .vtime { font-size: 11.5px; color: var(--muted); min-width: 34px; text-align: left; direction: ltr; }
.voice.playing .vplay { background: #ff3b30; }
.vnote { color: var(--muted); font-size: 14px; }
/* ویدیو — اصلاً پیش‌لود نمی‌شود؛ فقط با کلیک لود و پخش می‌شود */
.vwrap {
  position: relative; margin-top: 4px; border-radius: 8px; overflow: hidden;
  background: #000; min-height: 150px;
  display: flex; align-items: center; justify-content: center;
}
.vwrap video { width: 100%; max-height: 300px; display: block; background: #000; }
.vwrap .vplay {
  position: absolute; width: 52px; height: 52px; font-size: 20px;
  background: rgba(0,0,0,.55); border: 1px solid rgba(255,255,255,.35);
  transition: opacity .15s;
}
.vwrap.playing .vplay { opacity: 0; pointer-events: none; }
/* لایت‌باکس / زوم عکس */
#lightbox {
  position: fixed; inset: 0; background: rgba(0,0,0,.93); z-index: 100;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  overflow: hidden; touch-action: none;
}
#lbStage { flex: 1; width: 100%; position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; }
#lbImg {
  max-width: 94vw; max-height: 88vh; border-radius: 6px; cursor: grab;
  will-change: transform; transform-origin: 0 0;
  -webkit-user-select: none; user-select: none;
}
#lbImg.dragging { cursor: grabbing; }
#lbTools {
  display: flex; gap: 10px; align-items: center; padding: 10px; color: #fff;
  position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%);
  background: rgba(0,0,0,.5); border-radius: 22px; padding: 8px 14px;
}
#lbTools button { background: #222; color: #fff; border: none; border-radius: 50%; width: 34px; height: 34px; font-size: 16px; cursor: pointer; }
#lbTools span { min-width: 40px; text-align: center; font-size: 12px; }
.hidden { display: none !important; }
@media (max-width: 560px) {
  .bubble { max-width: 92%; }
  .top input { width: 120px; }
  .top h1 { max-width: 26vw; }
  #searchPanel { top: auto; bottom: 0; max-height: 55vh; }
}
"""

JS = """// آرشیو تلگرام — موتور مشاهدهٔ چت (سبک و جریان‌ی برای کانال/گروه‌های سنگین)
// - دادهٔ پیام‌ها در فایل‌های chunk جدا (data/c*.js) است؛ فقط chunk های نزدیک
//   به جای اسکرول لود می‌شود → رم گوشی یک‌دفعه پر نمی‌شود و اپ کرش نمی‌کند
// - فقط یک پنجرهٔ کوچک (چند پیام بالا/پایین) در DOM رندر می‌شود
// - ویس با پخش‌کنندهٔ سفارشی (دکمهٔ پخش همیشه هست؛ باگ پخش‌کنندهٔ پیش‌فرض اندروید)
// - ویدیو اصلاً پیش‌لود نمی‌شود؛ فقط با کلیک روی دکمهٔ پخش لود و پخش می‌شود
// - جستجوی تدریجی، سرعت ۱/۱.۵/۲/۳، اولین/آخرین، حفظ جای اسکرول، زوم عکس
(function () {
  "use strict";
  // جلوگیری از بازگردانی جای اسکرول توسط خود مرورگر (تا فقط ذخیرهٔ خودمان کار کند)
  try { if ('scrollRestoration' in history) history.scrollRestoration = 'manual'; } catch (e) {}

  var Conf = window.CHUNK_META || {};
  var META = window.CHAT_META || {};
  var N = META.count || 0;
  var CH = Conf.size || 250;          // چند پیام در هر chunk
  var totalChunks = Conf.count || 0;  // تعداد chunk ها
  var estStr = Conf.est || '';        // تخمین ارتفاع همهٔ پیام‌ها (فشرده)

  var UP = 30, DOWN = 40;                     // تعداد پیام بالا/پایین — بزرگ شد تا کل صفحه گوشی + بیشتر همیشه لود باشد (فیکس اسکرول خالی)
  var LOWER_GUARD = 10, UPPER_GUARD = 10;     // فاصلهٔ مرز — کمتر رندر الکی، اسکرول روان‌تر

  var hist = document.getElementById('history');
  var msgView = document.getElementById('msgView');
  var padTop = document.getElementById('padTop');
  var padBottom = document.getElementById('padBottom');
  var searchInput = document.getElementById('search');
  var player = document.getElementById('player');

  var loaded = {};    // chunkIndex -> [رکوردهای کوتاه]
  var pending = {};   // chunkIndex -> true
  var heights = new Int32Array(N);  // ارتفاع اندازه‌گیری‌شده (۰ = تخمین)
  var sums = [0];
  var totalH = 0;
  var winStart = -1, winEnd = -1;
  var idxOfId = {};
  var SPEED = 1;
  var searchActive = false;
  var curVoice = null;      // {mid, src, gi} — ویسِ در حال پخش
  var voiceScanFrom = -1;   // پرش به وویس بعدی (برای پخش خودکار)
  var voiceAdvancing = false; // در حال پخش خودکار ویس بعدی (اسکرول ذخیره نشود)

  // ---------- ارتفاع ----------
  function estH(i) {
    var p = i * 2;
    if (p + 2 > estStr.length) return 78;
    var v = parseInt(estStr.substr(p, 2), 36);
    return (isNaN(v) ? 48 : v) + 30;
  }
  function hAt(i) { var m = heights[i]; return m > 0 ? m : estH(i); }
  function rebuildSums() {
    var acc = 0;
    var s = new Float64Array(N + 1);
    for (var i = 0; i < N; i++) { acc += hAt(i); s[i + 1] = acc; }
    sums = s;
    totalH = acc;
  }

  // ---------- chunk ----------
  window.__tg_chunk = function (k, arr) {
    loaded[k] = arr;
    delete pending[k];
    var base = k * CH;
    for (var o = 0; o < arr.length; o++) {
      var e = arr[o];
      if (e && e.i != null) idxOfId[e.i] = base + o;
    }
    if (voiceScanFrom >= 0) advanceVoiceScan();
    if (searchActive) doSearch();
    if (pendingRestoreIdx >= 0) tryRestorePending();
    if (typeof pendingReplyId !== 'undefined' && pendingReplyId) tryJumpToReply(pendingReplyId);
    scheduleRender();
    // بعد از لود هر chunk، رندر دوباره امتحان کن تا reply preview هایی که قبلا "در حال لود" بودند درست شوند
    if (winStart >= 0) { setTimeout(function(){ if (winStart>=0) renderWindow(visibleIndex()); }, 60); }
  };
  function chunkFor(i) { return Math.floor(i / CH); }
  function entryAt(i) {
    var k = chunkFor(i);
    var a = loaded[k];
    return a ? a[i - k * CH] : null;
  }
  function ensureChunk(k) {
    if (k < 0 || k >= totalChunks || loaded[k] || pending[k]) return;
    pending[k] = true;
    var s = document.createElement('script');
    s.src = Conf.url + ('00000' + k).slice(-5) + '.js';
    s.onerror = function () { delete pending[k]; };
    document.head.appendChild(s);
  }
  // همهٔ chunk های بازه [a,b] را بخواه؛ true یعنی همه حاضرند
  function ensureRange(a, b) {
    if (b < a) return true;
    var k0 = chunkFor(Math.max(0, a));
    var k1 = chunkFor(Math.min(N - 1, b));
    var missing = false;
    for (var k = k0; k <= k1; k++) {
      if (!loaded[k]) { ensureChunk(k); missing = true; }
    }
    return !missing;
  }

  // ---------- ابزار متن/HTML ----------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function hasRtl(t) {
    return /[\\u0590-\\u08ff\\u0600-\\u06ff\\ufb1d-\\ufdff\\ufe70-\\ufefc]/.test(t || '');
  }
  function linkify(s) {
    return esc(s).replace(/(https?:\\/\\/[^\\s<>"']+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }
  function color(sid) {
    var pal = ["#ef6c00", "#e53935", "#d81b60", "#8e24aa", "#5e35b1", "#3949ab",
      "#1e88e5", "#00897b", "#43a047", "#7cb342", "#fdd835", "#ff8f00"];
    var n = parseInt(sid, 10);
    if (isNaN(n)) return pal[0];
    return pal[Math.abs(n) % pal.length];
  }
  function timeOf(iso) {
    var m = /T(\\d{1,2}):(\\d{2})/.exec(iso || '');
    return m ? (m[1] + ':' + m[2]) : '';
  }
  function voiceHTML(r) {
    var seekBar = '<input class="vseek" type="range" min="0" max="100" value="0" step="0.1">';
    return '<div class="voice' + (r.v ? '' : ' amusic') + '" data-mid="' + r.i + '" data-src="' + esc(r.m) + '">' +
      '<button class="vplay" type="button" aria-label="پخش">▶</button>' +
      seekBar +
      '<span class="vtime">0:00</span></div>';
  }
  function mediaHTML(r) {
    var m = r.m || '';
    switch (r.mt) {
      case 'photo':
        return '<a class="photo" href="' + esc(m) + '" data-lightbox>' +
          '<img loading="lazy" src="' + esc(m) + '" alt="photo"></a>';
      case 'video':
        // بدون src و preload=none → چیزی از قبل لود نمی‌شود؛ فقط با کلیک
        return '<div class="vwrap" data-mid="' + r.i + '" data-src="' + esc(m) + '">' +
          '<video class="media mv" preload="none" playsinline data-mid="' + r.i + '"></video>' +
          '<button class="vplay" type="button" aria-label="پخش">▶</button></div>';
      case 'audio':
        return voiceHTML(r);
      case 'sticker':
        return '<img class="sticker" loading="lazy" src="' + esc(m) + '" alt="sticker">';
      case 'document':
        return '<a class="doc" href="' + esc(m) + '" download>📄 ' + esc(m.split('/').pop() || m) + '</a>';
      default:
        return '';
    }
  }
  // ---------- جستجوی پیام با id (برای reply) ----------
  function findEntryById(id) {
    for (var k = 0; k < totalChunks; k++) {
      var a = loaded[k];
      if (!a) continue;
      for (var o = 0; o < a.length; o++) {
        if (a[o] && a[o].i === id) return a[o];
      }
    }
    return null;
  }

  function mediaLabel(mt) {
    if (mt === 'photo') return '📷 عکس';
    if (mt === 'video') return '🎥 ویدیو';
    if (mt === 'audio') return '🎤 ویس/صدا';
    if (mt === 'sticker') return '⭐ استیکر';
    if (mt === 'document') return '📄 فایل';
    return '📎 رسانه';
  }
  function replyHTML(r) {
    if (!r.rp) return '';
    // اگر پیش‌نمایش reply در زمان اکسپورت ذخیره شده (rs/rt/rm) — مستقیم استفاده کن، بدون "در حال لود"
    if (r.rs || r.rt || r.rm) {
      var namePart2 = r.rs ? '<span class="rr-name" style="color:' + color(r.rsi) + '">' + esc(r.rs) + '</span>' : '';
      var t2 = r.rt ? esc(r.rt) : '';
      var mp2 = r.rm ? mediaLabel(r.rm) : '';
      var textPart2 = t2 ? (mp2 ? t2 + ' — ' + mp2 : t2) : (mp2 || ('💬 پیام #' + r.rp));
      return '<div class="reply-ref" data-rp="' + r.rp + '">' + namePart2 + '<span class="rr-text">' + textPart2 + '</span></div>';
    }
    var orig = findEntryById(r.rp);
    if (!orig) return '<div class="reply-ref" data-rp="' + r.rp + '">' +
      '<span class="rr-text">💬 پیام #' + r.rp + '</span></div>';
    var namePart = '';
    if (orig.sn) namePart = '<span class="rr-name" style="color:' + color(orig.sid) + '">' + esc(orig.sn) + '</span>';
    var t = (orig.t || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
    var textPart = t ? esc(t) : mediaLabel(orig.mt);
    if (t && orig.mt) textPart += ' — ' + mediaLabel(orig.mt);
    return '<div class="reply-ref" data-rp="' + r.rp + '">' +
      namePart + '<span class="rr-text">' + textPart + '</span></div>';
  }

  function rowHTML(r) {
    if (r.svc) {
      return '<div class="row service-row"><div class="bubble service">' + esc(r.t) + '</div></div>';
    }
    var parts = '';
    parts += replyHTML(r);
    if (!r.out && r.sn) {
      parts += '<span class="from" style="color:' + color(r.sid) + '">' + esc(r.sn) + '</span>';
    }
    if (r.t) parts += '<div class="text" dir="' + (hasRtl(r.t) ? 'rtl' : 'ltr') + '">' + linkify(r.t) + '</div>';
    parts += mediaHTML(r);
    parts += '<span class="time">' + esc(timeOf(r.d)) + '</span>';
    return '<div class="row' + (r.out ? ' mine' : '') + '" data-id="' + r.i + '">' +
      '<div class="bubble">' + parts + '</div></div>';
  }

  // ---------- رندر پنجره‌ای ----------
  var programScrolling = false;  // اسکرول برنامه‌ای — کاربر دخالت نکند
  var userScrolling = false;     // کاربر دارد اسکرول می‌کند — رندر/ذخیره نکن
  var lastScrollTop = 0;         // آخرین جای اسکرول برای تشخیص جهت

  function renderWindow(center) {
    if (N === 0) {
      msgView.innerHTML = '<div class="empty">پیامی در این چت نیست.</div>';
      winStart = 0; winEnd = 0;
      updatePads(0, 0);
      return;
    }
    if (center == null) center = 0;
    var start = Math.max(0, center - UP);
    var end = Math.min(N, center + DOWN);
    if (start === winStart && end === winEnd) return;
    if (!ensureRange(start, end - 1)) return;

    // قبل از رندر، جای اسکرول واقعی را ذخیره کن
    var scrollBefore = getScrollTop();

    var html = '';
    for (var i = start; i < end; i++) {
      var e = entryAt(i);
      if (!e) continue;
      if (e.dy) html += '<div class="day"><span>' + esc(e.dy) + '</span></div>';
      else html += rowHTML(e);
    }
    msgView.innerHTML = html;

    var kids = msgView.children;
    for (var k = 0; k < kids.length && start + k < end; k++) {
      var h = kids[k].offsetHeight || 0;
      if (h > 0) heights[start + k] = h + 6; // +6 for margin-bottom
    }
    rebuildSums();
    winStart = start; winEnd = end;
    updatePads(start, end);
    bindMedia(msgView);

    // اگر اسکرول برنامه‌ای نیست، جای کاربر را حفظ کن
    if (!programScrolling) {
      var scrollAfter = getScrollTop();
      if (Math.abs(scrollAfter - scrollBefore) > 2) {
        scrollToTop(scrollBefore);
      }
    }
  }

  function updatePads(s, e) {
    var above = sums[s] || 0;
    var windowH = msgView.offsetHeight || 0;
    var below = Math.max(0, totalH - above - windowH);
    padTop.style.height = Math.max(0, above) + 'px';
    padBottom.style.height = below + 'px';
  }

  function topY() {
    return hist.getBoundingClientRect().top + getScrollTop();
  }
  function getScrollTop() {
    return window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
  }
  function scrollToTop(y) {
    programScrolling = true;
    var d = document.documentElement, b = document.body;
    if (d.scrollTop !== undefined) d.scrollTop = y;
    if (b.scrollTop !== undefined) b.scrollTop = y;
    try { window.scrollTo(0, y); } catch (e) {}
    // بعد از یک تیک، programScrolling رو خاموش کن
    setTimeout(function () { programScrolling = false; }, 80);
  }

  function visibleIndex() {
    var content = getScrollTop() - topY();
    if (content <= 0) return 0;
    var lo = 0, hi = N;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (sums[mid] <= content) lo = mid + 1; else hi = mid;
    }
    return Math.min(N - 1, Math.max(0, lo - 1));
  }

  function updatePosInfo(idx) {
    var el = document.getElementById('posInfo');
    if (!el) return;
    var pct = N ? Math.round((idx / N) * 100) : 0;
    el.textContent = META.count + ' پیام · ' + (META.media || 0) + ' رسانه · ' + pct + '٪';
  }

  var ticking = false;
  function scheduleRender() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      ticking = false;
      if (N === 0) return;
      var idx = visibleIndex();
      if (winStart < 0 || idx < winStart + LOWER_GUARD || idx >= winEnd - UPPER_GUARD) {
        renderWindow(idx);
      }
      updatePosInfo(idx);
    });
  }
  function onScroll() {
    // اسکرول برنامه‌ای: فقط ذخیره نکن ولی رندر را انجام بده (فیکس خالی ماندن بعد از restore)
    if (programScrolling) { scheduleRender(); return; }
    userScrolling = true;
    clearTimeout(userScrollingTimer);
    userScrollingTimer = setTimeout(function () { userScrolling = false; }, 200);
    scheduleSave();
    scheduleRender();
  }
  var userScrollingTimer = null;

  // ---------- پرش به یک پیام / اولین / آخرین ----------
  function goTo(idx, alignBottom, center) {
    idx = Math.max(0, Math.min(N - 1, Math.round(idx)));
    renderWindow(idx);
    var y = topY() + sums[idx];
    if (center) {
      // پیام در وسط صفحه نمایش داده شود
      var msgH = heights[idx] || estH(idx);
      y = y - window.innerHeight / 2 + msgH / 2;
    }
    if (alignBottom && idx >= N - 1) {
      y = document.body.scrollHeight + 4;
    }
    scrollToTop(Math.max(0, y));
  }

  // ---------- ذخیره / بازیابی جای اسکرول (فیکس: حتی بعد از بستن/باز کردن اپ) ----------
  var saveTimer = null;
  var lastSave = 0;
  var restoreSettling = false;
  var pendingRestoreIdx = -1;
  var pendingRestoreId = null;
  var pendingRestoreY = -1;
  var pendingRestoreOff = 100;
  var restoreTimer = null;
  var pendingReplyId = null;
  var pendingReplyTimer = null;
  function scheduleSave() {
    if (voiceAdvancing) return;
    if (restoreSettling) return;
    if (pendingRestoreIdx >= 0) return;
    if (programScrolling) return;
    var now = Date.now();
    if (now - lastSave < 90) {
      if (!saveTimer) saveTimer = setTimeout(saveNow, 90);
      return;
    }
    saveNow();
  }
  function storageSet(k, v) {
    try { if (typeof AndroidStore !== 'undefined' && AndroidStore.savePos) { AndroidStore.savePos(k, v); } } catch(e){}
    try { localStorage.setItem(k, v); } catch(e){}
    try { sessionStorage.setItem(k, v); } catch(e){}
  }
  function storageGet(k) {
    try { if (typeof AndroidStore !== 'undefined' && AndroidStore.loadPos) { var r = AndroidStore.loadPos(k); if (r) return r; } } catch(e){}
    try { var r = localStorage.getItem(k); if (r) return r; } catch(e){}
    try { var r2 = sessionStorage.getItem(k); if (r2) return r2; } catch(e){}
    return null;
  }
  // اولین پیام قابل‌مشاهده در DOM + فاصله‌اش از بالای ویوپورت (دقیق، مستقل از تخمین ارتفاع)
  function anchorFromDOM() {
    try {
      var rows = msgView.querySelectorAll('.row[data-id]');
      for (var q = 0; q < rows.length; q++) {
        var rc = rows[q].getBoundingClientRect();
        if (rc.bottom > 70 && rc.top < window.innerHeight) {
          return { id: parseInt(rows[q].getAttribute('data-id'), 10), off: rc.top };
        }
      }
    } catch (e) {}
    return null;
  }
  function saveNow() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    try {
      if (N === 0) return;
      if (restoreSettling) return;
      if (pendingRestoreIdx >= 0) return;
      lastSave = Date.now();
      // روش دقیق: انکر از DOM واقعی (نه visibleIndex تخمینی)
      var anchor = anchorFromDOM();
      var idx, eid, off;
      if (anchor && anchor.id != null && !isNaN(anchor.id)) {
        eid = anchor.id;
        off = anchor.off;
        idx = (idxOfId[eid] != null) ? idxOfId[eid] : visibleIndex();
      } else {
        idx = visibleIndex();
        var e = entryAt(idx);
        if (!e && idx >= 0) { setTimeout(saveNow, 120); return; }
        eid = e ? e.i : null;
        var el = e ? msgView.querySelector('[data-id=\"' + e.i + '\"]') : null;
        off = el ? el.getBoundingClientRect().top : 0;
      }
      var y = getScrollTop();
      var payload = JSON.stringify({ i: idx, id: eid, y: y, off: off, t: Date.now() });
      storageSet(commonKey(), payload);
      // ثانیه‌به‌ثانیه: یک کپی هم با کلید عمومی tg_last_pos ذخیره کن تا جاوا onPause بتواند آن را بخواند حتی اگر commonKey عوض شود
      try { storageSet('tg_last_pos', payload); } catch (e) {}
    } catch (e) {}
  }
  function commonKey() {
    return 'tgpos_' + (META.title || location.pathname);
  }
  // بازگردانی دقیق پیکسل‌به‌پیکسل: انکر (id + فاصله از بالای صفحه) — مستقل از تخمین ارتفاع
  function settleToAnchor(targetId, savedOff, tries) {
    if (tries <= 0) {
      restoreSettling = false;
      pendingRestoreIdx = -1; pendingRestoreId = null; pendingRestoreY = -1;
      if (restoreTimer) { clearTimeout(restoreTimer); restoreTimer = null; }
      setTimeout(function () { programScrolling = false; }, 60);
      saveNow();
      return;
    }
    var el = null;
    try { el = msgView.querySelector('[data-id=\"' + targetId + '\"]'); } catch (e) {}
    if (!el) {
      // انکر هنوز در DOM نیست (پنجره جابجا شده؟) → دوباره رندر حول idx واقعی
      var gi = idxOfId[targetId];
      if (gi != null) renderWindow(gi);
      setTimeout(function () { settleToAnchor(targetId, savedOff, tries - 1); }, 160);
      return;
    }
    var rect = el.getBoundingClientRect();
    var delta = rect.top - savedOff;
    if (Math.abs(delta) > 1) scrollToTop(getScrollTop() + delta);
    setTimeout(function () { settleToAnchor(targetId, savedOff, tries - 1); }, 130);
  }
  function tryRestorePending() {
    if (pendingRestoreIdx < 0 && pendingRestoreId == null) return false;
    var targetId = pendingRestoreId;
    var targetY = pendingRestoreY;
    var savedOff = (typeof pendingRestoreOff === 'number') ? pendingRestoreOff : 100;
    // اگر انکر id داریم ولی هنوز chunk آن لود نشده → chunkها را یکی‌یکی لود کن، عجله نکن سراغ i قدیمی
    if (targetId != null && idxOfId[targetId] == null) {
      var allLoaded = true;
      for (var kk = 0; kk < totalChunks; kk++) {
        if (!loaded[kk] && !pending[kk]) { ensureChunk(kk); allLoaded = false; break; }
        if (!loaded[kk]) allLoaded = false;
      }
      if (!allLoaded) {
        if (restoreTimer) clearTimeout(restoreTimer);
        restoreTimer = setTimeout(tryRestorePending, 240);
        return false;
      }
      // همه لود شدند ولی id پیدا نشد (حذف شده) → fallback به i/y
      targetId = null;
    }
    var idx = pendingRestoreIdx;
    if (targetId != null && idxOfId[targetId] != null) idx = idxOfId[targetId];
    if (idx < 0 || idx >= N) { pendingRestoreIdx = -1; pendingRestoreId = null; pendingRestoreY = -1; restoreSettling = false; return false; }
    var start = Math.max(0, idx - UP);
    var end = Math.min(N, idx + DOWN);
    if (!ensureRange(start, end - 1)) {
      if (restoreTimer) clearTimeout(restoreTimer);
      restoreTimer = setTimeout(tryRestorePending, 220);
      return false;
    }
    if (restoreTimer) { clearTimeout(restoreTimer); restoreTimer = null; }
    programScrolling = true;
    restoreSettling = true;
    renderWindow(idx);
    if (targetId != null) {
      // مسیر دقیق: انکر را دقیقاً همان فاصله قبلی از بالای صفحه بگذار
      setTimeout(function () { settleToAnchor(targetId, savedOff, 6); }, 80);
    } else if (targetY >= 0 && targetY <= totalH + 1000) {
      // fallback قدیمی (بدون id): همان y
      setTimeout(function () {
        scrollToTop(targetY);
        setTimeout(function () {
          restoreSettling = false;
          pendingRestoreIdx = -1; pendingRestoreId = null; pendingRestoreY = -1;
          programScrolling = false;
        }, 200);
      }, 70);
    } else {
      goTo(idx, false, true);
      setTimeout(function () {
        restoreSettling = false;
        pendingRestoreIdx = -1; pendingRestoreId = null; pendingRestoreY = -1;
        programScrolling = false;
      }, 200);
    }
    return true;
  }
  function restorePos() {
    try {
      var raw = storageGet(commonKey());
      var bestRaw = raw, bestT = -1;
      try { var o = raw ? JSON.parse(raw) : null; bestT = o && o.t ? o.t : -1; } catch(e){}
      // ثانیه‌به‌ثانیه: tg_last_pos عمومی را هم چک کن و جدیدترین را بردار
      try {
        var raw2 = storageGet("tg_last_pos");
        if (raw2) { var o2 = JSON.parse(raw2); if (o2 && o2.t > bestT) { bestRaw = raw2; bestT = o2.t; } }
      } catch(e){}
      if (!bestRaw) {
        try { var yOnly = storageGet("webview_y"); if (yOnly) { var yNum = parseInt(yOnly, 10); if (!isNaN(yNum)) bestRaw = JSON.stringify({ y: yNum, i: Math.floor((yNum/Math.max(1,totalH))*N), t: Date.now() }); } } catch(e){}
      }
      // fallback webview_y_raw
      if (!bestRaw) { try { bestRaw = storageGet("webview_y_raw"); } catch(e){} }
      if (!bestRaw) {
        try {
          if (typeof AndroidStore !== 'undefined' && AndroidStore.loadPos) {
            var yOnly2 = AndroidStore.loadPos("webview_y");
            if (yOnly2) { var yNum2 = parseInt(yOnly2, 10); if (!isNaN(yNum2)) bestRaw = JSON.stringify({ y: yNum2, i: Math.floor((yNum2/Math.max(1,totalH))*N), t: Date.now() }); }
          }
        } catch(e){}
      }
      raw = bestRaw;
      if (!raw) return false;
      var obj = JSON.parse(raw);
      var idx = -1;
      if (obj.id != null && idxOfId[obj.id] != null) idx = idxOfId[obj.id];
      else if (typeof obj.i === 'number') idx = obj.i;
      else if (typeof obj.y === 'number') idx = Math.max(0, Math.min(N-1, Math.floor((obj.y / Math.max(1, totalH)) * N)));
      else return false;
      if (idx < 0 || idx >= N) return false;
      // حتی idx=0 هم اگر y داریم باید restore کنیم (برای دقت پیکسلی)
      if (idx === 0 && obj.id == null && typeof obj.y !== 'number') return false;
      pendingRestoreIdx = idx;
      pendingRestoreId = obj.id != null ? obj.id : null;
      pendingRestoreY = (typeof obj.y === 'number') ? obj.y : -1;
      pendingRestoreOff = (typeof obj.off === 'number') ? obj.off : 100;
      return tryRestorePending();
    } catch (e) {}
    return false;
  }
  // ذخیره ثانیه‌به‌ثانیه (دقیقا هر 1000ms) + realtime روی هر حرکت
  try {
    document.addEventListener('visibilitychange', function(){ if (document.hidden) saveNow(); else scheduleSave(); });
    window.addEventListener('pagehide', saveNow);
    window.addEventListener('beforeunload', saveNow);
    window.addEventListener('blur', saveNow);
    // هر 1000ms = دقیقا ثانیه‌به‌ثانیه
    setInterval(function(){ if (!programScrolling && !restoreSettling && pendingRestoreIdx < 0) saveNow(); }, 1000);
    // علاوه بر ثانیه‌ای، روی هر پایان اسکرول لمسی هم 80ms بعد ذخیره کن
    document.addEventListener('touchend', function(){ setTimeout(saveNow, 80); }, {passive:true});
    document.addEventListener('mouseup', function(){ setTimeout(saveNow, 80); });
    document.addEventListener('touchcancel', function(){ setTimeout(saveNow, 80); }, {passive:true});
  } catch(e){}

  // ---------- پخش ویس/صوت (پخش‌کنندهٔ مشترک؛ یک صدا هم‌زمان) ----------
  function fmtTime(s) {
    s = Math.floor(s || 0);
    var m = Math.floor(s / 60), sec = s % 60;
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }
  function setVoiceUI() {
    var voices = document.querySelectorAll('.voice');
    for (var i = 0; i < voices.length; i++) {
      var v = voices[i];
      var bt = v.querySelector('.vplay');
      if (!bt) continue;
      var on = curVoice && curVoice.mid === parseInt(v.getAttribute('data-mid'), 10);
      var playing = on && !player.paused;
      bt.textContent = playing ? '❚❚' : '▶';
      if (playing) v.classList.add('playing'); else v.classList.remove('playing');
    }
  }
  function pauseVoice() {
    if (player && !player.paused) player.pause();
  }
  var userSeeking = false;
  function playVoice(mid, src, gi) {
    // هر ویدیوی در حال پخش را نگه دار
    var vids = msgView.querySelectorAll('video');
    for (var i = 0; i < vids.length; i++) { try { vids[i].pause(); } catch (e) {} }
    // کلیک روی همان ویسِ در حال پخش → توقف
    if (curVoice && curVoice.mid === mid && !player.paused) {
      player.pause();
      setVoiceUI();
      return;
    }
    curVoice = { mid: mid, src: src, gi: gi };
    player.setAttribute('data-src', src);
    player.src = src;
    player.playbackRate = SPEED;
    var p = player.play();
    if (p && p.catch) p.catch(function () {});
    setVoiceUI();
    player.ontimeupdate = function () {
      var wrap = document.querySelector('.voice[data-mid="' + mid + '"]');
      if (!wrap) return;
      var t = wrap.querySelector('.vtime');
      if (t) t.textContent = fmtTime(player.currentTime);
      var seek = wrap.querySelector('.vseek');
      if (seek && !userSeeking && player.duration) {
        seek.value = (player.currentTime / player.duration) * 100;
      }
    };
  }
  player.onended = function () {
    var cv = curVoice;
    curVoice = null;
    setVoiceUI();
    if (!cv) return;
    if (player.getAttribute('data-src') !== cv.src) return; // صدا عوض شده؛ کاری نکن
    voiceAdvancing = true;
    voiceScanFrom = cv.gi + 1;
    advanceVoiceScan();
  };
  player.onpause = function () { setVoiceUI(); };
  // پیدا کردن و پخش وویس بعدی (chunk به chunk — بدون لود همه)
  function advanceVoiceScan() {
    var j = voiceScanFrom;
    if (j < 0 || j >= N) { voiceScanFrom = -1; return; }
    while (j < N) {
      var r = entryAt(j);
      if (!r) { ensureChunk(chunkFor(j)); return; }
      if (r.v) {
        voiceScanFrom = -1;
        playVoiceAt(j);
        return;
      }
      j++;
    }
    voiceScanFrom = -1;
  }
  function playVoiceAt(gi) {
    var r = entryAt(gi);
    if (!r) return;
    // فقط chunk لازم رو لود کن، اسکرول کاربر رو تغییر نده
    ensureChunk(chunkFor(gi));
    var tries = 0;
    var t = setInterval(function () {
      tries++;
      var v = msgView.querySelector('.voice[data-mid="' + r.i + '"]');
      if (v) {
        clearInterval(t);
        voiceAdvancing = false;
        playVoice(r.i, v.getAttribute('data-src'), gi);
        return;
      }
      // اگر ویس در DOM نیست (خارج از پنجره)، بخش کوچکی اسکرول کن
      if (tries === 5) {
        renderWindow(gi);
        var y = topY() + (sums[gi] || 0);
        scrollToTop(Math.max(0, y - 50));
      }
      if (tries > 25) clearInterval(t);
    }, 100);
  }

  // ---------- پخش ویدیو (فقط با کلیک لود می‌شود) ----------
  function playVideo(wrap) {
    var video = wrap.querySelector('video');
    if (!video) return;
    pauseVoice();
    if (video.getAttribute('data-loaded')) {
      if (video.paused) {
        var p = video.play();
        if (p && p.catch) p.catch(function () {});
        wrap.classList.add('playing');
      } else {
        video.pause();
        wrap.classList.remove('playing');
      }
      return;
    }
    video.setAttribute('data-loaded', '1');
    video.src = wrap.getAttribute('data-src');
    video.load();
    video.controls = true;
    video.playbackRate = SPEED;
    var p2 = video.play();
    if (p2 && p2.catch) p2.catch(function () {});
    wrap.classList.add('playing');
  }

  function bindMedia(root) {
    var vids = root.querySelectorAll('video');
    for (var i = 0; i < vids.length; i++) {
      var v = vids[i];
      if (v._bound) continue;
      v._bound = true;
      v.addEventListener('play', function () { this.playbackRate = SPEED; });
      v.addEventListener('ended', function () {
        var w = this.closest('.vwrap');
        if (w) w.classList.remove('playing');
      });
    }
  }

  // ---------- سرعت پخش ----------
  var speeds = [1, 1.5, 2, 3];
  var speedBtn = document.getElementById('btnSpeed');
  function setSpeed(s) {
    SPEED = s;
    if (speedBtn) speedBtn.textContent = s + '×';
    if (player) player.playbackRate = s;
    var vids = msgView.querySelectorAll('video');
    for (var i = 0; i < vids.length; i++) vids[i].playbackRate = s;
  }
  if (speedBtn) {
    speedBtn.addEventListener('click', function () {
      var i = speeds.indexOf(SPEED);
      setSpeed(speeds[(i + 1) % speeds.length]);
    });
  }

  // ---------- اولین / آخرین پیام ----------
  var btnFirst = document.getElementById('btnFirst');
  if (btnFirst) btnFirst.addEventListener('click', function () { goTo(0); });
  var btnLast = document.getElementById('btnLast');
  if (btnLast) btnLast.addEventListener('click', function () {
    // رندر آخرین پیام‌ها + اسکرول به انتها
    programScrolling = true;
    renderWindow(N - 1);
    // صبر کن تا pad ها اعمال شوند بعد اسکرول کن
    requestAnimationFrame(function () {
      scrollToTop(document.body.scrollHeight + 4);
    });
  });

  // ---------- جستجو (تدریجی روی chunk های لودشده) ----------
  var panel = document.getElementById('searchPanel');
  var sbTimer = null;
  function doSearch() {
    var q = (searchInput && searchInput.value || '').trim().toLowerCase();
    if (!q) {
      searchActive = false;
      if (panel) panel.classList.add('hidden');
      return;
    }
    searchActive = true;
    var results = [];
    var LIMIT = 120;
    var scannedAll = true;
    for (var k = 0; k < totalChunks; k++) {
      var a = loaded[k];
      if (!a) { scannedAll = false; continue; }
      for (var o = 0; o < a.length; o++) {
        var r = a[o];
        if (r && r.i != null && r.t && r.t.toLowerCase().indexOf(q) !== -1) {
          results.push(k * CH + o);
          if (results.length >= LIMIT) break;
        }
      }
      if (results.length >= LIMIT) break;
    }
    if (!panel) return;
    panel.innerHTML = '';
    var head = document.createElement('div');
    head.className = 'sr-head';
    head.textContent = results.length + ' پیام یافت شد'
      + (results.length >= LIMIT ? ' (نمایش ' + LIMIT + ' مورد)' : '')
      + (scannedAll ? '' : ' — در حال جستجو…');
    panel.appendChild(head);
    if (results.length === 0) {
      var none = document.createElement('div');
      none.className = 'sr-none';
      none.textContent = scannedAll ? 'پیامی پیدا نشد.' : 'در حال جستجو…';
      panel.appendChild(none);
    } else {
      for (var x = 0; x < results.length; x++) {
        var gi = results[x];
        var r2 = entryAt(gi);
        if (!r2) continue;
        var a = document.createElement('a');
        a.className = 'sr-item';
        a.href = '#';
        var one = r2.t.replace(/\\s+/g, ' ').trim();
        var snip = document.createElement('div');
        snip.className = 'sr-snip';
        snip.textContent = one.slice(0, 120) + (one.length > 120 ? '…' : '');
        var meta = document.createElement('div');
        meta.className = 'sr-meta';
        meta.textContent = 'پیام #' + r2.i;
        a.appendChild(snip); a.appendChild(meta);
        (function (idx) {
          a.addEventListener('click', function (ev) {
            ev.preventDefault();
            searchActive = false;
            if (panel) panel.classList.add('hidden');
            goTo(idx);
          });
        })(gi);
        panel.appendChild(a);
      }
    }
    panel.classList.remove('hidden');
    // chunk های باقی‌مانده را یکی‌یکی لود کن تا جستجو کامل شود
    if (!scannedAll && results.length < LIMIT) {
      var next = -1;
      for (var kk = 0; kk < totalChunks; kk++) {
        if (!loaded[kk] && !pending[kk]) { next = kk; break; }
      }
      if (next >= 0) ensureChunk(next);
    }
  }
  if (searchInput) {
    searchInput.addEventListener('input', function () {
      if (sbTimer) clearTimeout(sbTimer);
      sbTimer = setTimeout(doSearch, 130);
    });
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); doSearch(); }
    });
  }
  document.addEventListener('click', function (e) {
    if (panel && !panel.classList.contains('hidden') && panel.contains(e.target) === false &&
        searchInput && searchInput.contains(e.target) === false) {
      panel.classList.add('hidden');
      searchActive = false;
    }
  });

  // ---------- کلیک روی reply → پرش به پیام اصلی (فیکس: حتی اگر chunk هنوز لود نشده) ----------
  function tryJumpToReply(rpId) {
    // اگر idx معلوم است مستقیم برو
    if (rpId && idxOfId[rpId] != null) {
      pendingReplyId = null;
      if (pendingReplyTimer) { clearTimeout(pendingReplyTimer); pendingReplyTimer = null; }
      var gi = idxOfId[rpId];
      goTo(gi, false, true);
      setTimeout(function () {
        var el = msgView.querySelector('[data-id="' + rpId + '"]');
        if (el) {
          el.style.transition = 'background .15s';
          el.style.background = 'rgba(255,235,59,.30)';
          setTimeout(function () { el.style.background = ''; }, 1200);
        }
      }, 160);
      return true;
    }
    // هنوز لود نشده — همه chunk های لودنشده را یکی‌یکی لود کن
    var found = false;
    // اول ببین در chunk های لودشده هست ولی idxOfId هنوز نساخته؟ (نباید)
    var orig = findEntryById(rpId);
    if (orig) {
      // پیدا شد ولی idxOfId ندارد → یعنی باگ، index را حدس بزن via scan
      for (var k2 = 0; k2 < totalChunks; k2++) {
        var a2 = loaded[k2];
        if (!a2) continue;
        for (var o2 = 0; o2 < a2.length; o2++) if (a2[o2] && a2[o2].i === rpId) {
          pendingReplyId = null;
          goTo(k2 * CH + o2, false, true);
          return true;
        }
      }
    }
    // هیچ کدام لود نشده — بعدی را لود کن
    for (var kk = 0; kk < totalChunks; kk++) {
      if (!loaded[kk] && !pending[kk]) {
        ensureChunk(kk);
        pendingReplyId = rpId;
        if (pendingReplyTimer) clearTimeout(pendingReplyTimer);
        pendingReplyTimer = setTimeout(function(){ tryJumpToReply(pendingReplyId); }, 300);
        // پیام کاربر
        var info = document.getElementById('posInfo');
        if (info) info.textContent = 'در حال لود پیام #' + rpId + '…';
        return false;
      }
    }
    // همه chunk ها لود شدند ولی پیدا نشد → پیام حذف شده
    pendingReplyId = null;
    return false;
  }
  hist.addEventListener('click', function (e) {
    var rr = e.target && e.target.closest ? e.target.closest('.reply-ref') : null;
    if (rr) {
      e.preventDefault(); e.stopPropagation();
      var rpId = parseInt(rr.getAttribute('data-rp'), 10);
      if (!rpId) return;
      tryJumpToReply(rpId);
      return;
    }

  // ---------- کلیک روی رسانه (event delegation) ----------
    var photo = e.target && e.target.closest ? e.target.closest('[data-lightbox]') : null;
    if (photo) {
      e.preventDefault();
      showLb(photo.getAttribute('href'));
      return;
    }
    var vw = e.target && e.target.closest ? e.target.closest('.vwrap') : null;
    if (vw) {
      var video = vw.querySelector('video');
      // وقتی کنترل‌های خود ویدیو فعال است، دخالت نکن (کلیک روی نوار کنترل)
      if (video && e.target === video && video.getAttribute('data-loaded')) return;
      playVideo(vw);
      return;
    }
    var vo = e.target && e.target.closest ? e.target.closest('.voice') : null;
    if (vo) {
      // اگر روی نوار seek کلیک شده، فقط play کن (seek خودش کار میکنه)
      if (e.target.classList && e.target.classList.contains('vseek')) return;
      var mid = parseInt(vo.getAttribute('data-mid'), 10);
      var gi = idxOfId[mid] != null ? idxOfId[mid] : -1;
      playVoice(mid, vo.getAttribute('data-src'), gi);
      // هایلایت کوتاه کارت پیام ویس
      setTimeout(function () {
        var cel = msgView.querySelector('[data-id="' + mid + '"]');
        if (cel) {
          cel.style.transition = 'background .15s';
          cel.style.background = 'rgba(255,235,59,.30)';
          setTimeout(function () { cel.style.background = ''; }, 1200);
        }
      }, 120);
      return;
    }
  });

  // ---------- نوار seek ویس (drag/seek مانند تلگرام) ----------
  hist.addEventListener('input', function (e) {
    if (!e.target.classList || !e.target.classList.contains('vseek')) return;
    var wrap = e.target.closest('.voice');
    if (!wrap) return;
    var mid = parseInt(wrap.getAttribute('data-mid'), 10);
    var pct = parseFloat(e.target.value);
    // اگر ویس دیگه‌ای داره پخش میشه، اول اون رو عوض کن
    if (!curVoice || curVoice.mid !== mid) {
      var src = wrap.getAttribute('data-src');
      var gi = idxOfId[mid] != null ? idxOfId[mid] : -1;
      playVoice(mid, src, gi);
    }
    if (player.duration) {
      player.currentTime = (pct / 100) * player.duration;
      var t = wrap.querySelector('.vtime');
      if (t) t.textContent = fmtTime(player.currentTime);
    }
  });
  hist.addEventListener('mousedown', function (e) {
    if (e.target.classList && e.target.classList.contains('vseek')) userSeeking = true;
  });
  hist.addEventListener('touchstart', function (e) {
    if (e.target.classList && e.target.classList.contains('vseek')) userSeeking = true;
  }, {passive: true});
  hist.addEventListener('change', function (e) {
    if (e.target.classList && e.target.classList.contains('vseek')) {
      userSeeking = false;
    }
  });

  // ---------- زوم عکس (لایت‌باکس) ----------
  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lbImg');
  var lbZoomVal = document.getElementById('lbZoomVal');
  var scale = 1, baseW = 0, baseH = 0, ox = 0, oy = 0;
  var dragging = false, sx = 0, sy = 0, sox = 0, soy = 0;
  var pinchD = 0, pinchScale = 1;

  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function applyLb() {
    var vw = window.innerWidth, vh = window.innerHeight;
    var showW = (baseW || vw) * scale, showH = (baseH || vh) * scale;
    var maxX = Math.max(0, (showW - vw) / 2);
    var maxY = Math.max(0, (showH - vh) / 2);
    ox = clamp(ox, -maxX, maxX);
    oy = clamp(oy, -maxY, maxY);
    lbImg.style.transform = 'translate(' + ox + 'px,' + oy + 'px) scale(' + scale + ')';
    if (lbZoomVal) lbZoomVal.textContent = Math.round(scale * 100) + '%';
  }
  function setScale(s) { scale = clamp(s, 1, 8); applyLb(); }
  function showLb(src) {
    lb.classList.remove('hidden');
    lbImg.src = src;
    baseW = lbImg.naturalWidth; baseH = lbImg.naturalHeight;
    scale = 1; ox = 0; oy = 0; pinchScale = 1;
    lbImg.onload = function () { baseW = lbImg.naturalWidth; baseH = lbImg.naturalHeight; applyLb(); };
    if (lbImg.complete && lbImg.naturalWidth) { baseW = lbImg.naturalWidth; baseH = lbImg.naturalHeight; }
    applyLb();
  }
  function hideLb() { lb.classList.add('hidden'); lbImg.onload = null; }
  function fitLb() { baseW = lbImg.naturalWidth || baseW; baseH = lbImg.naturalHeight || baseH; scale = 1; ox = 0; oy = 0; applyLb(); }

  if (lb) {
    lb.addEventListener('wheel', function (e) { e.preventDefault(); setScale(scale * (e.deltaY < 0 ? 1.15 : 0.87)); }, { passive: false });
    lbImg.addEventListener('mousedown', function (e) {
      dragging = true; sx = e.clientX; sy = e.clientY; sox = ox; soy = oy;
      lbImg.classList.add('dragging'); e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      ox = sox + (e.clientX - sx); oy = soy + (e.clientY - sy);
      applyLb();
    });
    window.addEventListener('mouseup', function () { dragging = false; lbImg.classList.remove('dragging'); });
    var tLast = 0;
    lbImg.addEventListener('touchstart', function (e) {
      e.preventDefault();
      if (e.touches.length === 2) {
        pinchD = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
        pinchScale = scale;
      } else if (e.touches.length === 1) {
        var now = Date.now();
        if (now - tLast < 280) { setScale(scale > 1 ? 1 : 2); tLast = 0; return; }
        tLast = now;
        dragging = true; sx = e.touches[0].clientX; sy = e.touches[0].clientY; sox = ox; soy = oy;
      }
    }, { passive: false });
    lbImg.addEventListener('touchmove', function (e) {
      e.preventDefault();
      if (e.touches.length === 2) {
        var d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
        if (pinchD) setScale(pinchScale * (d / pinchD));
      } else if (e.touches.length === 1 && dragging && scale > 1) {
        ox = sox + (e.touches[0].clientX - sx); oy = soy + (e.touches[0].clientY - sy);
        applyLb();
      }
    }, { passive: false });
    document.getElementById('lbClose').addEventListener('click', hideLb);
    document.getElementById('lbZoomIn').addEventListener('click', function () { setScale(scale * 1.25); });
    document.getElementById('lbZoomOut').addEventListener('click', function () { setScale(scale * 0.8); });
    document.getElementById('lbFit').addEventListener('click', fitLb);
    lb.addEventListener('click', function (e) { if (e.target === lb) { scale > 1 ? fitLb() : hideLb(); } });
  }

  // ---------- تنظیم سرعت اولیه ----------
  setSpeed(1);

  // ---------- شروع ----------
  if (N === 0) { renderWindow(0); return; }
  rebuildSums();
  if (META.count) updatePosInfo(0);
  // پیش‌لود chunk 0 تا اول ورود خالی نمونه
  if (totalChunks > 0 && !loaded[0]) ensureChunk(0);
  renderWindow(0);
  var restored = restorePos();
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', function () {
    if (lb && !lb.classList.contains('hidden')) applyLb();
    scheduleRender();
  });
  if (!restored) {
    setTimeout(function(){
      if (msgView.children.length === 0) renderWindow(0);
      scheduleRender();
    }, 140);
  } else {
    // اگر restore شد ولی هنوز خالیه (chunk در حال لود) هر 300ms چک کن
    var emptyCheck = setInterval(function(){
      if (msgView.children.length > 0) { clearInterval(emptyCheck); return; }
      if (pendingRestoreIdx >= 0) tryRestorePending();
      else scheduleRender();
    }, 300);
    setTimeout(function(){ clearInterval(emptyCheck); }, 5000);
  }
  // fallback نهایی: اگر بعد از 800ms هنوز خالی بود، رندر اجباری
  setTimeout(function(){
    if (msgView.children.length === 0 && N>0) {
      renderWindow(visibleIndex());
      scheduleRender();
    }
  }, 850);
})();
"""
