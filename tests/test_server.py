"""The HTTP API, against a temporary data folder. Nothing is sent to a printer:
printing is a dry run, and the printer address is never used."""

import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote, unquote

import fields
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


# What a module imports: import … from "./x.mjs", import "./x.mjs" or import("./x.mjs")
IMPORT = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*["']([^"']+\.mjs)["']""")


def editor_modules():
    """The editor's script files, by name."""
    return sorted(n for n in os.listdir(server.STATIC) if n.endswith(".mjs"))


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
        # The editor finds fields with the server's own pattern and built-ins
        self.assertEqual(meta["field_pattern"], fields.PLACEHOLDER.pattern)
        self.assertEqual(meta["builtin_fields"], ["date", "time", "datetime"])
        self.assertEqual([b["id"] for b in meta["barcodes"]], ["code128", "ean13", "ean8", "upca", "itf14"])
        self.assertEqual(meta["image_budget"], 128 * 1024)   # the editor shrinks images to fit
        self.assertEqual(meta["limits"], {"length_mm": [5, 1000], "copies": 100})   # and keeps to these

    def test_only_known_settings_are_saved(self):
        cfg = self.post("/api/config", {"printer_host": "192.168.1.50", "other": 1}).get_json()["config"]
        self.assertEqual(cfg["printer_host"], "192.168.1.50")
        self.assertNotIn("other", cfg)
        with open(os.path.join(self.data, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), cfg)

    def test_printer_test_without_an_address(self):
        self.assertEqual(self.post("/api/test").get_json(), {"ok": False, "message": "No printer address set"})

    def test_settings_are_tidied(self):
        cfg = self.post("/api/config", {"printer_host": "  printer.example ", "printer_port": "9101"}).get_json()["config"]
        self.assertEqual((cfg["printer_host"], cfg["printer_port"]), ("printer.example", 9101))

    def test_settings_that_cant_be_used_are_refused(self):
        self.post("/api/config", {"printer_host": "192.168.1.50"})
        port = "The port must be a number from 1 to 65535"
        cases = [
            ({"printer_port": "abc"}, port), ({"printer_port": 0}, port), ({"printer_port": 70000}, port),
            ({"printer_port": True}, port), ({"printer_port": 9100.5}, port),
            ({"printer_host": 5}, "The printer's address must be text"),
            ({"printer_host": "my printer"}, "That isn't a printer address: use its IP address or host name"),
            ({"model": "QL-9000"}, "Choose one of these printer models: QL-800, QL-810W, QL-820NWB"),
            # One bad setting keeps the good ones sent with it from being saved
            ({"printer_host": "printer.example", "printer_port": "abc"}, port),
        ]
        for payload, msg in cases:
            with self.subTest(payload):
                resp = self.post("/api/config", payload)
                self.assertEqual((resp.status_code, resp.get_json()), (400, {"error": msg}))
        self.assertEqual(self.client.get("/api/meta").get_json()["config"],
                         {**server.DEFAULT_CONFIG, "printer_host": "192.168.1.50"})

    def test_a_settings_file_that_cant_be_used_gives_the_defaults(self):
        # Each setting on its own: a bad one falls back, the rest are kept
        files = {
            "[1]": {}, "{bad": {}, '"text"': {}, "": {},
            '{"printer_host": "192.168.1.50", "printer_port": "abc", "model": "QL-9000"}': {"printer_host": "192.168.1.50"},
            '{"printer_host": 5, "printer_port": 9101}': {"printer_port": 9101},
        }
        for raw, kept in files.items():
            with self.subTest(raw):
                with open(os.path.join(self.data, "config.json"), "w", encoding="utf-8") as f:
                    f.write(raw)
                resp = self.client.get("/api/meta")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json()["config"], {**server.DEFAULT_CONFIG, **kept})


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

    def test_qr_code_with_too_much_data_is_listed_as_blank(self):
        # It used to replace the whole preview with "Invalid version (was 41, expected 1 to 40)"
        for n in (3000, 4000, 40000):   # qrcode reports these with different errors
            with self.subTest(n):
                resp = self.post("/api/render", {"layout": layout(TITLE, CODE), "record": {"title": "Hi", "code": "x" * n}})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(header(resp, "X-Blank"), [{"i": 1, "type": "qr", "why": "invalid"}])
                self.assertEqual(header(resp, "X-Warnings"),
                                 [f"QR code can't hold this much data ({n} characters); shorten it"])

    def test_a_layout_must_be_an_object(self):
        for path in ("/api/render", "/api/print"):
            with self.subTest(path):
                resp = self.post(path, {"layout": [1], "dry_run": True})
                self.assertEqual((resp.status_code, resp.get_json()), (400, {"error": "Expected a layout"}))


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

    def test_missing_image_is_a_warning(self):
        img = {"type": "image", "x": 2, "y": 2, "w": 10, "h": 10, "src": ""}
        self.assertEqual(self.print(layout(img), [{}, {}]).get_json()["warnings"],
                         ["Image empty on 2 labels; printed blank"])

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

    def test_labels_are_drawn_one_at_a_time(self):
        # Not all before the first is converted: 5,000 rows would need gigabytes
        records = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
        labels = server.Labels(layout(TITLE), records, 2, set(), None)
        self.assertEqual(len(labels), 6)
        with mock.patch.object(render, "render", wraps=render.render) as draw:
            each = iter(labels)
            first, copy = next(each), next(each)
            self.assertIs(first, copy)   # a copy is the same image again
            self.assertEqual(draw.call_count, 1)
            self.assertEqual(len(list(each)), 4)
            self.assertEqual(draw.call_count, 3)

    def test_an_error_names_its_row(self):
        real = render.render

        def draw(lay, record, **options):
            if record.get("title") == "bad":
                raise ValueError("boom")
            return real(lay, record, **options)

        records = [{"title": "A"}, {"title": "bad"}]
        with mock.patch.object(render, "render", draw):
            # The data file's row numbers, when the editor sends them
            self.assertEqual(self.print(layout(TITLE), records, rows=[3, 7]).get_json(),
                             {"error": "Rendering failed on row 7: boom"})
            self.assertEqual(self.print(layout(TITLE), records).get_json(),
                             {"error": "Rendering failed on label 2: boom"})
            self.assertEqual(self.print(layout(TITLE), records, rows=[3]).get_json(),   # not one for each record
                             {"error": "Rendering failed on label 2: boom"})
            self.assertEqual(self.print(layout(TITLE), records[1:]).get_json(), {"error": "Rendering failed: boom"})

    def test_records_must_be_objects(self):
        resp = self.print(layout(TITLE), ["Hi"])
        self.assertEqual((resp.status_code, resp.get_json()), (400, {"error": "Records must be a list of objects"}))

    def test_one_date_and_time_for_the_whole_job(self):
        with mock.patch.object(render, "render", wraps=render.render) as draw:
            self.print(layout(TITLE), [{"title": "A"}, {"title": "B"}, {"title": "C"}])
        times = [call.kwargs["now"] for call in draw.call_args_list]
        self.assertEqual(len(times), 3)
        self.assertIsNotNone(times[0])
        self.assertTrue(all(t is times[0] for t in times))

    def test_copies_stop_at_the_limit(self):
        self.assertEqual(self.print(layout(), [{}], copies=5000).get_json()["labels"], server.MAX_COPIES)


