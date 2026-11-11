# Development

The app is plain Python with a plain HTML, CSS and JavaScript front end. The JavaScript is a handful of modules that the browser loads as they are: there's no front-end build step, and nothing from npm. `build.sh` only fetches the Python runtime and packages.

## Layout

| Path | Contents | In the repo? |
|---|---|---|
| `app/` | Server (`main.py`, `server.py`, `render.py`, `tapes.py`, `fields.py`, `barcodes.py`, `printer.py`, `tables.py`, `remote.py`), web UI (`static/`), fonts | Yes |
| `requirements*.txt` | The packages and their checksums: the app's, the build tool's and CI's | Yes |
| `app/static/` | The editor: `index.html`, `style.css`, and its code in `.mjs` modules | Yes |
| `tests/` | Server-side tests, with reference images and print jobs in `tests/reference/` | Yes |
| `tests/editor/` | The editor's own tests, and the page and the Node script that run them | Yes |
| `samples/` | Sample templates (`samples/templates/`) and data, read-only in the app | Yes |
| `data/templates/` | The user's saved templates | No |
| `data/config.json` | Printer address, per machine | No |
| `docs/images/` | Screenshots for the README | Yes |
| `.github/workflows/` | Continuous integration on GitHub Actions | Yes |
| `runtime/<platform>/` | Standalone Python | No, built |
| `vendor/common/` | Pure-Python packages, shared by all platforms | No, built |
| `vendor/<platform>/` | Compiled packages (Pillow) | No, built |
| `private/` | Anything with real personal data | No |

## Build and run

```sh
sh build.sh
sh run.sh
```

`build.sh` with no arguments builds for the current machine. Name platforms to add more: `linux-x86_64`, `linux-aarch64`, `macos-arm64`, `macos-x86_64`. The runtime is pinned in `build.sh`. The packages are listed in `requirements.txt` (pure Python) and `requirements-binary.txt` (compiled), at exact versions with their dependencies, so every build of a commit gets the same app.

Everything the build downloads is checked against a SHA-256 kept in the repository, and a download that doesn't match stops the build:

