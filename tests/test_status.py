"""The printer's status, read over SNMP from a fake printer: a UDP listener on
this machine that answers GET requests the way a QL-820NWB did. Nothing
reaches a real printer.

The status blocks are built here from the layout brother_ql documents
(reader.RESP_BYTE_NAMES), with the values a QL-820NWB gave in each state."""

import os
import socket
import tempfile
import threading
import unittest
from unittest import mock

import server
import status
from .test_printer import JOBS, RECORDS, FakePrinter, build

DIE_CUT, CONTINUOUS, NO_MEDIA = 0x0B, 0x0A, 0x00


def block(width=62, media=CONTINUOUS, length=0, colour=0x81, err1=0, err2=0, status_type=0, phase=0):
    """A status block. The defaults are DK-2251, black/red 62 mm continuous tape."""
    b = bytearray(32)
    b[0:7] = bytes([0x80, 0x20, 0x42, 0x34, 0x41, 0x30, 0x04])   # header, QL-820NWB, power
    b[8], b[9], b[10], b[11], b[17] = err1, err2, width, media, length
    b[18], b[19], b[25] = status_type, phase, colour
    return bytes(b)


READY = block()
COVER_OPEN = block(err2=0x10, status_type=0x02)
DIE_CUT_29X90 = block(width=29, media=DIE_CUT, length=90, colour=0x01)
NO_TAPE = block(width=0, media=NO_MEDIA, colour=0x01)


def closed_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---- a fake printer's SNMP agent ------------------------------------------------

def tlv(tag, body):
    return status._tlv(tag, body)


class FakeSnmp:
    """Answers SNMP GETs on 127.0.0.1. `values` maps an OID to bytes, or to
    None for one it doesn't have. `answer` False makes it silent; a callable
    in `reply` replaces the reply for tests of what a bad one does."""

    def __init__(self, values):
        self.values, self.answer, self.reply, self.requests = values, True, None, []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        oids = {bytes(status._oid(o)): o for o in self.values}
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:   # closed
                return
            self.requests.append(data)
            if not self.answer:
                continue
            _, msg, _ = status._parse(data, 0)
            version, community, (_, pdu) = status._items(msg)
            rid, _, _, (_, binds) = status._items(pdu)
            out = b""
            for _, bind in status._items(binds):
                (oid_tag, oid_body), _ = status._items(bind)
                oid = tlv(oid_tag, oid_body)
                value = self.values.get(oids.get(oid))
                out += tlv(0x30, oid + (tlv(0x04, value) if value is not None else b"\x80\x00"))
            reply = tlv(0x30, tlv(*version) + tlv(*community) +
                        tlv(0xA2, tlv(*rid) + status._int(0) + status._int(0) + tlv(0x30, out)))
            self.sock.sendto(self.reply(reply) if self.reply else reply, addr)

    def close(self):
        self.sock.close()


def printer_with(block_bytes, display=b"READY           "):
    return FakeSnmp({status.STATUS_OID: block_bytes, status.DISPLAY_OID: display})


# ---- reading the status block ---------------------------------------------------

class Decode(unittest.TestCase):

    def test_ready_with_black_and_red_tape(self):
        st = status.decode(READY, "READY           ")
        self.assertEqual(st, {"state": "ready", "errors": [], "display": "READY", "tape": {
            "kind": "continuous", "width_mm": 62, "length_mm": 0, "two_colour": True,
            "name": "Continuous length tape", "matches": ["62red"]}})
        self.assertEqual(status.summary(st), "Ready · 62 mm black/red continuous tape")

    def test_cover_open(self):
        st = status.decode(COVER_OPEN, "COVER OPEN")
        self.assertEqual((st["state"], st["errors"], st["display"]), ("error", ["Cover open"], "COVER OPEN"))
        self.assertEqual(st["tape"]["matches"], ["62red"])   # the tape is still known
        self.assertEqual(status.summary(st), "Cover open")

    def test_die_cut_labels(self):
        st = status.decode(DIE_CUT_29X90)
        self.assertEqual((st["tape"]["kind"], st["tape"]["matches"]), ("die-cut", ["29x90"]))
        self.assertEqual(status.summary(st), "Ready · 29 × 90 mm labels")

    def test_no_tape(self):
        # A printer that's idle doesn't count a missing roll as an error
        st = status.decode(NO_TAPE)
        self.assertEqual((st["state"], st["tape"]), ("ready", None))
        self.assertEqual(status.summary(st), "Ready · no tape")

    def test_every_error_bit_has_words(self):
        for (byte, bit), words in status.ERRORS.items():
            with self.subTest(words):
                b = bytearray(READY)
                b[byte] |= 1 << bit
                self.assertEqual(status.decode(bytes(b))["errors"], [words])
        both = status.decode(block(err1=0x04, err2=0x10))
        self.assertEqual(both["errors"], ["The cutter is jammed", "Cover open"])

    def test_an_error_without_words(self):
        st = status.decode(block(status_type=0x02))
        self.assertEqual((st["state"], st["errors"]), ("error", ["Printer error"]))

    def test_printing(self):
        self.assertEqual(status.summary(status.decode(block(phase=0x01))), "Printing")

    def test_what_isnt_a_status_block(self):
        for data in (None, b"", READY[:31], b"\x00" * 32, b"READY" * 10):
            with self.subTest(data=data):
                self.assertIsNone(status.decode(data))


