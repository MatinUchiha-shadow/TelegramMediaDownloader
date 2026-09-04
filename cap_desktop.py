import sys
import time
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
time.sleep(1)
screen = QApplication.primaryScreen()
im = screen.grabWindow(0)
out = sys.argv[1] if len(sys.argv) > 1 else "desktop_cap.png"
im.save(out)
print("saved", im.width(), "x", im.height())