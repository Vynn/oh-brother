"""Label renderer.

Turns a layout (JSON-like dict, all geometry in millimetres) plus one data
record into a 300 dpi RGB image that is both the on-screen preview and the
exact bitmap sent to the printer.

Everything is drawn without anti-aliasing and in pure black (0,0,0) or pure
red (255,0,0), so brother_ql's black/red separation is unambiguous and the
preview shows exactly what the thermal head will produce. Tape sizes come from
tapes.py and field filling from fields.py.
"""

import base64
import binascii
import functools
import io
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

import qrcode

import barcodes
from fields import fill, fill_text
from tapes import DPI, DPMM, canvas_dots, label

COLORS = {"black": (0, 0, 0), "red": (255, 0, 0), "white": (255, 255, 255)}

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_FILES = {
    # family: (regular, bold)
    "sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "narrow": ("LiberationSansNarrow-Regular.ttf", "LiberationSansNarrow-Bold.ttf"),
    "serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    "mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
}


def mm(v):
    return round(float(v) * DPMM)


def _font(family, bold, px):
    files = FONT_FILES.get(family, FONT_FILES["sans"])
    # Pillow's basic layout, which uses only the FreeType bundled with Pillow.
    # Its other layout, Raqm, needs the computer's own FriBiDi library, so text
    # came out a dot different on computers without it (as on macOS). Labels
    # are now the same on every computer; right-to-left and other scripts that
    # need shaping, such as Arabic or Devanagari, aren't laid out correctly.
    return ImageFont.truetype(os.path.join(FONT_DIR, files[1 if bold else 0]), max(1, int(px)),
                              layout_engine=ImageFont.Layout.BASIC)


