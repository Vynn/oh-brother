"""Flask backend. Stateless apart from config and templates in the data folder."""

import io
import json
import os
import re
import threading
import time
from urllib.parse import quote, urlsplit

from flask import Flask, Response, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, InternalServerError

import printer
import render
import tables

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# Sample templates and data, shipped with the app and read-only. The data
# folder holds only the user's own templates and settings.
SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
MODELS = ["QL-800", "QL-810W", "QL-820NWB"]  # two-colour capable QL models
DEFAULT_CONFIG = {"printer_host": "", "printer_port": 9100, "model": "QL-820NWB"}
KEEPALIVE_S = 3   # how often the presence stream writes; a closed page is noticed on the next write
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}   # names this machine is reached by without --lan


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


def blank_code_warnings(blanks, copies):
    """Print warnings for QR codes and barcodes left blank, counted by label.

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
        name = "QR code" if kind == "qr" else "Barcode"
        out.append(f"{name} {why} on {n} label{'' if n == 1 else 's'}; printed blank")
    return out


def is_local_host(host):
    """True if a request's Host header names this machine."""
    try:
        return urlsplit("//" + host).hostname in LOCAL_HOSTS
    except ValueError:   # malformed, e.g. an unclosed [ for IPv6
        return False


def create_app(data_dir, lan=False, samples_dir=SAMPLES):
    """The app. `lan`: other machines may connect, by any name for this one."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    tpl_dir = os.path.join(data_dir, "templates")
    sample_dir = os.path.join(samples_dir, "templates")
    cfg_path = os.path.join(data_dir, "config.json")
    os.makedirs(tpl_dir, exist_ok=True)
    app.presence = Presence()

    def load_config():
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
        return cfg

    def tpl_path(name, folder=tpl_dir):
        safe = re.sub(r"[^\w\- ]+", "", name).strip()
        if not safe:
            abort(400, "Invalid template name")
        return os.path.join(folder, safe + ".json")

    def tpl_names(folder):
        try:
            return sorted(n[:-5] for n in os.listdir(folder) if n.endswith(".json"))
        except OSError:   # e.g. no samples folder
            return []

    def read_tpl(path):
        try:
            with open(path, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except OSError:
            abort(404, "No template by that name")

    def body():
        data = request.get_json(silent=True)   # guard() has made sure it's sent as JSON
        if not isinstance(data, dict):
            abort(400, "Expected a JSON object")
        return data

    # ---- requests from other sites ------------------------------------------

    @app.before_request
    def guard():
        # A site can point its own name at 127.0.0.1 ("DNS rebinding"), and the
        # browser then treats this app as part of that site. Its pages send
        # that name as the Host, so only this machine's own names are let in.
        # With --lan, other machines use whatever name they know it by.
        if not lan and not is_local_host(request.host):
            abort(403, "Unknown host name; open the app at 127.0.0.1 or localhost")
        # Pages on other sites can send forms and plain text here without
        # asking, but JSON only after a CORS check this server never answers.
        # So anything with a body must be JSON. The data upload is a form, but
        # it only reads the file and changes nothing.
        if request.method in ("POST", "PUT", "PATCH") and request.endpoint != "parse_csv" \
                and not request.is_json:
            abort(415, "Requests must be sent as JSON")

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
        return jsonify(config=cfg, models=MODELS, tapes=render.tape_list(cfg["model"]),
                       fonts=list(render.FONT_FILES), dpmm=render.DPMM)

    @app.post("/api/config")
    def save_config():
        cfg = load_config()
        b = body()
        for k in DEFAULT_CONFIG:
            if k in b:
                cfg[k] = b[k]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return jsonify(config=cfg)

    @app.post("/api/test")
    def test_printer():
        cfg = load_config()
        if not cfg["printer_host"]:
            return jsonify(ok=False, message="No printer address set")
        ok, msg = printer.check(cfg["printer_host"], cfg["printer_port"])
        return jsonify(ok=ok, message=msg)

    # ---- rendering & printing ---------------------------------------------

    @app.post("/api/render")
    def render_preview():
        # Raw PNG (fast compression) rather than base64 JSON: this runs on
        # every drag frame. Metadata rides along in headers as URL-encoded JSON.
        b = body()
        layout = b.get("layout", {})
        try:
            img, warnings, blank = render.render(layout, b.get("record"), keep_missing=True, chain=set(b.get("chain") or ()))
        except Exception as e:
            return jsonify(error=str(e)), 400
        buf = io.BytesIO()
        img.save(buf, "PNG", compress_level=1)
        return Response(buf.getvalue(), mimetype="image/png", headers={
            "Cache-Control": "no-store",
            "X-Warnings": quote(json.dumps(warnings)),
            "X-Placeholders": quote(json.dumps(render.placeholders(layout))),
            "X-Blank": quote(json.dumps(blank)),
        })

    @app.post("/api/print")
    def print_labels():
        b = body()
        cfg = load_config()
        layout = b.get("layout", {})
        records = b.get("records") or [{}]
        chain = set(b.get("chain") or ())   # fields whose fixed values may hold {{tags}}
        try:
            copies = max(1, min(100, int(b.get("copies", 1))))
        except (TypeError, ValueError):
            return jsonify(error="Copies must be a whole number"), 400
        dry_run = bool(b.get("dry_run"))
        if not cfg["printer_host"] and not dry_run:
            return jsonify(error="Set the printer address first"), 400

        images, warnings, blanks = [], [], []
        try:
            for rec in records:
                img, w, blank = render.render(layout, rec, keep_missing=False, chain=chain)
                warnings += [x for x in w if x not in warnings]
                images += [img] * copies
                blanks.append(blank)
        except Exception as e:   # as for the preview: a bad layout or record
            return jsonify(error=f"Rendering failed: {e}"), 400
        warnings += blank_code_warnings(blanks, copies)
        try:
            job = printer.build_job(layout, images, cfg["model"], cut=b.get("cut", True))
        except Exception as e:
            return jsonify(error=f"Conversion failed: {e}"), 400
        if not dry_run:
            try:
                printer.send(cfg["printer_host"], cfg["printer_port"], job)
            except OSError as e:
                return jsonify(error=f"Send failed: {e}"), 502
        return jsonify(labels=len(images), bytes=len(job), warnings=warnings, dry_run=dry_run)

    # ---- CSV ---------------------------------------------------------------

    @app.post("/api/csv")
    def parse_csv():
        # Any supported table file, despite the name: see tables.py
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
        headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
        records = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)} for r in rows[1:]]
        return jsonify(headers=headers, rows=records)

    # ---- templates ---------------------------------------------------------

    @app.get("/api/templates")
    def list_templates():
        return jsonify(templates=tpl_names(tpl_dir), samples=tpl_names(sample_dir))

    @app.get("/api/templates/<name>")
    def get_template(name):
        return read_tpl(tpl_path(name))

    # Samples can be opened but not saved over or deleted: saving writes a
    # template of the user's own
    @app.get("/api/samples/<name>")
    def get_sample(name):
        return read_tpl(tpl_path(name, sample_dir))

    @app.put("/api/templates/<name>")
    def put_template(name):
        with open(tpl_path(name), "w", encoding="utf-8") as f:
            json.dump(body(), f, indent=2)
        return jsonify(ok=True)

    @app.delete("/api/templates/<name>")
    def delete_template(name):
        try:
            os.remove(tpl_path(name))
        except OSError:
            abort(404, "No template by that name")
        return jsonify(ok=True)

    return app
