"""The HTTP API, against a temporary data folder. Nothing is sent to a printer:
printing is a dry run, and the printer address is never used."""

import io
import json
import os
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote, unquote

import printer
import render
import server
import tables

TITLE = {"type": "text", "x": 2, "y": 2, "w": 30, "h": 8, "text": "{{title}}"}
CODE = {"type": "qr", "x": 35, "y": 2, "w": 10, "h": 10, "data": "{{code}}"}
LINK = {"type": "qr", "x": 47, "y": 2, "w": 10, "h": 10, "data": "{{link}}"}
BAR = {"type": "barcode", "x": 2, "y": 14, "w": 50, "h": 10, "data": "{{code}}"}
SAMPLE = {"layout": {"tape": "62red", "elements": [TITLE]}, "fixed": {"title": "Example"}, "mapping": {}}


def layout(*elements):
    return {"tape": "62red", "length_mm": 30, "orientation": "portrait", "elements": list(elements)}


def header(resp, name):
    return json.loads(unquote(resp.headers[name]))


class ApiTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = os.path.join(tmp.name, "data")
        self.samples = os.path.join(tmp.name, "samples")
        os.makedirs(os.path.join(self.samples, "templates"))
        with open(os.path.join(self.samples, "templates", "Example.json"), "w", encoding="utf-8") as f:
            json.dump(SAMPLE, f)
        self.app = server.create_app(self.data, samples_dir=self.samples)
        self.client = self.app.test_client()

    def post(self, path, payload=None):
        return self.client.post(path, json=payload or {})


class Config(ApiTest):

    def test_meta(self):
        meta = self.client.get("/api/meta").get_json()
        self.assertEqual(meta["config"], server.DEFAULT_CONFIG)
        self.assertIn("QL-820NWB", meta["models"])
        self.assertIn("62red", [t["id"] for t in meta["tapes"]])

    def test_only_known_settings_are_saved(self):
        cfg = self.post("/api/config", {"printer_host": "192.168.1.50", "other": 1}).get_json()["config"]
        self.assertEqual(cfg["printer_host"], "192.168.1.50")
        self.assertNotIn("other", cfg)
        with open(os.path.join(self.data, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), cfg)

    def test_printer_test_without_an_address(self):
        self.assertEqual(self.post("/api/test").get_json(), {"ok": False, "message": "No printer address set"})


