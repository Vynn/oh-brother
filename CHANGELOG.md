# Changelog

All notable changes, by version. Versions follow the [roadmap](ROADMAP.md): a minor version per milestone, and until 1.0 patch versions for the builds between them.

## 0.3.3 · 2026-10-31

Quicker large data files, more text options, and comments brought up to date.

### Added

- Text has *Max size* and *Line spacing*. Max size limits how large shrink-to-fit text grows, and is off while a size is set. Line spacing sets the gap between lines: 1 is normal. Both could already be set in a template file, but not in the editor.

### Fixed

- With large data files, every click on a row or tick of its box rebuilt the whole rows table: about 0.7 s per click at 5,000 rows. The table is now built once, when the data loads, and clicks and ticks update it in place.
- A data file that couldn't be loaded reported in the print bar. The message now shows beside *Load data…*.
- Changing the label's size or direction rounded element positions to 0.1 mm, which could move a snapped centre off by up to 0.05 mm. Positions now keep 0.01 mm, as everywhere else.

### Changed

- Barcodes are listed as *Barcode* in the elements list, as on the add button and in the properties panel. They were listed as *Code*.
- The `hidden` element option is gone. Nothing in the editor set it.
- Code comments are checked against the code and brought up to date, and the developer notes now cover the inch grid and every header the preview sends.

## 0.3.2 · 2026-10-31

Safer template saving, tidier separators, UTF-16 data, and launcher fixes.

### Fixed

- Saving a template replaced one of the same name without asking. Since 0.3.1 your templates aren't in the repository, so the old one was gone for good. Saving now asks first.
- Template names were changed without telling you. Anything but letters, digits, spaces, `-` and `_` was dropped, so saving as "Bin label!" replaced "Bin label". Names are now kept as typed. A name that can't be a file name on Windows, macOS or Linux is refused, with the reason.
- A save request the app refused, because its content wasn't a template, emptied the template it named.
- A failed save showed no message. Saving, opening and deleting templates now report on a line under the name box.
- Data saved by Excel as *Unicode Text* (UTF-16) was refused as not text.
- If the default browser's `.desktop` file couldn't be parsed, no window opened, and the app kept running, since no window ever connected. It now falls back to `xdg-open`.
- Restarting the app within about a minute moved it to the next port, because the last run's connections were still closing. On the new port the editor's saved layout, units and open categories weren't found, since the browser keeps them per address.
- With `--lan`, the free-port check tested only `127.0.0.1`. A port in use on another network address stopped startup with an error.

### Changed

- A separator between fields (`·` `,` `;` `/` `|` or a dash) goes with an empty field beside it. `Ada · · Paris` now prints `Ada · Paris`, and `{{city}}, {{postcode}}` with no postcode prints `Paris` rather than `Paris,`. A dash starting a line stays, and so do brackets and colons.
- With `--lan`, the app also prints the address other devices use.

## 0.3.1 · 2026-10-30

Fixes, requests from other sites refused, and samples kept apart from your templates.

### Added

- Tests for the server side, using Python's built-in `unittest`, so nothing more is installed. Run them with `sh test.sh`.

### Fixed

- *Cut each label* was ignored, and every label was cut, whenever a label had hidden text or a blank QR code or barcode. This came in with 0.2.2.
- The print warning for blank QR codes and barcodes counted codes instead of labels, so two empty codes on one label read "on 2 labels".
- Some errors while printing or loading data showed only "500 Internal Server Error": a copies value that isn't a number, an unknown tape, or a damaged spreadsheet. Every error from the app now comes back as a message the editor shows, and a damaged spreadsheet is reported as damaged.

### Changed

- Requests from other sites are refused. A web page open in the same browser could send a print job or change the printer address. The app now accepts changes only as JSON, which other sites can't send without the app's permission, and answers only to its own names, `127.0.0.1` and `localhost`, unless started with `--lan`.
- Sample templates and data are in a new `samples/` folder, listed after your own templates as *Sample: Bin label*. They open like any template but can't be saved over or deleted. Opening one leaves the name box empty, so saving makes a copy under a name of your own. `data/` now holds only your templates and settings, and is no longer part of the repository. An existing `data/templates/Bin label.json` stays, as a template of your own.
- The sample template and sample data use lowercase fields: `{{item}}`, `{{location}}` and `{{code}}`.

## 0.3.0 · 2026-10-30

Data from spreadsheets, and fields that tidy up after themselves.

### Added

- Data can be loaded from OpenDocument spreadsheets (`.ods`, `.fods`), Excel workbooks (`.xlsx`) and JSON as well as CSV and TSV, with no extra packages. Spreadsheets give their first sheet. The button is now *Load data…*.
- Empty fields are hidden. They print as nothing and now show as nothing in the preview too, instead of their `{{tag}}`. In text, spaces beside an empty field go with it, a line left blank by empty fields is removed, and an element whose fields are all empty isn't drawn at all, fixed text and inverted bars included. The editor marks such text with a hatched placeholder.

### Fixed

- When a layout change brought in new fields, the first preview was drawn without their values. It now redraws once the fields are known.
- Spreadsheets and other binary files picked as data were read as rows of garbage. They're now read properly if supported, or refused with a message naming the formats that work.

### Changed

- Field names ignore case: `{{Code}}`, `{{code}}` and `{{CODE}}` are the same field, and so are built-ins such as `{{Date}}` and CSV columns named in fixed text. The Data table lists each field once, as first spelled. Templates and saved work from earlier versions are converted when loaded.
- Quick layouts and the hints use lowercase field names (`{{title}}`, `{{body}}`, `{{code}}`, `{{price}}`), matching the built-ins.

## 0.2.2 · 2026-10-30

Code placeholders, and the app closes with its window.

### Added

- Empty QR codes and barcodes show a placeholder in the editor: blue hatching with a caption such as "QR · no data", or "Barcode · invalid data" when a barcode can't encode its data. It is drawn only in the editor, never into the label, so it can't print or be mistaken for a code.
- Printing warns when a QR code or barcode was blank on any label, with the number of labels affected.
- The app stops by itself about 10 seconds after its last window or tab closes, so a reload doesn't stop it. This applies when `run.sh` opened the browser; with `--no-browser` or `--lan` it runs until Ctrl+C.

### Changed

- On Linux, the app opens in a new window of the default browser instead of a tab, for Firefox, Chrome, Chromium, Brave, Edge, Vivaldi and similar browsers.

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