- **The runtime.** `build.sh` holds the checksum of each platform's archive, taken from the `SHA256SUMS` file of the python-build-standalone release. The archive is downloaded whole and checked before any of it is unpacked.
- **The packages.** Each line of the requirements files carries the checksum of the file PyPI serves for it, and pip runs with `--require-hashes`, which also refuses a package that has none. Pillow and MarkupSafe are compiled, so they have one checksum for each platform.
- **The build tool.** packbits comes as source only, so pip builds it, and fetches setuptools to do that. `requirements-build.txt` pins and checks that as well (pip's `--build-constraint`).

Each folder is built beside the one it replaces (`vendor/common.new`) and swapped in once it's complete. A build that fails, or runs without a network, leaves the last working build in place.

### Changing a package

1. Change its version in the requirements file and delete its `--hash` lines.
2. Run `sh build.sh linux-x86_64 linux-aarch64 macos-arm64 macos-x86_64`. pip stops and prints the line it wants, with the checksum of the file it downloaded. For Pillow it stops once for each platform; for MarkupSafe it prints only this machine's file, and the other three are on its PyPI page.
3. Compare each checksum with the SHA-256 that PyPI lists for that file on the package's *Download files* page, then add it.
4. Rebuild, run the tests, and update the table under [Third-party code](#third-party-code).

For a new runtime, change `PBS_TAG` and `PY_VER` in `build.sh` and copy the four checksums from the release's `SHA256SUMS` file.

`sh build.sh --newest` installs the newest version of every package instead, with no checksums, as the monthly check does. It replaces the pinned build in `vendor/`, so run `sh build.sh` again afterwards.

`.claude/launch.json` starts the app for the Claude desktop preview. It's local and not in the repo.

## Tests

```sh
sh test.sh
```

The tests use Python's built-in `unittest`, so they run on the bundled runtime with nothing more to install. Options go to `unittest`: `sh test.sh -v` lists each test, and `sh test.sh -k cut` runs the tests whose names contain `cut`.

They cover the server side, against a temporary data folder:

- **Fields and data files:** filling and tidying fields, and reading every data format. Spreadsheets are built in memory, including small ones that ask for huge tables.
- **Drawing:** every element type and option, the size warnings, and canvas sizes. Thirteen layouts are compared pixel for pixel with reference images in `tests/reference/`. They cover continuous, die-cut, round and black-only tape, across and along, images in every mode, and every barcode type.
- **Images and barcodes:** image modes, transparency, fitting and the size limits; check digits, lengths, quiet zones, guard and bearer bars for each barcode type.
- **Images from a web address:** fetched from a small web server on this machine: images, SVG, redirects, pages that aren't images, an entity bomb, missing, oversized, endless and slow downloads, and the address rules.
- **Printing:** four print jobs are compared byte for byte with reference jobs, stored gzipped. A fake printer, a TCP listener on this machine, receives real jobs from `/api/print` and answers the printer test. Nothing reaches a real printer. Other tests check that a job's labels are drawn one at a time, share one date and time, and that an error names its row.
- **The API:** requests from other sites, the headers every response carries, errors, templates, the editor's page and files, and the stream that counts open pages. Also settings and templates that can't be used, damaged files, and a save that fails partway.
- **The launcher:** its port and browser helpers, and `run.sh` itself, started on a free port, asked for `/api/meta`, and stopped with Ctrl+C.

After an intended change to what's drawn or printed, rewrite the reference files, then look at the new images before committing them:

```sh
UPDATE_REFERENCES=1 sh test.sh
```

When output differs from a reference, the test saves this run's output in `oh-brother-tests/` in the system's temporary folder, and names the file.

### The editor's tests

The editor's code is split by what needs a page and what doesn't. `app.mjs` is the page: it holds the state, draws the panels, and handles the mouse and keyboard. The modules beside it work only on the values they're given, so they can be tested anywhere:

| Module | Holds |
|---|---|
| `units.mjs` | Millimetres and inches, rounding, the snap grid |
| `geometry.mjs` | Label sizes, snapping while moving and resizing, align, distribute, rescaling |
| `layouts.mjs` | Element defaults and every quick layout |
| `fields.mjs` | Which fields a layout has, and the record that fills them |
| `elements.mjs` | Making a layout safe to edit; removing, reordering and duplicating elements |
| `history.mjs` | The undo list |
| `images.mjs` | The sizes an image is tried at |
| `job.mjs` | What a click on Print sends |

Their tests are in `tests/editor/`, one `.test.mjs` file for each module, written with a small harness of its own (`harness.mjs`), so nothing is installed. Among other things they build every quick layout on every tape, across and along, and check that nothing lands off the label. They run two ways:

- **In a browser.** Start the app with `sh run.sh --tests` and open `/tests/editor/`. The page lists what failed and why. The tests are served only with `--tests`.
- **Under Node**, with `node tests/editor/run.mjs`. CI does this. Node isn't needed for anything else.

`sh test.sh` doesn't run them: the bundled runtime has no JavaScript. A server-side test does check that every module the editor imports exists and that `all.mjs` lists every test file.

The files end in `.mjs` so that Node reads them as modules without a `package.json`. The page itself, `app.mjs`, still has no tests: clicking through the editor after a change to it is done by hand. `window.ohBrother` gives the console the editor's state to look at, since a module's own names can't be reached from there.

What only a real printer can show is in the [printer checklist](printer-checklist.md), for releases that change printing.

## Continuous integration

GitHub Actions builds the portable folder from scratch and runs the tests on Linux x86_64, Linux ARM, macOS on Apple Silicon and macOS on Intel. `tests.yml` runs on every push to `main`, every version tag and every pull request, and can be started by hand from the repository's Actions tab. Each platform runs to the end even when another fails. When output differs from a reference, the differing images or print jobs are attached to the run.

A second job, *Lint and editor tests*, runs the [editor's tests](#the-editors-tests) under Node and looks for mistakes that tests wouldn't run into. `shellcheck` reads the three shell scripts, `node --check` reads each of the editor's files as a browser would, and `pyflakes` reads the Python for names that are never defined and imports left behind. shellcheck and Node come with GitHub's runner. pyflakes is pinned and checked in `requirements-lint.txt`, and is installed outside the app's folders.

`upstream.yml` runs the same build and tests once a month with the newest version of every package instead of the pinned ones (`sh build.sh --newest`), so a release that would break the app shows up before the pins are raised. GitHub runs schedules only from the default branch, may delay them when busy, and turns them off in a public repository after 60 days without activity.

The workflows can only read the repository and use no secrets. They use only GitHub's own actions, pinned to the commit of a release. The privacy check that runs before each commit stays local: its pattern is itself personal.

## How printing works

`render.py` draws a layout (geometry in millimetres) to an RGB image at 300 dpi. It uses no anti-aliasing and only three colours: black, red and white. That one image is both the preview and the print. `tapes.py` gives each tape's size, and `fields.py` fills in the fields. Images arrive from the editor as data URLs, at most 600 px on the long side and 128 KB as stored (`render.MAX_IMAGE_CHARS`, sent to the editor in `/api/meta`), and are kept in colour so a two-colour mode can use them later. The editor tries PNG first, which keeps logos lossless, then WebP, which suits photos, then both at smaller sizes until the image fits; the server refuses anything larger. `render.py` composites one onto white, makes it greyscale, scales it to its box at print size, and then applies a threshold or Floyd–Steinberg dithering, so the conversion to dots happens at the printer's own resolution. Decoded images are cached, since the preview redraws on every drag frame. SVGs are drawn by the browser before they're stored, since Pillow can't read them. Text uses Pillow's basic layout, which relies only on the FreeType bundled with Pillow, so a label comes out the same on every computer. Pillow's other layout, Raqm, would use the computer's own FriBiDi library if it had one, and moved some glyphs by a dot. The basic layout doesn't shape right-to-left or other complex scripts, such as Arabic or Devanagari.

The editor asks the server for a fresh preview as you work: `POST /api/render` returns the PNG itself, with URL-encoded JSON headers: `X-Warnings`, `X-Placeholders` (the layout's field names) and `X-Blank` (elements left blank, which the editor marks). Only one request is in flight at a time, so while dragging the preview updates as fast as the round trip allows.

A layout can come from anywhere, so `render.py` and `tapes.py` hold it to limits of their own: a continuous label is 5 to 1000 mm long, an element's box is at most twice the label's width and height (with a warning), and text is at most 720 pt. Each element is drawn into a mask the size of its box, so without these a width of 5000 typed by mistake asked for gigabytes of memory. The limits on length and copies go to the editor in `/api/meta`, so they're defined once.

`printer.py` converts the images with brother_ql into raster commands, splitting the red and black layers for two-colour tape. brother_ql picks out red and black by testing each pixel in Python, which takes about 50 ms a label, so `printer.py` swaps in `_filtered_hsv()`, which builds the same masks with Pillow. The jobs are byte for byte the same, and a test compares the two. brother_ql also builds the job in a `bytes` value, which copies the whole job every time something is added, so each label took longer than the one before. `build_job()` gives it a `bytearray`, which grows in place, and the job is again byte for byte the same.

`/api/print` doesn't draw the labels first. It hands `build_job()` a `Labels` object, which draws each label when brother_ql reaches it, so one label's image is in memory at a time rather than all of them. brother_ql needs only the number of images and one pass through them. The warnings are complete once the job is built, and the job is sent only then, so an error in any row prints nothing. The error names the row, from the row numbers the editor sends with the records. Every label of a job gets the same date and time for the built-in fields.

The job goes to port 9100 with a plain socket write. brother_ql's own network backend isn't used: it connects without a timeout, and it can't read status back over the network anyway.

## Launching and stopping

Each editor page holds `GET /api/alive` open: an event stream the server writes a keep-alive comment to every 3 seconds. Once a page closes, the next write fails and the stream ends. When the launcher opened the browser itself, and `--lan` is off, a watcher thread stops the server once no page has been open for 10 seconds. The page's `EventSource` reconnects by itself, so a reload stays inside that grace period. The timer uses `time.monotonic()`, which doesn't count time asleep, so a suspend shouldn't stop the app.

On Linux, the launcher reads the default browser from `xdg-settings` and its command from the `.desktop` file, and passes `--new-window` for browsers known to accept it (Firefox, Chrome, Chromium, Brave, Edge, Vivaldi and similar). Anything else goes to `xdg-open`, which usually opens a tab, and so does a `.desktop` file that can't be read or whose command can't be parsed.

The launcher uses the first free port from `--port`, testing it on the address the server will listen on: all interfaces with `--lan`, otherwise `127.0.0.1`. The test sets `SO_REUSEADDR`, as the server does, so connections from the last run, which take about a minute to close, don't make the port look taken. With it, macOS would also let the app share a port another program is listening on, so a port that anything answers on at `127.0.0.1` counts as taken. Moving to another port would lose the editor's saved layout, units and open categories, which the browser keeps per address. With `--lan` it also prints this machine's network address, found by connecting a UDP socket to an address reserved for documentation. Connecting a UDP socket sends nothing.

## Requests from other sites

The app has no login, so `server.py` checks every request in `guard()`:

- **Host name.** A site can point one of its own names at `127.0.0.1` (DNS rebinding), and the browser then treats the app as part of that site. Its pages send that name as the `Host`, so requests are refused with 403 unless the host is `127.0.0.1`, `localhost` or `::1`. With `--lan`, other machines reach the app by whatever name they know it by, so the check is off.
- **JSON only.** A page on another site can send a form or plain text to any address without asking, but it can send JSON only after a CORS check, which this server never answers. So every `POST` or `PUT` must be sent as JSON, or it's refused with 415. The one exception is the data upload, a form, which only reads the file and changes nothing.
- **Where the request comes from.** Browsers say this in the `Sec-Fetch-Site` header: `same-origin` for the editor's own page, `none` for the address bar or a bookmark, and `cross-site` or `same-site` for a page somewhere else. Requests under `/api/` with either of the last two are refused with 403, which covers the data upload too. The page itself still opens from a link anywhere. Browsers send the header only to addresses they count as secure. `127.0.0.1` and `localhost` are; a plain `http` address on the network is not ([Fetch Metadata](https://www.w3.org/TR/fetch-metadata/#sec-fetch-site-header)). So with `--lan` it's mostly absent, and a request without it is let through to the other checks.

Every response also carries two headers, added in `protect()`:

- **`Content-Security-Policy`** (`server.PAGE_POLICY`) lists what the editor's page may load: its own script and stylesheet, images from the app or held in the page (`blob:` for previews, `data:` for saved images), and requests to the app. Nothing comes from another site, and a script or style written into the page isn't run, so text from a template or data file can't become code even if a mistake in the editor let it into the page. `frame-ancestors 'none'` stops another site showing the editor inside its own page, where a click meant for that page could land on Print. The editor sets styles through classes and the style object, never a `style` attribute, which the policy refuses; a test checks that.
- **`X-Content-Type-Options: nosniff`** makes the browser take each response as the type it says it is.

Every error under `/api/` comes back as JSON, `{"error": "…"}`, which the editor shows. Unexpected errors are 500s, and their tracebacks go to the terminal.

## Barcodes

`barcodes.py` knows each barcode type: what it takes, its quiet zones (the blank margins scanners need), its guard bars, and where its digits go. python-barcode does the encoding. Module positions and quiet zones come from the GS1 specifications: EAN-13 needs 11 modules on the left and 7 on the right, EAN-8 7 each side, UPC-A 9, ITF-14 10 narrow bars, and Code 128 10 modules.

Retail codes must be given in full, check digit included. python-barcode would quietly replace a wrong check digit, printing a valid code for a different product, so `barcodes.encode()` checks it first and refuses it with the right digit named. Requiring every digit also catches a leading zero that a spreadsheet dropped, which would otherwise read as a code without its check digit. python-barcode doesn't work out ITF-14's check digit, so it's checked here the same way.

`render.py` sizes the bars to whole printer dots, with the quiet zones inside the element's box. It warns below 2 dots per module for any barcode, and below 3 (0.25 mm, about three quarters of the standard size) for retail codes, where checkout scanners start to struggle. The editor lists the types from `/api/meta`.

## Images from a web address

`POST /api/image-url` fetches an image for the editor, which stores it in the template like a chosen file. The server fetches it because browsers don't let a page read images from most other sites (CORS). It's fetched once, when the address is entered, never at print time. With `--lan`, anyone on the network can ask for a fetch, so `remote.py` is careful about what it fetches and what it hands back:

- **The address:** trimmed, at most 2048 characters, with no spaces or control characters. Only `http` and `https`, with a host, and with no user name or password.
- **Where it points:** the host is looked up first, and this machine (`127.0.0.1`, `::1`, `0.0.0.0`) and link-local addresses (`169.254.0.0/16`, `fe80::/10`) are refused. So are multicast addresses. Each redirect, at most five, is checked the same way. Ordinary network addresses are allowed, for a logo on a NAS, say. A name whose answer changes between the check and the download could still get past, which is acceptable for a home tool.
- **The download:** at most 10 MB, within 10 seconds, with no proxy. Both are checked as each piece arrives, so a site that sends a byte at a time is stopped too.
- **What comes back:** only an image. It must be a PNG, JPEG, WebP or GIF that Pillow can open, or XML whose root is `<svg>`; the type the site claims is ignored. Python's XML parser refuses entity bombs and fetches nothing, and the browser draws SVGs as images, so scripts in them don't run.

The tests serve their images from a small web server on this machine, so they allow this machine's addresses while they run, and check separately that the app refuses them.

## Data files

`tables.py` turns an uploaded file into rows of strings using only the standard library, so no spreadsheet package is bundled. It detects the format from the content, with the extension as a hint: a zip holding `content.xml` is OpenDocument and one holding `xl/workbook.xml` is Excel. Other zips, old binary `.xls` files and binary data are refused with a message. A file whose parts are missing or don't parse is reported as damaged. Text starting with a UTF-16 byte-order mark, as in Excel's *Unicode Text*, is decoded as UTF-16. Other text is decoded as UTF-8, then Windows-1252, then Latin-1. The delimiter is sniffed. OpenDocument cells give their displayed text. Excel cells hold raw values, so `tables.py` applies only date formats and zero-padded formats like `00000`, and prints other numbers with at most 15 significant digits, as Excel shows them. Repeated empty rows and cells, which spreadsheets store by the million, are dropped. A table may have a million cells (`tables.MAX_CELLS`), counting every row as wide as the widest, since each row is given every column. A spreadsheet can put a cell in its last column on every row in a few bytes each, and the empty cells before them are filled in: an Excel file under 1 MB took 2.6 GB. The count is kept as the table is built, so such a file is refused before the memory is used. The endpoint is `POST /api/data`. It takes the column names from the first row and makes each one different from the rest (`server.unique_headers()`): an empty name becomes `Column 3`, and a name that repeats an earlier one, ignoring case, becomes `name (2)`. Rows are sent to the editor by column name, so two columns with one name would otherwise be one.


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

`PUT /api/templates/<name>` won't replace an existing file (409) unless sent with `?replace=1`, which the editor adds once the user has confirmed. The check is made on the server, so a template saved from another window counts. On macOS and Windows, names that differ only in case are the same file, so they count as existing too.

Only a template is saved as one: `template_fault()` wants a layout, with a list of elements if it has any, and fixed values and a column mapping that are objects. The same check runs when a template is opened, so a file that's damaged or isn't a template gets a message (422) rather than breaking the editor. The editor then fills in whatever a layout leaves out (`tidyLayout()` in `elements.mjs`), as it does for the layout it keeps in the browser.

Templates and settings are saved by `write_json()`, which writes a new file beside the old one and moves it into place. The old file stays whole if the drive fills up or is pulled out partway.

## Settings

`data/config.json` holds the printer's address, port and model. `POST /api/config` checks each one (`clean_setting()`) and refuses what can't be used, and the settings dialog shows why. Reading is forgiving instead: a file that's missing, damaged or not an object gives the defaults, and so does any one setting with a bad value, so the editor always loads.

## Screenshots

The README images are taken in the Claude desktop app's browser, from a separate instance with its own data folder and the placeholder printer address `192.168.1.50`. Real printer addresses and personal data must not appear in them.

To retake them:

1. Start a separate instance with its own port and data folder, such as `sh run.sh --no-browser --port 8630 --data <folder>`, and give it the printer address `192.168.1.50`. `.claude/launch.json` has one as `oh-brother-demo`.
2. Set the browser pane's viewport to 1200 × 720, so the three columns and the data rows fit.
3. Set up each scene. The current images show *Sample: Bin label* previewing row 3 of `samples/parts.csv`; two elements mid-drag, with a snap guide and the chained field `INS-{{size}}-5`; and the *Layered shelf tag* with a plain star as its image. No printer answers at the placeholder address, so the printer chip's dot is set to connected from the page with `ohBrother.drawPrinterChip(true)`.
4. Capture the whole pane as a PNG, 800 × 480, into `docs/images/`, and check each image for private details before committing.

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
| Pillow | 13.0.0 | MIT-CMU |
| qrcode | 8.2 | BSD |
| python-barcode | 0.16.1 | MIT |
| packbits | 0.6 | MIT |
| pyusb | 1.3.1 | BSD-3-Clause |
| attrs | 26.1.0 | MIT |

brother_ql is GPL-3.0-or-later, which is one reason Oh-Brother is GPL-3.0.

Two more are fetched but never become part of the app: setuptools 84.2.1 (MIT), which pip uses to build packbits, and pyflakes 4.1.0 (MIT), which runs only in CI.