class Preview(ApiTest):

    def test_png_and_headers(self):
        resp = self.post("/api/render", {"layout": layout(TITLE, CODE), "record": {"title": "Hi"}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/png")
        self.assertTrue(resp.data.startswith(b"\x89PNG"))
        self.assertEqual(header(resp, "X-Placeholders"), ["title", "code"])
        self.assertEqual(header(resp, "X-Blank"), [{"i": 1, "type": "qr", "why": "empty"}])
        self.assertEqual(header(resp, "X-Warnings"), [])

    def test_text_max_size_and_line_spacing(self):
        def ink_height(**opts):
            box = {"type": "text", "x": 2, "y": 2, "w": 50, "h": 20, "text": "Ab\nAb", "size": 0, **opts}
            img = render.render(layout(box))[0].convert("L").point(lambda v: 255 if v < 128 else 0)
            top, bottom = img.getbbox()[1::2]
            return bottom - top
        auto = ink_height()
        self.assertLess(ink_height(max_size=8), auto * 0.6)   # shrink to fit, but no larger than 8 pt
        self.assertLess(ink_height(size=8, max_size=40), auto * 0.6)   # a set size ignores it
        tight, loose = ink_height(size=8), ink_height(size=8, spacing=2)
        self.assertGreater(loose, tight * 1.4)

    def test_hidden_text_is_listed_as_blank(self):
        resp = self.post("/api/render", {"layout": layout(TITLE), "record": {}})
        self.assertEqual(header(resp, "X-Blank"), [{"i": 0, "type": "text", "why": "empty"}])

    def test_invalid_barcode_is_listed_as_blank(self):
        resp = self.post("/api/render", {"layout": layout(BAR), "record": {"code": "☃"}})
        self.assertEqual(header(resp, "X-Blank"), [{"i": 0, "type": "barcode", "why": "invalid"}])
        self.assertTrue(any(w.startswith("Barcode error") for w in header(resp, "X-Warnings")))


class Print(ApiTest):

    def print(self, lay, records, **options):
        return self.post("/api/print", {"layout": lay, "records": records, "dry_run": True, **options})

    def test_needs_a_printer_address(self):
        resp = self.post("/api/print", {"layout": layout(TITLE), "records": [{"title": "Hi"}]})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "Set the printer address first")

    def test_one_label_per_record_and_copy(self):
        out = self.print(layout(TITLE), [{"title": "A"}, {"title": "B"}, {"title": "C"}], copies=2).get_json()
        self.assertEqual(out["labels"], 6)
        self.assertTrue(out["dry_run"])
        self.assertGreater(out["bytes"], 0)
        self.assertEqual(out["warnings"], [])

    def test_blank_codes_are_counted_by_label(self):
        # Two empty QR codes on the first record's labels, none on the second's
        records = [{}, {"code": "A1", "link": "https://example.com"}]
        out = self.print(layout(CODE, LINK), records, copies=2).get_json()
        self.assertEqual(out["labels"], 4)
        self.assertEqual(out["warnings"], ["QR code empty on 2 labels; printed blank"])

    def test_hidden_text_is_not_a_warning(self):
        self.assertEqual(self.print(layout(TITLE), [{}]).get_json()["warnings"], [])

    def test_cut_setting_is_passed_on(self):
        # Whether or not an element is blank: hidden text and an empty QR code
        # used to replace the request, so the label was always cut.
        for record in ({"title": "Hi", "code": "A1"}, {}):
            for cut in (True, False, None):
                with self.subTest(record=record, cut=cut), \
                        mock.patch.object(printer, "build_job", wraps=printer.build_job) as build:
                    options = {} if cut is None else {"cut": cut}
                    self.assertEqual(self.print(layout(TITLE, CODE), [record], **options).status_code, 200)
                    self.assertIs(build.call_args.kwargs["cut"], True if cut is None else cut)


class DataFiles(ApiTest):

    def upload(self, name, raw):
        return self.client.post("/api/csv", data={"file": (io.BytesIO(raw), name)},
                                content_type="multipart/form-data")

    def test_rows_and_headers(self):
        out = self.upload("parts.csv", b"code, \nA1,Bolt\n,\n").get_json()
        self.assertEqual(out, {"headers": ["code", "Column 2"], "rows": [{"code": "A1", "Column 2": "Bolt"}]})

    def test_no_file(self):
        self.assertEqual(self.client.post("/api/csv").status_code, 400)

    def test_empty_file(self):
        self.assertEqual(self.upload("empty.csv", b"").get_json(), {"error": "The file has no rows"})

    def test_unsupported_file(self):
        resp = self.upload("photo.jpg", bytes(range(256)) * 8)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(".jpg", resp.get_json()["error"])

    def test_damaged_spreadsheet(self):
        resp = self.upload("data.fods", b'<?xml version="1.0"?>\n<office:document')
        self.assertEqual(resp.get_json(), {"error": "The file looks damaged"})


class Templates(ApiTest):

    def test_save_list_load_delete(self):
        tpl = {"layout": layout(TITLE), "fixed": {"title": "Hi"}, "mapping": {}}
        self.assertEqual(self.client.put("/api/templates/My label", json=tpl).get_json(), {"ok": True})
        self.assertEqual(self.client.get("/api/templates").get_json(),
                         {"templates": ["My label"], "samples": ["Example"]})
        self.assertEqual(self.client.get("/api/templates/My label").get_json(), tpl)
        self.assertEqual(self.client.delete("/api/templates/My label").get_json(), {"ok": True})
        self.assertEqual(self.client.get("/api/templates/My label").status_code, 404)

    def test_samples_open_but_stay_read_only(self):
        self.assertEqual(self.client.get("/api/samples/Example").get_json(), SAMPLE)
        self.assertEqual(self.client.get("/api/samples/Missing").status_code, 404)
        # Deleting or saving under a sample's name only ever touches your own
        self.assertEqual(self.client.delete("/api/templates/Example").status_code, 404)
        self.client.put("/api/templates/Example", json={"layout": layout()})
        self.client.delete("/api/templates/Example")
        self.assertEqual(self.client.get("/api/samples/Example").get_json(), SAMPLE)
        self.assertEqual(os.listdir(os.path.join(self.data, "templates")), [])

    def test_no_samples_folder(self):
        client = server.create_app(self.data, samples_dir=os.path.join(self.data, "nowhere")).test_client()
        self.assertEqual(client.get("/api/templates").get_json(), {"templates": [], "samples": []})

    def saved(self):
        return sorted(os.listdir(os.path.join(self.data, "templates")))

    def put(self, name, tpl=None):
        # Encoded the way the editor sends it, so ? # % reach the server
        return self.client.put("/api/templates/" + quote(name, safe=""), json=tpl or {})

    def test_saving_over_a_template_needs_replace(self):
        self.client.put("/api/templates/Mine", json={"v": 1})
        resp = self.client.put("/api/templates/Mine", json={"v": 2})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), {"v": 1})
        self.assertEqual(self.client.put("/api/templates/Mine?replace=1", json={"v": 2}).get_json(), {"ok": True})
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), {"v": 2})

    def test_a_refused_body_leaves_the_template_alone(self):
        self.client.put("/api/templates/Mine", json={"v": 1})
        self.assertEqual(self.client.put("/api/templates/Mine?replace=1", json=[1]).status_code, 400)
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), {"v": 1})

    def test_names_are_used_as_typed(self):
        for name in ("Bin label!", "Étiquette #2 (red)", "50% off", "x" * server.MAX_NAME):
            with self.subTest(name):
                self.assertEqual(self.put(name).status_code, 200)
                self.assertEqual(self.client.get("/api/templates/" + quote(name, safe="")).status_code, 200)
        self.assertEqual(self.saved(), sorted(["50% off.json", "Bin label!.json", "Étiquette #2 (red).json",
                                               "x" * server.MAX_NAME + ".json"]))

    def test_names_that_cant_be_file_names_are_refused(self):
        cases = {
            " ": "Give the template a name",
            "a/b": server.BAD_NAME_MSG,
            "../evil": server.BAD_NAME_MSG,
            ".hidden": "Template names can't start or end with a dot",
            "ends.": "Template names can't start or end with a dot",
            "CON": "“CON” is a name Windows keeps for devices. Choose another.",
            "x" * (server.MAX_NAME + 1): f"Template names can be up to {server.MAX_NAME} characters",
        }
        for c in '\\:*?"<>|\t':
            cases[f"a{c}b"] = cases["a/b"]
        for name, msg in cases.items():
            with self.subTest(name):
                resp = self.put(name)
                self.assertEqual((resp.status_code, resp.get_json()), (400, {"error": msg}))
        for name in ("lpt1", "nul.v2", "Com9 .x"):
            with self.subTest(name):
                self.assertEqual(self.put(name).status_code, 400)
        self.assertEqual(self.saved(), [])