class Tapes(unittest.TestCase):

    def matches(self, **kw):
        return status.decode(block(**kw))["tape"]["matches"]

    def test_continuous_tape_by_width_and_colour(self):
        self.assertEqual(self.matches(width=62, colour=0x81), ["62red"])
        self.assertEqual(self.matches(width=62, colour=0x01), ["62"])
        self.assertEqual(self.matches(width=29, colour=0x01), ["29"])
        self.assertEqual(self.matches(width=12, colour=0x01), ["12", "12+17"])   # both are 12 mm rolls

    def test_die_cut_labels_by_size(self):
        die = lambda w, h: self.matches(width=w, length=h, media=DIE_CUT, colour=0x01)
        self.assertEqual(die(62, 100), ["62x100"])
        self.assertEqual(die(38, 90), ["39x90"])   # brother_ql's size for it
        self.assertEqual(die(39, 90), ["39x90"])   # its name, a millimetre out
        self.assertEqual(die(60, 86), ["60x86"])   # 60 x 87 in brother_ql's table
        self.assertEqual(die(24, 24), ["d24"])     # exact beats 23 x 23 within a millimetre
        self.assertEqual(die(23, 23), ["23x23"])
        self.assertEqual(die(50, 50), [])          # no such label

    def test_a_kind_the_app_doesnt_know(self):
        self.assertEqual(self.matches(media=0x01), [])   # laminated P-touch tape


class Fits(unittest.TestCase):

    def test_the_right_tape(self):
        self.assertIsNone(status.fits("62red", status.decode(READY)))
        self.assertIsNone(status.fits("29x90", status.decode(DIE_CUT_29X90)))

    def test_black_on_two_colour_tape(self):
        self.assertIsNone(status.fits("62", status.decode(READY)))
        black_tape = status.decode(block(colour=0x01))
        self.assertEqual(status.fits("62red", black_tape),
                         "The printer has 62 mm continuous tape loaded; this layout is for 62 mm continuous · black/red")

    def test_another_tape(self):
        self.assertEqual(status.fits("62red", status.decode(DIE_CUT_29X90)),
                         "The printer has 29 × 90 mm labels loaded; this layout is for 62 mm continuous · black/red")

    def test_trouble_comes_first(self):
        self.assertEqual(status.fits("62red", status.decode(COVER_OPEN)), "Cover open")
        self.assertEqual(status.fits("62red", status.decode(NO_TAPE)), "No tape")

    def test_mismatch_in_parts(self):
        self.assertEqual(status.mismatch("62red", status.decode(DIE_CUT_29X90)),
                         {"loaded": "29 × 90 mm labels", "wanted": "62 mm continuous · black/red"})
        self.assertEqual(status.mismatch("nope", status.decode(DIE_CUT_29X90)),
                         {"loaded": "29 × 90 mm labels", "wanted": ""})
        for st in (None, status.decode(READY), status.decode(NO_TAPE)):
            self.assertIsNone(status.mismatch("62red", st))

    def test_nothing_known_lets_the_job_through(self):
        self.assertIsNone(status.fits("62red", None))
        self.assertIsNone(status.fits("62red", status.decode(block(media=0x01))))   # a tape it can't name


