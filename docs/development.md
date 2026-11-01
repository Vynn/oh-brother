# Development

The app is plain Python with a plain HTML, CSS and JavaScript front end. There's no front-end build step. `build.sh` only fetches the Python runtime and packages.

## Layout

| Path | Contents | In the repo? |
|---|---|---|
| `app/` | Server (`main.py`, `server.py`, `render.py`, `tapes.py`, `fields.py`, `printer.py`, `tables.py`), web UI (`static/`), fonts | Yes |
| `tests/` | Server-side tests, with reference images and print jobs in `tests/reference/` | Yes |
| `samples/` | Sample templates (`samples/templates/`) and data, read-only in the app | Yes |
| `data/templates/` | The user's saved templates | No |
| `data/config.json` | Printer address, per machine | No |
| `docs/images/` | Screenshots for the README | Yes |
| `runtime/<platform>/` | Standalone Python | No, built |
| `vendor/common/` | Pure-Python packages, shared by all platforms | No, built |
| `vendor/<platform>/` | Compiled packages (Pillow) | No, built |
| `private/` | Anything with real personal data | No |

## Build and run

```sh
sh build.sh
sh run.sh
```

`build.sh` with no arguments builds for the current machine. Name platforms to add more: `linux-x86_64`, `linux-aarch64`, `macos-arm64`, `macos-x86_64`. The runtime is pinned in `build.sh`. The packages are listed in `requirements.txt` (pure Python) and `requirements-binary.txt` (compiled).

`.claude/launch.json` starts the app for the Claude desktop preview. It's local and not in the repo.

## Tests

```sh
sh test.sh
```

The tests use Python's built-in `unittest`, so they run on the bundled runtime with nothing more to install. Options go to `unittest`: `sh test.sh -v` lists each test, and `sh test.sh -k cut` runs the tests whose names contain `cut`.

They cover the server side, against a temporary data folder:

- **Fields and data files:** filling and tidying fields, and reading every data format. Spreadsheets are built in memory.
- **Drawing:** every element type and option, the size warnings, and canvas sizes. Ten layouts are compared pixel for pixel with reference images in `tests/reference/`. They cover continuous, die-cut, round and black-only tape, across and along.
- **Printing:** four print jobs are compared byte for byte with reference jobs, stored gzipped. A fake printer, a TCP listener on this machine, receives real jobs from `/api/print` and answers the printer test. Nothing reaches a real printer.
- **The API:** requests from other sites, errors, templates, the editor's page and files, and the stream that counts open pages.
- **The launcher:** its port and browser helpers, and `run.sh` itself, started on a free port, asked for `/api/meta`, and stopped with Ctrl+C.

After an intended change to what's drawn or printed, rewrite the reference files, then look at the new images before committing them:

```sh
UPDATE_REFERENCES=1 sh test.sh
```

When output differs from a reference, the test saves this run's output in `oh-brother-tests/` in the system's temporary folder, and names the file.

The editor in `app/static/` has no tests yet; it would need a browser to drive it.

## How printing works

`render.py` draws a layout (geometry in millimetres) to an RGB image at 300 dpi. It uses no anti-aliasing and only three colours: black, red and white. That one image is both the preview and the print. `tapes.py` gives each tape's size, and `fields.py` fills in the fields.

