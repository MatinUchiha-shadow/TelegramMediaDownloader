# 🚀 وضعیت پروژه — Freebuff Desktop (TelegramMediaDownloader)

> آخرین بهروزرسانی: ۱۴۰۵/۰۶/۰۸ (2026-08-29) — ساخت APK واقعی **کامل شد و تست شد** ✅

---

## ✅ کارهای امروز (کامل شد)

### ساخت APK واقعی و قابلنصب — DONE
- **`app/apk_builder.py`** نوشته شد: پایپلاین `aapt2 compile → link → تزریق assets+classes.dex با zipfile → zipalign → apksigner sign`
- **JRE 17 کوچک (۳۵MB)** با jlink ساخته شد → `android_bundle/jre17/` — امضای APK بدون نیاز به JDK نصبشده
- **`android_bundle/`** (۶۷MB) ساخته شد و داخل EXE باندل شد: aapt2.exe, zipalign.exe, apksigner.jar, android.jar, classes.dex, debug.keystore, jre17
- **۳ باگ مهم پیدا و حل شد:**
  1. aapt2 ویندوز نامهای **فارسی داخل assets** را نمیتواند باز کند → assets با `zipfile` پایتون تزریق میشود (نه `-A`)
  2. پکیج جاوا نباید با رقم شروع شود → hash با حرف `a` شروع میشود (`...a40e8825a`)
  3. apksigner (JRE 17) مسیرهای **غیر-ASCII** را نمیتواند بخواند (argv با cp1252) → امضا روی نام ASCII در temp، کپی نهایی با پایتون
- **GUI**: دکمهٔ ساخت بعد از دانلود، خودش APK میسازد و مسیرش را نشان میدهد (`📱 APK (قابل نصب مستقیم): ...`)
- **fallback**: اگر ابزارها نباشند → پروژهٔ Gradle + ZIP (مثل قبل)
- **پکیج یکتا** per ساخت (`ir.freebuff.tgviewer.<name>.a<hash>`) → چند اپ بدون خطای «update» کنار هم نصب میشوند
- APK نهایی روی **دسکتاپ** هم کپی میشود

### تستها (همه سبز)
- `selftest.py`: **۱۶/۱۶ ✅** (تست MainActivity به .java بهروز شد)
- ساخت APK از `demo_export` با ابزارهای باندلشدهٔ EXE (شبیهسازی `_MEIPASS`): ✅ امضا + badging + assets فارسی تأیید شد
- نمونه: `ir.freebuff.tgviewer.tg.a40e8825a` / label «آرشیو تست چت» / 805KB

### فایلهای نهایی
- **EXE روی دسکتاپ**: `C:\Users\Matin_uchiha\Desktop\TelegramMediaDownloader.exe` (۷۷.۵MB — شامل همهٔ ابزارهای ساخت APK)
- سورس: `C:\Users\Matin_uchiha\Desktop\Ai\`

---

## 📌 نکات فنی مهم (اگر دوباره نیاز شد)
- **SDK روی سیستم**: `C:\Users\Matin_uchiha\AppData\Local\Android\Sdk\` (build-tools/android-14 + platforms/android-34 + jre17)
- **گوگل مسدود است** (dl.google.com, maven.google.com همه ۴۰۴) → آینهٔ تنسنت باز است: `https://mirrors.cloud.tencent.com/AndroidSDK/`
- android.jar: `https://raw.githubusercontent.com/Sable/android-platforms/master/android-34/android.jar`
- **zip در سیستم نیست** → همیشه `zipfile` پایتون
- **apksigner با نام فارسی کار نمیکند** (هم ورودی هم خروجی) → فقط از طریق کپی پایتون
- **aapt2 با نام فارسی assets کار نمیکند** → تزریق با zipfile
- Python native ویندوز `/tmp` را نمیبیند — از مسیرهای `C:/...` استفاده کن

## 🔧 ساخت دوبارهٔ EXE
```bash
cd /c/Users/Matin_uchiha/Desktop/Ai
export PATH="$LOCALAPPDATA/Programs/Python/Python313:$LOCALAPPDATA/Programs/Python/Python313/Scripts:$PATH"
# بستن نمونههای قبلی:
for pid in $(tasklist 2>/dev/null | grep -i "TelegramMediaDownloader" | awk '{print $2}'); do taskkill //F //PID $pid; done
pyinstaller --clean TelegramMediaDownloader.spec
cp -f dist/TelegramMediaDownloader.exe "/c/Users/Matin_uchiha/Desktop/TelegramMediaDownloader.exe"
```

