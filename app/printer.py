"""Printer output: brother_ql raster conversion plus a plain TCP sender.

brother_ql's own network backend connects without a timeout and cannot read
status back over the network, so jobs are sent with a short raw socket write
to port 9100 instead.
"""

import socket

from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

import render


def build_job(layout, images, model, cut=True):
    """Convert rendered canvases into one raster job (bytes)."""
    tape = render._label(layout.get("tape", "62red"))
    qlr = BrotherQLRaster(model)
    qlr.exception_on_warning = True
    return convert(
        qlr=qlr,
        images=[render.print_image(layout, im) for im in images],
        label=tape.identifier,
        rotate="0" if tape.form_factor == render.FormFactor.ENDLESS else "auto",
        threshold=50,
        dither=False,
        compress=False,
        red=bool(tape.color),
        dpi_600=False,
        hq=True,
        cut=cut,
    )


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
