"""Drawing labels: render.render() and print_image(), canvas sizes from
tapes.py, and reference images of every element type and option on the main
kinds of tape."""

import base64
import datetime
import io
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import render
import tapes
from . import reference

BLACK, RED, WHITE = render.COLORS["black"], render.COLORS["red"], render.COLORS["white"]


def text(x, y, w, h, s, **o):
    return {"type": "text", "x": x, "y": y, "w": w, "h": h, "text": s, "size": 0, **o}


def qr(x, y, s, data="{{code}}", **o):
    return {"type": "qr", "x": x, "y": y, "w": s, "h": s, "data": data, **o}


def bar(x, y, w, h, data="{{code}}", **o):
    return {"type": "barcode", "x": x, "y": y, "w": w, "h": h, "data": data, **o}


def box(x, y, w, h, **o):
    return {"type": "rect", "x": x, "y": y, "w": w, "h": h, **o}


def image(x, y, w, h, src, **o):
    return {"type": "image", "x": x, "y": y, "w": w, "h": h, "src": src, "color": "black",
            "mode": "threshold", "threshold": 50, "invert": False, **o}


def data_url(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, fmt)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def glyph(size=240):
    """A plain test glyph: a dark disc crossed by a white band, on transparency."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((size * 0.05, size * 0.05, size * 0.95, size * 0.95), fill=(20, 20, 20, 255))
    d.rectangle((0, size * 0.42, size, size * 0.58), fill=(255, 255, 255, 255))
    return data_url(im)


def gradient(w=300, h=60):
    """Black to white, left to right."""
    im = Image.new("L", (w, h))
    im.putdata([round(x * 255 / (w - 1)) for _ in range(h) for x in range(w)])
    return data_url(im)


GLYPH, GRADIENT = glyph(), gradient()


def layout(*elements, tape="62red", length=30, orientation="portrait"):
    return {"tape": tape, "length_mm": length, "orientation": orientation, "elements": list(elements)}


RECORD = {"title": "Bolt M3 × 12", "body": "Zinc plated, box of 100", "code": "B-0012",
          "name": "Ada", "street": "", "city": "Paris",
          "category": "Hardware", "variant": "Box of 100", "price": "$4.50", "note": "Bulk price"}

# One layout per reference image. Fixed text only: no {{date}} or {{time}}.
REFERENCES = {
    "text-styles": layout(
        text(1, 1, 58, 8, "{{title}}"),
        text(1, 10, 28, 8, "Serif bold, centred", font="serif", bold=True, align="center", size=9),
        text(30, 10, 28, 8, "Mono right, bottom", font="mono", align="right", valign="bottom", size=7),
        text(1, 19, 28, 10, "Narrow, wrapped, line spacing 1.4", font="narrow", size=8, spacing=1.4),
        text(30, 19, 28, 10, "{{body}}", valign="top", max_size=9, padding_mm=1),
        length=30),
    "text-inverted-red": layout(
        text(1, 1, 58, 8, "Inverted black", invert=True, align="center", padding_mm=1),
        text(1, 10, 58, 8, "Inverted red", invert=True, color="red", align="center", padding_mm=1),
        text(1, 19, 58, 8, "Red text", color="red", wrap=False),
        length=28),
    "codes": layout(
        qr(1, 1, 18), qr(21, 1, 18, ec="H", color="red"),
        bar(1, 21, 38, 9), bar(41, 21, 18, 9, data="A1", show_text=False, color="red"),
        text(41, 1, 18, 18, "QR M, QR H red, barcodes", size=6),
        length=31),
    "boxes": layout(
        box(1, 1, 18, 10), box(21, 1, 18, 10, fill=False, stroke_mm=0.5),
        box(41, 1, 18, 10, fill=False, stroke_mm=1.5, color="red"), box(1, 13, 58, 0.3),
        length=15),
    "landscape": layout(
        text(1, 1, 30, 10, "{{title}}", bold=True), qr(1, 13, 40), bar(32, 1, 40, 14),
        text(44, 17, 28, 20, "{{body}}"),
        length=75, orientation="landscape"),
    "black-tape": layout(
        text(1, 1, 40, 10, "Red prints black here", color="red"), qr(43, 1, 16, color="red"),
        tape="62", length=20),
    "die-cut": layout(text(1, 1, 24, 30, "{{title}}", bold=True), bar(1, 33, 24, 12), tape="29x90"),
    "round": layout(text(2, 2, 16, 6, "Round", align="center"), qr(6, 9, 8), tape="d24"),
    "narrow-tape": layout(text(0.5, 0.5, 39, 8, "{{title}} · {{body}}", wrap=False), tape="12",
                          length=40, orientation="landscape"),
    "fields": layout(
        text(1, 1, 58, 6, "{{name}} · {{street}} · {{city}}"),
        text(1, 8, 58, 6, "SKU {{missing}}"),   # every field empty: hidden
        text(1, 15, 58, 6, "{{title}}\n{{missing}}\nend", size=5),
        length=22),
    # The Layered shelf tag quick layout's arrangement, on 62 mm tape, 25 mm long
    "layered-shelf-tag": layout(
        image(2, 2.74, 7.39, 7.39, GLYPH),
        text(10.39, 3.78, 22.13, 5.32, "{{category}}", wrap=False),
        box(35.13, 2, 21.8, 9.24, fill=False, stroke_mm=0.3),
        text(35.87, 2.74, 20.32, 5.28, "{{price}}", align="center", wrap=False),
        text(35.87, 8.02, 20.32, 2.48, "{{note}}", align="center", wrap=False),
        text(2, 12.24, 54.93, 6.3, "{{title}}", wrap=False),
        text(2, 18.54, 54.93, 4.46, "{{variant}}", wrap=False),
        length=25),
    "image-modes": layout(
        image(1, 1, 56, 6, GRADIENT),                     # threshold at 50%: the darker half
        image(1, 8, 56, 6, GRADIENT, threshold=80),       # more of it
        image(1, 15, 56, 6, GRADIENT, mode="dither"),     # shading as dots
        image(1, 22, 12, 12, GLYPH, invert=True),         # the box prints, the glyph stays blank
        image(15, 22, 12, 12, GLYPH, color="red"),
        image(29, 22, 28, 12, GLYPH),                     # wide box: centred, not stretched
        length=35),
    "barcode-types": layout(
        bar(1, 1, 38, 16, "4006381333931", symbology="ean13"),
        bar(41, 1, 17, 16, "96385074", symbology="ean8"),
        bar(1, 19, 38, 16, "036000291452", symbology="upca"),
        bar(41, 19, 17, 16, "{{code}}", symbology="code128"),
        bar(1, 37, 57, 16, "15400141288763", symbology="itf14"),
        bar(1, 55, 28, 12, "4006381333931", symbology="ean13", show_text=False),
        bar(31, 55, 27, 12, "978-3-16-148410-0", symbology="ean13", color="red"),
        length=68),
}


def colours(img):
    return {c for _, c in img.getcolors(1 << 20)}


class References(unittest.TestCase):
    """Each layout drawn as it was when its reference image was made."""

    def test_reference_images(self):
        for name, lay in REFERENCES.items():
            with self.subTest(name):
                img, _, _ = render.render(lay, RECORD, keep_missing=False)
                self.assertLessEqual(colours(img), {BLACK, RED, WHITE})
                reference.check_image(self, name, img)


class Elements(unittest.TestCase):

    def draw(self, *elements, record=RECORD, **lay):
        return render.render(layout(*elements, **lay), record, keep_missing=False)

    def test_only_three_colours_and_no_red_on_black_tape(self):
        img, warnings, _ = self.draw(box(1, 1, 10, 10, color="red"), tape="62")
        self.assertEqual(colours(img), {BLACK, WHITE})
        self.assertEqual(warnings, ["This tape is black-only; red elements print in black"])

    def test_inverted_text_is_white_on_its_colour(self):
        img, _, _ = self.draw(text(0, 0, 20, 10, "Hi", invert=True, color="red"))
        dpmm = tapes.DPMM
        inside = img.crop((0, 0, round(20 * dpmm), round(10 * dpmm)))
        self.assertEqual(colours(inside), {RED, WHITE})
        self.assertEqual(inside.getpixel((1, 1)), RED)

    def test_outline_box_is_hollow(self):
        img, _, _ = self.draw(box(0, 0, 20, 10, fill=False, stroke_mm=1))
        self.assertEqual(img.getpixel((2, 2)), BLACK)
        self.assertEqual(img.getpixel((round(10 * tapes.DPMM), round(5 * tapes.DPMM))), WHITE)

    def test_barcode_text_can_be_left_off(self):
        def white_rows(**o):
            size = (round(40 * tapes.DPMM), round(10 * tapes.DPMM))
            img = self.draw(bar(0, 0, 40, 10, **o))[0].convert("L").crop((0, 0, *size))
            return sum(img.crop((0, y, size[0], y + 1)).getextrema()[0] > 128 for y in range(size[1]))
        self.assertEqual(white_rows(show_text=False), 0)   # bars run the full height
        self.assertGreater(white_rows(), 0)   # the gap between the bars and the text

    def test_size_warnings(self):
        cases = {
            "QR code too small": qr(0, 0, 3, data="https://example.com/a/fairly/long/address"),
            "Barcode too dense": bar(0, 0, 8, 8, data="0123456789ABCDEFGHIJ"),
            "overflows its box": text(0, 0, 10, 3, "Far too large", size=30),
            "does not fit even at minimum size": text(0, 0, 2, 0.5, "Much too long for this box " * 4),
        }
        for words, el in cases.items():
            with self.subTest(words):
                warnings = self.draw(el)[1]
                self.assertTrue(any(words in w for w in warnings), warnings)

    def test_unknown_element_types_are_skipped(self):
        img, warnings, blank = self.draw({"type": "sparkle", "x": 0, "y": 0, "w": 10, "h": 10})
        self.assertEqual(colours(img), {WHITE})
        self.assertEqual((warnings, blank), ([], []))

    def test_qr_code_with_too_much_data_is_blank(self):
        img, warnings, blank = self.draw(qr(0, 0, 20, data="x" * 4000))
        self.assertEqual(colours(img), {WHITE})
        self.assertEqual(blank, [{"i": 0, "type": "qr", "why": "invalid"}])
        self.assertEqual(warnings, ["QR code can't hold this much data (4000 characters); shorten it"])

    def test_a_box_far_larger_than_the_label_is_cut_down(self):
        # A width of 5000 typed by mistake once asked for gigabytes of memory.
        # What's on the label is drawn as before; the rest never printed.
        huge = "An element is far larger than the label; only part of it is drawn"
        with mock.patch.object(render.Image, "new", wraps=Image.new) as new:
            img, warnings, _ = self.draw(box(-5, -5, 5000, 5000), box(0, 0, 9000, 1, color="red"))
        self.assertEqual(warnings, [huge])
        self.assertEqual(colours(img), {BLACK, RED})   # the label is covered
        W, H = img.size
        for call in new.call_args_list:   # the label, then each element's mask
            w, h = call.args[1]
            self.assertLessEqual(w, render.MAX_BOX * W)
            self.assertLessEqual(h, render.MAX_BOX * H)
        # Just under twice the label's size each way draws in full, and says nothing
        self.assertEqual(self.draw(box(-29, -15, 116, 59))[1], [])

    def test_text_size_has_a_limit(self):
        for el in (text(0, 0, 50, 20, "A", size=1e7), text(0, 0, 50, 20, "A", max_size=1e7)):
            with self.subTest(el=el), mock.patch.object(render, "_font", wraps=render._font) as font:
                self.draw(el)
                self.assertLessEqual(max(call.args[2] for call in font.call_args_list), render.MAX_FONT_PX)

    def test_one_date_and_time_for_every_element(self):
        # Asked for once, so a label can't show two times when the minute turns
        stamp = text(0, 0, 50, 8, "{{time}}")
        with mock.patch.object(render.datetime, "datetime", wraps=datetime.datetime) as clock:
            self.draw(stamp, {**stamp, "y": 10}, qr(40, 12, 12, data="{{datetime}}"))
        self.assertEqual(clock.now.call_count, 1)


class Images(unittest.TestCase):

    def ink(self, el, **lay):
        """Share of the element's box that prints, its colours, warnings and blanks."""
        img, warnings, blank = render.render(layout(el, **lay))
        dpmm = tapes.DPMM
        box = img.crop((round(el["x"] * dpmm), round(el["y"] * dpmm),
                        round((el["x"] + el["w"]) * dpmm), round((el["y"] + el["h"]) * dpmm)))
        printed = sum(n for n, c in box.getcolors(1 << 20) if c != WHITE)
        return printed / (box.width * box.height), colours(box), warnings, blank

    def test_threshold_level(self):
        # The gradient is 5:1, as is its box, so it fills the box
        half = self.ink(image(0, 0, 50, 10, GRADIENT))[0]
        more = self.ink(image(0, 0, 50, 10, GRADIENT, threshold=80))[0]
        self.assertAlmostEqual(half, 0.5, delta=0.03)
        self.assertAlmostEqual(more, 0.8, delta=0.03)

    def test_dither_shows_grey_as_dots(self):
        grey = data_url(Image.new("L", (50, 50), 128))
        share, cols, _, _ = self.ink(image(0, 0, 20, 20, grey, mode="dither"))
        self.assertAlmostEqual(share, 0.5, delta=0.05)
        # Thresholded, grey 128 is all or nothing
        self.assertEqual(self.ink(image(0, 0, 20, 20, grey, threshold=60))[0], 1.0)
        self.assertEqual(self.ink(image(0, 0, 20, 20, grey, threshold=40))[0], 0)

    def test_transparent_parts_print_nothing(self):
        clear = data_url(Image.new("RGBA", (50, 50), (0, 0, 0, 0)))
        self.assertEqual(self.ink(image(0, 0, 20, 20, clear))[0], 0)

    def test_inverted_fills_the_box(self):
        clear = data_url(Image.new("RGBA", (50, 50), (0, 0, 0, 0)))
        self.assertEqual(self.ink(image(0, 0, 20, 20, clear, invert=True))[0], 1.0)

    def test_fits_without_stretching(self):
        # A square image in a box twice as wide: the side strips stay blank
        black = data_url(Image.new("L", (50, 50), 0))
        self.assertAlmostEqual(self.ink(image(0, 0, 40, 20, black))[0], 0.5, delta=0.01)

    def test_prints_in_its_colour(self):
        self.assertEqual(self.ink(image(0, 0, 20, 20, GLYPH, color="red"))[1], {RED, WHITE})
        self.assertEqual(self.ink(image(0, 0, 20, 20, GLYPH, color="red"), tape="62")[1], {BLACK, WHITE})

    def test_jpeg_and_webp(self):
        for fmt in ("JPEG", "WEBP"):
            with self.subTest(fmt):
                src = data_url(Image.new("RGB", (50, 50), (0, 0, 0)), fmt)
                self.assertEqual(self.ink(image(0, 0, 20, 20, src))[0], 1.0)

    def test_low_resolution_warning(self):
        tiny = data_url(Image.new("L", (8, 8), 0))
        self.assertIn("Image is low resolution for its size on the label; it may print blocky",
                      self.ink(image(0, 0, 20, 20, tiny))[2])

    def test_missing_or_unusable(self):
        big = data_url(Image.new("L", (2100, 2100), 0))
        cases = {
            "": ("empty", None),
            "data:image/png;base64,AAAA": ("invalid", "it isn't a PNG, JPEG, WebP or GIF image"),
            "data:image/png;base64,@@@@": ("invalid", "its data is damaged"),
            "data:text/plain;base64,AAAA": ("invalid", "it isn't an image"),
            big: ("invalid", "the image has too many pixels"),
            "data:image/png;base64," + "A" * render.MAX_IMAGE_CHARS:
                ("invalid", "it's over 128 KB; choose it again, and the editor will shrink it"),
        }
        for src, (why, msg) in cases.items():
            with self.subTest(why=why, msg=msg):
                share, _, warnings, blank = self.ink(image(0, 0, 20, 20, src))
                self.assertEqual((share, blank), (0, [{"i": 0, "type": "image", "why": why}]))
                self.assertEqual(warnings, [] if msg is None else [f"Image can't be used: {msg}"])