def _wrap(text, font, width, wrap):
    """Split into lines on explicit newlines, then greedy word-wrap if enabled."""
    lines = []
    for para in text.split("\n"):
        if not wrap or not para:
            lines.append(para)
            continue
        cur = ""
        for word in para.split(" "):
            trial = word if not cur else cur + " " + word
            if font.getlength(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _layout_text(text, family, bold, px, width, wrap, spacing):
    font = _font(family, bold, px)
    lines = _wrap(text, font, width, wrap)
    ascent, descent = font.getmetrics()
    line_h = (ascent + descent) * spacing
    total_h = line_h * (len(lines) - 1) + ascent + descent
    max_w = max((font.getlength(l) for l in lines), default=0)
    return font, lines, line_h, total_h, max_w


def _draw_text(mask, el, text, warnings):
    W, H = mask.size
    pad = mm(el.get("padding_mm", 0))
    bw, bh = max(1, W - 2 * pad), max(1, H - 2 * pad)
    family, bold = el.get("font", "sans"), bool(el.get("bold"))
    wrap, spacing = bool(el.get("wrap", True)), float(el.get("spacing", 1.0))
    size_pt = float(el.get("size", 0) or 0)

    if size_pt > 0:
        px = size_pt * DPI / 72
        font, lines, line_h, total_h, max_w = _layout_text(text, family, bold, px, bw, wrap, spacing)
        if max_w > bw + 1 or total_h > bh + 1:
            warnings.append(f"Text “{text[:20]}” overflows its box")
    else:
        # Auto size: largest size that fits the box (binary search on pixel size)
        cap = float(el.get("max_size", 0) or 0) * DPI / 72 or bh
        lo, hi, best = 4, max(4, int(cap)), None
        while lo <= hi:
            mid = (lo + hi) // 2
            res = _layout_text(text, family, bold, mid, bw, wrap, spacing)
            if res[4] <= bw and res[3] <= bh:
                best, lo = res, mid + 1
            else:
                hi = mid - 1
        if best is None:
            best = _layout_text(text, family, bold, 4, bw, wrap, spacing)
            warnings.append(f"Text “{text[:20]}” does not fit even at minimum size")
        font, lines, line_h, total_h, max_w = best

    valign = el.get("valign", "middle")
    y = pad + {"top": 0, "bottom": bh - total_h}.get(valign, (bh - total_h) / 2)
    align = el.get("align", "left")
    d = ImageDraw.Draw(mask)
    d.fontmode = "1"  # no anti-aliasing: thermal printing is 1-bit
    for line in lines:
        lw = font.getlength(line)
        x = pad + {"center": (bw - lw) / 2, "right": bw - lw}.get(align, 0)
        d.text((round(x), round(y)), line, font=font, fill=255)
        y += line_h


def _draw_qr(mask, el, data, warnings):
    """Draw a QR code. Returns "empty" when there is nothing to encode."""
    W, H = mask.size
    if not data:
        return "empty"
    ec = {"L": qrcode.constants.ERROR_CORRECT_L, "M": qrcode.constants.ERROR_CORRECT_M,
          "Q": qrcode.constants.ERROR_CORRECT_Q, "H": qrcode.constants.ERROR_CORRECT_H}
    qr = qrcode.QRCode(border=0, error_correction=ec.get(el.get("ec", "M"), ec["M"]))
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    side = min(W, H)
    mod = side // n  # whole dots per module keeps the code crisp
    if mod < 2:
        warnings.append(f"QR code too small for its data ({n}×{n} modules); enlarge it")
        mod = max(1, mod)
    ox, oy = (W - n * mod) // 2, (H - n * mod) // 2
    d = ImageDraw.Draw(mask)
    for r, row in enumerate(matrix):
        for c, on in enumerate(row):
            if on:
                d.rectangle([ox + c * mod, oy + r * mod, ox + (c + 1) * mod - 1, oy + (r + 1) * mod - 1], fill=255)


def _draw_barcode(mask, el, data, warnings):
    """Draw a barcode. Returns "empty" or "invalid" when nothing is drawn.

    The quiet zones, blank margins that scanners need, are kept inside the
    box. Retail codes get their standard look: the digits in groups under
    each half, with the guard bars running down between them. ITF-14 gets
    bars along its top and bottom, as printed on cartons.
    """
    W, H = mask.size
    if not data:
        return "empty"
    try:
        code = barcodes.encode(el.get("symbology", "code128"), data)
    except barcodes.BarcodeError as e:
        warnings.append(f"Barcode error: {e}")
        return "invalid"
    kind, modules = code.kind, code.modules
    left, right = kind.quiet
    n = left + len(modules) + right
    mod = W // n
    msg = (f"Barcode too dense for its width ({len(modules)} modules); widen it or shorten the data" if mod < 2
           else f"{kind.name} barcode is small for checkout scanners; widen it" if mod < kind.min_dots else None)
    if msg and msg not in warnings:   # once, however many barcodes it applies to
        warnings.append(msg)
    mod = max(1, mod)
    x0 = (W - n * mod) // 2 + left * mod   # where the bars start
    d = ImageDraw.Draw(mask)
    d.fontmode = "1"

    text_h, font = 0, None
    if el.get("show_text", True):
        px = max(12, H * (0.22 if kind.groups else 0.18))
        # One size for every group, small enough that each fits under its bars
        for a, b, m0, m1, scale in kind.groups:
            w = _font("mono", False, px * scale).getlength(code.text[a:b])
            if w > (m1 - m0) * mod * 0.92:
                px *= (m1 - m0) * mod * 0.92 / w
        font = _font("mono", False, max(8, px))
        text_h = sum(font.getmetrics())
    if kind.groups:
        bar_end = H - text_h                       # the digits sit just below the bars
        guard_end = H - round(text_h * 0.45)       # and the guards run down between them
    else:
        bar_end = guard_end = H - (text_h + mm(0.5) if text_h else 0)
    bearer = max(2, 4 * mod) if kind.bearers else 0   # twice a narrow bar's width
    top, bar_end, guard_end = bearer, bar_end - bearer, guard_end - bearer
    guards = {i for a, b in kind.guards for i in range(a, b + 1)}
    for i, bit in enumerate(modules):
        if bit == "1":
            end = guard_end if i in guards else bar_end
            d.rectangle([x0 + i * mod, top, x0 + (i + 1) * mod - 1, max(top, end - 1)], fill=255)
    if bearer:
        sx0, sx1 = x0 - left * mod, x0 + (len(modules) + right) * mod - 1
        d.rectangle([sx0, 0, sx1, bearer - 1], fill=255)
        d.rectangle([sx0, bar_end, sx1, bar_end + bearer - 1], fill=255)

    if font is None:
        return None
    if not kind.groups:
        d.text(((W - font.getlength(code.text)) / 2, H - text_h), code.text, font=font, fill=255)
        return None
    for a, b, m0, m1, scale in kind.groups:
        f = font if scale == 1 else _font("mono", False, font.size * scale)
        txt = code.text[a:b]
        gx = x0 + (m0 + m1) / 2 * mod - f.getlength(txt) / 2
        d.text((round(gx), H - sum(f.getmetrics())), txt, font=f, fill=255)
    return None


# Images: the editor stores them as data URLs, in colour so that a two-colour
# mode can use them later; for now they print in one colour.
IMAGE_FORMATS = ["PNG", "JPEG", "WEBP", "GIF"]
MAX_IMAGE_CHARS = 128 * 1024   # the data URL, as stored in a template; the editor shrinks images to fit
MAX_IMAGE_PIXELS = 2048 * 2048


@functools.lru_cache(maxsize=8)   # the preview redraws on every drag frame
def _load_image(src):
    """A data URL's image, composited onto white and made greyscale ("L")."""
    if len(src) > MAX_IMAGE_CHARS:
        raise ValueError(f"it's over {MAX_IMAGE_CHARS // 1024} KB; choose it again, and the editor will shrink it")
    head, _, data = src.partition(",")
    if not head.startswith("data:image/") or not head.endswith(";base64"):
        raise ValueError("it isn't an image")
    try:
        raw = base64.b64decode(data, validate=True)
    except binascii.Error:
        raise ValueError("its data is damaged") from None
    try:
        with Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS) as im:
            if im.width * im.height > MAX_IMAGE_PIXELS:
                raise ValueError("the image has too many pixels")
            rgba = im.convert("RGBA")
    except Image.DecompressionBombError:
        raise ValueError("the image has too many pixels") from None
    except OSError:   # includes Pillow's "cannot identify image file"
        raise ValueError("it isn't a PNG, JPEG, WebP or GIF image") from None
    # Transparent parts become paper
    return Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba).convert("L")


