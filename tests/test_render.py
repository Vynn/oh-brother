"""Drawing labels: render.render() and print_image(), canvas sizes from
tapes.py, and reference images of every element type and option on the main
kinds of tape."""

import unittest

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


def layout(*elements, tape="62red", length=30, orientation="portrait"):
    return {"tape": tape, "length_mm": length, "orientation": orientation, "elements": list(elements)}


RECORD = {"title": "Bolt M3 × 12", "body": "Zinc plated, box of 100", "code": "B-0012",
          "name": "Ada", "street": "", "city": "Paris"}

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


class Canvas(unittest.TestCase):

    def test_sizes_on_each_kind_of_tape(self):
        dpmm = tapes.DPMM
        self.assertEqual(tapes.canvas_dots(layout(length=30)), (696, round(30 * dpmm)))
        self.assertEqual(tapes.canvas_dots(layout(length=30, orientation="landscape")), (round(30 * dpmm), 696))
        # Die-cut labels have a fixed size, whatever length is asked for
        self.assertEqual(tapes.canvas_dots(layout(tape="29x90", length=5)),
                         tapes.canvas_dots(layout(tape="29x90", length=500)))

    def test_landscape_is_turned_for_the_printer(self):
        lay = layout(box(0, 0, 5, 5), length=40, orientation="landscape")
        img = render.render(lay)[0]
        out = render.print_image(lay, img)
        self.assertEqual(out.size, (img.size[1], img.size[0]))
        self.assertEqual(render.print_image(layout(), img), img)   # portrait goes as drawn

    def test_unknown_tape(self):
        with self.assertRaises(ValueError):
            render.render(layout(tape="99x99"))
