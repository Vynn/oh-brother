"""Entry point. Run via run.sh, which picks the bundled Python runtime.

Python is started with -I (isolated), so this file sets up sys.path itself:
the app folder, then vendor/<platform> (compiled packages), then vendor/common.
"""

import argparse
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
import webbrowser

VERSION = "0.2.2"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
GRACE_S = 10   # stop this long after the last page closes (covers reloads)

# Default browsers known to accept --new-window (matched in the .desktop name)
NEW_WINDOW = ("firefox", "librewolf", "chrome", "chromium", "brave", "edge", "vivaldi", "opera")


def free_port(start):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found")


def default_browser_cmd():
    """Linux: the default browser's command, if it is one that takes --new-window."""
    try:
        desk = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not desk.endswith(".desktop") or not any(n in desk.lower() for n in NEW_WINDOW):
        return None
    dirs = [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")]
    dirs += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for d in dirs:
        try:
            with open(os.path.join(d, "applications", desk), encoding="utf-8") as f:
                line = next((l for l in f if l.startswith("Exec=")), None)
        except OSError:
            continue
        if line:
            # Drop field codes (%u) and Flatpak's @@ markers; the URL is added later
            cmd = [t for t in shlex.split(line[5:]) if not t.startswith(("%", "@@"))]
            return cmd or None
    return None


def open_browser(url):
    """Open the editor in a new window of the default browser where possible."""
    # On Linux, detach the browser and drop its output: GTK browsers print
    # session warnings (e.g. atk-bridge) that would land in our terminal.
    if sys.platform.startswith("linux"):
        cmd = default_browser_cmd()
        for argv in ([*cmd, "--new-window", url] if cmd else None, ["xdg-open", url]):
            if not argv:
                continue
            try:
                subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return
            except OSError:
                pass
    webbrowser.open(url, new=1)


def stop_when_closed(presence, server):
    """Shut the server down once no editor page has been open for GRACE_S."""
    while True:
        time.sleep(1)
        if presence.idle_for() > GRACE_S:
            print("Window closed; stopping.")
            server.shutdown()
            return


def main():
    ap = argparse.ArgumentParser(description="Oh-Brother label printing")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--port", type=int, default=8620)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces, not just this machine")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open a browser; keep running until Ctrl+C")
    args = ap.parse_args()

    sys.path[:0] = [APP_DIR,
                    os.path.join(ROOT, "vendor", args.platform),
                    os.path.join(ROOT, "vendor", "common")]
    from server import create_app

    # Hide per-request logs and the "development server" warning: this is a
    # single-user local tool, not a public deployment.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    from werkzeug.serving import make_server

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    app = create_app(os.path.abspath(args.data))
    server = make_server("0.0.0.0" if args.lan else "127.0.0.1", port, app, threaded=True)
    # Stop with the window only when we opened it, and not when other machines may use it
    auto_stop = not args.no_browser and not args.lan
    print(f"Oh-Brother {VERSION} running at {url}  "
          + ("(closes with its window, or Ctrl+C)" if auto_stop else "(Ctrl+C to stop)"))
    if not args.no_browser:
        threading.Timer(0.8, open_browser, [url]).start()
    if auto_stop:
        threading.Thread(target=stop_when_closed, args=(app.presence, server), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
