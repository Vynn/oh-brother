# Printer checklist

The tests compare every label image and print job byte for byte, but they can't show what the printer does with them. Before a release that changes printing (`render.py`, `printer.py`, `tapes.py`, `barcodes.py`, or the Pillow, brother_ql or python-barcode versions), go through this list on a real QL-820NWB. It takes about ten minutes and a metre or so of tape.

Start the app with a separate data folder, so your own templates and settings stay out of it:

```sh
sh run.sh --data /tmp/oh-brother-check
```

Note anything that fails, with a photo of the label, before releasing.

## Connection

- [ ] Enter the printer's address with the printer chip, top right. *Test connection* says "Printer reachable".

## Two-colour tape (DK-2251)

- [ ] Open *Sample: Bin label*, load `samples/parts.csv`, tick three rows, and print. Three labels come out, each with its own item, location and code.
- [ ] The location prints red and the item and QR code black. Red and black line up, with no red specks in black areas or the other way round.
- [ ] The QR code scans with a phone and gives the row's code, such as `BLT-M3-10`.
- [ ] With *Cut each label* on, each label is cut off. With it off, nothing is cut, and the labels come out as one strip.
- [ ] Two copies of one row give two identical labels.

## Size and direction

- [ ] A continuous label set to 50 mm measures the *Cut* size shown under the preview, give or take 0.5 mm.
- [ ] With *Along tape*, the text runs along the tape and reads the right way round, as in the preview.
- [ ] A barcode, from the *Barcode* quick layout, scans with a phone.

## Images and barcodes

- [ ] An image element with a logo, on *Threshold*, prints with crisp edges, dot for dot as in the preview. In red, on two-colour tape, it prints red.
- [ ] The same image on *Dither* shows its shading as a fine pattern of dots.
- [ ] Barcodes of each retail type scan with a phone or a checkout scanner and give their digits: EAN-13 `4006381333931`, EAN-8 `96385074`, UPC-A `036000291452`, and ITF-14 `15400141288763`, which prints with bars along its top and bottom.
- [ ] A Code 128 barcode with text or a box right beside it still scans: the quiet zones keep it clear.

## Other tapes, if you have them

- [ ] On black-only tape, a red element prints black, and the editor warned about it before printing.
- [ ] On die-cut labels, the print sits inside the label, as in the preview.
- [ ] On 12 mm or 29 mm continuous tape, the *Single line* quick layout prints in full, with nothing cut off at the edges.

## When the printer can't be reached

- [ ] With the printer switched off, *Print* reports "Send failed" within about ten seconds, and the editor keeps working.
