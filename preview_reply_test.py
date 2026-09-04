# -*- coding: utf-8 -*-
"""ساخت پیش‌نمایش تستی با پیام‌های ریپلای، ویس و عکس."""
import json
import shutil
import sys
from pathlib import Path

# اضافه کردن مسیر پروژه
sys.path.insert(0, str(Path(__file__).parent))

from app.exporter import (
    generate_chat_page,
    generate_index,
    ensure_assets,
)

TEST_DIR = Path("_preview_reply_demo")
CHAT_NAME = "test_reply"
CHAT_DIR = TEST_DIR / "chats" / CHAT_NAME


def setup():
    # پاک‌سازی قبلی
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)
    CHAT_DIR.mkdir(parents=True)
    (CHAT_DIR / "photos").mkdir(exist_ok=True)
    (CHAT_DIR / "audio").mkdir(exist_ok=True)

    # ساخت عکس‌های تستی (فایل‌های کوچک ساده)
    # یک SVG ساده به عنوان عکس
    svg_birthday = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
  <rect width="200" height="200" fill="#ff6b6b"/>
  <text x="100" y="100" text-anchor="middle" dy=".3em" fill="white" font-size="40">🎂</text>
  <text x="100" y="140" text-anchor="middle" fill="white" font-size="16">تولدت مبارک!</text>
</svg>'''
    (CHAT_DIR / "photos" / "00010_birthday.svg").write_text(svg_birthday, encoding="utf-8")

    svg_nature = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
  <rect width="200" height="200" fill="#4ecdc4"/>
  <text x="100" y="100" text-anchor="middle" dy=".3em" fill="white" font-size="40">🏔️</text>
  <text x="100" y="140" text-anchor="middle" fill="white" font-size="16">طبیعت زیبا</text>
</svg>'''
    (CHAT_DIR / "photos" / "00015_nature.svg").write_text(svg_nature, encoding="utf-8")

    svg_food = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
  <rect width="200" height="200" fill="#f39c12"/>
  <text x="100" y="100" text-anchor="middle" dy=".3em" fill="white" font-size="40">🍕</text>
  <text x="100" y="140" text-anchor="middle" fill="white" font-size="16">ناهار</text>
