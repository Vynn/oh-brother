# Changelog

All notable changes, by version. Versions follow the [roadmap](ROADMAP.md): a minor version per milestone, and until 1.0 patch versions for the builds between them.

## Unreleased

### Added

- Empty QR codes and barcodes show a placeholder in the editor: blue hatching with a caption such as "QR · no data", or "Barcode · invalid data" when a barcode can't encode its data. It is drawn only in the editor, never into the label, so it can't print or be mistaken for a code.
- Printing warns when a QR code or barcode was blank on any label, with the number of labels affected.

## 0.2.1 · 2026-10-29

Metric or imperial units.

### Added

- A Units switch in the Label section: millimetres (the default) or inches. Lengths, positions, sizes and readouts are shown and typed in the chosen unit, and tape names gain their width in inches. Templates and layouts are still stored in millimetres, so they work in either unit. Each browser remembers its choice.
- In inches, the snap grid and arrow-key nudge are 0.02 in, or 0.1 in with Shift.

## 0.2.0 · 2026-10-29

Undo, and more quick layouts that adapt to the label.

### Added

- Undo and redo for every change to the label: Ctrl+Z, and Ctrl+Shift+Z or Ctrl+Y, plus buttons in the top bar. The last 100 steps are kept. A drag or a burst of typing counts as one step.
- Eleven quick layouts: Two columns, QR only, Bin label, Date stamp, Filament spool, Cable flag, Return address, and price and sale tags with a barcode or QR code.
- Quick layouts are grouped into collapsible categories, each showing how many of its layouts fit the current label. Open categories are remembered.

### Changed

- Quick layouts adapt to the label's shape. On long, narrow labels, parts sit side by side, and the red header becomes a red block at the start.
- Quick-layout margins scale with the label, from 2 mm on 62 mm tape down to 0.5 mm on 12 mm tape.
- Quick-layout thumbnails are drawn at the current label's shape. Layouts that can't fit are greyed out, with the reason in a tooltip.
- Quick layouts share field names: `{{Title}}`, `{{Body}}` and `{{Code}}`. Switching layouts keeps typed values.
- Applying a quick layout no longer asks for confirmation; undo restores the previous layout.
- The sample CSV and the *Bin label* template use a `Code` column instead of `SKU`, matching the quick layouts.

## 0.1.2 · 2026-10-29

Multiple selection and chained fields.

### Added

- Multiple selection: Shift- or Ctrl-click, drag across empty space, or Ctrl+A. The elements list follows the same clicks.
- Moving, nudging, duplicating and deleting the whole selection. The selection's bounding box snaps like a single element.
- Align several elements to each other or to the printable area, and distribute three or more with equal gaps.
- Colour for every selected element at once.
- The element whose text is being typed is outlined on the label and tagged *Editing*. Double-click an element on the label to jump to its text field.
- Chained fields: a field's fixed text can include other fields (`{{SKU}}` = `P-{{Item}}`) and any CSV column. Loops are caught and reported. CSV cells are never expanded.

### Changed

- Deleting an element clears the selection instead of selecting the next one.

## 0.1.1 · 2026-10-29

A smoother editor.

### Added

- Snapping: element edges and centres snap to the printable area's edges and centre and to other elements, with guide lines. Alt turns it off.
- Resize handles on every corner and edge (corners only for QR codes and small elements).
- Align buttons for the selected element: left, centre, right, top, middle, bottom.
- The label is drawn at its cut size, with a dashed line around the printable area. The readout shows both sizes.

### Changed

- The preview updates live while dragging, instead of after the pointer stops.
- Dragging no longer stalls when a preview arrives mid-drag.
- Previews are sent as plain PNG images rather than base64 JSON.

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
