"""Flask backend. Its only state is the config and templates in the data
folder, and the count of open editor pages."""

import datetime
import io
import json
import os
import re
import threading
import time
from urllib.parse import quote, urlsplit

from flask import Flask, Response, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, InternalServerError

import barcodes
import fields
import printer
import remote
import render
import status
import tables
import tapes

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# Sample templates and data, shipped with the app and read-only. The data
# folder holds only the user's own templates and settings.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples")
# The editor's own tests, served only when asked for (--tests); see create_app()
EDITOR_TESTS = os.path.join(ROOT, "tests", "editor")
MODELS = ["QL-800", "QL-810W", "QL-820NWB"]  # two-colour capable QL models
DEFAULT_CONFIG = {"printer_host": "", "printer_port": 9100, "model": "QL-820NWB"}
KEEPALIVE_S = 3   # how often the presence stream writes; a closed page is noticed on the next write
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}   # names this machine is reached by without --lan
MAX_COPIES = 100   # of each label in one job; the editor is sent this (/api/meta)

# What the editor's page may load and do, sent with every response as its
# Content-Security-Policy. The page uses its own script and stylesheet and
# nothing from elsewhere. Previews are blob: addresses; saved images are data:
# addresses, which the editor also reads back with fetch(), hence connect-src.
# frame-ancestors stops another site showing the editor inside its own page,
# where a click meant for that page could land on Print.
PAGE_POLICY = "; ".join((
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' blob: data:",
    "connect-src 'self' data:",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
))

# Template names become file names, so they follow the rules of Windows, macOS
# and Linux together. Names that break them are refused, not changed.
BAD_NAME_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
# The list is joined with no-break spaces so it never wraps partway
BAD_NAME_MSG = "Template names can't contain " + "\u00a0".join('/\\:*?"<>|')
# Device names Windows keeps for itself, with any extension: "con" and "con.v2"
# would be saved as con.json and con.v2.json, which Windows can't open
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10))}
MAX_NAME = 60   # characters; at up to 4 bytes each, under the usual 255-byte limit with ".json"


class Presence:
    """Counts open editor pages, each holding a stream to /api/alive."""

    def __init__(self):
        self.lock = threading.Lock()
        self.count, self.seen, self.idle_since = 0, False, None

    def join(self):
        with self.lock:
            self.count += 1
            self.seen, self.idle_since = True, None

    def leave(self):
        with self.lock:
            self.count -= 1
            if self.count == 0:
                self.idle_since = time.monotonic()   # monotonic: doesn't count time asleep

    def idle_for(self):
        """Seconds since the last page closed; 0 while one is open or none has opened yet."""
        with self.lock:
            if not self.seen or self.count or self.idle_since is None:
                return 0
            return time.monotonic() - self.idle_since


def reason(e):
    """An error's message, or its name when it has none (as some of brother_ql's)."""
    return str(e) or type(e).__name__


def write_json(path, data):
    """Write a JSON file so that it's the old one or the new one, never part of one.

    It's written beside the file under another name, then moved into place.
    A drive pulled out or filled up partway leaves the file as it was, where
    writing over it would have left it cut short.
    """
    tmp = path + ".tmp"   # not ".json", so a leftover is never listed as a template
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def clean_setting(key, value):
    """A printer setting, tidied, or ValueError with the reason for the user."""
    if key == "printer_host":
        if not isinstance(value, str):
            raise ValueError("The printer's address must be text")
        value = value.strip()
        if len(value) > 253 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("That isn't a printer address: use its IP address or host name")
        return value
    if key == "printer_port":
        try:
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ValueError
            port = int(value)
        except ValueError:
            port = 0
        if not 1 <= port <= 65535:
            raise ValueError("The port must be a number from 1 to 65535")
        return port
    if value not in MODELS:   # key == "model"
        raise ValueError("Choose one of these printer models: " + ", ".join(MODELS))
    return value


def template_fault(data):
    """Why saved data can't be used as a template, or None if it can.

    A template holds a layout, and may hold fixed values and a column mapping.
    """
    if not isinstance(data, dict) or not isinstance(data.get("layout"), dict):
        return "it has no layout"
    elements = data["layout"].get("elements", [])
    if not isinstance(elements, list) or not all(isinstance(e, dict) for e in elements):
        return "its elements aren't a list"
    for key, name in (("fixed", "fixed values"), ("mapping", "column choices")):
        if not isinstance(data.get(key, {}), dict):
            return f"its {name} can't be read"
    return None


