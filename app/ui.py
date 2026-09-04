# -*- coding: utf-8 -*-
"""رابط کاربری برنامه (PySide6) — پنجرهٔ بدون کادر با افکت شیشه‌ای/بلور، تم تیره."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QFormLayout,
)

from app import exporter
from app.android_builder import build_android_app
from app.config import load_config, save_config
from app.downloader import DownloadWorker, sanitize_name
from app.logger_setup import get_emitter, get_logger
from app.tg_client import fetch_dialogs, is_logged_in, send_code, sign_in
from app.window_effects import enable_acrylic

log = get_logger("ui")

ACCENT = "#3390ec"
GLASS_BG = "rgba(16, 23, 40, 205)"
SIDEBAR_BG = "rgba(9, 14, 26, 120)"
CARD_BG = "rgba(255, 255, 255, 9)"
INPUT_BG = "rgba(0, 0, 0, 90)"
LIST_BG = "rgba(0, 0, 0, 75)"
BORDER = "rgba(255, 255, 255, 16)"

QSS = f"""
* {{ font-family: "Segoe UI", "Vazirmatn", "Tahoma", sans-serif; }}
QWidget {{ background-color: transparent; color: #e8eef7; font-size: 13px; }}
QMainWindow, QStackedWidget {{ background: transparent; }}

/* ---------- شیشهٔ اصلی ---------- */
QFrame#rootGlass {{
    background: {GLASS_BG};
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 16px;
}}
QFrame#rootGlassMax {{
    background: {GLASS_BG};
    border: none;
    border-radius: 0px;
}}

/* ---------- تایتل‌بار ---------- */
QFrame#titleBar {{ background: transparent; }}
QLabel#winTitle {{ font-size: 14px; font-weight: 700; color: #ffffff; }}
QLabel#winSub {{ color: #7d8ca3; font-size: 11px; }}
QPushButton#winBtn {{
    background: transparent; border: none; border-radius: 8px;
    color: #c7d3e4; font-size: 13px;
}}
QPushButton#winBtn:hover {{ background: rgba(255, 255, 255, 22); }}
QPushButton#winClose:hover {{ background: #e81123; color: white; }}

/* ---------- سایدبار ---------- */
QFrame#glassSidebar {{
    background: {SIDEBAR_BG};
    border-right: 1px solid rgba(255, 255, 255, 12);
}}
QLabel#appTitle {{ font-size: 16px; font-weight: 700; color: #ffffff; padding: 4px 16px 2px; }}
QLabel#appSub {{ color: #7d8ca3; font-size: 11px; padding: 0 16px 10px; }}
QPushButton#navBtn {{
    background: transparent; border: none; border-radius: 10px;
    padding: 10px 14px; margin: 2px 10px; text-align: left; font-size: 13.5px; color: #b9c6da;
}}
QPushButton#navBtn:hover {{ background: rgba(255, 255, 255, 14); color: #ffffff; }}
QPushButton#navBtn:checked {{
    background: rgba(51, 144, 236, 40); color: #ffffff; font-weight: 600;
    border: 1px solid rgba(51, 144, 236, 90);
}}
QLabel#sideFooter {{ color: #5f6e85; font-size: 11px; padding: 8px 16px; }}

/* ---------- تیتر صفحات ---------- */
QLabel#pageTitle {{ font-size: 20px; font-weight: 700; padding: 6px 0 2px; }}
QLabel#pageSub {{ color: #7d8ca3; font-size: 12.5px; margin-bottom: 12px; }}