class DataFiles(ApiTest):

    def upload(self, name, raw):
        return self.client.post("/api/data", data={"file": (io.BytesIO(raw), name)},
                                content_type="multipart/form-data")

    def test_rows_and_headers(self):
        out = self.upload("parts.csv", b"code, \nA1,Bolt\n,\n").get_json()
        self.assertEqual(out, {"headers": ["code", "Column 2"], "rows": [{"code": "A1", "Column 2": "Bolt"}]})

    def test_repeated_column_names_are_numbered(self):
        # Rows are kept by column name: the second "name" used to replace the
        # first without a word. Field names ignore case, so "Code" repeats "code".
        out = self.upload("parts.csv", b"name,code,name,Code,name\nBolt,1,Nut,2,Washer\n").get_json()
        self.assertEqual(out["headers"], ["name", "code", "name (2)", "Code (2)", "name (3)"])
        self.assertEqual(out["rows"], [{"name": "Bolt", "code": "1", "name (2)": "Nut", "Code (2)": "2",
                                        "name (3)": "Washer"}])

    def test_a_numbered_name_avoids_one_already_there(self):
        self.assertEqual(server.unique_headers(["a", "a (2)", "A", "", "column 4"]),
                         ["a", "a (2)", "A (3)", "Column 4", "column 4 (2)"])

    def test_no_file(self):
        self.assertEqual(self.client.post("/api/data").status_code, 400)

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
        return self.client.put("/api/templates/" + quote(name, safe=""), json=tpl or self.tpl(0))

    @staticmethod
    def tpl(v):
        """A small template, told from another by its fixed value."""
        return {"layout": layout(), "fixed": {"v": str(v)}}

    def test_saving_over_a_template_needs_replace(self):
        self.client.put("/api/templates/Mine", json=self.tpl(1))
        resp = self.client.put("/api/templates/Mine", json=self.tpl(2))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), self.tpl(1))
        self.assertEqual(self.client.put("/api/templates/Mine?replace=1", json=self.tpl(2)).get_json(), {"ok": True})
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), self.tpl(2))

    def test_a_refused_body_leaves_the_template_alone(self):
        self.client.put("/api/templates/Mine", json=self.tpl(1))
        self.assertEqual(self.client.put("/api/templates/Mine?replace=1", json=[1]).status_code, 400)
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), self.tpl(1))

    def test_only_templates_are_saved(self):
        cases = {
            "it has no layout": [{}, {"v": 1}, {"layout": [1]}, {"layout": "x"}],
            "its elements aren't a list": [{"layout": {"elements": "x"}}, {"layout": {"elements": [TITLE, 5]}}],
            "its fixed values can't be read": [{"layout": layout(), "fixed": [1]}],
            "its column choices can't be read": [{"layout": layout(), "mapping": "x"}],
        }
        for fault, bodies in cases.items():
            for tpl in bodies:
                with self.subTest(tpl=tpl):
                    resp = self.client.put("/api/templates/Mine", json=tpl)
                    self.assertEqual((resp.status_code, resp.get_json()),
                                     (400, {"error": f"That isn't a template: {fault}"}))
        self.assertEqual(self.saved(), [])
        # A layout alone is enough, with or without elements
        self.assertEqual(self.client.put("/api/templates/Mine", json={"layout": {"tape": "62"}}).status_code, 200)

    def test_a_damaged_template_file_says_so(self):
        folder = os.path.join(self.data, "templates")
        files = {
            "Cut short": (b'{"layout": {"tape": "62red", "elem', "That template's file is damaged and can't be opened"),
            "Not text": (b"\xff\xfe\x00\x01", "That template's file is damaged and can't be opened"),
            "A list": (b"[1]", "That template can't be opened: it has no layout"),
        }
        for name, (raw, msg) in files.items():
            with self.subTest(name):
                with open(os.path.join(folder, name + ".json"), "wb") as f:
                    f.write(raw)
                resp = self.client.get("/api/templates/" + quote(name))
                self.assertEqual((resp.status_code, resp.get_json()), (422, {"error": msg}))

    def test_a_save_that_fails_leaves_the_template_whole(self):
        # As when the drive fills up or is pulled out partway through writing
        self.client.put("/api/templates/Mine", json=self.tpl(1))

        def cut_short(data, f, **options):
            f.write('{"layout": {"ta')
            raise OSError(28, "No space left on device")

        with mock.patch.object(server.json, "dump", cut_short):
            resp = self.client.put("/api/templates/Mine?replace=1", json=self.tpl(2))
            self.assertEqual((resp.status_code, resp.get_json()),
                             (500, {"error": "Couldn't save it: No space left on device"}))
            resp = self.post("/api/config", {"printer_host": "192.168.1.50"})
            self.assertEqual(resp.status_code, 500)
        self.assertEqual(self.client.get("/api/templates/Mine").get_json(), self.tpl(1))
        self.assertEqual(self.saved(), ["Mine.json"])   # and no part-written file beside it
        self.assertEqual(os.listdir(self.data), ["templates"])

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


    def test_api_requests_from_other_sites_are_refused(self):
        # A browser says what kind of page a request comes from. "same-site"
        # is another program's page on this machine, at another port.
        for site in ("cross-site", "same-site"):
            with self.subTest(site):
                resp = self.client.get("/api/meta", headers={"Sec-Fetch-Site": site})
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.get_json(), {"error": "Requests from other sites aren't accepted"})
        # The data upload is a form, which any page may send without asking
        resp = self.client.post("/api/data", data={"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")},
                                content_type="multipart/form-data", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.status_code, 403)

    def test_the_editor_and_other_programs_are_let_in(self):
        # The editor's own page, the address bar, and anything that isn't a
        # browser and so doesn't say
        for site in ("same-origin", "none", None):
            with self.subTest(site):
                headers = {"Sec-Fetch-Site": site} if site else {}
                self.assertEqual(self.client.get("/api/meta", headers=headers).status_code, 200)
        # A link on another site still opens the editor
        with self.client.get("/", headers={"Sec-Fetch-Site": "cross-site"}) as resp:
            self.assertEqual(resp.status_code, 200)