class OtherSites(ApiTest):

    def test_bodies_must_be_json(self):
        # Pages on other sites can send plain text and forms without asking
        for path in ("/api/config", "/api/print", "/api/render", "/api/test"):
            with self.subTest(path):
                resp = self.client.post(path, data='{"printer_host": "192.168.1.50"}', content_type="text/plain")
                self.assertEqual(resp.status_code, 415)
                self.assertEqual(resp.get_json(), {"error": "Requests must be sent as JSON"})
        resp = self.client.put("/api/templates/Sneaky", data={"layout": "x"})
        self.assertEqual(resp.status_code, 415)
        self.assertEqual(os.listdir(self.data), ["templates"])   # no config.json either
        self.assertEqual(os.listdir(os.path.join(self.data, "templates")), [])

    def test_only_local_host_names(self):
        for host in ("127.0.0.1:8620", "localhost:8620", "LOCALHOST", "[::1]:8620"):
            with self.subTest(host):
                self.assertEqual(self.client.get("/api/meta", environ_overrides={"HTTP_HOST": host}).status_code, 200)
        for host in ("rebound.example", "rebound.example:8620", "127.0.0.1.rebound.example", "[::1"):
            with self.subTest(host):
                self.assertEqual(self.client.get("/", environ_overrides={"HTTP_HOST": host}).status_code, 403)
                self.assertEqual(self.client.get("/api/meta", environ_overrides={"HTTP_HOST": host}).status_code, 403)

    def test_lan_takes_any_host_name_but_still_only_json(self):
        client = server.create_app(self.data, lan=True).test_client()
        self.assertEqual(client.get("/api/meta", environ_overrides={"HTTP_HOST": "labels.example:8620"}).status_code, 200)
        self.assertEqual(client.post("/api/config", data="{}", content_type="text/plain").status_code, 415)


