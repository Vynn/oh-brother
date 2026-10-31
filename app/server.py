"""Flask backend. Stateless apart from config and templates in the data folder."""

import io
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

from flask import Flask, Response, abort, jsonify, request, send_from_directory

import printer
import render
import tables

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MODELS = ["QL-800", "QL-810W", "QL-820NWB"]  # two-colour capable QL models
DEFAULT_CONFIG = {"printer_host": "", "printer_port": 9100, "model": "QL-820NWB"}
KEEPALIVE_S = 3   # how often the presence stream writes; a closed page is noticed on the next write


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


def create_app(data_dir):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    tpl_dir = os.path.join(data_dir, "templates")
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

    def tpl_path(name):
        safe = re.sub(r"[^\w\- ]+", "", name).strip()
        if not safe:
            abort(400, "Invalid template name")
        return os.path.join(tpl_dir, safe + ".json")

    def body():
        return request.get_json(force=True, silent=True) or {}

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
        copies = max(1, min(100, int(b.get("copies", 1))))
        dry_run = bool(b.get("dry_run"))
        if not cfg["printer_host"] and not dry_run:
            return jsonify(error="Set the printer address first"), 400

        images, warnings, blanks = [], [], {}
        for rec in records:
            img, w, blank = render.render(layout, rec, keep_missing=False, chain=chain)
            warnings += [x for x in w if x not in warnings]
            images += [img] * copies
            for b in blank:   # count labels printed with a blank code
                if b["type"] == "text":
                    continue   # text with empty fields is hidden on purpose
                key = (b["type"], b["why"])
                blanks[key] = blanks.get(key, 0) + copies
        for (kind, why), n in blanks.items():
            name = "QR code" if kind == "qr" else "Barcode"
            warnings.append(f"{name} {why} on {n} label{'' if n == 1 else 's'}; printed blank")
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
        except ValueError as e:
            return jsonify(error=str(e)), 400
        except ET.ParseError:
            return jsonify(error="The file looks damaged"), 400
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            return jsonify(error="The file has no rows"), 400
        headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
        records = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)} for r in rows[1:]]
        return jsonify(headers=headers, rows=records)

    # ---- templates ---------------------------------------------------------

    @app.get("/api/templates")
    def list_templates():
        names = sorted(n[:-5] for n in os.listdir(tpl_dir) if n.endswith(".json"))
        return jsonify(templates=names)

    @app.get("/api/templates/<name>")
    def get_template(name):
        try:
            with open(tpl_path(name), encoding="utf-8") as f:
                return jsonify(json.load(f))
        except OSError:
            abort(404)

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
            abort(404)
        return jsonify(ok=True)

    return app