/* ---------- دکمه‌ها ---------- */
QPushButton {{
    background: rgba(255, 255, 255, 12); border: 1px solid {BORDER};
    border-radius: 9px; padding: 9px 18px; color: #dbe6f5;
}}
QPushButton:hover {{ background: rgba(255, 255, 255, 20); }}
QPushButton:pressed {{ background: rgba(255, 255, 255, 26); }}
QPushButton:disabled {{ color: #5a6b8a; background: rgba(255, 255, 255, 6); border-color: rgba(255,255,255,8); }}
QPushButton#primary {{ background: {ACCENT}; color: #ffffff; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #2f86da; }}
QPushButton#primary:disabled {{ background: rgba(51, 144, 236, 80); color: #9db8d6; }}
QPushButton#danger {{ background: rgba(192, 57, 43, 220); color: #fff; border: none; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {BORDER}; }}

/* ---------- ورودی‌ها ---------- */
QLineEdit, QPlainTextEdit {{
    background: {INPUT_BG}; border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 9px; padding: 9px 12px; selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}

/* ---------- چک‌باکس ---------- */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid rgba(255, 255, 255, 40); background: {INPUT_BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* ---------- لیست چت‌ها ---------- */
QListWidget {{
    background: {LIST_BG}; border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 12px; padding: 5px; outline: none;
}}
QListWidget::item {{ border-radius: 10px; margin: 1px 0; }}
QListWidget::item:hover {{ background: rgba(255, 255, 255, 12); }}
QListWidget::item:selected {{ background: rgba(51, 144, 236, 70); }}

/* ---------- نوار پیشرفت ---------- */
QProgressBar {{
    background: {INPUT_BG}; border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 8px; text-align: center; color: #dbe6f5; font-size: 12px; height: 22px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 7px; }}

/* ---------- کارت‌ها ---------- */
QFrame#card {{
    background: {CARD_BG}; border: 1px solid rgba(255, 255, 255, 14);
    border-radius: 14px;
}}
QLabel#hint {{ color: #8fa2c0; font-size: 12px; }}
QLabel#status {{ color: #6fdb8a; font-size: 12.5px; }}
QLabel#statusErr {{ color: #ff7b72; font-size: 12.5px; }}
QPlainTextEdit#logView {{ background: rgba(0, 0, 0, 130); border-color: rgba(255,255,255,12); font-family: Consolas, monospace; font-size: 12px; }}

/* ---------- اسکرول‌بار ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 45); border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 80); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(255, 255, 255, 45); border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""


def open_folder(path: str) -> None:
    p = str(Path(path))
    try:
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:
        log.warning("باز کردن پوشه ناموفق: %s", e)


# --------------------------------------------------------------------------
# کارگرهای ترد
# --------------------------------------------------------------------------
class TaskRunner(QThread):
    """اجرای یک تابع ناهمگام (coroutine) در ترد جداگانه."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, corofunc, *args):
        super().__init__()
        self._corofunc = corofunc
        self._args = args

    def run(self) -> None:
        try:
            result = asyncio.run(self._corofunc(*self._args))
            self.finished.emit(result)
        except Exception as e:
            log.exception("Task failed")
            self.failed.emit(str(e))


class ExportWorker(QThread):
    finished = Signal(str)  # پیام
    failed = Signal(str)

    def __init__(self, account_dir: Path):
        super().__init__()
        self.account_dir = account_dir

    def run(self) -> None:
        try:
            exporter.ensure_assets(self.account_dir)
            n = 0
            chats_dir = self.account_dir / exporter.CHATS_DIR
            if chats_dir.exists():
                for sub in sorted(chats_dir.iterdir()):
                    if sub.is_dir():
                        exporter.generate_chat_page(sub, self.account_dir)
                        n += 1
            exporter.generate_index(self.account_dir)
            self.finished.emit(f"خروجی HTML برای {n} چت ساخته شد ✅")
        except Exception as e:
            log.exception("Export failed")
            self.failed.emit(str(e))


class AndroidBuildWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, account_dir: Path, out_dir: Path):
        super().__init__()
        self.account_dir = account_dir
        self.out_dir = out_dir

    def run(self) -> None:
        try:
            project = build_android_app(self.account_dir, self.out_dir)
            self.finished.emit(str(project))
        except Exception as e:
            log.exception("Android build failed")
            self.failed.emit(str(e))


# --------------------------------------------------------------------------
# تایتل‌بار سفارشی (بدون کادر ویندوز)
# --------------------------------------------------------------------------
class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(46)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)

        title = QLabel("Telegram Downloader")
        title.setObjectName("winTitle")
        sub = QLabel("آرشیو کامل تلگرام")
        sub.setObjectName("winSub")
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addStretch(1)

        self.min_btn = self._btn("🗕", self._minimize)
        self.max_btn = self._btn("🗖", self._toggle_max)
        self.close_btn = self._btn("✕", self._close)
        self.close_btn.setObjectName("winBtn winClose")
        lay.addWidget(self.min_btn)
        lay.addWidget(self.max_btn)
        lay.addWidget(self.close_btn)

    def _btn(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("winBtn")
        b.setFixedSize(42, 30)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _minimize(self) -> None:
        self.window().showMinimized()

    def _toggle_max(self) -> None:
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    def _close(self) -> None:
        self.window().close()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()


# --------------------------------------------------------------------------
# ردیف چت (دو خطی با آیکون رنگی و نشان جدید)
# --------------------------------------------------------------------------
class ChatItemWidget(QWidget):
    TYPE_ICON = {"user": "👤", "group": "👥", "channel": "📢", "unknown": "💬"}
    TYPE_COLOR = {"user": "#1e88e5", "group": "#43a047", "channel": "#e53935", "unknown": "#8a98a5"}
    TYPE_NAME = {"user": "گفتگوی خصوصی", "group": "گروه", "channel": "کانال", "unknown": "چت"}

    def __init__(self, dialog: dict, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)

        icon = QLabel(self.TYPE_ICON.get(dialog.get("type"), "💬"))
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background: {self.TYPE_COLOR.get(dialog.get('type'), '#8a98a5')}3d;"
            f"border-radius: 13px; font-size: 19px;"
        )
        lay.addWidget(icon)

        v = QVBoxLayout()
        v.setSpacing(2)
        t = QLabel(dialog.get("title", ""))
        t.setStyleSheet("font-weight: 600; font-size: 13.5px;")
        t.setWordWrap(False)
        sub_txt = self.TYPE_NAME.get(dialog.get("type"), "چت")
        if dialog.get("unread"):
            sub_txt += f"  ·  {dialog['unread']} جدید"
        s = QLabel(sub_txt)
        s.setStyleSheet("color: #7d8ca3; font-size: 11.5px;")
        v.addWidget(t)
        v.addWidget(s)
        lay.addLayout(v, 1)

        if dialog.get("unread"):
            badge = QLabel(str(dialog["unread"]))
            badge.setStyleSheet(
                f"background: {ACCENT}; color: white; border-radius: 11px;"
                f"padding: 2px 9px; font-size: 11px; font-weight: 600;"
            )
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(badge)


# --------------------------------------------------------------------------
# صفحات
# --------------------------------------------------------------------------
class LoginPage(QWidget):
    logged_in = Signal()

    def __init__(self):
        super().__init__()
        self._task = None
        self.cfg = load_config()
        self._build_ui()
        self._check_session()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 20)

        title = QLabel("ورود به تلگرام")
        title.setObjectName("pageTitle")
        sub = QLabel("برای دریافت api_id و api_hash از my.telegram.org وارد شوید (نکته: باید ابتدا در آنجا یک اپ بسازید).")
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(22, 20, 22, 20)
        form.setSpacing(12)

        self.api_id = QLineEdit(self.cfg.get("api_id", ""))
        self.api_id.setPlaceholderText("مثلاً 1234567")
        self.api_id.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.api_hash = QLineEdit(self.cfg.get("api_hash", ""))
        self.api_hash.setPlaceholderText("مثلاً 0123456789abcdef0123456789abcdef")
        self.api_hash.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.phone = QLineEdit(self.cfg.get("phone", ""))
        self.phone.setPlaceholderText("مثلاً +989121234567")
        self.phone.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code = QLineEdit()
        self.code.setPlaceholderText("کد ۵ رقمی پیامک‌شده")
        self.code.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code.setEnabled(False)
        self.password = QLineEdit()
        self.password.setPlaceholderText("رمز دومرحله‌ای (فقط در صورت داشتن)")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setEnabled(False)

        form.addRow("api_id:", self.api_id)
        form.addRow("api_hash:", self.api_hash)
        form.addRow("شماره موبایل:", self.phone)

        self.send_btn = QPushButton("ارسال کد")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self._send_code)
        form.addRow("", self.send_btn)

        self.form2 = QWidget()
        f2 = QFormLayout(self.form2)
        f2.setContentsMargins(0, 0, 0, 0)
        f2.addRow("کد ورود:", self.code)
        f2.addRow("رمز دومرحله‌ای:", self.password)
        self.login_btn = QPushButton("ورود")
        self.login_btn.setObjectName("primary")
        self.login_btn.setEnabled(False)
        self.login_btn.clicked.connect(self._login)
        f2.addRow("", self.login_btn)
        form.addRow("", self.form2)

        lay.addWidget(card)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)

    def _check_session(self) -> None:
        if not (self.cfg.get("api_id") and self.cfg.get("api_hash")):
            return
        self.status.setText("بررسی نشست قبلی…")

        def done(ok):
            if ok:
                self.status.setText("نشست قبلی معتبر است ✅")
                self.logged_in.emit()

        self._task = TaskRunner(is_logged_in, self.cfg)
        self._task.finished.connect(lambda res: done(bool(res)))
        self._task.failed.connect(lambda e: self.status.setText(f"خطا: {e}"))
        self._task.start()

    def _save(self) -> bool:
        self.cfg["api_id"] = self.api_id.text().strip()
        self.cfg["api_hash"] = self.api_hash.text().strip()
        self.cfg["phone"] = self.phone.text().strip()
        if not (self.cfg["api_id"] and self.cfg["api_hash"] and self.cfg["phone"]):
            self.status.setText("⚠️ api_id، api_hash و شماره موبایل را کامل وارد کنید.")
            return False
        save_config(self.cfg)
        return True

    def _send_code(self) -> None:
        if not self._save():
            return
        self.send_btn.setEnabled(False)
        self.status.setText("در حال ارسال کد…")
        self._task = TaskRunner(send_code, self.cfg, self.cfg["phone"])
        self._task.finished.connect(self._code_sent)
        self._task.failed.connect(self._task_failed)
        self._task.start()

    def _code_sent(self, _res) -> None:
        self.send_btn.setEnabled(True)
        self.code.setEnabled(True)
        self.login_btn.setEnabled(True)
        self.status.setText("کد ارسال شد ✅ — کد را وارد و «ورود» را بزنید.")

    def _login(self) -> None:
        self.login_btn.setEnabled(False)
        self.status.setText("در حال ورود…")
        pwd = self.password.text() if self.password.isEnabled() else None
        self._task = TaskRunner(sign_in, self.cfg, self.cfg["phone"], self.code.text().strip(), pwd)
        self._task.finished.connect(self._login_ok)
        self._task.failed.connect(self._login_failed)
        self._task.start()

    def _login_ok(self, name) -> None:
        self.status.setText(f"خوش آمدید {name} ✅")
        self.logged_in.emit()

    def _login_failed(self, err: str) -> None:
        self.login_btn.setEnabled(True)
        if err == "2FA":
            self.password.setEnabled(True)
            self.status.setText("این حساب رمز دومرحله‌ای دارد — رمز را وارد کنید.")
        else:
            self.status.setText(f"❌ {err}")

    def _task_failed(self, err: str) -> None:
        self.send_btn.setEnabled(True)
        self.status.setText(f"❌ {err}")


class ChatsPage(QWidget):
    chat_selected = Signal(dict)

    def __init__(self):
        super().__init__()
        self._task = None
        self._dialogs = []
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 20)

        title = QLabel("چت‌ها و گروه‌ها")
        title.setObjectName("pageTitle")
        lay.addWidget(title)
        sub = QLabel("همهٔ گفتگوها، گروه‌ها و کانال‌های شما. با دوبار کلیک روی هر کدام، کل تاریخچه‌اش دانلود می‌شود (از اولین پیام تا آخرین).")
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی چت…")
        self.search.textChanged.connect(self._filter)
        self.refresh_btn = QPushButton("بارگذاری چت‌ها")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(self.load_dialogs)
        row.addWidget(self.search, 1)
        row.addWidget(self.refresh_btn)
        lay.addLayout(row)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._pick)
        lay.addWidget(self.list, 1)

        pick_row = QHBoxLayout()
        self.pick_btn = QPushButton("دانلود این چت ⬇")
        self.pick_btn.setObjectName("primary")
        self.pick_btn.clicked.connect(self._pick_current)
        pick_row.addWidget(self.pick_btn)
        pick_row.addStretch(1)
        lay.addLayout(pick_row)

        self.status = QLabel("")
        self.status.setObjectName("status")
        lay.addWidget(self.status)

    def load_dialogs(self) -> None:
        cfg = load_config()
        self.refresh_btn.setEnabled(False)
        self.status.setText("در حال دریافت چت‌ها…")
        self._task = TaskRunner(fetch_dialogs, cfg)
        self._task.finished.connect(self._dialogs_loaded)
        self._task.failed.connect(self._dialogs_failed)
        self._task.start()

    def _dialogs_loaded(self, dialogs) -> None:
        self.refresh_btn.setEnabled(True)
        self._dialogs = dialogs
        self.list.clear()
        for d in dialogs:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, d)
            item.setSizeHint(QSize(0, 62))
            self.list.addItem(item)
            self.list.setItemWidget(item, ChatItemWidget(d))
        self.status.setText(f"{len(dialogs)} چت دریافت شد ✅ — روی چت دوبار کلیک کنید.")

    def _dialogs_failed(self, err: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(f"❌ {err}")

    def _filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            w = self.list.itemWidget(item)
            title = (w.dialog.get("title", "") if w else item.text()).lower()
            item.setHidden(bool(text) and text not in title)

    def _pick_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self._pick(item)

    def _pick(self, item) -> None:
        dialog = item.data(Qt.ItemDataRole.UserRole)
        if dialog:
            self.chat_selected.emit(dialog)


class DownloadPage(QWidget):
    def __init__(self):
        super().__init__()
        self.dialog = None
        self.account_dir: Path | None = None
        self._worker: DownloadWorker | None = None
        self._export_worker: ExportWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 20)

        title = QLabel("دانلود و خروجی")
        title.setObjectName("pageTitle")
        lay.addWidget(title)
        sub = QLabel("همهٔ پیام‌ها از اول تا آخر، مرتب و بدون تکراری دانلود می‌شوند. می‌توانید بعداً ادامه دهید.")
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        self.chat_label = QLabel("هنوز چتی انتخاب نشده — از صفحهٔ «چت‌ها» انتخاب کنید.")
        self.chat_label.setWordWrap(True)
        self.chat_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        v.addWidget(self.chat_label)

        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("پوشهٔ خروجی")
        self.dir_btn = QPushButton("انتخاب پوشه")
        self.dir_btn.setObjectName("ghost")
        self.dir_btn.clicked.connect(self._choose_dir)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.dir_btn)
        v.addLayout(dir_row)

        opts = QHBoxLayout()
        self.media_cb = QCheckBox("دانلود فایل‌ها و رسانه‌ها (عکس، ویدیو، صوت، سند)")
        self.media_cb.setChecked(True)
        self.text_cb = QCheckBox("ذخیرهٔ متن پیام‌ها")
        self.text_cb.setChecked(True)
        opts.addWidget(self.media_cb)
        opts.addWidget(self.text_cb)
        opts.addStretch(1)
        v.addLayout(opts)

        self.msg_bar = QProgressBar()
        self.msg_bar.setRange(0, 100)
        self.msg_bar.setValue(0)
        v.addWidget(self.msg_bar)

        self.file_bar = QProgressBar()
        self.file_bar.setRange(0, 100)
        self.file_bar.setValue(0)
        self.file_bar.setFormat("")
        v.addWidget(self.file_bar)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("شروع دانلود ⬇")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("توقف")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.export_btn = QPushButton("ساخت خروجی HTML")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._make_export)
        self.open_btn = QPushButton("باز کردن پوشه")
        self.open_btn.setObjectName("ghost")
        self.open_btn.clicked.connect(self._open_dir)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.export_btn)
        btns.addWidget(self.open_btn)
        btns.addStretch(1)
        v.addLayout(btns)

        lay.addWidget(card)
        lay.addStretch(1)

        cfg = load_config()
        self.dir_edit.setText(cfg.get("export_root", ""))

    def set_chat(self, dialog: dict) -> None:
        self.dialog = dialog
        self.chat_label.setText(f"چت انتخاب‌شده: {dialog['title']}  ({self._type_name(dialog['type'])})")
        self._prepare_account_dir()

    def _type_name(self, t: str) -> str:
        return {"user": "خصوصی", "group": "گروه", "channel": "کانال"}.get(t, t)

    def _prepare_account_dir(self) -> None:
        export_root = Path(self.dir_edit.text().strip() or Path.home() / "Desktop")
        account = sanitize_name(self.dialog.get("self_name") or str(self.dialog.get("self_id", "account"))) + "_export"
        self.account_dir = export_root / account
        self.account_dir.mkdir(parents=True, exist_ok=True)

    def _choose_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "پوشهٔ خروجی", self.dir_edit.text())
        if p:
            self.dir_edit.setText(p)
            cfg = load_config()
            cfg["export_root"] = p
            save_config(cfg)
            self._prepare_account_dir()

    def _start(self) -> None:
        if not self.dialog:
            QMessageBox.information(self, "نکته", "اول از صفحهٔ «چت‌ها» یک چت را انتخاب کنید.")
            return
        self._prepare_account_dir()
        chat_dir = self.account_dir / exporter.CHATS_DIR / sanitize_name(self.dialog["title"])
        options = {"media": self.media_cb.isChecked(), "text": self.text_cb.isChecked()}

        cfg = load_config()
        self._worker = DownloadWorker(cfg, self.dialog, chat_dir, options, None)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.status.connect(self._on_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.msg_bar.setValue(0)
        self.file_bar.setValue(0)
        self.status.setText("دانلود شروع شد…")

    def _stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self.status.setText("در حال توقف… (تا پایان فایل جاری صبر کنید)")

    def _on_progress(self, _key, done, total, pct, label) -> None:
        self.msg_bar.setValue(int(pct))
        self.msg_bar.setFormat(f"{label}  ·  {pct:.0f}%")
        self.status.setText(label)

    def _on_file_progress(self, _key, pct, label) -> None:
        self.file_bar.setValue(int(pct))
        self.file_bar.setFormat(label)

    def _on_status(self, _key, msg) -> None:
        self.status.setText(msg)

    def _on_finished(self, _key, stats) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.file_bar.setValue(100)
        self.file_bar.setFormat("")
        self.msg_bar.setValue(100 if stats.get("total") else 0)
        total = stats.get("total") or 0
        done = stats.get("count") or 0
        self.status.setText(
            f"✅ {done} از {total} پیام · {stats.get('media', 0)} فایل دانلود شد "
            f"({stats.get('skipped_media', 0)} فایل از قبل موجود بود)"
        )
        self.export_btn.setEnabled(True)
        self._make_export()

    def _on_failed(self, _key, err: str) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"❌ {err}")

    def _make_export(self) -> None:
        if not self.account_dir:
            return
        self.export_btn.setEnabled(False)
        self.status.setText("در حال ساخت خروجی HTML…")
        self._export_worker = ExportWorker(self.account_dir)
        self._export_worker.finished.connect(self._export_done)
        self._export_worker.failed.connect(self._export_failed)
        self._export_worker.start()

    def _export_done(self, msg: str) -> None:
        self.export_btn.setEnabled(True)
        self.status.setText(f"{msg} — مسیر: {self.account_dir}")

    def _export_failed(self, err: str) -> None:
        self.export_btn.setEnabled(True)
        self.status.setText(f"❌ خطا در ساخت خروجی: {err}")

    def _open_dir(self) -> None:
        d = self.account_dir if self.account_dir else self.dir_edit.text()
        if d:
            open_folder(str(d))


class AndroidPage(QWidget):
    def __init__(self, get_account_dir):
        super().__init__()
        self.get_account_dir = get_account_dir
        self._worker: AndroidBuildWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 20)

        title = QLabel("ساخت اپ اندروید")
        title.setObjectName("pageTitle")
        lay.addWidget(title)
        sub = QLabel(
            "از خروجی HTML یک پروژهٔ اپ اندروید (WebView) ساخته می‌شود. "
            "با Android Studio آن را باز کنید و Build APK بزنید. "
            "هر بار با نام یکتا ساخته می‌شود تا خطای تداخل/آپدیت پیش نیاید."
        )
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        self.src_label = QLabel("خروجی: هنوز خروجی‌ای ساخته نشده.")
        self.src_label.setWordWrap(True)
        v.addWidget(self.src_label)

        row = QHBoxLayout()
        self.build_btn = QPushButton("ساخت اپ اندروید 📱")
        self.build_btn.setObjectName("primary")
        self.build_btn.clicked.connect(self._build)
        self.open_btn = QPushButton("باز کردن پوشهٔ خروجی")
        self.open_btn.setObjectName("ghost")
        self.open_btn.clicked.connect(self._open_out)
        row.addWidget(self.build_btn)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        v.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        lay.addWidget(card)
        lay.addStretch(1)

    def refresh(self) -> None:
        account_dir = self.get_account_dir()
        if account_dir:
            self.src_label.setText(f"خروجی: {account_dir}")
            self.build_btn.setEnabled(True)
        else:
            self.build_btn.setEnabled(False)

    def _build(self) -> None:
        account_dir = self.get_account_dir()
        if not account_dir:
            QMessageBox.information(self, "نکته", "اول یک چت را دانلود کنید تا خروجی ساخته شود.")
            return
        out_dir = account_dir.parent
        self.build_btn.setEnabled(False)
        self.status.setText("در حال ساخت پروژهٔ اندروید… (ممکن است کمی طول بکشد)")
        self._worker = AndroidBuildWorker(account_dir, out_dir)
        self._worker.finished.connect(self._build_done)
        self._worker.failed.connect(self._build_failed)
        self._worker.start()

    def _build_done(self, project: str) -> None:
        self.build_btn.setEnabled(True)
        self.status.setText(f"✅ پروژه ساخته شد: {project}")
        self._last_project = project

    def _build_failed(self, err: str) -> None:
        self.build_btn.setEnabled(True)
        self.status.setText(f"❌ {err}")

    def _open_out(self) -> None:
        account_dir = self.get_account_dir()
        if account_dir:
            open_folder(str(account_dir.parent))


class LogPage(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 20)

        title = QLabel("لاگ برنامه")
        title.setObjectName("pageTitle")
        lay.addWidget(title)
        sub = QLabel("همهٔ رویدادها اینجا و در فایل logs/app.log ثبت می‌شوند.")
        sub.setObjectName("pageSub")
        lay.addWidget(sub)

        self.view = QPlainTextEdit()
        self.view.setObjectName("logView")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        lay.addWidget(self.view, 1)

        row = QHBoxLayout()
        clear_btn = QPushButton("پاک کردن")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self.view.clear)
        row.addWidget(clear_btn)
        row.addStretch(1)
        lay.addLayout(row)

        get_emitter().message.connect(self.view.appendPlainText)


# --------------------------------------------------------------------------
# پنجرهٔ اصلی
# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Media Downloader — آرشیو تلگرام")
        self.resize(1080, 700)
        self.setMinimumSize(880, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setStyleSheet(QSS)
        self._effects_applied = False

        # ---------- ریشهٔ شیشه‌ای ----------
        self.root = QFrame()
        self.root.setObjectName("rootGlass")
        outer = QVBoxLayout(self.root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.titlebar = TitleBar(self.root)
        outer.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ---------- سایدبار ----------
        sidebar = QFrame()
        sidebar.setObjectName("glassSidebar")
        sidebar.setFixedWidth(230)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 6, 0, 12)
        sb.setSpacing(2)

        app_title = QLabel("Telegram Downloader")
        app_title.setObjectName("appTitle")
        app_sub = QLabel("آرشیو کامل چت‌ها")
        app_sub.setObjectName("appSub")
        sb.addWidget(app_title)
        sb.addWidget(app_sub)

        self.stack = QStackedWidget()
        self.login_page = LoginPage()
        self.chats_page = ChatsPage()
        self.download_page = DownloadPage()
        self.android_page = AndroidPage(self._current_account_dir)
        self.log_page = LogPage()
        for page in (self.login_page, self.chats_page, self.download_page, self.android_page, self.log_page):
            self.stack.addWidget(page)

        self.nav_buttons = {}
        for key, label in [
            ("login", "🔑  ورود"),
            ("chats", "💬  چت‌ها"),
            ("download", "⬇  دانلود و خروجی"),
            ("android", "📱  اپ اندروید"),
            ("log", "📋  لاگ"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self._goto(k))
            self.nav_buttons[key] = btn
            sb.addWidget(btn)

        sb.addStretch(1)
        footer = QLabel("نسخهٔ ۱.۰ — ساخته‌شده با ♥")
        footer.setObjectName("sideFooter")
        sb.addWidget(footer)
        self.nav_buttons["login"].setChecked(True)

        body.addWidget(sidebar)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(self.root)

        # ---------- سایهٔ پنجره ----------
        self._shadow = QGraphicsDropShadowEffect(self.root)
        self._shadow.setBlurRadius(48)
        self._shadow.setOffset(0, 10)
        self._shadow.setColor(QColor(0, 0, 0, 210))
        self.root.setGraphicsEffect(self._shadow)

        # ---------- اتصالات ----------
        self.login_page.logged_in.connect(lambda: self._goto("chats"))
        self.chats_page.chat_selected.connect(self._chat_picked)

    # ---------- افکت بلور ویندوز ----------
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._effects_applied:
            self._effects_applied = True
            QTimer.singleShot(80, self._apply_effects)

    def _apply_effects(self) -> None:
        try:
            hwnd = int(self.winId())
            enable_acrylic(hwnd)
        except Exception as exc:
            log.warning("فعال‌سازی بلور ناموفق: %s", exc)

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            if maximized:
                self.root.setObjectName("rootGlassMax")
                self.root.setStyleSheet(
                    f"QFrame#rootGlassMax {{ background: {GLASS_BG}; border: none; border-radius: 0px; }}"
                )
                self._shadow.setEnabled(False)
            else:
                self.root.setObjectName("rootGlass")
                self.root.setStyleSheet("")
                self._shadow.setEnabled(True)

    # ---------- ناوبری ----------
    def _goto(self, key: str) -> None:
        order = ["login", "chats", "download", "android", "log"]
        self.stack.setCurrentIndex(order.index(key))
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        if key == "chats":
            self.chats_page.load_dialogs()
        if key == "android":
            self.android_page.refresh()

    def _chat_picked(self, dialog: dict) -> None:
        self.download_page.set_chat(dialog)
        self._goto("download")

    def _current_account_dir(self):
        return self.download_page.account_dir
