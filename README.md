# Oh-Brother

Label printing for a network Brother QL-820NWB, in black or in black and red. It's a local web app that runs from its own folder, with nothing installed on the host, so it can live on a thumbdrive.

> **Status: pre-release.** Version 0.1 is the current build. Anything may change. See the [roadmap](ROADMAP.md) and [changelog](CHANGELOG.md).

## Requirements

- A Brother QL-820NWB on the network. Other two-colour QL models (QL-800, QL-810W) are selectable but untested.
- For red: DK-2251 tape (62 mm, black and red), also sold as the DK-22513 3-pack.
- Linux on x86_64. Other platforms: see the [roadmap](ROADMAP.md).

## Run

On a fresh copy, run `sh build.sh` once (it needs internet). Then:

```sh
sh run.sh
```

Your browser opens the app. Click the printer chip (top right) and enter the printer's IP address. The port is 9100.

| Option | Effect |
|---|---|
| `--no-browser` | Don't open a browser tab |
| `--port N` | First port to try (default 8620) |
| `--lan` | Allow other devices on the network to use the app. There's no login, so only use this on a trusted network. |

## Use

- **Label:** tape, length (continuous tape), and text direction (across or along the tape). The layout scales when these change.
- **Quick layouts** replace the current elements with a starting layout.
- **Editor:** the label is shown at its cut size. The dashed line is the printable area.
- **Elements:** text, QR code, Code 128 barcode, and box or line, each in black or red.
  - Drag to move. Drag a corner or edge handle to resize.
  - Edges and centres snap to the printable area's edges and centre, and to other elements, with a guide line. Otherwise they snap to a 0.5 mm grid. Hold Alt to place freely.
  - The align buttons place the selected element at the left, centre or right, and top, middle or bottom of the printable area.
  - Arrow keys nudge the selected element (Shift for bigger steps). Delete removes it.
  - Text size 0 shrinks the text to fit its box.
- **Fields:** `{{Name}}` in any text, QR code or barcode becomes a field. Fill it with fixed text or a CSV column. Built-in fields: `{{date}}`, `{{time}}` and `{{datetime}}`.
- **CSV:** load a file, map fields to columns, click a row to preview it, and tick the rows to print.
- **Templates** save the layout, fixed values and column mapping. A sample CSV in `data/samples/` matches the *Bin label* template.

The preview is exactly what prints. Over the network the printer doesn't report back, so "Sent" means the job reached it.

## Thumbdrives

- Start the app with `sh run.sh` rather than `./run.sh`, since FAT32 and exFAT don't keep the executable flag.
- If the drive doesn't allow running programs, the Python runtime (about 110 MB) is copied once to `~/.cache/oh-brother/`. Your settings and templates stay on the drive.

## Development

See [development](docs/development.md) for the folder layout, how printing works, and third-party code.

## License

GPL-3.0. See [LICENSE](LICENSE). Bundled fonts keep their own licences, listed in [development](docs/development.md#third-party-code).
