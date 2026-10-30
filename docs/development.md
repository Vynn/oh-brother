# Development

The app is plain Python with a plain HTML, CSS and JavaScript front end. There's no front-end build step. `build.sh` only fetches the Python runtime and packages.

## Layout

| Path | Contents | In the repo? |
|---|---|---|
| `app/` | Server (`main.py`, `server.py`, `render.py`, `printer.py`), web UI (`static/`), fonts | Yes |
| `data/templates/` | Saved templates | Yes |
| `data/samples/` | Sample data | Yes |
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

## How printing works

`render.py` draws a layout (geometry in millimetres) to an RGB image at 300 dpi. It uses no anti-aliasing and only three colours: black, red and white. That one image is both the preview and the print.

The editor asks the server for a fresh preview as you work: `POST /api/render` returns the PNG itself, with warnings and field names in URL-encoded JSON headers. Only one request is in flight at a time, so while dragging the preview updates as fast as the round trip allows.

## Stopping with the window

Each editor page holds `GET /api/alive` open: an event stream the server writes a keep-alive comment to every 3 seconds. Once a page closes, the next write fails and the stream ends. When the launcher opened the browser itself, and `--lan` is off, a watcher thread stops the server once no page has been open for 10 seconds. The page's `EventSource` reconnects by itself, so a reload stays inside that grace period. The timer uses `time.monotonic()`, which doesn't count time asleep, so a suspend shouldn't stop the app.

On Linux, the launcher reads the default browser from `xdg-settings` and its command from the `.desktop` file, and passes `--new-window` for browsers known to accept it (Firefox, Chrome, Chromium, Brave, Edge, Vivaldi and similar). Anything else goes to `xdg-open`, which usually opens a tab.

`printer.py` converts the image with brother_ql into raster commands, splitting the red and black layers for two-colour tape. It sends them with a plain socket write to port 9100. brother_ql's own network backend is not used: it connects without a timeout, and it can't read status back over the network anyway.

## Editor geometry

Element positions are in millimetres from the top left of the printable area, which is the rendered canvas. The editor draws the label at its cut size around it:

- Across the tape, the cut size is the tape width from brother_ql's label table.
- Along continuous tape, brother_ql's feed margin (35 dots, about 3 mm) is added at each end.
- On die-cut labels, the margins are split evenly between the label size and the printable size.

These cut sizes are derived from brother_ql's label data, not measured.

Snapping works in millimetres. Targets are the printable area's edges and centre lines, plus every other element's edges and centre lines. The snap distance is 6 screen pixels. Away from any target, positions snap to a 0.5 mm grid.

## Fields

The browser builds one record per label. A record holds the CSV row's columns, if a CSV is loaded, then the layout's fields, each from its fixed value or its mapped column. With the record, the browser sends `chain`: the names of fields whose values are fixed text.

`render.fill()` replaces each `{{Name}}`. A value is expanded again only if its field is in `chain`, so text typed by the user can refer to other fields and columns, while CSV cells are used exactly as written. Each expansion carries the path of fields it came through. A field already on the path is a loop: the preview keeps its tag, print leaves it blank, and a warning names the path.

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
