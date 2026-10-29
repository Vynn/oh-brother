"""Flask backend. Stateless apart from config and templates in the data folder."""

import base64
import csv
import io
import json
import os
import re

from flask import Flask, abort, jsonify, request, send_from_directory

import printer
import render

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MODELS = ["QL-800", "QL-810W", "QL-820NWB"]  # two-colour capable QL models
DEFAULT_CONFIG = {"printer_host": "", "printer_port": 9100, "model": "QL-820NWB"}


def create_app(data_dir):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    tpl_dir = os.path.join(data_dir, "templates")
    cfg_path = os.path.join(data_dir, "config.json")
    os.makedirs(tpl_dir, exist_ok=True)

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
        b = body()
        layout = b.get("layout", {})
        try:
            img, warnings = render.render(layout, b.get("record"), keep_missing=True)
        except Exception as e:
            return jsonify(error=str(e)), 400
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return jsonify(image="data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                       width=img.width, height=img.height, warnings=warnings,
                       placeholders=render.placeholders(layout))

    @app.post("/api/print")
    def print_labels():
        b = body()
        cfg = load_config()
        layout = b.get("layout", {})
        records = b.get("records") or [{}]
        copies = max(1, min(100, int(b.get("copies", 1))))
        dry_run = bool(b.get("dry_run"))
        if not cfg["printer_host"] and not dry_run:
            return jsonify(error="Set the printer address first"), 400

        images, warnings = [], []
        for rec in records:
            img, w = render.render(layout, rec, keep_missing=False)
            warnings += [x for x in w if x not in warnings]
            images += [img] * copies
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
        f = request.files.get("file")
        if not f:
            return jsonify(error="No file"), 400
        raw = f.read()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        rows = [r for r in reader if any(c.strip() for c in r)]
        if not rows:
            return jsonify(error="CSV is empty"), 400
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