# ---- SNMP ----------------------------------------------------------------------

class Snmp(unittest.TestCase):

    def setUp(self):
        self.agent = printer_with(READY)
        self.addCleanup(self.agent.close)

    def test_read(self):
        st = status.read("127.0.0.1", port=self.agent.port)
        self.assertEqual((st["state"], st["display"], st["tape"]["matches"]), ("ready", "READY", ["62red"]))
        self.assertEqual(len(self.agent.requests), 1)   # one request for both values

    def test_the_request(self):
        # SNMP v2c, community "public", one GET for the status block and the display
        status.read("127.0.0.1", port=self.agent.port)
        req = self.agent.requests[0]
        self.assertIn(bytes(status._oid(status.STATUS_OID)), req)
        self.assertIn(bytes(status._oid(status.DISPLAY_OID)), req)
        self.assertEqual(req[2:5], b"\x02\x01\x01")    # version 1, which is v2c
        self.assertEqual(req[5:13], b"\x04\x06public")

    def test_a_printer_without_a_display_entry(self):
        agent = FakeSnmp({status.STATUS_OID: COVER_OPEN, status.DISPLAY_OID: None})
        self.addCleanup(agent.close)
        st = status.read("127.0.0.1", port=agent.port)
        self.assertEqual((st["errors"], st["display"]), (["Cover open"], ""))

    def test_a_printer_without_the_status_block(self):
        agent = FakeSnmp({status.STATUS_OID: None, status.DISPLAY_OID: b"READY"})
        self.addCleanup(agent.close)
        self.assertIsNone(status.read("127.0.0.1", port=agent.port))

    def test_no_answer(self):
        self.agent.answer = False
        self.assertIsNone(status.read("127.0.0.1", port=self.agent.port, timeout=0.2))
        self.assertIsNone(status.read("127.0.0.1", port=closed_udp_port(), timeout=0.2))

    def test_an_answer_to_another_request(self):
        # The reply's request id is changed; a fixed id of four bytes keeps it in place
        rid = status._int(0x1234567)
        self.agent.reply = lambda r: r.replace(rid, status._int(0x7654321), 1)
        with mock.patch.object(status.secrets, "randbelow", return_value=0x1234567):
            self.assertIsNone(status.read("127.0.0.1", port=self.agent.port, timeout=0.5))
            self.agent.reply = None
            self.assertIsNotNone(status.read("127.0.0.1", port=self.agent.port))   # and unchanged, it's read

    def test_a_damaged_answer(self):
        # Every way of cutting a good reply short, and some bytes that aren't one
        good = []
        self.agent.reply = lambda r: (good.append(r), r)[1]
        status.read("127.0.0.1", port=self.agent.port)
        good = good[0]
        rid = status._items(status._items(status._parse(good, 0)[1])[2][1])[0][1]
        rid = int.from_bytes(rid, "big", signed=True)
        for n in range(len(good)):
            with self.subTest(cut=n):
                with self.assertRaises(status.SnmpError):
                    status.parse_response(good[:n], rid)
        for junk in (b"\x30\x84\xff\xff\xff\xff", b"\x30\x02\x04\x00", b"\xff" * 40):
            with self.subTest(junk=junk), self.assertRaises(status.SnmpError):
                status.parse_response(junk, rid)
        self.agent.reply = lambda r: r[:-3]
        self.assertIsNone(status.read("127.0.0.1", port=self.agent.port, timeout=0.5))


# ---- the API ---------------------------------------------------------------------

