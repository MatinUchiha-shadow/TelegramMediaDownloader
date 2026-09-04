# -*- coding: utf-8 -*-
"""ساخت APK واقعی و امضا‌شده از خروجی HTML — بدون Gradle/Android Studio.

پایپلاین (ثابت‌شده با تست واقعی):
    aapt2 compile --dir res -o compiled.flata
    aapt2 link -I android.jar --manifest AndroidManifest.xml \
        --rename-manifest-package "<pkg یکتا>" -A assets -o unsigned.apk compiled.flata
    [تزریق classes.dex با zipfile پایتون — چون zip در سیستم نیست]
    zipalign -f 4 unsigned.apk aligned.apk
    java -jar apksigner.jar sign --ks debug.keystore ... --out final.apk aligned.apk

هر ساخت یک applicationId یکتا می‌گیرد (ir.freebuff.tgviewer.<name>.<hash>)
تا دو اپ از دو چت مختلف بدون خطای «update» کنار هم نصب شوند.
ابزارها به ترتیب از: android_bundle/ داخل EXE (_MEIPASS) → android_bundle/ کنار سورس
→ %LOCALAPPDATA%/Android/Sdk (نصب‌شده روی سیستم) پیدا می‌شوند.
"""
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from app.logger_setup import get_logger

log = get_logger("apk")

# ---------- مسیر ابزارها ----------


def _bundle_dirs() -> list[Path]:
    """پوشه‌های جستجوی android_bundle — به ترتیب اولویت."""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "android_bundle")
    dirs.append(Path(__file__).resolve().parent.parent / "android_bundle")
    dirs.append(Path.home() / "AppData" / "Local" / "Android" / "Sdk")
    return dirs


def _resolve(name: str, sub: str | None = None) -> Path | None:
    """پیدا کردن یک ابزار داخل android_bundle/SDK.
    name: نام فایل (aapt2.exe, zipalign.exe, apksigner.jar, android.jar, java.exe, ...)
    sub: مسیر زیرپوشه نسبی در bundle (مثلاً build-tools/android-14 یا platforms/android-34)
    """
    for base in _bundle_dirs():
        p = base / sub / name if sub else base / name
        if p.exists():
            return p
    return None


def tools_available() -> bool:
    """آیا همهٔ ابزارهای لازم برای ساخت APK حاضرند؟ (برای fallback به حالت قبلی)"""
    return bool(
        _resolve("aapt2.exe", "build-tools/android-14")
        and _resolve("zipalign.exe", "build-tools/android-14")
        and _resolve("apksigner.jar", "build-tools/android-14/lib")
        and _resolve("android.jar", "platforms/android-34")
        and _resolve("classes.dex")
        and _resolve("debug.keystore")
        and find_java()
    )


def find_java() -> Path | None:
    """java.exe — اول JRE باندل‌شده، بعد JDK سیستم، بعد PATH."""
    jre = _resolve("java.exe", "jre17/bin")
    if jre:
        return jre
    for cand in (
        Path(r"C:\Program Files\Java") / "jdk-17.0.3" / "bin" / "java.exe",
        Path(r"C:\Program Files\Java") / "jdk-17" / "bin" / "java.exe",
    ):
        if cand.exists():
            return cand
    import shutil as _sh

    found = _sh.which("java")
    return Path(found) if found else None


