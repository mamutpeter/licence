# dummy_server.py

import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))  # Бере порт з Render змінної середовища
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🛜 Dummy HTTP Server running on port {port}")
    server.serve_forever()

def start_server_in_thread():
    threading.Thread(target=run_dummy_server, daemon=True).start()