## ⏳ باقیمانده
- کاربر: اجرای واقعی → انتخاب یک چت → «📱 Android» → APK ساخته میشود → نصب روی گوشی (اجازهٔ «منابع ناشناس») → تست دو اپ کنار هم بدون update
- (اختیاری) اگر APK نصب نشد: چک `aapt2 dump badging` و `apksigner verify`

---

## 🆕 قابلیتهای جدید موتور مشاهدهٔ چت (اضافه شد ۱۴۰۵/۰۶/۰۸)
همه در `app/exporter.py` (CSS/JS + ساخت صفحه) — روی خروجیهای HTML و APK جدید اعمال میشود:
- **رندر پنجرهای (لگیز):** فقط ~۳۰ پیام بالا/پایین پیامِ در حال مشاهده در DOM است؛ بقیه بهصورت spacer تخمینی. کانال/گروه خیلی سنگین دیگر گوشی را کرش/لگ نمیکند. صفحهٔ HTML هم **جریان‌ی** (streaming) نوشته میشود — دیگر رشتهٔ غولآسا در رم ساخته نمیشود.
- **جستجو:** فقط پیامهای منطبق را در پنل جدا نشان میدهد؛ کلیک → پرش به همان پیام.
- **ویس:** فقط یک صدا همزمان پخش میشود؛ با تمام شدن یک ویس، خودکار ویس بعدی پخش میشود.
- **سرعت پخش:** دکمهٔ «۱×» → ۱.۵× → ۲× → ۳× (برای ویس/صدا/ویدیو).
- **دکمههای «⏮ اولین» و «آخرین ⏭»:** پرش به اولین/آخرین پیام.
- **ذخیرهٔ جای اسکرول:** موقعیت در localStorage با id پیام ذخیره و بعد از بستن/باز کردن برمیگردد (`history.scrollRestoration='manual'`).
- **زوم عکس:** لایتباکس با دکمههای +/−، چرخ ماوس، دابلتپ و پینچ + درگ.
- **فقط همان کانال در اپ:** `app/android_builder.build_single_chat()` + `exporter.make_single_chat_export()` → خروجی موقت تککانال (با hard link، بدون کپی دوبارهٔ رسانه) و APK/پروژه فقط از همان چت ساخته میشود — کانالهای قبلیِ جمعشده در پوشهٔ مشترک دیگر داخل اپ نمیآیند.
- **نام اپ = عنوان کانال:** `_unique_package` در `apk_builder.py` و `android_builder.py` دیگر پیشوند «آرشیو» نمیگذارد.
- مسیرها: `webview_backend._build_job` (EXE)، `web_server._api_build_android` (مرورگر)، `web_app.api_build_android` (Qt) همگی از `build_single_chat` استفاده میکنند؛ `html_gui/app.js` چت انتخابشده را میفرستد.
- تست: `selftest.py` حالا **۲۰/۲۰ ✅** (شامل تست تککانال).
- **✅ EXE دسکتاپ بازسازی شد (~۱۰:۴۷):** `pyinstaller --clean TelegramMediaDownloader.spec` اجرا و به `Desktop/TelegramMediaDownloader.exe` کپی شد — از این پس هر APK جدید همهٔ قابلیتها را دارد (EXE قبلی ۰۵:۳۰ بود و قدیمی بود؛ علت «ندیدن» قابلیتها).

---

## 🐛 فیکس «App not installed as app isn't compatible with your phone» (اضافه شد ۰۵:۴۶)
علت: aapt2 بدون `--target-sdk-version` مقدار **۱** میگذاشت → اندروید ۱۴/۱۵ نصب را بلاک میکند.
فیکس: در `app/apk_builder.py` به aapt2 link اضافه شد `--min-sdk-version 21 --target-sdk-version 34`
و در `android_template/app/src/main/AndroidManifest.xml` تگ `<uses-sdk android:minSdkVersion="21" android:targetSdkVersion="34"/>`.
همچنین نام فایل APK **ASCII** شد (`chat_<hash>_<stamp>.apk`) چون بعضی گوشیها (شیائومی) APK با نام فارسی را همینطور بلاک میکنند — label فارسی میماند.
تأییدشده: badging = `sdkVersion:'21' targetSdkVersion:'34'`، امضا v1+v2+v3 ✅