class Errors(ApiTest):

    def assertJsonError(self, resp, status, message=None):
        self.assertEqual(resp.status_code, status)
        self.assertTrue(resp.is_json)
        if message:
            self.assertEqual(resp.get_json()["error"], message)
        return resp.get_json()["error"]

    def test_api_errors_are_json(self):
        self.assertJsonError(self.client.get("/api/nothing"), 404)
        self.assertJsonError(self.client.get("/api/templates/Missing"), 404, "No template by that name")
        self.assertJsonError(self.client.delete("/api/templates/Missing"), 404, "No template by that name")
        self.assertJsonError(self.client.put("/api/templates/.x", json={}), 400,
                             "Template names can't start or end with a dot")
        for raw in ("[1]", "{bad", ""):
            with self.subTest(raw=raw):
                resp = self.client.post("/api/config", data=raw, content_type="application/json")
                self.assertJsonError(resp, 400, "Expected a JSON object")

    def test_print_errors(self):
        def print_(**payload):
            return self.post("/api/print", {"layout": layout(TITLE), "dry_run": True, **payload})
        for copies in ("two", None, [2]):
            with self.subTest(copies=copies):
                self.assertJsonError(print_(copies=copies), 400, "Copies must be a whole number")
        msg = self.assertJsonError(print_(layout={"tape": "nope", "elements": []}), 400)
        self.assertTrue(msg.startswith("Rendering failed"), msg)
        self.assertEqual(print_(copies="3").get_json()["labels"], 3)

    def test_unexpected_errors_are_json_and_logged(self):
        with mock.patch.object(server.render, "tape_list", side_effect=RuntimeError("boom")), \
                self.assertLogs(self.app.logger, "ERROR"):
            resp = self.client.get("/api/meta")
        self.assertJsonError(resp, 500, "Server error: boom")

    def test_pages_keep_html_errors(self):
        resp = self.client.get("/nothing")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.mimetype, "text/html")


class ShippedSamples(unittest.TestCase):

    def test_bin_label_matches_the_sample_data(self):
        with open(os.path.join(server.SAMPLES, "templates", "Bin label.json"), encoding="utf-8") as f:
            tpl = json.load(f)
        with open(os.path.join(server.SAMPLES, "parts.csv"), "rb") as f:
            headers = tables.read_table("parts.csv", f.read())[0]
        fields = render.placeholders(tpl["layout"])
        self.assertEqual(sorted(fields), sorted(headers))
        self.assertEqual(fields, [f.lower() for f in fields])   # lowercase, the house style
        self.assertEqual(tpl["mapping"], {f: f for f in fields})


class Presence(unittest.TestCase):

    def test_idle_time_starts_when_the_last_page_closes(self):
        p = server.Presence()
        self.assertEqual(p.idle_for(), 0)   # no page has opened yet
        p.join()
        p.join()
        p.leave()
        self.assertEqual(p.idle_for(), 0)   # one page still open
        with mock.patch.object(server.time, "monotonic", side_effect=[100.0, 112.5]):
            p.leave()
            self.assertEqual(p.idle_for(), 12.5)
        p.join()
        self.assertEqual(p.idle_for(), 0)
