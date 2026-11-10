"""Barcode types: what each accepts, its check digit, its quiet zones, and
where its guard bars and digits go. python-barcode does the encoding.

Retail codes (EAN-13, EAN-8, UPC-A, ITF-14) must be given in full, check
digit included, and a wrong check digit is refused. python-barcode would
quietly replace it, printing a valid code for a different product. Requiring
every digit also catches a leading zero that a spreadsheet dropped, which
would otherwise read as a shorter code with its check digit missing.
"""

from dataclasses import dataclass

import barcode as pybarcode


class BarcodeError(ValueError):
    """Data a barcode type can't take, with a message for the user."""


@dataclass
class Kind:
    name: str
    hint: str                 # what to type, for the editor
    digits: int = 0           # retail: exact length, check digit included
    lib: str = ""             # python-barcode's name for it
    quiet: tuple = (10, 10)   # blank modules each side, which scanners need
    min_dots: int = 2         # narrowest module, in printer dots, that scans reliably
    guards: tuple = ()        # (first, last) module ranges drawn longer than the rest
    groups: tuple = ()        # (digits from, to, modules from, to, scale) for the text under the bars
    bearers: bool = False     # bars along the top and bottom, as on cartons


# Module positions are from the GS1 specifications: EAN-13 and UPC-A are 95
# modules (guards 0-2, 45-49, 92-94), EAN-8 is 67 (guards 0-2, 31-35, 64-66).
# Modules outside the bars (negative, or past the end) are in the quiet zone.
KINDS = {
    "code128": Kind("Code 128", "Letters, digits and symbols"),
    "ean13": Kind("EAN-13", "13 digits, with the check digit (ISBN-13 and JAN too)", 13, "ean13", (11, 7), 3,
                  ((0, 2), (45, 49), (92, 94)),
                  ((0, 1, -11, -1, 1), (1, 7, 3, 45, 1), (7, 13, 50, 92, 1))),
    "ean8": Kind("EAN-8", "8 digits, with the check digit", 8, "ean8", (7, 7), 3,
                 ((0, 2), (31, 35), (64, 66)),
                 ((0, 4, 3, 31, 1), (4, 8, 36, 64, 1))),
    # UPC-A's first and last digits print smaller, outside the bars, and their
    # own bars run long like the guards
    "upca": Kind("UPC-A", "12 digits, with the check digit", 12, "upca", (9, 9), 3,
                 ((0, 9), (45, 49), (85, 94)),
                 ((0, 1, -9, -1, 0.75), (1, 6, 10, 45, 1), (6, 11, 50, 85, 1), (11, 12, 96, 104, 0.75))),
    # python-barcode draws narrow bars 2 modules wide, so 20 modules is 10 narrow bars
    "itf14": Kind("ITF-14", "14 digits, with the check digit (outer cartons)", 14, "itf", (20, 20), 2,
                  bearers=True),
}


def check_digit(digits):
    """The GS1 check digit for the digits before it (EAN, UPC, ITF-14)."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return str((10 - total % 10) % 10)


@dataclass
class Code:
    kind: Kind
    modules: str              # "1" for a bar module, "0" for a space
    text: str                 # the human-readable line


def encode(kind_id, data):
    """A Code for the data, or BarcodeError with the reason."""
    kind = KINDS.get(kind_id)
    if kind is None:
        raise BarcodeError(f"unknown barcode type “{kind_id}”")
    if not kind.digits:
        try:
            return Code(kind, pybarcode.get(kind_id, data).build()[0], data)
        except Exception as e:   # python-barcode raises several kinds for data it can't take
            raise BarcodeError(str(e)) from None
    # Spaces and hyphens go, as printed: 978-3-16-148410-0. Digits typed in
    # another script (full-width １２３, Arabic-Indic ١٢٣) are the same numbers,
    # so they become 0-9. Characters that only look like digits, such as ², are
    # refused below: isdecimal() is false for them, where isdigit() is true.
    digits = "".join(str(int(c)) if c.isdecimal() else c for c in data if c not in " -")
    if not digits.isdecimal():
        raise BarcodeError(f"{kind.name} takes digits only")
    if len(digits) != kind.digits:
        msg = f"{kind.name} needs {kind.digits} digits, with the check digit; this has {len(digits)}"
        if len(digits) < kind.digits:
            msg += ". If it came from a spreadsheet, a leading zero may have been dropped"
        raise BarcodeError(msg)
    want = check_digit(digits[:-1])
    if digits[-1] != want:
        raise BarcodeError(f"the check digit of {digits} should be {want}, not {digits[-1]}")
    # python-barcode works out EAN and UPC check digits itself, from the digits
    # before; ITF takes them all as given
    given = digits if kind_id == "itf14" else digits[:-1]
    return Code(kind, pybarcode.get(kind.lib, given).build()[0], digits)
