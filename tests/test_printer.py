"""Printer output: raster jobs compared with reference jobs, and sending to a
fake printer, a TCP listener on this machine that records what it receives."""

import os
import queue
import socket
import tempfile
import threading
import unittest
import warnings

from brother_ql import image_trafos
from PIL import Image

import printer
import render
import server
from . import reference
from .test_render import RECORD, bar, box, layout, qr, text


class FakePrinter:
    """Listens on 127.0.0.1 like a printer's port 9100; each job received goes in `jobs`."""

    def __init__(self):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.jobs = queue.Queue()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:   # closed
                return
            with conn:
                chunks = []
                while chunk := conn.recv(65536):
                    chunks.append(chunk)
                self.jobs.put(b"".join(chunks))

    def close(self):
        self.sock.close()


def closed_port():
    """A port with nothing listening on it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Two labels each, so the job's page breaks are covered too
JOBS = {
    "job-red-across": layout(text(1, 1, 40, 10, "{{title}}"), qr(44, 1, 14, color="red"), length=20),
    "job-red-along": layout(text(1, 1, 30, 8, "{{title}}", color="red"), bar(1, 10, 30, 8),
                            length=40, orientation="landscape"),
    "job-black": layout(text(1, 1, 40, 10, "{{title}}"), box(1, 12, 58, 1), tape="62", length=20),
    "job-die-cut": layout(text(1, 1, 24, 20, "{{title}}"), bar(1, 22, 24, 10), tape="29x90"),
}
RECORDS = [RECORD, {**RECORD, "title": "Nut M3", "code": "N-0003"}]


def build(lay, model="QL-820NWB", cut=True):
    images = [render.render(lay, r, keep_missing=False)[0] for r in RECORDS]
    return printer.build_job(lay, images, model, cut=cut)


class Jobs(unittest.TestCase):

    def test_reference_jobs(self):
        for name, lay in JOBS.items():
            with self.subTest(name):
                reference.check_bytes(self, name, build(lay))

    def test_colour_filter_matches_brother_ql(self):
        # Every hue, saturation and value, through brother_ql's red and black filters
        hsv = Image.new("HSV", (256, 256))
        hsv.putdata([(h, s, v) for h in range(0, 256, 4) for s in range(0, 256, 16) for v in range(0, 256, 4)])
        im = hsv.convert("RGB")
        filters = [(lambda h: 255 if (h < 40 or h > 210) else 0, lambda s: 255 if s > 100 else 0,
                    lambda v: 255 if v > 80 else 0),
                   (lambda h: 255, lambda s: 255, lambda v: 255 if v < 80 else 0)]
        for f in filters:
            with warnings.catch_warnings():   # brother_ql's uses Image.getdata, which Pillow warns is going
                warnings.simplefilter("ignore", DeprecationWarning)
                theirs = image_trafos.filtered_hsv(im, *f)
            self.assertEqual(printer._filtered_hsv(im, *f).tobytes(), theirs.tobytes())

    def test_cut_changes_the_job(self):
        lay = JOBS["job-black"]
        self.assertNotEqual(build(lay, cut=True), build(lay, cut=False))

    def test_red_needs_a_two_colour_model(self):
        with self.assertRaises(Exception):
            build(JOBS["job-red-across"], model="QL-700")


class Sending(unittest.TestCase):

    def setUp(self):
        self.printer = FakePrinter()
        self.addCleanup(self.printer.close)

    def test_send(self):
        printer.send("127.0.0.1", self.printer.port, b"job bytes")
        self.assertEqual(self.printer.jobs.get(timeout=5), b"job bytes")

    def test_check(self):
        self.assertEqual(printer.check("127.0.0.1", self.printer.port), (True, "Printer reachable"))
        ok, msg = printer.check("127.0.0.1", closed_port())
        self.assertFalse(ok)
        self.assertTrue(msg.startswith("Cannot reach 127.0.0.1:"), msg)


class PrintEndpoint(unittest.TestCase):
    """/api/print and /api/test, sending to the fake printer."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.printer = FakePrinter()
        self.addCleanup(self.printer.close)
        self.client = server.create_app(os.path.join(tmp.name, "data")).test_client()

    def use_printer(self, port):
        self.client.post("/api/config", json={"printer_host": "127.0.0.1", "printer_port": port})

    def test_job_reaches_the_printer(self):
        self.use_printer(self.printer.port)
        lay = JOBS["job-black"]
        out = self.client.post("/api/print", json={"layout": lay, "records": RECORDS}).get_json()
        self.assertEqual((out["labels"], out["dry_run"]), (2, False))
        self.assertEqual(self.printer.jobs.get(timeout=5), build(lay))

    def test_printer_not_answering(self):
        self.use_printer(closed_port())
        resp = self.client.post("/api/print", json={"layout": JOBS["job-black"], "records": RECORDS})
        self.assertEqual(resp.status_code, 502)
        self.assertTrue(resp.get_json()["error"].startswith("Send failed"))

    def test_printer_test_button(self):
        self.assertEqual(self.client.post("/api/test", json={}).get_json(),
                         {"ok": False, "message": "No printer address set"})
        self.use_printer(self.printer.port)
        self.assertEqual(self.client.post("/api/test", json={}).get_json(), {"ok": True, "message": "Printer reachable"})
        self.use_printer(closed_port())
        self.assertFalse(self.client.post("/api/test", json={}).get_json()["ok"])