def unique_headers(row):
    """Column names from a data file's first row, no two the same.

    An empty name becomes "Column 3". A name that repeats an earlier one
    becomes "name (2)": rows are kept by column name, so the second "name"
    column used to replace the first without a word. Field names ignore case,
    so "Code" after "code" counts as a repeat too.
    """
    out, used = [], set()
    for i, h in enumerate(row):
        base = h.strip() or f"Column {i + 1}"
        name, n = base, 1
        while name.lower() in used:
            n += 1
            name = f"{base} ({n})"
        used.add(name.lower())
        out.append(name)
    return out


class RowError(Exception):
    """A label that couldn't be drawn, with a message naming its row."""


class Labels:
    """A print job's labels, each drawn when printer.build_job() reaches it.

    A job used to draw every label before converting any, holding 0.74 MB for
    each 62 x 30 mm label: 3.7 GB for 5,000 rows. Now one label's image exists
    at a time. The warnings and blank lists are complete once the job is built.
    `rows` are the records' row numbers in the data file, for error messages.
    """

    def __init__(self, layout, records, copies, chain, now, rows=None):
        self.layout, self.records, self.copies = layout, records, copies
        self.chain, self.now, self.rows = chain, now, rows
        self.warnings, self.blanks = [], []

    def __len__(self):
        return len(self.records) * self.copies

    def where(self, n):
        if self.rows:
            return f" on row {self.rows[n]}"
        return f" on label {n + 1}" if len(self.records) > 1 else ""

    def __iter__(self):
        for n, rec in enumerate(self.records):
            try:
                img, w, blank = render.render(self.layout, rec, keep_missing=False, chain=self.chain, now=self.now)
            except Exception as e:   # as for the preview: a record the layout can't take
                raise RowError(f"Rendering failed{self.where(n)}: {reason(e)}") from e
            self.warnings += [x for x in w if x not in self.warnings]
            self.blanks.append(blank)
            for _ in range(self.copies):
                yield img


BLANK_NAMES = {"qr": "QR code", "barcode": "Barcode", "image": "Image"}


def blank_code_warnings(blanks, copies):
    """Print warnings for QR codes, barcodes and images left blank, counted by label.

    `blanks` holds render()'s blank list for each record. Text hidden because
    its fields are empty isn't counted: hiding it is intended.
    """
    counts = {}
    for blank in blanks:
        # A set, so two blank codes on one label count that label once
        for key in {(x["type"], x["why"]) for x in blank if x["type"] != "text"}:
            counts[key] = counts.get(key, 0) + copies
    out = []
    for (kind, why), n in sorted(counts.items()):
        name = BLANK_NAMES.get(kind, kind)
        out.append(f"{name} {why} on {n} label{'' if n == 1 else 's'}; printed blank")
    return out


def is_local_host(host):
    """True if a request's Host header names this machine."""
    try:
        return urlsplit("//" + host).hostname in LOCAL_HOSTS
    except ValueError:   # malformed, e.g. an unclosed [ for IPv6
        return False


