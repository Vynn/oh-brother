"""Reference files: images and print jobs that tests compare output against.

They live in tests/reference/. After an intended change to what's drawn or
sent to the printer, rewrite them with:  UPDATE_REFERENCES=1 sh test.sh
and look at the new images before committing them.
"""

import gzip
import os
import tempfile

from PIL import Image

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference")
UPDATE = os.environ.get("UPDATE_REFERENCES") == "1"
FAILED = os.path.join(tempfile.gettempdir(), "oh-brother-tests")   # this run's output, when it differs


def _missing(test, name):
    test.fail(f"No reference file {name}. Make one with:  UPDATE_REFERENCES=1 sh test.sh")


def check_image(test, name, img):
    """Compare an RGB image with tests/reference/<name>.png, pixel for pixel."""
    path = os.path.join(FOLDER, name + ".png")
    if UPDATE:
        os.makedirs(FOLDER, exist_ok=True)
        img.save(path, optimize=True)
        return
    if not os.path.exists(path):
        _missing(test, name + ".png")
    with Image.open(path) as ref:
        same = ref.size == img.size and ref.convert("RGB").tobytes() == img.tobytes()
    if not same:
        os.makedirs(FAILED, exist_ok=True)
        img.save(os.path.join(FAILED, name + ".png"))
        test.fail(f"{name}.png differs from its reference. This run's image: {FAILED}/{name}.png")


def check_bytes(test, name, data):
    """Compare bytes with tests/reference/<name>.bin.gz (stored compressed)."""
    path = os.path.join(FOLDER, name + ".bin.gz")
    if UPDATE:
        os.makedirs(FOLDER, exist_ok=True)
        with open(path, "wb") as f:
            f.write(gzip.compress(data, mtime=0))   # no timestamp, so unchanged output gives an unchanged file
        return
    if not os.path.exists(path):
        _missing(test, name + ".bin.gz")
    with gzip.open(path) as f:
        ref = f.read()
    if ref != data:
        os.makedirs(FAILED, exist_ok=True)
        with open(os.path.join(FAILED, name + ".bin"), "wb") as f:
            f.write(data)
        first = next(i for i, (a, b) in enumerate(zip(ref + b"\0", data + b"\1")) if a != b)
        test.fail(f"{name} differs from its reference from byte {first} "
                  f"({len(data)} bytes, reference {len(ref)}). This run's output: {FAILED}/{name}.bin")