class Canvas(unittest.TestCase):

    def test_sizes_on_each_kind_of_tape(self):
        dpmm = tapes.DPMM
        self.assertEqual(tapes.canvas_dots(layout(length=30)), (696, round(30 * dpmm)))
        self.assertEqual(tapes.canvas_dots(layout(length=30, orientation="landscape")), (round(30 * dpmm), 696))
        # Die-cut labels have a fixed size, whatever length is asked for
        self.assertEqual(tapes.canvas_dots(layout(tape="29x90", length=5)),
                         tapes.canvas_dots(layout(tape="29x90", length=500)))

    def test_length_is_held_to_the_editors_limits(self):
        dpmm = tapes.DPMM
        self.assertEqual(tapes.canvas_dots(layout(length=1))[1], round(tapes.MIN_LENGTH_MM * dpmm))
        self.assertEqual(tapes.canvas_dots(layout(length=1e9))[1], round(tapes.MAX_LENGTH_MM * dpmm))
        for length in (tapes.MIN_LENGTH_MM, 123.4, tapes.MAX_LENGTH_MM):   # within them, as asked
            self.assertEqual(tapes.canvas_dots(layout(length=length))[1], round(length * dpmm))

    def test_landscape_is_turned_for_the_printer(self):
        lay = layout(box(0, 0, 5, 5), length=40, orientation="landscape")
        img = render.render(lay)[0]
        out = render.print_image(lay, img)
        self.assertEqual(out.size, (img.size[1], img.size[0]))
        self.assertEqual(render.print_image(layout(), img), img)   # portrait goes as drawn

    def test_unknown_tape(self):
        with self.assertRaises(ValueError):
            render.render(layout(tape="99x99"))
