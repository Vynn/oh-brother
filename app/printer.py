"""Printer output: brother_ql raster conversion plus a plain TCP sender.

brother_ql's own network backend connects without a timeout and cannot read
status back over the network, so jobs are sent with a short raw socket write
to port 9100 instead.
"""

import socket

import brother_ql.conversion
from brother_ql.conversion import convert
from brother_ql.labels import FormFactor
from brother_ql.raster import BrotherQLRaster
from PIL import Image, ImageChops

import render
import tapes


def _filtered_hsv(im, filter_h, filter_s, filter_v, default_col=(255, 255, 255)):
    """brother_ql's colour filter for two-colour tape, without its per-pixel loop.

    brother_ql picks out red and black by testing each pixel's hue, saturation
    and value in Python, about 50 ms a label. Multiplying the three 0/255 masks
    gives the same mask in Pillow, so the job is byte for byte the same. Its
    loop also uses Image.getdata, which Pillow 14 removes.
    """
    h, s, v = im.convert("HSV").split()
    mask = ImageChops.multiply(ImageChops.multiply(h.point(filter_h), s.point(filter_s)), v.point(filter_v))
    out = Image.new("RGB", im.size, color=default_col)
    out.paste(im, None, mask)
    return out


brother_ql.conversion.filtered_hsv = _filtered_hsv   # convert() looks it up there


class _Turned:
    """Canvases turned for the printer one at a time, as convert() reaches them.

    convert() asks only for the number of images and goes through them once,
    so a long job never needs every label's image in memory together.
    """

    def __init__(self, layout, images):
        self.layout, self.images = layout, images

    def __len__(self):
        return len(self.images)

    def __iter__(self):
        return (render.print_image(self.layout, im) for im in self.images)


def build_job(layout, images, model, cut=True):
    """Convert rendered canvases into one raster job (bytes).

    `images` is a list, or anything with a length that can be gone through
    once: the server passes labels that are drawn only as they're reached.
    """
    tape = tapes.label(layout.get("tape", "62red"))
    qlr = BrotherQLRaster(model)
    qlr.exception_on_warning = True
    # brother_ql builds the job with +=. Its own buffer is bytes, which copies
    # the whole job on every addition, so each label took longer than the one
    # before: 24 to 68 ms a label at 400 labels, against 6.5 ms for any number
    # now. A bytearray grows in place, and the job is byte for byte the same.
    qlr.data = bytearray()
    return bytes(convert(
        qlr=qlr,
        images=_Turned(layout, images),
        label=tape.identifier,
        rotate="0" if tape.form_factor == FormFactor.ENDLESS else "auto",
        threshold=50,
        dither=False,
        compress=False,
        red=bool(tape.color),
        dpi_600=False,
        hq=True,
        cut=cut,
    ))


def send(host, port, data, timeout=10):
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        s.sendall(data)


def check(host, port, timeout=3):
    """(ok, message): whether something accepts TCP connections at host:port."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, "Printer reachable"
    except OSError as e:
        return False, f"Cannot reach {host}:{port} — {e.strerror or e}"
