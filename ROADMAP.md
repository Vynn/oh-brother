# Roadmap

Oh-Brother grows one milestone at a time. Each milestone is a minor version (0.2, 0.3, …) until 1.0. Until then every build is a pre-release, and builds between milestones are patch versions (0.1.1, 0.1.2, …).

## 0.1 · First build · released

- [x] One- and two-colour printing to a network QL-820NWB
- [x] Text, QR code, barcode and box elements, in black or red
- [x] Quick layouts and saved templates
- [x] Fields filled from fixed values or CSV columns
- [x] Portable folder for Linux x86_64
- [x] Confirmed printing black and red on a real QL-820NWB
- [x] Live preview while dragging, snapping, alignment, and the label shown at its cut size (shipped in 0.1.1)
- [x] Multiple selection with align and distribute, and fields that refer to other fields (shipped in 0.1.2)

## 0.2 · Undo and adaptive layouts · released

- [x] Undo and redo for every change, with the usual shortcuts
- [x] Quick layouts that adapt to the label's shape and size
- [x] More quick layouts, in collapsible categories: storage, dates, cables and mailing, and retail price tags
- [x] Metric or imperial units (shipped in 0.2.1)
- [x] Placeholders for empty QR codes and barcodes, and the app stops when its window closes (shipped in 0.2.2)

## 0.3 · Data and fields · released

- [x] Data from OpenDocument and Excel spreadsheets and JSON, as well as CSV and TSV
- [x] Field names that ignore case
- [x] Empty fields hidden in the preview and in print, with the lines and spaces around them tidied
- [x] Sample templates kept apart from your own, requests from other sites refused, and a test suite (shipped in 0.3.1)
- [x] Saving asks before replacing a template, separators tidied beside empty fields, and UTF-16 data (shipped in 0.3.2)
- [x] Large data files that stay quick to click through, and a maximum size and line spacing for text (shipped in 0.3.3)
- [x] Faster printing on two-colour tape, and tests for drawing, printing and starting the app (shipped in 0.3.4)
- [x] Exact package versions, tests on four platforms on every change, and labels laid out the same on every computer (shipped in 0.3.5)

## 0.4 · Images and retail barcodes · released

- [x] An image element, printed in black or red with a threshold or dithering, from a file or a web address, and saved with the template
- [x] A layered shelf tag quick layout, with a slot for a logo or symbol
- [x] Retail barcodes: EAN-13, EAN-8, UPC-A and ITF-14, with their check digits checked, and quiet zones kept for every barcode
- [x] Pillow 13, new screenshots, and a note on setting red's print density (shipped in 0.4.1)
- [x] Large print jobs that stay quick and light on memory, a question before printing more than 25 labels, and saves that can't leave a file cut short (shipped in 0.4.2)

## 0.5 · Keyboard use, editor tests and checked builds · released

- [x] The editor worked from the keyboard, with copy and paste of elements
- [x] The editor's code in modules, with tests of its own that run in a browser and in CI
- [x] Every download the build makes checked against a checksum, and a build that fails leaves the last one working
- [x] A policy for what the editor's page may load, requests from other sites refused, and a limit on the size of a data file

## 0.6 · Printer status · released

- [x] The printer's state and loaded tape, read over SNMP, and a question before printing onto another tape, with the cover open or with no tape
- [x] The printer chip shows the printer's state and tape, and the print bar a tape the layout isn't for (study: `design/printer-status.html`)
- [x] Print progress, label by label as the printer prints, "Printed" in place of "Sent" when the printer shows it, and Cancel until the labels are sent (study: `design/print-bar.html`)
- [x] Save the label in the preview as a PNG, as printed, at 300 dpi

## Under consideration

Not scheduled yet.

- Click-to-launch: a Quit button, a single running instance, an Ubuntu app-grid launcher (`run.sh --install`), a macOS `.app` wrapper, and an app icon
- Windows: a `run.bat` launcher and a Windows runtime
- ARM Linux and macOS tried in real use (CI has built and tested them since 0.3.5)
- Two-colour images: the black and red parts of one image printed in their own colours
- More barcodes: UPC-E for small packages, and GS1-128 for shipping labels
