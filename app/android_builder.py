# -*- coding: utf-8 -*-
"""ساخت پروژهٔ اپ اندروید (WebView) از خروجی HTML:
- کپی خروجی در app/src/main/assets/www/
- کپی قالب پروژهٔ اندروید (android_template/)
- ساخت ZIP برای انتقال آسان
کاربر با Android Studio پروژه را باز کرده و APK می‌سازد.
"""
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from app.logger_setup import get_logger

log = get_logger("android")


def _template_dir() -> Path:
    """پوشهٔ قالب اندروید — هم در حالت منبع و هم در EXE (PyInstaller)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "android_template"


TEMPLATE_DIR = _template_dir()


def build_android_app(export_root: Path, out_dir: Path, app_name: str | None = None) -> Path:
    """از پوشهٔ خروجی HTML یک پروژهٔ اندروید می‌سازد. مسیر پروژه را برمی‌گرداند.
    هر ساخت یک applicationId و نام اپ یکتا می‌گیرد تا دو اپ همزمان روی گوشی
    بدون خطای «update» کنار هم نصب شوند.
    app_name: نام دلخواه اپ (مثلاً عنوان چت)؛ اگر ندهید از نام پوشهٔ خروجی می‌سازد.
    """
    export_root = Path(export_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = export_root.name or "telegram_export"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  # با میلی‌ثانیه تا دو ساخت هم‌زمان تداخل نداشته باشند
    project = out_dir / f"{base}_android_{stamp}"

    www = project / "app" / "src" / "main" / "assets" / "www"
    www.mkdir(parents=True, exist_ok=True)

    # ۱) کپی قالب
    if TEMPLATE_DIR.exists():
        shutil.copytree(TEMPLATE_DIR, project, dirs_exist_ok=True)

    # ۲) پکیج و نام یکتا (رفع باگ «update» موقع نصب دو اپ)
    pkg, app_label = _unique_package(app_name or base, stamp)
    _rewrite_android_ids(project, pkg, app_label)

    # ۳) کپی خروجی HTML
    for item in export_root.iterdir():
        dst = www / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)

    # ۴) راهنمای ساخت
    (project / "BUILD_ANDROID_README.txt").write_text(
        BUILD_README.format(project=project.name, app=app_label), encoding="utf-8"
    )

    # ۵) ZIP
    zip_path = out_dir / f"{project.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in project.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(project.parent))

    log.info("پروژهٔ اندروید ساخته شد: %s (package=%s)", project, pkg)
    return project


def _unique_package(base: str, stamp: str) -> tuple[str, str]:
    """ساخت applicationId و نام اپ یکتا از روی نام چت + زمان.
    applicationId فقط حروف کوچک a-z، رقم و نقطه می‌تواند داشته باشد.
    """
    import hashlib
    import re

    # نرمال‌سازی نام پایه به کاراکترهای امن.
    # هر بخش پکیج جاوا باید با حرف شروع شود (مثل apk_builder) — هم safe و هم
    # هش ممکن است با رقم شروع شوند (مثلاً «1405» از عنوان فارسی).
    safe = re.sub(r"[^a-z0-9]", "", (base or "tg").lower())[:16] or "tg"
    if safe[0].isdigit():
        safe = "c" + safe
    h = hashlib.sha1((base + stamp).encode("utf-8")).hexdigest()[:8]
    pkg = f"ir.freebuff.tgviewer.{safe}.a{h}"

    # نام اپ = همان عنوان چت/کانال (بدون پیشوند «آرشیو»)
    label = (base or "آرشیو تلگرام").replace("_", " ").strip()[:40]
    app_label = label if label else "آرشیو تلگرام"
    return pkg, app_label


def _rewrite_android_ids(project: Path, pkg: str, app_label: str) -> None:
    """بازنویسی applicationId (build.gradle) و app_name (strings.xml)
    و namespace تا پکیج جدید اعمال شود.
    """
    gradle = project / "app" / "build.gradle"
    if gradle.exists():
        text = gradle.read_text(encoding="utf-8")
        text = text.replace('namespace \'ir.freebuff.tgviewer\'', f'namespace \'{pkg}\'')
        text = text.replace('applicationId "ir.freebuff.tgviewer"', f'applicationId "{pkg}"')
        gradle.write_text(text, encoding="utf-8")

    strings = project / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    if strings.exists():
        text = strings.read_text(encoding="utf-8")
        # نام یکتا — جلوگیری از اشتباه گرفتن دو اپ روی گوشی
        text = text.replace("آرشیو تلگرام", app_label)
        strings.write_text(text, encoding="utf-8")

    # پکیج فایل کاتلین هم باید با namespace جدید یکی شود وگرنه build می‌شکند
    src = project / "app" / "src" / "main" / "java"
    old_kt = src / "ir" / "freebuff" / "tgviewer" / "MainActivity.kt"
    if old_kt.exists():
        text = old_kt.read_text(encoding="utf-8")
        text = text.replace("package ir.freebuff.tgviewer", f"package {pkg}")
        # فقط فایل قدیمی را حذف می‌کنیم؛ چون پکیج جدید هم با ir.freebuff…
        # شروع می‌شود و پوشهٔ جدید زیر همین درخت ساخته می‌شود، پس rmtree
        # روی درخت قدیمی فایل تازه‌نوشته را هم از بین می‌برد.
        old_kt.unlink()
        new_dir = src / pkg.replace(".", "/")
        new_dir.mkdir(parents=True, exist_ok=True)
        new_kt = new_dir / "MainActivity.kt"
        new_kt.write_text(text, encoding="utf-8")


def build_single_chat(export_root, chat_title, out_dir, progress=None) -> dict:
    """ساخت اپ/APK فقط از یک چت (فقط همین کانال داخل اپ ظاهر می‌شود).
    - یک خروجی تک‌کانال موقت می‌سازد (hard link برای جلوگیری از کپی دوبارهٔ رسانه)
    - اول APK واقعی را امتحان می‌کند (app.apk_builder) و اگر ابزارها نباشند
      به پروژهٔ Gradle + ZIP برمی‌گردد
    - خروجی موقت را همیشه پاک می‌کند
    برمی‌گرداند dict با کلیدهای (ok, apk/apk_name) یا (ok, project_name, zip).
    """
    import shutil
    from app import exporter

    export_root = Path(export_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    single = exporter.make_single_chat_export(export_root, chat_title)
    try:
        # ۱) تلاش برای ساخت APK واقعی و امضاشده (ابزارها همراه EXE هستند)
        try:
            from app.apk_builder import build_apk, tools_available
            if tools_available():
                apk = build_apk(single, out_dir, app_name=chat_title, progress=progress)
                return {
                    "ok": True,
                    "apk": str(apk),
                    "apk_name": apk.name,
                    "project_name": "",
                    "zip": "",
                }
            log.warning("ابزارهای ساخت APK در دسترس نیستند — ساخت پروژهٔ Gradle + ZIP")
        except Exception as e:
            log.exception("ساخت APK شکست خورد — fallback به پروژهٔ Gradle")

        # ۲) fallback: پروژهٔ Gradle + ZIP (مثل قبل — باز کردن با Android Studio)
        project = build_android_app(single, out_dir, app_name=chat_title)
        return {
            "ok": True,
            "project_name": project.name,
            "zip": str(project.parent / f"{project.name}.zip"),
            "apk": "",
            "apk_name": "",
        }
    finally:
        log.info("پاک‌سازی خروجی موقت تک‌کانال: %s", single)
        shutil.rmtree(single, ignore_errors=True)


BUILD_README = """# ساخت APK از این پروژه

نام اپ: {app}

1. Android Studio (نسخهٔ جدید) را نصب کنید.
2. در Android Studio: File > Open و پوشهٔ «{project}» را انتخاب کنید.
3. اجازه دهید Gradle Sync کامل شود (اولین بار چند دقیقه طول می‌کشد).
4. از منو: Build > Build APK(s) > Build APK.
5. فایل APK در پوشهٔ  app/build/outputs/apk/debug/  قرار می‌گیرد.
6. آن را به گوشی منتقل کرده و نصب کنید (اجازهٔ نصب از منابع ناشناس را بدهید).

نکته: همهٔ پیام‌ها و فایل‌ها داخل خود APK هستند و به اینترنت نیازی ندارند.
هر بار ساخت، applicationId یکتا می‌گیرد (ir.freebuff.tgviewer.<name>.<hash>)
پس می‌توانید چند اپ را همزمان نصب کنید؛ هیچ‌کدام «update» نمی‌شود.
"""

# گرادیان/راهنمای حذف: این فایل‌ها هنگام ساخت کپی می‌شوند
