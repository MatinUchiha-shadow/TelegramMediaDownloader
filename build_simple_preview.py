# -*- coding: utf-8 -*-
"""ساخت پیش‌نمایش ساده (بدون virtual scroll) برای تست reply."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from app.exporter import (
    iter_records, load_chat_info, escape, format_time, format_jalali,
    SENDER_COLORS, sender_color, _record_for, CSS, JS,
)

CHAT_DIR = Path("_preview_reply_demo/chats/test_reply")

def _esc(s):
    import html as h
    return h.escape(s or "", quote=False)

def _color(sid):
    try: return SENDER_COLORS[abs(int(sid)) % len(SENDER_COLORS)]
    except: return SENDER_COLORS[0]

def _has_rtl(t):
    import re
    return bool(re.search(r'[\u0590-\u08ff\u0600-\u06ff\ufb1d-\ufdff\ufe70-\ufefc]', t or ''))

def build_simple():
    info = load_chat_info(CHAT_DIR) or {}
    title = info.get("title", "تست")
    records = list(iter_records(CHAT_DIR))
    
    # Build a lookup map for reply targets
    id_map = {}
    for rec in records:
        id_map[rec["id"]] = rec
    
    rows = []
    for rec in records:
        mid = rec["id"]
        sender = rec.get("sender_name", "")
        out = rec.get("out", False)
        text = rec.get("text", "")
        reply_to = rec.get("reply_to")
        media = rec.get("media")
        media_type = rec.get("media_type")
        time_str = format_time(rec.get("date", ""))
        is_service = rec.get("service", False)
        
        if is_service:
            rows.append(f'<div class="row service-row"><div class="bubble service">{_esc(text)}</div></div>')
            continue
        
        parts = ''
        
        # Reply preview
        if reply_to:
            orig = id_map.get(reply_to)
            if orig:
                name_part = ''
                if orig.get("sender_name"):
                    name_part = f'<span class="rr-name" style="color:{_color(orig.get("sender_id"))}">{_esc(orig.get("sender_name", ""))}</span>'
                orig_text = orig.get("text", "")
                if orig_text:
                    text_part = _esc(orig_text[:80])
                else:
                    text_part = orig.get("media_type") or "رسانه"
                parts += f'<div class="reply-ref" data-rp="{reply_to}">{name_part}<span class="rr-text">{text_part}</span></div>'
            else:
                parts += f'<div class="reply-ref" data-rp="{reply_to}"><span class="rr-text">💬 پیام #{reply_to}</span></div>'
        
        # Sender name
        if not out and sender:
            parts += f'<span class="from" style="color:{_color(rec.get("sender_id"))}">{_esc(sender)}</span>'
        
        # Text
        if text:
            direction = 'rtl' if _has_rtl(text) else 'ltr'
            import re as _re
            linked = _re.sub(r'(https?://[^\s<>"\']+)', r'<a href="\1" target="_blank">\1</a>', _esc(text))
            parts += f'<div class="text" dir="{direction}">{linked}</div>'
        
        # Media
        if media and media_type == "photo":
            parts += f'<a class="photo" href="{_esc(media)}" data-lightbox><img loading="lazy" src="{_esc(media)}" alt="photo"></a>'
        elif media and media_type == "audio":
            parts += f'<div class="voice" data-mid="{mid}" data-src="{_esc(media)}"><button class="vplay" type="button">▶</button><input class="vseek" type="range" min="0" max="100" value="0" step="0.1"><span class="vtime">0:00</span></div>'
        
        # Time
        parts += f'<span class="time">{_esc(time_str)}</span>'
        
        mine_class = ' mine' if out else ''
        rows.append(f'<div class="row{mine_class}" data-id="{mid}"><div class="bubble">{parts}</div></div>')
    
    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{_esc(title)} — تست ریپلای</title>
<style>{CSS}</style>
</head>
<body>
<header class="top chat-top">
  <h1>{_esc(title)}</h1>
  <span class="sub">{len(records)} پیام · {sum(1 for r in records if r.get('media'))} رسانه</span>
</header>
<main id="history">
<div style="max-width:760px;margin:0 auto;padding:0 14px 40px">
{''.join(rows)}
</div>
</main>
<div id="lightbox" class="hidden">
  <div id="lbStage"><img id="lbImg" alt=""></div>
  <div id="lbTools">
    <button id="lbClose" title="بستن">✕</button>
  </div>
</div>
</body>
</html>"""
    
    out = Path("_preview_reply_demo/simple_preview.html")
    out.write_text(html, encoding="utf-8")
    print(f"✅ Simple preview: {out.resolve()}")

if __name__ == "__main__":
    build_simple()