def _draw_image(mask, el, warnings):
    """Draw an image in one colour. Returns "empty" or "invalid" when nothing is drawn.

    The image is scaled to fit its box without stretching, centred, and made
    black and white at print size: with a threshold (anything darker prints),
    which keeps a logo's edges crisp, or by dithering, which shows shading as
    a pattern of dots. Inverted, the box prints and the image's dark parts
    stay blank, as inverted text does.
    """
    src = el.get("src") or ""
    if not src:
        return "empty"
    try:
        grey = _load_image(src)
    except ValueError as e:
        warnings.append(f"Image can't be used: {e}")
        return "invalid"
    W, H = mask.size
    scale = min(W / grey.width, H / grey.height)
    if scale > 3:
        warnings.append("Image is low resolution for its size on the label; it may print blocky")
    w, h = max(1, round(grey.width * scale)), max(1, round(grey.height * scale))
    canvas = Image.new("L", (W, H), 255)
    canvas.paste(grey.resize((w, h), Image.LANCZOS), ((W - w) // 2, (H - h) // 2))
    if el.get("invert"):
        canvas = ImageOps.invert(canvas)
    if el.get("mode") == "dither":
        ink = ImageOps.invert(canvas.convert("1").convert("L"))   # Pillow dithers (Floyd-Steinberg) by default
    else:
        level = max(1, min(99, float(el.get("threshold", 50)))) / 100 * 255
        ink = canvas.point(lambda v: 255 if v < level else 0)
    mask.paste(ink)
    return None


def _draw_rect(mask, el):
    W, H = mask.size
    d = ImageDraw.Draw(mask)
    if el.get("fill", True):
        d.rectangle([0, 0, W - 1, H - 1], fill=255)
    else:
        d.rectangle([0, 0, W - 1, H - 1], outline=255, width=max(1, mm(el.get("stroke_mm", 0.5))))


def render(layout, record=None, keep_missing=True, chain=()):
    """Render a layout. Returns (RGB image, warning strings, blank elements).

    Blank elements drew nothing: QR codes and barcodes with empty or invalid
    data, images missing or unreadable, and text whose fields are all empty, as
    {"i": element index, "type": "qr"|"barcode"|"image"|"text", "why": "empty"|"invalid"}.
    The editor marks them; they are never drawn into the image.
    """
    record = record or {}
    warnings, blank = [], []
    tape = label(layout.get("tape", "62red"))
    red_ok = bool(tape.color)
    W, H = canvas_dots(layout)
    img = Image.new("RGB", (W, H), COLORS["white"])
    red_downgraded = False

    for i, el in enumerate(layout.get("elements", [])):
        x, y = mm(el.get("x", 0)), mm(el.get("y", 0))
        w, h = max(1, mm(el.get("w", 10))), max(1, mm(el.get("h", 10)))
        color = el.get("color", "black")
        if color == "red" and not red_ok:
            color, red_downgraded = "black", True
        kind = el.get("type")

        # Each element draws white-on-black into its own mask, which is then
        # stamped onto the label in the element's colour. This clips every
        # element to its box and lets later elements sit on top.
        mask = Image.new("L", (w, h), 0)
        if kind == "text":
            text, hide = fill_text(el.get("text", ""), record, keep_missing, chain, warnings)
            if hide:
                blank.append({"i": i, "type": "text", "why": "empty"})
                continue
            if el.get("invert"):
                img.paste(COLORS[color], (x, y, x + w, y + h))
                _draw_text(mask, el, text, warnings)
                img.paste(COLORS["white"], (x, y), mask)
                continue
            _draw_text(mask, el, text, warnings)
        elif kind in ("qr", "barcode"):
            draw = _draw_qr if kind == "qr" else _draw_barcode
            why = draw(mask, el, fill(el.get("data", ""), record, False, chain, warnings), warnings)
            if why:
                blank.append({"i": i, "type": kind, "why": why})
        elif kind == "image":
            why = _draw_image(mask, el, warnings)
            if why:
                blank.append({"i": i, "type": kind, "why": why})
        elif kind == "rect":
            _draw_rect(mask, el)
        else:
            continue
        img.paste(COLORS[color], (x, y), mask)

    if red_downgraded:
        warnings.append("This tape is black-only; red elements print in black")
    return img, warnings, blank


def print_image(layout, img):
    """Rotate a rendered canvas into the orientation brother_ql expects."""
    if layout.get("orientation") == "landscape":
        return img.rotate(90, expand=True)
    return img
