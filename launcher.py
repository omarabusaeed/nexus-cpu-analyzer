"""
NEXUS CPU Analyzer — Application Launcher
This is the entry point used by PyInstaller.
It starts Flask, waits for it to be ready, then auto-opens the browser.
"""
import os
import sys
import time
import threading
import webbrowser

# ── Fix paths when running as a PyInstaller .exe ──────────────────
def resource_path(relative_path):
    """Get absolute path to resource — works for dev + PyInstaller bundle."""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller extracts files to a temp folder (_MEIPASS)
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)

# Point Flask to the correct template + static folders
os.environ['NEXUS_TEMPLATE_DIR'] = resource_path('templates')
os.environ['NEXUS_STATIC_DIR']   = resource_path('static')

# ── Import the Flask app ───────────────────────────────────────────
# Must happen AFTER setting env vars above
from app import app

PORT = 8050
URL  = f"http://localhost:{PORT}"

def open_browser():
    """Wait for Flask to start, then open the browser."""
    time.sleep(2.0)
    print(f"  Opening browser: {URL}")
    webbrowser.open(URL)

if __name__ == "__main__":
    print("\n" + "="*52)
    print("  NEXUS CPU Analyzer v1.0")
    print(f"  Dashboard: {URL}")
    print("  Close this window to stop NEXUS.")
    print("="*52 + "\n")

    # Open browser in a background thread (non-blocking)
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    # Start Flask (blocking — keeps the app alive)
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)