class Api(unittest.TestCase):
    """/api/status, /api/test and /api/print, with a fake printer for jobs
    (port 9100) and one for status (SNMP)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.jobs = FakePrinter()
        self.addCleanup(self.jobs.close)
        self.agent = printer_with(READY)
        self.addCleanup(self.agent.close)
        patch = mock.patch.object(status, "SNMP_PORT", self.agent.port)
        patch.start()
        self.addCleanup(patch.stop)
        self.client = server.create_app(os.path.join(tmp.name, "data")).test_client()
        self.client.post("/api/config", json={"printer_host": "127.0.0.1", "printer_port": self.jobs.port})

    def show(self, block_bytes, display=b"READY"):
        self.agent.values = {status.STATUS_OID: block_bytes, status.DISPLAY_OID: display}

    def print_(self, lay="job-red-across", **extra):
        return self.client.post("/api/print", json={"layout": JOBS[lay], "records": RECORDS, **extra})

    def test_status(self):
        out = self.client.get("/api/status?tape=62red").get_json()
        self.assertEqual(out["summary"], "Ready · 62 mm black/red continuous tape")
        self.assertEqual(out["status"]["tape"]["matches"], ["62red"])
        self.assertEqual((out["mismatch"], out["reachable"]), (None, None))   # reachable goes without saying

    def test_status_names_a_tape_that_doesnt_suit_the_layout(self):
        self.show(DIE_CUT_29X90)
        self.assertEqual(self.client.get("/api/status?tape=62red").get_json()["mismatch"],
                         {"loaded": "29 × 90 mm labels", "wanted": "62 mm continuous · black/red"})
        self.assertIsNone(self.client.get("/api/status?tape=29x90").get_json()["mismatch"])
        self.assertIsNone(self.client.get("/api/status").get_json()["mismatch"])   # no layout tape given

    def test_status_without_an_answer_says_whether_jobs_get_through(self):
        self.agent.answer = False
        with mock.patch.object(status, "TIMEOUT_S", 0.2):
            out = self.client.get("/api/status").get_json()
            self.assertEqual(out, {"status": None, "summary": None, "mismatch": None, "reachable": True})
            # Asked again soon after, port 9100 isn't tried again
            with mock.patch.object(server.printer, "check", side_effect=AssertionError("tried again")):
                self.assertTrue(self.client.get("/api/status").get_json()["reachable"])
            # Half a minute later it is, and a printer gone since is seen to be
            later = server.time.monotonic() + 31
            with mock.patch.object(server.time, "monotonic", return_value=later), \
                    mock.patch.object(server.printer, "check", return_value=(False, "gone")):
                self.assertFalse(self.client.get("/api/status").get_json()["reachable"])

    def test_status_without_an_address(self):
        self.client.post("/api/config", json={"printer_host": ""})
        self.assertEqual(self.client.get("/api/status").get_json(),
                         {"status": None, "summary": None, "mismatch": None, "reachable": None})
        self.assertEqual(self.agent.requests, [])

    def test_the_test_button_says_what_the_printer_says(self):
        self.show(COVER_OPEN, b"COVER OPEN")
        out = self.client.post("/api/test", json={}).get_json()
        self.assertEqual((out["ok"], out["message"]), (True, "Printer reachable · Cover open"))

    def test_the_right_tape_prints(self):
        self.assertEqual(self.print_().status_code, 200)
        self.assertEqual(self.jobs.jobs.get(timeout=5), build(JOBS["job-red-across"]))

    def test_another_tape_asks_first(self):
        self.show(DIE_CUT_29X90)
        resp = self.print_()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json(), {"ask": True, "error":
                         "The printer has 29 × 90 mm labels loaded; this layout is for 62 mm continuous · black/red"})
        self.assertTrue(self.jobs.jobs.empty())
        # Sent again "anyway", it goes, without asking the printer again
        asked = len(self.agent.requests)
        self.assertEqual(self.print_(anyway=True).status_code, 200)
        self.assertEqual(self.jobs.jobs.get(timeout=5), build(JOBS["job-red-across"]))
        self.assertEqual(len(self.agent.requests), asked)

    def test_an_error_asks_first(self):
        for bad, words in ((COVER_OPEN, "Cover open"), (NO_TAPE, "No tape")):
            with self.subTest(words):
                self.show(bad)
                self.assertEqual(self.print_().get_json(), {"ask": True, "error": words})

    def test_a_printer_that_doesnt_say_prints_as_before(self):
        self.agent.answer = False
        with mock.patch.object(status, "TIMEOUT_S", 0.2):
            self.assertEqual(self.print_().status_code, 200)
        self.assertEqual(self.jobs.jobs.get(timeout=5), build(JOBS["job-red-across"]))

    def test_a_dry_run_doesnt_ask_the_printer(self):
        self.show(DIE_CUT_29X90)
        self.assertEqual(self.print_(dry_run=True).status_code, 200)
        self.assertEqual(self.agent.requests, [])