</svg>'''
    (CHAT_DIR / "photos" / "00020_food.svg").write_text(svg_food, encoding="utf-8")

    # ساخت فایل ویس تستی (OGG خالی - فقط برای نمایش UI)
    # یک OGG file header ساده
    ogg_header = b'OggS\x00\x02' + b'\x00' * 27 + b'\x00' * 200
    (CHAT_DIR / "audio" / "00012_voice_ali.ogg").write_bytes(ogg_header)
    (CHAT_DIR / "audio" / "00018_voice_sara.ogg").write_bytes(ogg_header)

    # ---------- پیام‌ها ----------
    messages = [
        # پیام‌های اولیه
        {
            "id": 1, "date": "2024-08-10T09:00:00+03:30",
            "sender_id": 1001, "sender_name": "علی",
            "out": False, "text": "سلام صبح بخیر همه! ☀️",
            "service": False, "reply_to": None,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 2, "date": "2024-08-10T09:05:00+03:30",
            "sender_id": 1002, "sender_name": "سارا",
            "out": False, "text": "سلام! صبح تو هم بخیر 😊",
            "service": False, "reply_to": 1,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 3, "date": "2024-08-10T09:10:00+03:30",
            "sender_id": 1003, "sender_name": "محمد",
            "out": False, "text": "امروز هوا عالیه! کسی میاد پارک؟",
            "service": False, "reply_to": None,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 4, "date": "2024-08-10T09:12:00+03:30",
            "sender_id": 1004, "sender_name": "من",
            "out": True, "text": "من میام! ساعت چند؟",
            "service": False, "reply_to": 3,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # عکس تولد
        {
            "id": 5, "date": "2024-08-10T09:15:00+03:30",
            "sender_id": 1001, "sender_name": "علی",
            "out": False, "text": "دیشب تولد سارا بود، عکساش رو ببینید 🎂",
            "service": False, "reply_to": None,
            "media_type": "photo", "media_name": "birthday.svg", "media_size": 1200,
            "media": "photos/00010_birthday.svg",
        },
        {
            "id": 6, "date": "2024-08-10T09:18:00+03:30",
            "sender_id": 1002, "sender_name": "سارا",
            "out": False, "text": "ممنونم از همه! خیلی خوش گذشت ❤️",
            "service": False, "reply_to": 5,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # ویس علی
        {
            "id": 7, "date": "2024-08-10T09:20:00+03:30",
            "sender_id": 1001, "sender_name": "علی",
            "out": False, "text": "",
            "service": False, "reply_to": None,
            "media_type": "audio", "media_name": "voice_ali.ogg", "media_size": 45000,
            "media": "audio/00012_voice_ali.ogg",
        },
        {
            "id": 8, "date": "2024-08-10T09:22:00+03:30",
            "sender_id": 1003, "sender_name": "محمد",
            "out": False, "text": "ویس علی رو گوش دادم، خیلی مسخره بود 😂",
            "service": False, "reply_to": 7,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # لینک
        {
            "id": 9, "date": "2024-08-10T09:25:00+03:30",
            "sender_id": 1004, "sender_name": "من",
            "out": True, "text": "بچه‌ها این مقاله رو بخونید https://example.com/cool-article خیلی جالبه",
            "service": False, "reply_to": None,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 10, "date": "2024-08-10T09:30:00+03:30",
            "sender_id": 1002, "sender_name": "سارا",
            "out": False, "text": "عالی بود! مخصوصاً بخش آخرش 👍",
            "service": False, "reply_to": 9,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # عکس طبیعت
        {
            "id": 11, "date": "2024-08-10T10:00:00+03:30",
            "sender_id": 1003, "sender_name": "محمد",
            "out": False, "text": "اینم عکس طبیعت امروز",
            "service": False, "reply_to": None,
            "media_type": "photo", "media_name": "nature.svg", "media_size": 980,
            "media": "photos/00015_nature.svg",
        },
        {
            "id": 12, "date": "2024-08-10T10:02:00+03:30",
            "sender_id": 1004, "sender_name": "من",
            "out": True, "text": "وای چه زیبا! کجاست؟",
            "service": False, "reply_to": 11,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # ویس سارا
        {
            "id": 13, "date": "2024-08-10T10:05:00+03:30",
            "sender_id": 1002, "sender_name": "سارا",
            "out": False, "text": "",
            "service": False, "reply_to": None,
            "media_type": "audio", "media_name": "voice_sara.ogg", "media_size": 32000,
            "media": "audio/00018_voice_sara.ogg",
        },
        {
            "id": 14, "date": "2024-08-10T10:08:00+03:30",
            "sender_id": 1001, "sender_name": "علی",
            "out": False, "text": " Spartacus همون جاییه که رفتیم؟",
            "service": False, "reply_to": 11,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # عکس غذا
        {
            "id": 15, "date": "2024-08-10T12:30:00+03:30",
            "sender_id": 1004, "sender_name": "من",
            "out": True, "text": "ناهارم آماده شد 🍕",
            "service": False, "reply_to": None,
            "media_type": "photo", "media_name": "food.svg", "media_size": 750,
            "media": "photos/00020_food.svg",
        },
        # ریپلای زنجیره‌ای
        {
            "id": 16, "date": "2024-08-10T12:35:00+03:30",
            "sender_id": 1002, "sender_name": "سارا",
            "out": False, "text": "ähm لعنتی من هم گرسنمه 😋",
            "service": False, "reply_to": 15,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 17, "date": "2024-08-10T12:38:00+03:30",
            "sender_id": 1001, "sender_name": "علی",
            "out": False, "text": "بیاید بیرون بریم رستوران!",
            "service": False, "reply_to": 16,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 18, "date": "2024-08-10T12:40:00+03:30",
            "sender_id": 1003, "sender_name": "محمد",
            "out": False, "text": "من هم میام! ولی اول این ویس رو گوش بدید",
            "service": False, "reply_to": 17,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # پیام سرویسی
        {
            "id": 19, "date": "2024-08-10T13:00:00+03:30",
            "sender_id": 0, "sender_name": "",
            "out": False, "text": "علی عکس جدیدی اضافه کرد",
            "service": True, "reply_to": None,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # ریپلای به پیام سرویسی
        {
            "id": 20, "date": "2024-08-10T13:05:00+03:30",
            "sender_id": 1004, "sender_name": "من",
            "out": True, "text": "کدوم عکس؟",
            "service": False, "reply_to": 19,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        # پیام طولانی با ریپلای
        {
            "id": 21, "date": "2024-08-10T14:00:00+03:30",
            "sender_id": 1001, "sender_name": "علی",
            "out": False,
            "text": "بچه‌ها فردا صبح ساعت ۸ جلوی در پارک قرار بذاریم. لباس گرم بپوشید چون هوا سرده. من قهوه و سنگک میارم. محمد هم لطفاً توپ فوتبال رو بیاره. سارا هم اگه میشه یه پتو بیاره برای نشستن روی چمن. خلاصه حسابی حال کنیم! 🎉⚽☕",
            "service": False, "reply_to": None,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
        {
            "id": 22, "date": "2024-08-10T14:05:00+03:30",
            "sender_id": 1002, "sender_name": "سارا",
            "out": False, "text": "放过我！ 😅 باشه میارم",
            "service": False, "reply_to": 21,
            "media_type": None, "media_name": None, "media_size": 0, "media": None,
        },
    ]

    # نوشتن messages.jsonl
    with open(CHAT_DIR / "messages.jsonl", "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    # نوشتن chat_info.json
    info = {
        "id": 9999,
        "title": "گروه تست ریپلای",
        "type": "group",
        "message_count": len(messages),
        "media_count": sum(1 for m in messages if m.get("media")),
    }
    (CHAT_DIR / "chat_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"✅ {len(messages)} پیام تستی ساخته شد")
    print(f"   📁 {CHAT_DIR}")


def build():
    # ساخت assets
    ensure_assets(TEST_DIR)

    # ساخت صفحه چت
    result = generate_chat_page(CHAT_DIR, TEST_DIR)
    print(f"✅ صفحه چت ساخته شد:")
    print(f"   📄 پیام‌ها: {result['messages']}")
    print(f"   📷 رسانه: {result['media']}")
    print(f"   📅 از {result['first_date'][:10]} تا {result['last_date'][:10]}")

    # ساخت index
    chats = generate_index(TEST_DIR)
    print(f"✅ index.html ساخته شد ({len(chats)} چت)")

    # مسیر نهایی
    chat_html = CHAT_DIR / "index.html"
    print(f"\n🌐 برای مشاهده مرورگر باز کنید:")
    print(f"   {chat_html.resolve()}")


if __name__ == "__main__":
    setup()
    build()
