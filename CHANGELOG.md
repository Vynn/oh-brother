# Changelog

All notable changes, by version. Versions follow the [roadmap](ROADMAP.md): a minor version per milestone, and until 1.0 patch versions for the builds between them.

## 0.1.0 · 2026-10-29

The first build. A pre-release.

### Added

- Label printing to a network Brother QL-820NWB over TCP port 9100, in black, or black and red on DK-2251 tape.
- A preview that is the exact 300 dpi, 1-bit bitmap sent to the printer.
- Elements: text (shrink-to-fit, wrapping, inverted), QR codes, Code 128 barcodes, and boxes and lines, each in black or red.
- An editor with drag-to-move, drag-to-resize, and arrow-key nudging.
- Six quick layouts, and templates saved in `data/templates/`.
- Fields: `{{Name}}` in any text, QR code or barcode, filled from fixed values or from a CSV column. Built-in fields: `{{date}}`, `{{time}}` and `{{datetime}}`.
- CSV import with automatic delimiter and encoding detection, row selection, and per-row preview.
- Every continuous and die-cut QL tape, with layouts scaling to fit when the tape, length or text direction changes.
- A portable folder: a bundled Python runtime and packages, with nothing installed on the host. On drives that don't allow running programs, the runtime is copied once to `~/.cache/oh-brother/`.
