#!/bin/sh
# Run the server-side tests with the bundled Python:  sh test.sh
# Options go to unittest, e.g.  sh test.sh -v   or   sh test.sh -k cut

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)               PLAT=linux-x86_64 ;;
    Linux-aarch64|Linux-arm64)  PLAT=linux-aarch64 ;;
    Darwin-arm64)               PLAT=macos-arm64 ;;
    Darwin-x86_64)              PLAT=macos-x86_64 ;;
    *) echo "Unsupported system: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

# The bundled runtime, or the copy run.sh makes when the drive can't run programs
PY="$HERE/runtime/$PLAT/python/bin/python3"
if ! "$PY" -c "" 2>/dev/null; then
    PY="${XDG_CACHE_HOME:-$HOME/.cache}/oh-brother/$PLAT/python/bin/python3"
fi
if ! "$PY" -c "" 2>/dev/null || [ ! -d "$HERE/vendor/$PLAT" ]; then
    echo "No runtime for $PLAT. Run:  sh build.sh $PLAT" >&2
    exit 1
fi

cd "$HERE"
exec "$PY" -I -B -m unittest discover -s tests -t . "$@"
