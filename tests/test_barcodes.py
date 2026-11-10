"""Barcode types: barcodes.encode(), and how render.py draws them. Codes are
the examples from GS1 and the barcode makers' documentation."""

import unittest

import barcodes
import render
import tapes

GOOD = {
    "ean13": "4006381333931",
    "ean8": "96385074",
    "upca": "036000291452",
    "itf14": "15400141288763",
}


def bar(kind, data, w=50, h=16, **o):
    return {"type": "barcode", "x": 0, "y": 0, "w": w, "h": h, "data": data, "symbology": kind, **o}


def draw(el):
    """The barcode's box, as a black-and-white mask, and the render's warnings."""
    img, warnings, blank = render.render({"tape": "62", "length_mm": 30, "elements": [el]})
    box = img.crop((0, 0, round(el["w"] * tapes.DPMM), round(el["h"] * tapes.DPMM))).convert("L")
    return box.point(lambda v: 255 if v < 128 else 0), warnings, blank


class CheckDigits(unittest.TestCase):

    def test_known_codes(self):
        for kind, code in GOOD.items():
            with self.subTest(kind):
                self.assertEqual(barcodes.check_digit(code[:-1]), code[-1])
                self.assertEqual(barcodes.encode(kind, code).text, code)

    def test_wrong_check_digit_is_refused_not_fixed(self):
        with self.assertRaises(barcodes.BarcodeError) as cm:
            barcodes.encode("ean13", "4006381333932")
        self.assertEqual(str(cm.exception), "the check digit of 4006381333932 should be 1, not 2")

    def test_every_digit_is_needed(self):
        with self.assertRaises(barcodes.BarcodeError) as cm:
            barcodes.encode("upca", "36000291452")   # 036000291452 with its leading zero dropped
        self.assertEqual(str(cm.exception), "UPC-A needs 12 digits, with the check digit; this has 11. "
                                            "If it came from a spreadsheet, a leading zero may have been dropped")
        with self.assertRaises(barcodes.BarcodeError) as cm:
            barcodes.encode("ean8", "963850741")
        self.assertEqual(str(cm.exception), "EAN-8 needs 8 digits, with the check digit; this has 9")

    def test_digits_only(self):
        for kind in GOOD:
            with self.subTest(kind), self.assertRaises(barcodes.BarcodeError) as cm:
                barcodes.encode(kind, "40063813A3931")
            self.assertIn("takes digits only", str(cm.exception))

    def test_digits_in_other_scripts_are_the_same_numbers(self):
        # Full-width, as a Japanese keyboard types them, and Arabic-Indic
        plain = barcodes.encode("ean13", GOOD["ean13"])
        for digits in ("４００６３８１３３３９３１", "٤٠٠٦٣٨١٣٣٣٩٣١", "４００６-３８１３ 33931"):
            with self.subTest(digits):
                code = barcodes.encode("ean13", digits)
                self.assertEqual((code.modules, code.text), (plain.modules, GOOD["ean13"]))

    def test_characters_that_only_look_like_digits_are_refused(self):
        # str.isdigit() is true for ² and ①, which int() can't read: this was an unhandled error
        for data in ("40063²1333931", "400638133393①"):
            with self.subTest(data), self.assertRaises(barcodes.BarcodeError) as cm:
                barcodes.encode("ean13", data)
            self.assertEqual(str(cm.exception), "EAN-13 takes digits only")

    def test_spaces_and_hyphens_are_ignored(self):
        self.assertEqual(barcodes.encode("ean13", "978-3-16-148410-0").text, "9783161484100")
        self.assertEqual(barcodes.encode("upca", "0 36000 29145 2").text, "036000291452")

    def test_code128_takes_text(self):
        self.assertEqual(barcodes.encode("code128", "B-0012 ok").text, "B-0012 ok")
        with self.assertRaises(barcodes.BarcodeError):
            barcodes.encode("code128", "☃")

    def test_unknown_type(self):
        with self.assertRaises(barcodes.BarcodeError):
            barcodes.encode("qr", "x")


class Drawing(unittest.TestCase):

    def columns(self, mask):
        """Per column of the box, the lowest inked row, or -1."""
        w, h = mask.size
        px = mask.load()
        return [max((y for y in range(h) if px[x, y]), default=-1) for x in range(w)]

    def test_quiet_zones_stay_blank(self):
        for kind, code in [*GOOD.items(), ("code128", "B-0012")]:
            with self.subTest(kind):
                el = bar(kind, code, show_text=False)
                mask = draw(el)[0]
                k = barcodes.KINDS[kind]
                n = k.quiet[0] + len(barcodes.encode(kind, code).modules) + k.quiet[1]
                mod = mask.width // n
                x0 = (mask.width - n * mod) // 2
                bars = mask.crop((x0, mask.height // 2, x0 + n * mod, mask.height // 2 + 1)).getbbox()
                # Rows between ITF-14's bearer bars, through the middle of the code
                self.assertGreaterEqual(bars[0], k.quiet[0] * mod)
                self.assertLessEqual(bars[2], (n - k.quiet[1]) * mod)

    def test_guard_bars_run_down_between_the_digits(self):
        mask = draw(bar("ean13", GOOD["ean13"]))[0]
        lowest = [y for y in self.columns(mask) if y >= 0]
        self.assertGreater(max(lowest), min(lowest) + 5)   # guards end lower than the other bars

    def test_without_text_every_bar_runs_the_full_height(self):
        mask = draw(bar("ean13", GOOD["ean13"], show_text=False))[0]
        ends = {y for y in self.columns(mask) if y >= 0}
        self.assertEqual(ends, {mask.height - 1})

    def test_itf14_has_bearer_bars(self):
        mask = draw(bar("itf14", GOOD["itf14"], w=57, show_text=False))[0]
        top = mask.crop((0, 0, mask.width, 1)).getbbox()
        k = barcodes.KINDS["itf14"]
        n = k.quiet[0] + len(barcodes.encode("itf14", GOOD["itf14"]).modules) + k.quiet[1]
        self.assertEqual(top[2] - top[0], n * (mask.width // n))   # across the code and its quiet zones

    def test_invalid_data_is_blank_with_the_reason(self):
        mask, warnings, blank = draw(bar("ean13", "4006381333932"))
        self.assertIsNone(mask.getbbox())
        self.assertEqual(blank, [{"i": 0, "type": "barcode", "why": "invalid"}])
        self.assertEqual(warnings, ["Barcode error: the check digit of 4006381333932 should be 1, not 2"])

    def test_small_retail_code_warns_once(self):
        img, warnings, _ = render.render({"tape": "62", "length_mm": 30, "elements": [
            bar("ean13", GOOD["ean13"], w=27), {**bar("ean13", GOOD["ean13"], w=27), "y": 17}]})
        self.assertEqual(warnings, ["EAN-13 barcode is small for checkout scanners; widen it"])