class PagePolicy(ApiTest):

    def test_every_response_carries_the_headers(self):
        for method, path in (("get", "/"), ("get", "/static/app.mjs"), ("get", "/api/meta"),
                             ("get", "/api/nothing"), ("get", "/nothing"), ("post", "/api/render")):
            with self.subTest(path), getattr(self.client, method)(path, json={"layout": layout(TITLE)}) as resp:
                self.assertEqual(resp.headers["Content-Security-Policy"], server.PAGE_POLICY)
                self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")

    def test_static_files_say_what_they_are(self):
        # With nosniff a browser goes by the type alone, and runs or applies nothing else
        for path, kind in (("/", "text/html"), ("/static/app.mjs", "javascript"), ("/static/units.mjs", "javascript"),
                           ("/static/style.css", "text/css")):
            with self.subTest(path), self.client.get(path) as resp:
                self.assertIn(kind, resp.content_type)

    def test_the_page_keeps_to_its_policy(self):
        # The policy allows scripts and styles from the app's own files only,
        # so the page has none written into it, and the editor adds none
        self.assertIn("script-src 'self';", server.PAGE_POLICY)
        self.assertIn("style-src 'self';", server.PAGE_POLICY)
        with open(os.path.join(server.STATIC, "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertNotRegex(page, r"<style|\sstyle=|<script(?![^>]*\ssrc=)|\son[a-z]+=|javascript:")
        for name in editor_modules():
            with self.subTest(name), open(os.path.join(server.STATIC, name), encoding="utf-8") as f:
                self.assertNotRegex(f.read(), r"""\bstyle:\s*["'`]|setAttribute\(\s*["']style|\beval\(|new Function""")


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
        with mock.patch.object(server.tapes, "tape_list", side_effect=RuntimeError("boom")), \
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
        names = fields.placeholders(tpl["layout"])
        self.assertEqual(sorted(names), sorted(headers))
        self.assertEqual(names, [f.lower() for f in names])   # lowercase, the house style
        self.assertEqual(tpl["mapping"], {f: f for f in names})


class Pages(ApiTest):

    def test_editor_and_its_files(self):
        with self.client.get("/") as page:   # files are sent open: close them
            self.assertEqual((page.status_code, page.mimetype), (200, "text/html"))
            self.assertIn(b'<script type="module" src="/static/app.mjs">', page.data)
        for path in ("/static/style.css", *("/static/" + name for name in editor_modules())):
            with self.subTest(path), self.client.get(path) as resp:
                self.assertEqual(resp.status_code, 200)

    def test_every_module_the_editor_imports_is_there(self):
        # A module renamed or left out stops the whole page, and only in a browser
        self.assertIn("app.mjs", editor_modules())
        for folder in (server.STATIC, server.EDITOR_TESTS):
            for name in sorted(n for n in os.listdir(folder) if n.endswith(".mjs")):
                with self.subTest(name), open(os.path.join(folder, name), encoding="utf-8") as f:
                    for target in IMPORT.findall(f.read()):
                        self.assertTrue(os.path.isfile(os.path.join(folder, target)), target)

    def test_the_editors_tests_are_served_only_when_asked_for(self):
        for path in ("/tests/editor/", "/tests/editor/all.mjs", "/app/static/units.mjs"):
            with self.subTest(path):
                self.assertEqual(self.client.get(path).status_code, 404)
        client = server.create_app(self.data, editor_tests=True).test_client()
        for path, kind in (("/tests/editor/", "text/html"), ("/tests/editor/all.mjs", "javascript"),
                           ("/tests/editor/page.css", "text/css"), ("/app/static/units.mjs", "javascript")):
            with self.subTest(path), client.get(path) as resp:
                self.assertEqual(resp.status_code, 200)
                self.assertIn(kind, resp.content_type)
        self.assertEqual(client.get("/tests/editor/../test_server.py").status_code, 404)

    def test_the_editors_tests_cover_every_test_file_and_use_the_servers_pattern(self):
        with open(os.path.join(server.EDITOR_TESTS, "all.mjs"), encoding="utf-8") as f:
            listed = sorted(IMPORT.findall(f.read()))
        on_disk = sorted("./" + n for n in os.listdir(server.EDITOR_TESTS) if n.endswith(".test.mjs"))
        self.assertEqual([n for n in listed if n.endswith(".test.mjs")], on_disk)
        # The editor is sent the server's field pattern; its tests hold a copy
        with open(os.path.join(server.EDITOR_TESTS, "fields.test.mjs"), encoding="utf-8") as f:
            self.assertIn("const PATTERN = " + json.dumps(fields.PLACEHOLDER.pattern) + ";", f.read())

    def test_nothing_outside_the_static_folder(self):
        for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/missing.js"):
            with self.subTest(path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_open_page_is_counted_until_it_closes(self):
        stream = self.client.get("/api/alive", buffered=False)
        self.assertEqual(stream.mimetype, "text/event-stream")
        self.assertEqual(next(iter(stream.response)), b"retry: 2000\n\n")
        self.assertEqual(self.app.presence.count, 1)
        stream.close()   # as when the page closes
        self.assertEqual(self.app.presence.count, 0)


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
