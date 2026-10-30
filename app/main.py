"""Entry point. Run via run.sh, which picks the bundled Python runtime.

Python is started with -I (isolated), so this file sets up sys.path itself:
the app folder, then vendor/<platform> (compiled packages), then vendor/common.
"""

import argparse
import os
import socket
import subprocess
import sys
import threading
import webbrowser

VERSION = "0.1.2"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)


def free_port(start):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found")


def open_browser(url):
    # On Linux, detach the browser and drop its output: GTK browsers print
    # session warnings (e.g. atk-bridge) that would land in our terminal.
    if sys.platform.startswith("linux"):
        try:
            subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return
        except OSError:
            pass
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(description="Oh-Brother label printing")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--port", type=int, default=8620)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces, not just this machine")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    sys.path[:0] = [APP_DIR,
                    os.path.join(ROOT, "vendor", args.platform),
                    os.path.join(ROOT, "vendor", "common")]
    from server import create_app

    # Hide per-request logs and the "development server" warning: this is a
    # single-user local tool, not a public deployment.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"Oh-Brother {VERSION} running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.8, open_browser, [url]).start()
    create_app(os.path.abspath(args.data)).run(
        host="0.0.0.0" if args.lan else "127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
