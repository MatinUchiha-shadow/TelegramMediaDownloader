import http.server
import socketserver
import threading
import time

PORT = 8770
DIRECTORY = "_preview_reply_demo"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    
    def log_message(self, format, *args):
        pass  # Suppress logs

httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
thread = threading.Thread(target=httpd.serve_forever, daemon=True)
thread.start()
print(f"Server started on http://127.0.0.1:{PORT}")
time.sleep(999999)  # Keep running
