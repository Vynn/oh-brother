"""Images from a web address: remote.fetch_image() and /api/image-url, against
a small web server on this machine. Fetching from this machine is refused in
the app, so the tests allow it, and check separately that it's refused."""

import base64
import http.server
import io
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from PIL import Image

import remote
import server

PNG = io.BytesIO()
Image.new("RGB", (40, 20), (0, 0, 0)).save(PNG, "PNG")
PNG = PNG.getvalue()
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'
BOMB = (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">'
        + b"".join(b'<!ENTITY %c "&%c;&%c;&%c;&%c;&%c;&%c;&%c;&%c;&%c;&%c;">' % ((c,) + (c - 1,) * 10)
                   for c in range(ord("b"), ord("k")))
        + b']><svg xmlns="http://www.w3.org/2000/svg">&j;</svg>')


class Site(http.server.BaseHTTPRequestHandler):
    """Pages for the tests, by path."""

    def log_message(self, *args):   # keep the test output quiet
        pass

    def send(self, code, body=b"", kind="image/png", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/logo.png":
            self.send(200, PNG)
        elif path == "/icon.svg":
            self.send(200, SVG, "image/svg+xml")
        elif path == "/page.html":
            self.send(200, b"<html><body>Not an image</body></html>", "text/html")
        elif path == "/pretend.png":   # says it's an image, isn't
            self.send(200, b"<html>hello</html>")
        elif path == "/bomb.svg":
            self.send(200, BOMB, "image/svg+xml")
        elif path == "/to-logo":
            self.send(302, headers=[("Location", "/logo.png")])
        elif path == "/to-link-local":
            self.send(302, headers=[("Location", "http://169.254.169.254/logo.png")])
        elif path == "/to-file":
            self.send(302, headers=[("Location", "file:///etc/hostname")])
        elif path == "/loop":
            self.send(302, headers=[("Location", "/loop")])
        elif path == "/says-big.png":
            self.send_response(200)
            self.send_header("Content-Length", str(remote.MAX_BYTES + 1))
            self.end_headers()
        elif path == "/endless.png":   # no length given, more than allowed
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(remote.MAX_BYTES // 1000 + 2):
                    self.wfile.write(b"x" * 1000)
            except OSError:   # the app stops reading
                pass
        elif path == "/slow.png":
            time.sleep(remote.TIMEOUT_S + 0.5)
            self.send(200, PNG)
        else:
            self.send(404, b"", "text/plain")


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass   # the app hanging up early, on purpose: too large, too slow


class SiteTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.site = Server(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.site.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()
        cls.site.server_close()

    def setUp(self):
        # This machine is allowed, so the test site can be reached; other refusals stay
        original = remote.refused
        allow = mock.patch.object(remote, "refused", lambda ip: None if ip.is_loopback else original(ip))
        allow.start()
        self.addCleanup(allow.stop)

    def fetch(self, path):
        return remote.fetch_image(self.base + path)

    def refused_with(self, path, msg):
        with self.assertRaises(remote.FetchError) as cm:
            self.fetch(path)
        self.assertEqual(str(cm.exception), msg)


class Fetching(SiteTest):

    def test_png(self):
        out = self.fetch("/logo.png?size=2")
        self.assertEqual(out["data"], "data:image/png;base64," + base64.b64encode(PNG).decode())
        self.assertEqual((out["name"], out["url"]), ("logo.png", self.base + "/logo.png?size=2"))

    def test_svg(self):
        self.assertTrue(self.fetch("/icon.svg")["data"].startswith("data:image/svg+xml;base64,"))

    def test_redirect_to_an_image(self):
        self.assertTrue(self.fetch("/to-logo")["data"].startswith("data:image/png;base64,"))

    def test_only_images_come_back(self):
        not_image = "That address isn't an image: use one ending in a PNG, JPEG, WebP, GIF or SVG file"
        for path in ("/page.html", "/pretend.png", "/bomb.svg"):
            with self.subTest(path):
                self.refused_with(path, not_image)

    def test_not_found(self):
        self.refused_with("/nothing.png", "Couldn't get it: 404 Not Found")

    def test_redirects_are_checked(self):
        self.refused_with("/to-link-local", "Refused: link-local addresses can't be used")
        with self.assertRaises(remote.FetchError) as cm:
            self.fetch("/to-file")
        self.assertIn("not allowed", str(cm.exception))
        with self.assertRaises(remote.FetchError):
            self.fetch("/loop")

    def test_too_large(self):
        self.refused_with("/says-big.png", "It's over 10 MB")
        with mock.patch.object(remote, "MAX_BYTES", 1024 * 1024):   # a smaller cap, to keep the test quick
            self.refused_with("/endless.png", "It's over 1 MB")

    def test_too_slow(self):
        with mock.patch.object(remote, "TIMEOUT_S", 0.3):
            self.refused_with("/slow.png", "It took longer than 0.3 seconds")


class Addresses(unittest.TestCase):

    def check(self, url):
        with self.assertRaises(remote.FetchError) as cm:
            remote.fetch_image(url)
        return str(cm.exception)

    def test_input_is_checked_before_anything_is_fetched(self):
        cases = {
            None: "Enter the image's address",
            "   ": "Enter the image's address",
            "https://example.com/" + "a" * remote.MAX_URL: f"That address is longer than {remote.MAX_URL} characters",
            "https://exa mple.com/a.png": "That address has spaces or control characters in it",
            "https://example.com/a.png\n": None,   # surrounding whitespace is trimmed
            "https://example.com/\x07.png": "That address has spaces or control characters in it",
            "file:///etc/hostname": "Only http and https addresses can be used",
            "javascript:alert(1)": "Only http and https addresses can be used",
            "data:image/png;base64,AAAA": "Only http and https addresses can be used",
            "ftp://example.com/a.png": "Only http and https addresses can be used",
            "https:///a.png": "That address has no host",
            "https://user:secret@example.com/a.png": "Addresses with a user name or password can't be used",
            "https://example.com:99999/a.png": "That isn't a web address",
        }
        with mock.patch.object(remote.socket, "getaddrinfo", side_effect=AssertionError("looked up")):
            for url, msg in cases.items():
                with self.subTest(url=url):
                    if msg is None:
                        self.assertEqual(remote.check_url(url), url.strip())
                    else:
                        self.assertEqual(self.check(url), msg)

    def test_this_machine_and_link_local_are_refused(self):
        for url in ("http://127.0.0.1/a.png", "http://localhost/a.png", "http://[::1]/a.png",
                    "http://[::ffff:127.0.0.1]/a.png", "http://0.0.0.0/a.png"):
            with self.subTest(url):
                self.assertEqual(self.check(url), "Refused: that address is this machine")
        self.assertEqual(self.check("http://169.254.169.254/a.png"), "Refused: link-local addresses can't be used")
        self.assertEqual(self.check("http://[fe80::1]/a.png"), "Refused: link-local addresses can't be used")

    def test_private_network_addresses_are_allowed(self):
        # A logo on a NAS: the check passes, so only the (here, stopped) download can fail
        for ip in ("192.168.1.50", "10.0.0.2", "172.16.0.9", "fd00::1"):
            with self.subTest(ip):
                self.assertIsNone(remote.refused(remote.ipaddress.ip_address(ip)))


class Endpoint(SiteTest):

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.client = server.create_app(os.path.join(tmp.name, "data")).test_client()

    def test_image_from_an_address(self):
        out = self.client.post("/api/image-url", json={"url": self.base + "/logo.png"}).get_json()
        self.assertEqual(out["name"], "logo.png")
        self.assertTrue(out["data"].startswith("data:image/png;base64,"))

    def test_errors_are_messages(self):
        resp = self.client.post("/api/image-url", json={"url": self.base + "/page.html"})
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.get_json()["error"].startswith("That address isn't an image"))
        self.assertEqual(self.client.post("/api/image-url", json={}).get_json(), {"error": "Enter the image's address"})

    def test_json_only(self):
        resp = self.client.post("/api/image-url", data={"url": self.base + "/logo.png"})
        self.assertEqual(resp.status_code, 415)
