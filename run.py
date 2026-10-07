"""Entry point: starts the local Flask server and opens the browser.

    python run.py                 normal start
    python run.py --reset-demo    back up and rebuild the demo database, then exit
Environment: RENTAL_NO_BROWSER=1 stops the browser from opening automatically.
"""
import os
import socket
import sys
import threading
import traceback
import webbrowser
from datetime import datetime

PREFERRED_PORT = 5000
HOST = "127.0.0.1"


def find_port(preferred=PREFERRED_PORT, tries=50):
    """Return the preferred port, or the next free one."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:   # any free port
        s.bind((HOST, 0))
        return s.getsockname()[1]


def log_startup_error():
    from app.config import Config
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    path = os.path.join(Config.LOG_DIR, "startup-error.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write("%s\n%s\n" % (datetime.now().isoformat(timespec="seconds"), traceback.format_exc()))
    return path


def main():
    if "--reset-demo" in sys.argv:
        from scripts.reset_db import reset
        reset()
        return
    from werkzeug.serving import make_server
    from app import create_app
    application = create_app()
    port = find_port()
    server = make_server(HOST, port, application, threaded=True)
    url = "http://%s:%d" % (HOST, port)
    application.logger.info("Server started at %s", url)
    print("Rental Management System is running at", url)
    print("Close this window to stop the application.")
    if not os.environ.get("RENTAL_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        where = log_startup_error()
        print("The application could not start. Details: " + where)
        if getattr(sys, "frozen", False):
            input("Press Enter to close...")
        sys.exit(1)
