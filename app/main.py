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

VERSION = "0.3.4"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
GRACE_S = 10   # stop this long after the last page closes (covers reloads)

# Default browsers known to accept --new-window (matched in the .desktop name)
NEW_WINDOW = ("firefox", "librewolf", "chrome", "chromium", "brave", "edge", "vivaldi", "opera")


def in_use(port):
    """True if something on this machine already answers on the port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def free_port(start, host):
    """The first port from `start` that is free on `host`, the address the server will use."""
    for port in range(start, start + 50):
        # macOS, unlike Linux, lets a socket with SO_REUSEADDR (below) share a
        # port another program listens on, and connections to 127.0.0.1 then
        # reach that program. So a port anything answers on counts as taken.
        if in_use(port):
            continue
        with socket.socket() as s:
            # As the server does: otherwise connections from the last run, closing
            # for about a minute, make the port look taken, and the app moves to
            # the next one, where the editor's saved layout and units aren't found.
            # Not on Windows, where this would also let it share a port in use.
            if os.name != "nt":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found")


def lan_address():
    """This machine's address on the local network, or None when it has none.

    Connecting a UDP socket sends nothing: it only picks the interface that
    would reach the address given, here one reserved for documentation.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
        except OSError:
            return None


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
        except (OSError, UnicodeDecodeError):
            continue
        if line:
            # Drop field codes (%u) and Flatpak's @@ markers; the URL is added later
            try:
                cmd = [t for t in shlex.split(line[5:]) if not t.startswith(("%", "@@"))]
            except ValueError:   # unbalanced quotes: leave it to xdg-open
                return None
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

    # Hide Werkzeug's log line for every request: this is a single-user local tool
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    from werkzeug.serving import make_server

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    port = free_port(args.port, host)
    url = f"http://127.0.0.1:{port}/"   # this machine's own window uses the local address
    app = create_app(os.path.abspath(args.data), lan=args.lan)
    server = make_server(host, port, app, threaded=True)
    # Stop with the window only when we opened it, and not when other machines may use it
    auto_stop = not args.no_browser and not args.lan
    print(f"Oh-Brother {VERSION} running at {url}  "
          + ("(closes with its window, or Ctrl+C)" if auto_stop else "(Ctrl+C to stop)"))
    if args.lan:
        ip = lan_address()
        print(f"Other devices: http://{ip}:{port}/" if ip
              else f"Other devices: this machine's network address, port {port}")
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
