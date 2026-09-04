import ctypes, time, sys
user32 = ctypes.windll.user32
def find(title_part):
    res=[]
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd,_):
        if user32.IsWindowVisible(hwnd):
            L=user32.GetWindowTextLengthW(hwnd); b=ctypes.create_unicode_buffer(L+1)
            user32.GetWindowTextW(hwnd,b,L+1)
            if title_part.lower() in b.value.lower(): res.append(hwnd)
        return True
    user32.EnumWindows(WNDENUMPROC(cb),0)
    return res
for t in ["Telegram Media Downloader","TelegramMediaTest"]:
    for h in find(t):
        print("found",t,hex(h))
        user32.ShowWindow(h,9)
        user32.SetForegroundWindow(h)
        time.sleep(0.6)
time.sleep(2)
