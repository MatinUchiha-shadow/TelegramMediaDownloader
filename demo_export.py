#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ساخت خروجی نمونه برای بررسی ظاهری (بدون تلگرام)."""
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import exporter  # noqa: E402
from app.downloader import CHAT_INFO_FILE, MESSAGES_FILE, sanitize_name  # noqa: E402

OUT = Path(__file__).resolve().parent / "demo_export"


def svg_photo(path: Path, color: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320">'
        f'<rect width="480" height="320" fill="{color}"/>'
        f'<text x="50%" y="50%" fill="#fff" font-size="34" text-anchor="middle" '
        f'font-family="Tahoma"> {label} </text></svg>'
    )
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    exporter.ensure_assets(OUT)

    chats = [
        {
            "id": 1001, "title": "گروه خانواده",
            "rows": [
                ("علی", False, "سلام به همه 👋", None, None),
                ("سارا", False, "سلام! امروز برنامه چیه؟", None, None),
                ("مادر", False, "عکس تولدت رو بفرست 🎂", "photo", "photos/000003_tavalod.svg"),
                ("من", True, "باشه، اینم عکس 👇", None, None),
                ("پدر", False, "https://example.com خبر مهم رو ببینید", None, None),
                ("سارا", False, "این ویدیو خیلی خنده‌داره 😂", "video", "videos/000006_fun.mp4"),
                ("علی", False, "ویس گوش کن", "audio", "audio/000007_voice.ogg"),
                ("من", True, "هاها 😄 حتماً", None, None),
            ],
        },
        {
            "id": 2002, "title": "English Chat",
            "rows": [
                ("John", False, "Hello everyone!", None, None),
                ("Maria", False, "Nice to meet you all :)", None, None),
                ("Me", True, "Welcome! This is a test message with a https://telegram.org link.", None, None),
            ],
        },
    ]

    start = datetime(2024, 8, 10, 9, 15, tzinfo=timezone.utc)
    media_id = 0
    for ci, chat in enumerate(chats):
        chat_dir = OUT / exporter.CHATS_DIR / sanitize_name(chat["title"])
        chat_dir.mkdir(parents=True, exist_ok=True)
        rows_out = []
        msg_id = 0
        for sender, mine, text, mtype, mrel in chat["rows"]:
            msg_id += 1
            date = start + timedelta(hours=ci * 30 + msg_id * 2)
            rec = {
                "id": msg_id,
                "date": date.isoformat(),
                "sender_id": 1000 + msg_id,
                "sender_name": sender,
                "out": mine,
                "text": text,
                "service": False,
                "reply_to": None,
                "media_type": mtype,
                "media_name": Path(mrel).name if mrel else None,
                "media_size": 0,
                "media": None,
            }
            if mrel:
                media_id += 1
                rel = f"{mrel}"
                src = chat_dir / rel
                if mtype == "photo":
                    svg_photo(src, ["#d81b60", "#1e88e5", "#43a047", "#fdd835"][media_id % 4], f"عکس {media_id}")
                else:
                    src.parent.mkdir(parents=True, exist_ok=True)
                    src.write_text("dummy", encoding="utf-8")
                rec["media"] = rel
            rows_out.append(rec)

        with open(chat_dir / MESSAGES_FILE, "w", encoding="utf-8") as fh:
            for r in rows_out:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        (chat_dir / CHAT_INFO_FILE).write_text(
            json.dumps({
                "id": chat["id"], "title": chat["title"], "type": "group",
                "message_count": len(rows_out), "media_count": sum(1 for r in rows_out if r["media"]),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        exporter.generate_chat_page(chat_dir, OUT)

    exporter.generate_index(OUT)
    print("خروجی نمونه ساخته شد:", OUT)


if __name__ == "__main__":
    main()