The editor asks the server for a fresh preview as you work: `POST /api/render` returns the PNG itself, with URL-encoded JSON headers: `X-Warnings`, `X-Placeholders` (the layout's field names) and `X-Blank` (elements left blank, which the editor marks). Only one request is in flight at a time, so while dragging the preview updates as fast as the round trip allows.

`printer.py` converts the images with brother_ql into raster commands, splitting the red and black layers for two-colour tape. brother_ql picks out red and black by testing each pixel in Python, which takes about 50 ms a label, so `printer.py` swaps in `_filtered_hsv()`, which builds the same masks with Pillow. The jobs are byte for byte the same, and a test compares the two. The job goes to port 9100 with a plain socket write. brother_ql's own network backend isn't used: it connects without a timeout, and it can't read status back over the network anyway.

## Launching and stopping

Each editor page holds `GET /api/alive` open: an event stream the server writes a keep-alive comment to every 3 seconds. Once a page closes, the next write fails and the stream ends. When the launcher opened the browser itself, and `--lan` is off, a watcher thread stops the server once no page has been open for 10 seconds. The page's `EventSource` reconnects by itself, so a reload stays inside that grace period. The timer uses `time.monotonic()`, which doesn't count time asleep, so a suspend shouldn't stop the app.

On Linux, the launcher reads the default browser from `xdg-settings` and its command from the `.desktop` file, and passes `--new-window` for browsers known to accept it (Firefox, Chrome, Chromium, Brave, Edge, Vivaldi and similar). Anything else goes to `xdg-open`, which usually opens a tab, and so does a `.desktop` file that can't be read or whose command can't be parsed.

The launcher uses the first free port from `--port`, testing it on the address the server will listen on: all interfaces with `--lan`, otherwise `127.0.0.1`. The test sets `SO_REUSEADDR`, as the server does, so connections from the last run, which take about a minute to close, don't make the port look taken. Moving to another port would lose the editor's saved layout, units and open categories, which the browser keeps per address. With `--lan` it also prints this machine's network address, found by connecting a UDP socket to an address reserved for documentation. Connecting a UDP socket sends nothing.

## Requests from other sites

The app has no login, so `server.py` checks every request in `guard()`:

- **Host name.** A site can point one of its own names at `127.0.0.1` (DNS rebinding), and the browser then treats the app as part of that site. Its pages send that name as the `Host`, so requests are refused with 403 unless the host is `127.0.0.1`, `localhost` or `::1`. With `--lan`, other machines reach the app by whatever name they know it by, so the check is off.
- **JSON only.** A page on another site can send a form or plain text to any address without asking, but it can send JSON only after a CORS check, which this server never answers. So every `POST` or `PUT` must be sent as JSON, or it's refused with 415. The one exception is the data upload, a form, which only reads the file and changes nothing.

Every error under `/api/` comes back as JSON, `{"error": "…"}`, which the editor shows. Unexpected errors are 500s, and their tracebacks go to the terminal.

## Data files

`tables.py` turns an uploaded file into rows of strings using only the standard library, so no spreadsheet package is bundled. It detects the format from the content, with the extension as a hint: a zip holding `content.xml` is OpenDocument and one holding `xl/workbook.xml` is Excel. Other zips, old binary `.xls` files and binary data are refused with a message. A file whose parts are missing or don't parse is reported as damaged. Text starting with a UTF-16 byte-order mark, as in Excel's *Unicode Text*, is decoded as UTF-16. Other text is decoded as UTF-8, then Windows-1252, then Latin-1. The delimiter is sniffed. OpenDocument cells give their displayed text. Excel cells hold raw values, so `tables.py` applies only date formats and zero-padded formats like `00000`, and prints other numbers with at most 15 significant digits, as Excel shows them. Repeated empty rows and cells, which spreadsheets store by the million, are dropped. The endpoint is `POST /api/data`.


## Editor geometry

Element positions are in millimetres from the top left of the printable area, which is the rendered canvas. The editor draws the label at its cut size around it:

- Across the tape, the cut size is the tape width from brother_ql's label table.
- Along continuous tape, brother_ql's feed margin (35 dots, about 3 mm) is added at each end.
- On die-cut labels, the margins are split evenly between the label size and the printable size.

These cut sizes are derived from brother_ql's label data, not measured.

Snapping works in millimetres. Targets are the printable area's edges and centre lines, plus every other element's edges and centre lines. The snap distance is 6 screen pixels. Away from any target, positions snap to a 0.5 mm grid, or 0.02 in (0.508 mm) when using inches. Positions are stored to 0.01 mm, so snapped centres stay exact, including after the label is reshaped.

## Fields

The browser builds one record per label. A record holds the data row's columns, if data is loaded, then the layout's fields, each from its fixed value or its mapped column. With the record, the browser sends `chain`: the names of fields whose values are fixed text.

`fields.fill()` replaces each `{{name}}` (names are case-insensitive). A value is expanded again only if its field is in `chain`, so text typed by the user can refer to other fields and columns, while data cells are used exactly as written. Each expansion carries the path of fields it came through. A field already on the path is a loop: the preview keeps its tag, print leaves it blank, and a warning names the path. Other empty fields fill as nothing in both.

Text elements go through `fields.fill_text()`, which fills each line field by field and tidies up after empty ones. Spaces beside an empty field are dropped, leaving one space only when there was space on both sides. A separator beside it (`fields.SEPARATORS`: `·` `,` `;` `/` `|` and dashes) goes too when it would be left doubled or dangling. Between two separators one stays, a separator at either end of what's left goes, and a separator starting the line, such as a list dash, stays. Empty fields are tidied one at a time, left to right, so a run of them leaves a single separator. A line that had fields and is left blank is removed. When a text element has fields and all are empty, it isn't drawn, and it's listed in `X-Blank` like an empty code so the editor can mark it. Print doesn't warn about these, since hiding them is intended.

The editor finds fields with the server's own tag pattern and list of built-in fields, sent in `/api/meta`, so the two always agree on what counts as a field.

## Templates

Templates are JSON files in `data/templates/`, named after the template, and samples are read the same way from `samples/templates/`. A name must work as a file name on Windows, macOS and Linux, so `tpl_path()` refuses one rather than changing it: `/ \ : * ? " < > |` and control characters, a dot at either end, Windows device names such as `CON` (with any extension), or more than 60 characters. The routes take the name as a path, so a name with a slash gets that message rather than a 404.

`PUT /api/templates/<name>` won't replace an existing file (409) unless sent with `?replace=1`, which the editor adds once the user has confirmed. The check is made on the server, so a template saved from another window counts. On macOS and Windows, names that differ only in case are the same file, so they count as existing too. The body is checked before the file is opened, since opening it for writing empties it.

## Screenshots

The README images are taken in the Claude desktop app's browser, from a separate instance with its own data folder and the placeholder printer address `192.168.1.50`. Real printer addresses and personal data must not appear in them.

## Commits

Every commit is checked for personal details: names, home paths, IP addresses, hostnames and addresses. Item names in templates and samples are fine. Commit messages are short prose paragraphs.

## Third-party code

### Fonts (in the repo)

All from Ubuntu's packages, unmodified, in `app/fonts/`.

| File | Version | SHA-256 |
|---|---|---|
| `DejaVuSans.ttf` | 2.37 | `b4c632e3cdf9acc7f28758fb5a323c8524d7fc6660d46904d9b6cbe2809c419c` |
| `DejaVuSans-Bold.ttf` | 2.37 | `e1d733afbbfce842a1b43dced0c9885a76a4e67290dc7e690c4e9b76ebfc7d23` |
| `DejaVuSansMono.ttf` | 2.37 | `a54dca07c76d6289e717e75e0a58c0128f6d7269ef3faf76417c9d7d3bba37ab` |
| `DejaVuSansMono-Bold.ttf` | 2.37 | `2d67eed9b325ee2e69f906ce4f3f6264d5105230a13352c8494daad4f17b12c8` |
| `DejaVuSerif.ttf` | 2.37 | `a52c2a69dfc93d0b511b98c1019a57eb3d6a62d328bdf1387f00851b02e3a315` |
| `DejaVuSerif-Bold.ttf` | 2.37 | `3f704f75238454f68a8202e5098cb0687887480dd63d3dc20b34bdbdfa9d9f3f` |
| `LiberationSansNarrow-Regular.ttf` | 1.07 | `8ff00a422289dce865973a299c9284ab7cb91a2b1ef1c7b9ef622b793cab5447` |
| `LiberationSansNarrow-Bold.ttf` | 1.07 | `3271f41b67a81a806aadbf71762c14a405e617b738d9ceeb81191dd681c66fc4` |

- **DejaVu** comes from [dejavu-fonts](https://dejavu-fonts.github.io/), Ubuntu package `fonts-dejavu-core` 2.37. Its licence is the Bitstream Vera licence (DejaVu's changes are public domain), in `LICENSE-DejaVu.txt`.
- **Liberation Sans Narrow** comes from [liberationfonts/liberation-sans-narrow](https://github.com/liberationfonts/liberation-sans-narrow), Ubuntu package `fonts-liberation-sans-narrow` 1.07.6. Its licence is GPL-2 with a font exception, in `LICENSE-LiberationSansNarrow.txt` and `GPL-2.txt`.

### Runtime and packages (built, not in the repo)

| Component | Version | Licence |
|---|---|---|
| [python-build-standalone](https://github.com/astral-sh/python-build-standalone) CPython | 3.13.18 (20261026) | PSF-2.0 |
| [brother-ql-inventree](https://pypi.org/project/brother-ql-inventree/) | 1.3 | GPL-3.0-or-later |
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.9 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| click | 8.5.0 | BSD-3-Clause |
| blinker | 1.9.0 | MIT |
| Pillow | 12.3.0 | MIT-CMU |
| qrcode | 8.2 | BSD |
| python-barcode | 0.16.1 | MIT |
| packbits | 0.6 | MIT |
| pyusb | 1.3.1 | BSD-3-Clause |
| attrs | 26.1.0 | MIT |

brother_ql is GPL-3.0-or-later, which is one reason Oh-Brother is GPL-3.0.
