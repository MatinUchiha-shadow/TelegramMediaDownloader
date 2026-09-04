# -*- coding: utf-8 -*-
"""Generate a self-contained demo chat page (inline CSS/JS + data-URL media)
so the new archive engine can be tested in the Preview without a server."""
import base64
import io
import json
import struct
import sys
import wave
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import exporter  # noqa: E402

ROOT = Path(__file__).resolve().parent
PREVIEW = ROOT / "_preview"
PREVIEW.mkdir(exist_ok=True)


def make_png(w, h, rgb):
    """Solid-color PNG via zlib (no deps)."""
    row = b"\x00" + bytes(rgb) * w
    raw = row * h
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_wav(seconds=0.6, freq=440):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        frames = bytearray()
        for i in range(int(22050 * seconds)):
            v = int(8000 * (0.5 + 0.5 * ((i // 200) % 2)) - 4000)  # beep-ish
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def data_url(b, mime):
    return f"data:{mime};base64," + base64.b64encode(b).decode()


PNG = data_url(make_png(420, 300, (24, 130, 200)), "image/png")
WAV1 = data_url(make_wav(0.7, 440), "audio/wav")
WAV2 = data_url(make_wav(0.5, 660), "audio/wav")

SENDERS = ["هادی فرشیدی", "مدیر کانال", "علی رضایی", "سارا محمدی"]

def build_rows():
    rows = []
    base = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    texts = [
        "قیمت طلا امروز چقدر شد؟",
        "آموزش رمزارز برای مبتدیان",
        "این دوره را از دست ندهید",
        "لینک گروه در پست بعدی",
        "تحلیل بازار ارز",
        "ویدیو آموزشی هفته",
        "سوالات متداول",
        "جلسه بعدی شنبه ساعت ۹",
        "معرفی اپ جدید",
        "پاسخ به سوالات شما",
    ]
    n = 160
    for i in range(n):
        mid = 1000 + i
        d = base + timedelta(minutes=i * 37)
        kind = i % 10
        rec = {
            "id": mid,
            "date": d.isoformat(),
            "sender_id": 100 + (i % 4),
            "sender_name": SENDERS[i % 4],
            "out": False,
            "text": "",
            "service": False,
            "media": None,
            "media_type": None,
        }
        if kind == 2:
            rec["media"] = "photos/000002_x.jpg"
            rec["media_type"] = "photo"
            rec["text"] = "عکس جدید:"
        elif kind == 3:
            rec["media"] = "audio/voice.ogg"
            rec["media_type"] = "audio"
            rec["text"] = "ویس:"
        elif kind == 4:
            rec["media"] = "audio/voice.ogg"
            rec["media_type"] = "audio"
            rec["text"] = "ویس:"
        else:
            rec["text"] = texts[i % len(texts)] + f" — پیام {i + 1}"
        rows.append(rec)
    return rows


def main():
    tmp = PREVIEW / "_demo"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    chat = tmp / "chats" / "Demo_Channel"
    chat.mkdir(parents=True)
    (chat / exporter.CHAT_INFO_FILE).write_text(
        json.dumps({"id": 1, "title": "دمو کانال تست", "message_count": 160}), encoding="utf-8"
    )
    with open(chat / exporter.MESSAGES_FILE, "w", encoding="utf-8") as fh:
        for r in build_rows():
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    exporter.ensure_assets(tmp)
    exporter.generate_chat_page(chat, tmp)

    page = (chat / "index.html").read_text(encoding="utf-8")
    css = (tmp / "assets" / "style.css").read_text(encoding="utf-8")
    js = (tmp / "assets" / "app.js").read_text(encoding="utf-8")

    page = page.replace('<link rel="stylesheet" href="../../assets/style.css">',
                        "<style>" + css + "</style>")
    page = page.replace('<script src="../../assets/app.js"></script>',
                        "<script>" + js + "</script>")
    # replace media paths with data URLs so the single-file preview works
    page = page.replace("photos/000002_x.jpg", PNG)
    page = page.replace("audio/voice.ogg", WAV1)
    out = PREVIEW / "demo_chat.html"
    out.write_text(page, encoding="utf-8")
    print("OK ->", out)


if __name__ == "__main__":
    main()
