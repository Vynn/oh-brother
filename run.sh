#!/bin/sh
# Oh-Brother launcher. Start with:  sh run.sh   (works even without exec bits)
# Extra options are passed through, e.g.  sh run.sh --lan --no-browser
#
# Uses the bundled Python in runtime/<platform>. If the drive does not allow
# running programs (FAT32/exFAT are often mounted that way), the runtime is
# copied once to ~/.cache/oh-brother and run from there. Data stays here.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)               PLAT=linux-x86_64 ;;
    Linux-aarch64|Linux-arm64)  PLAT=linux-aarch64 ;;
    Darwin-arm64)               PLAT=macos-arm64 ;;
    Darwin-x86_64)              PLAT=macos-x86_64 ;;
    *) echo "Unsupported system: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

RT="$HERE/runtime/$PLAT"
if [ ! -d "$RT/python" ] || [ ! -d "$HERE/vendor/$PLAT" ]; then
    echo "No runtime for $PLAT in this folder. Run:  sh build.sh $PLAT" >&2
    exit 1
fi

PY="$RT/python/bin/python3"
if ! "$PY" -c "" 2>/dev/null; then
    CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/oh-brother/$PLAT"
    if [ "$(cat "$CACHE/STAMP" 2>/dev/null)" != "$(cat "$RT/STAMP")" ]; then
        echo "Drive does not allow running programs; copying runtime to $CACHE (one time)…"
        rm -rf "$CACHE"
        mkdir -p "$CACHE"
        cp -R "$RT/python" "$CACHE/"
        chmod -R u+rwX "$CACHE/python"
        chmod u+x "$CACHE/python/bin/"*
        cp "$RT/STAMP" "$CACHE/STAMP"
    fi
    PY="$CACHE/python/bin/python3"
fi

# -I: isolated mode (ignore host PYTHONPATH, user site-packages, etc.)
# -B: don't write .pyc files onto the drive
exec "$PY" -I -B "$HERE/app/main.py" --platform "$PLAT" --data "$HERE/data" "$@"
