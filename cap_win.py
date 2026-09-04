import sys, time
ctypes = __import__("ctypes")
user32 = ctypes.windll.user32

# find hwnd
def find(title_part):
    results = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)  # placeholder
    def _dummy(): pass
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_part.lower() in buf.value.lower():
                results.append(hwnd)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return results

hwnds = find("Telegram Media Downloader")
if not hwnds:
    print("NO WINDOW"); sys.exit(1)
hwnd = hwnds[0]
print("hwnd", hex(hwnd))
user32.SetForegroundWindow(hwnd)
time.sleep(1.5)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QWindow
app = QApplication(sys.argv)
w = QWindow.fromWinId(hwnd)
w.setFlags(w.flags() | 0x1)  # FramelessWindowHint hack to map
rect = w.frameGeometry()
print("size", rect.width(), rect.height())
# grab via screen using window id
screen = QApplication.primaryScreen()
im = screen.grabWindow(int(hwnd))
out = sys.argv[1] if len(sys.argv) > 1 else "win_cap2.png"
im.save(out)
print("saved", im.width(), "x", im.height())