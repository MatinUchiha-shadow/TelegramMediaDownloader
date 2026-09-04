# -*- coding: utf-8 -*-
"""ساخت یک فایل HTML خود-contained با همه چیز inline (برای preview)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.exporter import (
    iter_records, load_chat_info, escape, format_time, format_jalali,
    SENDER_COLORS, _record_for, CHUNK_SIZE, _pack_hint, _height_hint_rec,
    _sanitize_script, CSS, JS,
)

CHAT_DIR = Path("_preview_reply_demo/chats/test_reply")

def build_self_contained():
    info = load_chat_info(CHAT_DIR) or {}
    title = info.get("title", "تست")

    records = list(iter_records(CHAT_DIR))
    
    # Build chunk data
    chunks = []
    current_chunk = []
    est_parts = []
    
    for rec in records:
        entry = _record_for(rec)
        if entry is None:
            continue
        iso = rec.get("date") or ""
        if iso:
            day = format_jalali(iso)
            current_chunk.append({"dy": day})
            est_parts.append(_pack_hint(44))
        
        current_chunk.append(entry)
        est_parts.append(_pack_hint(_height_hint_rec(entry)))
        
        if len(current_chunk) >= CHUNK_SIZE:
            chunks.append(current_chunk)
            current_chunk = []
    
    if current_chunk:
        chunks.append(current_chunk)
    
    # Build meta
    meta = {"title": title, "count": len(records), "media": sum(1 for r in records if r.get("media")), "text": sum(1 for r in records if r.get("text"))}
    chunk_meta = {"size": CHUNK_SIZE, "count": len(chunks), "url": "#", "est": "".join(est_parts)}
    
    # Build chunk JS calls
    chunk_js = ""
    for i, chunk in enumerate(chunks):
        chunk_js += f"window.__tg_chunk({i},{json.dumps(chunk, ensure_ascii=False)});\n"
    
    # Read CSS and JS (escape for inline)
    css = CSS
    js = JS
    
    # Fix JS path references - the JS loads chunks via script tags but we inline them
    # Replace Conf.url references
    js_fixed = js
    
    # Read app.js and style.css from assets
    assets_dir = Path("_preview_reply_demo/assets")
    if assets_dir.exists():
        js_from_file = (assets_dir / "app.js").read_text(encoding="utf-8")
        css_from_file = (assets_dir / "style.css").read_text(encoding="utf-8")
        js_fixed = js_from_file
    
    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{escape(title)} — پیش‌نمایش ریپلای</title>
<style>
{css}
</style>
</head>
<body>
<header class="top chat-top">
  <a class="back" href="#" title="بازگشت">‹</a>
  <h1>{escape(title)}</h1>
  <span class="sub" id="posInfo"></span>
  <div class="header-actions">
    <button id="btnFirst" class="jump" title="اولین پیام">⏮ اولین</button>
    <button id="btnLast" class="jump" title="آخرین پیام">آخرین ⏭</button>
    <button id="btnSpeed" class="jump" title="سرعت پخش">۱×</button>
  </div>
  <input id="search" type="search" placeholder="جستجو در پیام‌ها…">
</header>
<main id="history">
  <div id="padTop"></div>
  <div id="msgView"></div>
  <div id="padBottom"></div>
</main>
<div id="searchPanel" class="hidden"></div>
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
<script>
window.CHAT_META = {json.dumps(meta, ensure_ascii=False)};
window.CHUNK_META = {json.dumps(chunk_meta, ensure_ascii=False)};
</script>
<script>
{js_fixed}
</script>
<script>
{chunk_js}
</script>
</body>
</html>"""
    
    out = Path("_preview_reply_demo/test_reply_preview.html")
    out.write_text(html, encoding="utf-8")
    print(f"✅ Self-contained preview: {out.resolve()}")
    print(f"   {len(records)} messages, {len(chunks)} chunks")

if __name__ == "__main__":
    build_self_contained()