def create_app(data_dir, lan=False, samples_dir=SAMPLES, editor_tests=False):
    """The app. `lan`: other machines may connect, by any name for this one.
    `editor_tests`: also serve the editor's tests, as a page to open."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    tpl_dir = os.path.join(data_dir, "templates")
    sample_dir = os.path.join(samples_dir, "templates")
    cfg_path = os.path.join(data_dir, "config.json")
    os.makedirs(tpl_dir, exist_ok=True)
    app.presence = Presence()

    def load_config():
        # Whatever config.json holds, the settings that come back are usable:
        # a file that's missing, damaged or not an object gives the defaults,
        # and so does any one setting with a value that can't be used.
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(cfg_path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            for k in DEFAULT_CONFIG:
                if k in saved:
                    try:
                        cfg[k] = clean_setting(k, saved[k])
                    except ValueError:
                        pass
        return cfg

    def save_json(path, data):
        try:
            write_json(path, data)
        except OSError as e:   # a full or read-only drive
            abort(500, f"Couldn't save it: {e.strerror or e}")

    def tpl_path(name, folder=tpl_dir):
        name = name.strip()
        if not name:
            abort(400, "Give the template a name")
        if BAD_NAME_CHARS.search(name):
            abort(400, BAD_NAME_MSG)
        if name.startswith(".") or name.endswith("."):
            abort(400, "Template names can't start or end with a dot")
        if name.split(".")[0].rstrip().lower() in RESERVED_NAMES:
            abort(400, f"“{name}” is a name Windows keeps for devices. Choose another.")
        if len(name) > MAX_NAME:
            abort(400, f"Template names can be up to {MAX_NAME} characters")
        return os.path.join(folder, name + ".json")

    def tpl_names(folder):
        try:
            return sorted(n[:-5] for n in os.listdir(folder) if n.endswith(".json"))
        except OSError:   # e.g. no samples folder
            return []

    def read_tpl(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            abort(404, "No template by that name")
        except ValueError:   # not JSON, or not text at all
            abort(422, "That template's file is damaged and can't be opened")
        fault = template_fault(data)
        if fault:
            abort(422, f"That template can't be opened: {fault}")
        return jsonify(data)

    def body():
        data = request.get_json(silent=True)   # guard() has made sure it's sent as JSON
        if not isinstance(data, dict):
            abort(400, "Expected a JSON object")
        return data

    def layout_of(b):
        layout = b.get("layout", {})
        if not isinstance(layout, dict):
            abort(400, "Expected a layout")
        return layout

    # ---- requests from other sites ------------------------------------------

    @app.before_request
    def guard():
        # A site can point its own name at 127.0.0.1 ("DNS rebinding"), and the
        # browser then treats this app as part of that site. Its pages send
        # that name as the Host, so only this machine's own names are let in.
        # With --lan, other machines use whatever name they know it by.
        if not lan and not is_local_host(request.host):
            abort(403, "Unknown host name; open the app at 127.0.0.1 or localhost")
        # Browsers say where a request comes from, in Sec-Fetch-Site: the
        # editor's own page ("same-origin"), the address bar or a bookmark
        # ("none"), or a page on another site. Only the first two have any
        # reason to call the API. The page itself stays open to links from
        # anywhere. Browsers send this only to addresses they count as secure,
        # which 127.0.0.1 and localhost are and a plain http address on the
        # network is not, so with --lan it's mostly absent, as it is from other
        # programs; then the checks around this one are what applies.
        if request.path.startswith("/api/") \
                and request.headers.get("Sec-Fetch-Site", "none") not in ("same-origin", "none"):
            abort(403, "Requests from other sites aren't accepted")
        # Pages on other sites can send forms and plain text here without
        # asking, but JSON only after a CORS check this server never answers.
        # So anything with a body must be JSON. The data upload is a form, but
        # it only reads the file and changes nothing.
        if request.method in ("POST", "PUT", "PATCH") and request.endpoint != "read_data" \
                and not request.is_json:
            abort(415, "Requests must be sent as JSON")

    @app.after_request
    def protect(resp):
        resp.headers.setdefault("Content-Security-Policy", PAGE_POLICY)
        # A response is only ever what its Content-Type says: an uploaded
        # image or a template's text is never run as a script or shown as a page
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    # ---- errors: the API answers in JSON, which the editor shows -----------

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    @app.errorhandler(Exception)
    def server_error(e):
        app.logger.exception("Error on %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify(error=f"Server error: {str(e) or type(e).__name__}"), 500
        return InternalServerError()

    # ---- pages -------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:p>")
    def static_files(p):
        return send_from_directory(STATIC, p)

    # ---- the editor's tests, with --tests -----------------------------------
    # The test files import the editor's modules by the path between the two
    # folders ("../../app/static/units.mjs"), as Node needs in CI. So here
    # both folders are served where they sit in the repository, and the same
    # files run in a browser at /tests/editor/.
    if editor_tests:
        @app.get("/tests/editor/")
        def editor_tests_page():
            return send_from_directory(EDITOR_TESTS, "index.html")

        @app.get("/tests/editor/<path:p>")
        def editor_tests_files(p):
            return send_from_directory(EDITOR_TESTS, p)

        @app.get("/app/static/<path:p>")
        def editor_modules(p):
            return send_from_directory(STATIC, p)

    # ---- presence: lets the launcher stop once the last page closes --------

    @app.get("/api/alive")
    def alive():
        def stream():
            app.presence.join()
            try:
                yield "retry: 2000\n\n"   # reconnect quickly after a drop
                while True:
                    time.sleep(KEEPALIVE_S)
                    yield ": keep-alive\n\n"   # fails once the page is gone, ending the stream
            finally:
                app.presence.leave()

        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-store"})

    # ---- config ------------------------------------------------------------

    @app.get("/api/meta")
    def meta():
        cfg = load_config()
        # The field tag pattern and built-in fields, so the editor finds fields as the server
        # does, the barcode types with what each takes, and the most an image may
        # take up, which the editor shrinks images to fit; and the limits on
        # lengths and copies, which the editor keeps to and the server enforces
        return jsonify(config=cfg, models=MODELS, tapes=tapes.tape_list(cfg["model"]),
                       fonts=list(render.FONT_FILES), dpmm=tapes.DPMM,
                       field_pattern=fields.PLACEHOLDER.pattern, builtin_fields=list(fields.BUILTINS),
                       barcodes=[{"id": k, "name": v.name, "hint": v.hint} for k, v in barcodes.KINDS.items()],
                       image_budget=render.MAX_IMAGE_CHARS,
                       limits={"length_mm": [tapes.MIN_LENGTH_MM, tapes.MAX_LENGTH_MM], "copies": MAX_COPIES})

    @app.post("/api/config")
    def save_config():
        cfg = load_config()
        b = body()
        # Every setting sent is checked before any is saved
        for k in DEFAULT_CONFIG:
            if k in b:
                try:
                    cfg[k] = clean_setting(k, b[k])
                except ValueError as e:
                    abort(400, str(e))
        save_json(cfg_path, cfg)
        return jsonify(config=cfg)

    @app.post("/api/test")
    def test_printer():
        cfg = load_config()
        if not cfg["printer_host"]:
            return jsonify(ok=False, message="No printer address set")
        ok, msg = printer.check(cfg["printer_host"], cfg["printer_port"])
        st = status.read(cfg["printer_host"]) if ok else None
        if st:
            msg += " · " + status.summary(st)
        return jsonify(ok=ok, message=msg, status=st)

    # Whether port 9100 takes a connection, for a printer that gives no status,
    # remembered for a while: the editor asks for the status every 5 seconds,
    # and that's too often to keep opening connections to the port jobs go to
    reach = {"at": None, "ok": None}
    REACH_FOR_S = 30

    # What the printer says it's doing and what tape it has, for the printer
    # chip, polled by the editor. `tape`, the layout's tape, adds `mismatch`
    # when the printer has another loaded. `status` is None when there's no
    # address, or the printer doesn't say (status.py); `reachable` then says
    # whether it takes jobs at all.
    @app.get("/api/status")
    def printer_status():
        cfg = load_config()
        host = cfg["printer_host"]
        if not host:
            return jsonify(status=None, summary=None, mismatch=None, reachable=None)
        st = status.read(host)
        reachable = None
        if st is None:
            key = (host, cfg["printer_port"])
            if reach["at"] is None or reach["at"][0] != key or time.monotonic() - reach["at"][1] > REACH_FOR_S:
                reach["ok"], _ = printer.check(host, cfg["printer_port"])
                reach["at"] = (key, time.monotonic())
            reachable = reach["ok"]
        return jsonify(status=st, summary=status.summary(st) if st else None,
                       mismatch=status.mismatch(request.args.get("tape", ""), st), reachable=reachable)

    # ---- rendering & printing ---------------------------------------------

    @app.post("/api/render")
    def render_preview():
        # Raw PNG (fast compression) rather than base64 JSON: this runs on
        # every drag frame. Metadata rides along in headers as URL-encoded JSON.
        b = body()
        layout = layout_of(b)
        try:
            img, warnings, blank = render.render(layout, b.get("record"), keep_missing=True, chain=set(b.get("chain") or ()))
        except Exception as e:
            return jsonify(error=reason(e)), 400
        buf = io.BytesIO()
        img.save(buf, "PNG", compress_level=1)
        return Response(buf.getvalue(), mimetype="image/png", headers={
            "Cache-Control": "no-store",
            "X-Warnings": quote(json.dumps(warnings)),
            "X-Placeholders": quote(json.dumps(fields.placeholders(layout))),
            "X-Blank": quote(json.dumps(blank)),
        })

    @app.post("/api/print")
    def print_labels():
        b = body()
        cfg = load_config()
        layout = layout_of(b)
        records = b.get("records") or [{}]
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            return jsonify(error="Records must be a list of objects"), 400
        # The records' row numbers in the data file, when the editor sends them
        rows = b.get("rows")
        if not isinstance(rows, list) or len(rows) != len(records):
            rows = None
        chain = set(b.get("chain") or ())   # fields whose fixed values may hold {{tags}}
        try:
            copies = max(1, min(MAX_COPIES, int(b.get("copies", 1))))
        except (TypeError, ValueError):
            return jsonify(error="Copies must be a whole number"), 400
        dry_run = bool(b.get("dry_run"))
        if not cfg["printer_host"] and not dry_run:
            return jsonify(error="Set the printer address first"), 400
        # Before sending, ask the printer what it has loaded and whether it's
        # in trouble. A reason comes back as 409, and the editor asks before
        # sending again with "anyway": the reading may be wrong, and a printer
        # that doesn't say lets the job through as before.
        if not dry_run and not b.get("anyway"):
            problem = status.fits(layout.get("tape", "62red"), status.read(cfg["printer_host"]))
            if problem:
                return jsonify(error=problem, ask=True), 409

        # What's wrong with the layout itself is found here, so it isn't
        # reported as a fault in the first row
        try:
            tapes.canvas_dots(layout)
        except Exception as e:
            return jsonify(error=f"Rendering failed: {reason(e)}"), 400
        # One date and time for the whole job. Each label is drawn as the
        # conversion reaches it, and the job is sent only once all are done,
        # so an error in any row still prints nothing.
        labels = Labels(layout, records, copies, chain, datetime.datetime.now(), rows)
        try:
            job = printer.build_job(layout, labels, cfg["model"], cut=b.get("cut", True))
        except RowError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:
            return jsonify(error=f"Conversion failed: {reason(e)}"), 400
        warnings = labels.warnings + blank_code_warnings(labels.blanks, copies)
        if not dry_run:
            try:
                printer.send(cfg["printer_host"], cfg["printer_port"], job)
            except OSError as e:
                return jsonify(error=f"Send failed: {e}"), 502
        return jsonify(labels=len(labels), bytes=len(job), warnings=warnings, dry_run=dry_run)

    # ---- images from a web address ------------------------------------------

    # Fetched here, not in the browser, which most sites don't allow; see remote.py
    @app.post("/api/image-url")
    def image_from_url():
        try:
            return jsonify(remote.fetch_image(body().get("url")))
        except remote.FetchError as e:
            return jsonify(error=str(e)), 400

    # ---- data files --------------------------------------------------------

    @app.post("/api/data")
    def read_data():
        # Any data file tables.py reads: CSV, TSV, spreadsheets or JSON
        f = request.files.get("file")
        if not f:
            return jsonify(error="No file"), 400
        try:
            rows = tables.read_table(f.filename or "", f.read())
        except tables.TableError as e:
            return jsonify(error=str(e)), 400
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            return jsonify(error="The file has no rows"), 400
        headers = unique_headers(rows[0])
        records = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)} for r in rows[1:]]
        return jsonify(headers=headers, rows=records)

    # ---- templates ---------------------------------------------------------
    # Names are matched as paths, so one with a slash reaches tpl_path() and is
    # refused with its reason rather than a bare "not found".

    @app.get("/api/templates")
    def list_templates():
        return jsonify(templates=tpl_names(tpl_dir), samples=tpl_names(sample_dir))

    @app.get("/api/templates/<path:name>")
    def get_template(name):
        return read_tpl(tpl_path(name))

    # Samples can be opened but not saved over or deleted: saving writes a
    # template of the user's own
    @app.get("/api/samples/<path:name>")
    def get_sample(name):
        return read_tpl(tpl_path(name, sample_dir))

    @app.put("/api/templates/<path:name>")
    def put_template(name):
        path, data = tpl_path(name), body()
        fault = template_fault(data)
        if fault:
            abort(400, f"That isn't a template: {fault}")
        # Saving over a template takes ?replace=1, sent once the editor has asked
        if os.path.exists(path) and request.args.get("replace") != "1":
            abort(409, "A template by that name exists")
        save_json(path, data)   # the template it replaces stays whole if this fails
        return jsonify(ok=True)

    @app.delete("/api/templates/<path:name>")
    def delete_template(name):
        try:
            os.remove(tpl_path(name))
        except OSError:
            abort(404, "No template by that name")
        return jsonify(ok=True)

    return app
