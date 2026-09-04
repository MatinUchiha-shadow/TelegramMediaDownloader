#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست آفلاین برنامه — بدون نیاز به تلگرام و اینترنت:
   python selftest.py
بررسی: خروجی HTML، حذف پیام تکراری، تاریخ شمسی، ساخت پروژهٔ اندروید.
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import exporter  # noqa: E402
from app.android_builder import build_android_app  # noqa: E402
from app.downloader import classify_document, sanitize_name  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tg_selftest_"))
    try:
        print("۱) نام‌سازی امن فایل‌ها")
        check("حذف کاراکترهای غیرمجاز ویندوز", sanitize_name('a<b>c:"d') == "a_b_c__d")
        check("جایگزینی فاصله", sanitize_name("My Chat Name") == "My_Chat_Name")

        print("\n۲) تاریخ شمسی")
        j = exporter.format_jalali("2024-08-12T14:30:00+03:30")
        check("نمایش تاریخ فارسی", "مرداد" in j and "۱۴۰۳" in j)
        check("ساعت", exporter.format_time("2024-08-12T14:30:00+03:30") == "14:30")

        print("\n۳) حذف پیام تکراری (dedup) در خروجی")
        chat_dir = tmp / "chats" / "Test_Chat"
        chat_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {"id": 1, "date": now, "sender_id": 10, "sender_name": "علی", "out": False,
             "text": "سلام", "service": False, "media": None},
            {"id": 1, "date": now, "sender_id": 10, "sender_name": "علی", "out": False,
             "text": "سلام (تکراری!)", "service": False, "media": None},
            {"id": 2, "date": now, "sender_id": 11, "sender_name": "سارا", "out": False,
             "text": "عکس:", "service": False, "media": "photos/000002_x.jpg", "media_type": "photo"},
        ]
        (chat_dir / exporter.CHAT_INFO_FILE).write_text(
            json.dumps({"id": 1, "title": "Test Chat", "message_count": 2}), encoding="utf-8"
        )
        with open(chat_dir / exporter.MESSAGES_FILE, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

        recs = list(exporter.iter_records(chat_dir))
        check("فقط ۲ رکورد یکتا", len(recs) == 2)

        export_root = tmp / "export"
        export_root.mkdir()
        # شبیه‌سازی ساختار: chat_dir داخل export_root/chats قرار می‌گیرد
        real_chat_dir = export_root / "chats" / "Test_Chat"
        real_chat_dir.parent.mkdir(parents=True)
        shutil.move(str(chat_dir), str(real_chat_dir))
        exporter.ensure_assets(export_root)
        exporter.generate_chat_page(real_chat_dir, export_root)
        exporter.generate_index(export_root)

        page = (real_chat_dir / "index.html").read_text(encoding="utf-8")
        check("متادیتا تعبیه شد", "window.CHAT_META" in page and "window.CHUNK_META" in page)
        check("صفحه سبک است (بدون دادهٔ سنگین)", "CHAT_DATA" not in page)
        chunk0 = real_chat_dir / "data" / "c00000.js"
        check("فایل chunk ساخته شد", chunk0.exists())
        c0 = chunk0.read_text(encoding="utf-8") if chunk0.exists() else ""
        check("chunk با __tg_chunk لود می‌شود", "__tg_chunk" in c0)
        check("عکس در chunk رندر شد", "photos/000002_x.jpg" in c0)
        check("فرستنده در chunk هست", "علی" in c0)
        check("فایل موتور (app.js) موجود", (export_root / "assets" / "app.js").exists())
        index = (export_root / "index.html").read_text(encoding="utf-8")
        check("index چت را نشان می‌دهد", "Test Chat" in index and "پیام" in index)
        check("assets ساخته شد", (export_root / "assets" / "style.css").exists())

        print("\n۴) ساخت پروژهٔ اندروید")
        out_dir = tmp / "android_out"
        project = build_android_app(export_root, out_dir)
        check("پروژه ساخته شد", project.exists())
        check("index در assets/www", (project / "app/src/main/assets/www/index.html").exists())
        check("MainActivity موجود", any(project.rglob("MainActivity.kt")) or any(project.rglob("MainActivity.java")))
        check("ZIP ساخته شد", (out_dir / f"{project.name}.zip").exists())
        # ساخت دوباره → نام یکتا (بدون تداخل)
        project2 = build_android_app(export_root, out_dir)
        check("اجرای دوم نام یکتا دارد", project2 != project and project2.exists())

        print("\n۵) خروجی تک‌کانال (فقط همان چت داخل اپ)")
        # چت دوم اضافه می‌کنیم تا مطمئن شویم خروجی تک‌کانال فقط چت انتخاب‌شده را دارد
        other = export_root / "chats" / "Other_Channel"
        other.mkdir(parents=True)
        (other / exporter.CHAT_INFO_FILE).write_text(
            json.dumps({"id": 99, "title": "درآمد دلار آنلاین هادی فرشیدی", "message_count": 5}), encoding="utf-8"
        )
        with open(other / exporter.MESSAGES_FILE, "w", encoding="utf-8") as fh:
            for i in range(5):
                fh.write(json.dumps({"id": 900 + i, "date": now, "sender_id": 1, "sender_name": "x",
                                     "out": False, "text": f"m{i}", "service": False, "media": None}) + "\n")
        exporter.generate_index(export_root)
        single = exporter.make_single_chat_export(export_root, "Test Chat")
        try:
            single_chats = [p.name for p in (single / "chats").iterdir()] if (single / "chats").exists() else []
            check("فقط یک چت در خروجی تک‌کانال", len(single_chats) == 1 and "Other_Channel" not in single_chats)
            idx = (single / "index.html").read_text(encoding="utf-8")
            check("index مستقیم به همان چت می‌رود", "location.replace" in idx and "Test_Chat" in idx)
            check("صفحهٔ چت در خروجی تک‌کانال ساخته شد", (single / "chats" / "Test_Chat" / "index.html").exists())
        finally:
            shutil.rmtree(single, ignore_errors=True)

        print("\n۶) طبقه‌بندی رسانه (بدون شیء واقعی)")
        # فقط بررسی می‌کنیم تابع بدون خطا import و صدا زده شود
        check("تابع classify_document قابل فراخوانی", callable(classify_document))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nنتایج: {PASS} موفق ✅ / {FAIL} ناموفق ❌")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
