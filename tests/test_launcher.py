"""The launcher: main.py's helpers for the browser and the port, and run.sh
started as a user starts it."""

import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

import main
from . import ROOT


class BrowserCommand(unittest.TestCase):

    def command(self, exec_line, desktop="firefox.desktop"):
        """default_browser_cmd() with a default browser whose Exec= line is given."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "applications"))
        with open(os.path.join(tmp.name, "applications", desktop), "w", encoding="utf-8") as f:
            f.write(f"[Desktop Entry]\nExec={exec_line}\n")
        found = subprocess.CompletedProcess([], 0, stdout=desktop + "\n")
        env = {"XDG_DATA_HOME": tmp.name, "XDG_DATA_DIRS": tmp.name}
        with mock.patch.object(main.subprocess, "run", return_value=found), mock.patch.dict(os.environ, env):
            return main.default_browser_cmd()

    def test_field_codes_dropped(self):
        self.assertEqual(self.command("/usr/bin/firefox %u"), ["/usr/bin/firefox"])
        self.assertEqual(self.command("flatpak run org.mozilla.firefox @@u %u @@"),
                         ["flatpak", "run", "org.mozilla.firefox"])

    def test_unbalanced_quotes_leave_it_to_xdg_open(self):
        self.assertIsNone(self.command('"/usr/bin/firefox %u'))

    def test_browsers_without_new_window_skipped(self):
        self.assertIsNone(self.command("/usr/bin/other %u", desktop="other.desktop"))


class Ports(unittest.TestCase):

    def test_taken_port_skipped_on_the_servers_address(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            self.assertNotEqual(main.free_port(port, "127.0.0.1"), port)
            # Listening on all interfaces needs the port free on each, this one included
            self.assertNotEqual(main.free_port(port, "0.0.0.0"), port)

    def test_port_of_the_last_run_reused(self):
        # A run's closed connections wait about a minute (TIME_WAIT) on its port.
        # Linux lets the port be reused only if the old server allowed it too,
        # as Werkzeug's does.
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port)) as client:
                conn, _ = server.accept()
                conn.close()   # the side that closes first waits
                client.recv(1)
        self.assertEqual(main.free_port(port, "127.0.0.1"), port)

    def test_lan_address(self):
        ip = main.lan_address()
        self.assertTrue(ip is None or socket.inet_aton(ip))


class Startup(unittest.TestCase):
    """sh run.sh, on a free port with a temporary data folder."""

    def test_starts_answers_and_stops_with_ctrl_c(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = os.path.join(tmp.name, "data")
        port = main.free_port(8700, "127.0.0.1")
        proc = subprocess.Popen(["sh", os.path.join(ROOT, "run.sh"), "--no-browser", "--port", str(port),
                                 "--data", data], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(proc.kill)   # in case a check below fails first
        # Straight to this machine, whatever proxy the environment names
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 20
        while True:
            try:
                with opener.open(f"http://127.0.0.1:{port}/api/meta", timeout=1) as resp:
                    meta = json.load(resp)
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    self.fail("The app didn't start: " + (proc.communicate(timeout=5)[0] if proc.poll() is not None else "timed out"))
                time.sleep(0.1)
        self.assertIn("QL-820NWB", meta["models"])
        proc.send_signal(signal.SIGINT)   # Ctrl+C; run.sh has exec'd Python, so it gets it directly
        out = proc.communicate(timeout=10)[0]
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn(f"running at http://127.0.0.1:{port}/", out)
        self.assertTrue(os.path.isdir(os.path.join(data, "templates")))