def _template_dir() -> Path:
    """پوشهٔ قالب اندروید — هم در حالت منبع و هم در EXE (PyInstaller)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "android_template"


def _unique_package(base: str, stamp: str) -> tuple[str, str]:
    """applicationId و نام اپ یکتا از روی نام چت + زمان."""
    import hashlib
    import re

    safe = re.sub(r"[^a-z0-9]", "", (base or "tg").lower())[:16] or "tg"
    # هر بخش پکیج جاوا باید با حرف شروع شود؛ عنوان فارسی «تمرین تاروت مرداد 1405»
    # بعد از حذف حروف فارسی می‌شود «1405» که با رقم شروع می‌شود و aapt2 ردش می‌کند
    if safe[0].isdigit():
        safe = "c" + safe
    h = hashlib.sha1((base + stamp).encode("utf-8")).hexdigest()[:8]
    # بخش آخر باید با حرف شروع شود (قانون پکیج جاوا) — پس «a» جلو می‌گذاریم
    pkg = f"ir.freebuff.tgviewer.{safe}.a{h}"

    # نام اپ = همان عنوان چت/کانال (بدون پیشوند «آرشیو»)
    label = (base or "آرشیو تلگرام").replace("_", " ").strip()[:40]
    app_label = label if label else "آرشیو تلگرام"
    return pkg, app_label


def _run(cmd: list[str], workdir: Path, timeout: int = 600) -> None:
    """اجرای یک ابزار و بالا انداختن خطا با خروجی مفید."""
    log.info("run: %s", " ".join(str(c) for c in cmd))
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.stdout.strip():
        log.info("out: %s", proc.stdout.strip()[-2000:])
    if proc.stderr.strip():
        log.warning("err: %s", proc.stderr.strip()[-2000:])
    if proc.returncode != 0:
        raise RuntimeError(
            f"دستور شکست خورد ({proc.returncode}): {' '.join(str(c) for c in cmd[:3])}…\n{proc.stderr.strip()[-1500:]}"
        )


# ---------- ساخت APK ----------


def build_apk(export_root: Path, out_dir: Path, app_name: str | None = None,
              progress=None) -> Path:
    """از پوشهٔ خروجی HTML یک APK امضا‌شده و قابل‌نصب می‌سازد.
    مسیر APK نهایی را برمی‌گرداند. اگر ابزارها نباشند RuntimeError می‌دهد
    (caller باید fallback به حالت قبلی بدهد).
    progress: تابع اختیاری progress(متن_فارسی_مرحله) برای نمایش زندهٔ مراحل ساخت.
    """
    export_root = Path(export_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _phase(msg: str) -> None:
        try:
            if progress:
                progress(msg)
        except Exception:
            pass

    aapt2 = _resolve("aapt2.exe", "build-tools/android-14")
    zipalign = _resolve("zipalign.exe", "build-tools/android-14")
    apksigner = _resolve("apksigner.jar", "build-tools/android-14/lib")
    android_jar = _resolve("android.jar", "platforms/android-34")
    classes_dex = _resolve("classes.dex")
    keystore = _resolve("debug.keystore")
    java = find_java()
    for name, p in (("aapt2", aapt2), ("zipalign", zipalign), ("apksigner", apksigner),
                    ("android.jar", android_jar), ("classes.dex", classes_dex),
                    ("debug.keystore", keystore), ("java", java)):
        if not p:
            raise RuntimeError(f"ابزار ساخت APK پیدا نشد: {name}")

    base = export_root.name or "telegram_export"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pkg, app_label = _unique_package(app_name or base, stamp)
    # نام فایل APK باید ASCII باشد — بعضی گوشی‌ها (مثل شیائومی) APK با نام
    # فارسی را با «App isn't compatible» بلاک می‌کنند. نام نمایشی (label)
    # فارسی می‌ماند؛ فقط نام فایل ASCII است.
    import re as _re
    safe = _re.sub(r"[^a-z0-9]", "", (app_name or base).lower())[:24] or "chat"
    fname_base = f"{safe}_{pkg.rsplit('.', 1)[-1]}"

    with tempfile.TemporaryDirectory(prefix="tgapk_") as tmp:
        work = Path(tmp)
        res_dir = work / "res"
        assets_dir = work / "assets" / "www"

        # ۱) کپی منابع قالب + بازنویسی نام اپ
        tpl_res = _template_dir() / "app" / "src" / "main" / "res"
        if not tpl_res.exists():
            raise RuntimeError("قالب اندروید (res) پیدا نشد")
        shutil.copytree(tpl_res, res_dir, dirs_exist_ok=True)
        strings = res_dir / "values" / "strings.xml"
        if strings.exists():
            text = strings.read_text(encoding="utf-8")
            text = text.replace("آرشیو تلگرام", app_label)
            strings.write_text(text, encoding="utf-8")

        # ۲) مانیفست (پکیج اصلی ir.freebuff.tgviewer؛ rename بعداً اعمال می‌شود
        #    و activity نسبی .MainActivity به کلاس واقعی در dex اشاره می‌کند)
        manifest = _template_dir() / "app" / "src" / "main" / "AndroidManifest.xml"
        if not manifest.exists():
            raise RuntimeError("AndroidManifest.xml قالب پیدا نشد")
        shutil.copy2(manifest, work / "AndroidManifest.xml")

        # ۳) محتوای خروجی چت → assets/www
        assets_dir.mkdir(parents=True, exist_ok=True)
        for item in export_root.iterdir():
            dst = assets_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)

        # ۴) aapt2 compile (فقط res — نه assets؛ چون aapt2 ویندوز نام‌های
        #    فارسی داخل assets را نمی‌تواند باز کند)
        _phase("کامپایل منابع اندروید…")
        compiled = work / "compiled.flata"
        _run([aapt2, "compile", "--dir", res_dir, "-o", compiled], work)

        # ۵) aapt2 link — پکیج یکتا برای هر ساخت (رفع باگ «update»).
        #    min-sdk/target-sdk صریح: بدون آن‌ها aapt2 targetSdk را ۱ می‌گیرد
        #    و اندروید ۱۴/۱۵ نصب را با «App isn't compatible» بلاک می‌کند.
        unsigned = work / "unsigned.apk"
        _run([
            aapt2, "link",
            "-I", android_jar,
            "--manifest", work / "AndroidManifest.xml",
            "--rename-manifest-package", pkg,
            "--min-sdk-version", "21",
            "--target-sdk-version", "34",
            "--version-code", "1",
            "--version-name", "1.0",
            "-o", unsigned,
            compiled,
        ], work)

        # ۶) تزریق assets/www (نام‌های فارسی حفظ می‌شوند — zipfile UTF-8)
        #    و classes.dex با zipfile (چون zip در این سیستم نیست)
        _phase("بسته‌بندی رسانه‌ها داخل APK… (ممکن است چند دقیقه طول بکشد)")
        _add_assets_and_dex(unsigned, work / "assets", classes_dex)

        # ۷) zipalign
        _phase("هم‌ترازی APK…")
        aligned = work / "aligned.apk"
        _run([zipalign, "-f", "4", unsigned, aligned], work)

        # ۸) امضا با debug.keystore.
        #    نکتهٔ مهم: apksigner (JRE 17) مسیرهای غیر-ASCII را نمی‌تواند بخواند
        #    (argv با cp1252 دیکد می‌شود → Bad pathname). پس فایل میانی نام
        #    ASCII دارد و کپی نهایی (با اسم فارسی/چت) توسط پایتون انجام می‌شود
        #    که یونیکد ویندوز را درست مدیریت می‌کند.
        _phase("امضای APK…")
        final_work = work / f"out_{stamp}.apk"
        _run([
            java, "-jar", apksigner, "sign",
            "--ks", keystore, "--ks-pass", "pass:android",
            "--key-pass", "pass:android",
            "--out", final_work, aligned,
        ], work)

        # ۹) کپی به مقصد (نام فارسی اپ) + دسکتاپ
        final_name = f"{fname_base}_{stamp}.apk"
        dest = out_dir / final_name
        shutil.copy2(final_work, dest)
        desktop_apk = Path.home() / "Desktop" / final_name
        try:
            shutil.copy2(final_work, desktop_apk)
            log.info("APK روی دسکتاپ هم کپی شد: %s", desktop_apk)
        except Exception as e:
            log.warning("کپی APK روی دسکتاپ نشد: %s", e)

    log.info("APK ساخته شد: %s (package=%s, label=%s)", dest, pkg, app_label)
    return dest


# فایل‌هایی که از قبل فشرده‌اند (ویدیو/عکس/صوت) — فشرده‌سازی دوباره فقط CPU
# حرام می‌کند و بسته‌بندی چندصد مگابایت را ده‌ها دقیقه طول می‌دهد. این‌ها STORED.
_NO_COMPRESS_EXTS = frozenset({
    ".mp4", ".mov", ".mkv", ".avi", ".3gp", ".mpg", ".mpeg", ".webm",
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma", ".flac",
    ".zip", ".rar", ".7z", ".apk",
})


def _add_assets_and_dex(apk_path: Path, assets_dir: Path, dex_path: Path) -> None:
    """افزودن assets/... و classes.dex به داخل APK با zipfile.
    نام‌های غیر-ASCII (فارسی) به‌درستی با پرچم UTF-8 ذخیره می‌شوند.
    رسانه‌های ازپیش‌فشرده (mp4/jpg/ogg/...) بدون فشرده‌سازی (STORED) می‌روند تا
    بسته‌بندی چندصد مگابایت چند دقیقه — نه چند ده دقیقه — طول بکشد.
    """
    tmp = apk_path.with_suffix(".filled.apk")
    with zipfile.ZipFile(apk_path, "r") as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        if assets_dir.exists():
            for f in sorted(assets_dir.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(assets_dir).as_posix()
                    ctype = (zipfile.ZIP_STORED if f.suffix.lower() in _NO_COMPRESS_EXTS
                             else zipfile.ZIP_DEFLATED)
                    zout.write(str(f), "assets/" + rel, compress_type=ctype)
        zout.write(str(dex_path), "classes.dex")
    shutil.move(str(tmp), str(apk_path))
    log.info("assets + classes.dex به APK اضافه شد")
