import ctypes, time
import sys
# find window by title
user32 = ctypes.windll.user32
def find(title_part):
    results = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            t = buf.value
            if title_part.lower() in t.lower():
                results.append((hwnd, t))
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return results
for hwnd, t in find("Telegram Media Downloader"):
    print("found:", hex(hwnd), repr(t))
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.5)
time.sleep(2)
