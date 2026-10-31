"""Server-side tests, using only unittest. Run them with:  sh test.sh

Like main.py, this sets up sys.path itself, since the tests run under
python -I: the app folder, then vendor/<platform>, then vendor/common.
"""

import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The same platform names as run.sh
PLATFORMS = {
    ("Linux", "x86_64"): "linux-x86_64",
    ("Linux", "aarch64"): "linux-aarch64",
    ("Linux", "arm64"): "linux-aarch64",
    ("Darwin", "arm64"): "macos-arm64",
    ("Darwin", "x86_64"): "macos-x86_64",
}
PLATFORM = PLATFORMS.get((platform.system(), platform.machine()))
if not PLATFORM:
    raise SystemExit(f"Unsupported system: {platform.system()}-{platform.machine()}")

sys.path[:0] = [os.path.join(ROOT, "app"),
                os.path.join(ROOT, "vendor", PLATFORM),
                os.path.join(ROOT, "vendor", "common")]
