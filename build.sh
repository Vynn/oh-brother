#!/bin/sh
# Oh-Brother build script.
# Populates the portable folder: a standalone CPython runtime per platform,
# and vendored Python packages. Fonts are kept in the repo (app/fonts). Needs network access.
#
# Usage:  sh build.sh                 # build for the current machine
#         sh build.sh macos-arm64 ... # add runtimes for other platforms
#
# Platforms: linux-x86_64 linux-aarch64 macos-arm64 macos-x86_64
# Only the host platform is tested; others are downloaded the same way.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)

# Pinned runtime: python-build-standalone (https://github.com/astral-sh/python-build-standalone)
PBS_TAG="20261026"
PY_VER="3.13.18"
PY_MINOR="3.13"
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG"

host_platform() {
    case "$(uname -s)-$(uname -m)" in
        Linux-x86_64)               echo linux-x86_64 ;;
        Linux-aarch64|Linux-arm64)  echo linux-aarch64 ;;
        Darwin-arm64)               echo macos-arm64 ;;
        Darwin-x86_64)              echo macos-x86_64 ;;
        *) echo "unsupported host: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
    esac
}

# platform -> python-build-standalone target triple
pbs_triple() {
    case "$1" in
        linux-x86_64)  echo x86_64-unknown-linux-gnu ;;
        linux-aarch64) echo aarch64-unknown-linux-gnu ;;
        macos-arm64)   echo aarch64-apple-darwin ;;
        macos-x86_64)  echo x86_64-apple-darwin ;;
        *) echo "unknown platform: $1" >&2; exit 1 ;;
    esac
}

# platform -> pip --platform tags for Pillow wheels (newest first)
pip_tags() {
    case "$1" in
        linux-x86_64)  echo "manylinux_2_28_x86_64 manylinux2014_x86_64" ;;
        linux-aarch64) echo "manylinux_2_28_aarch64 manylinux2014_aarch64" ;;
        macos-arm64)   echo "macosx_11_0_arm64" ;;
        macos-x86_64)  echo "macosx_10_13_x86_64" ;;
    esac
}

fetch_runtime() {
    plat=$1
    dest="$HERE/runtime/$plat"
    if [ -x "$dest/python/bin/python3" ] && [ "$(cat "$dest/STAMP" 2>/dev/null)" = "$PBS_TAG-$PY_VER" ]; then
        echo "runtime/$plat: up to date"
        return
    fi
    file="cpython-$PY_VER+$PBS_TAG-$(pbs_triple "$plat")-install_only_stripped.tar.gz"
    echo "runtime/$plat: downloading $file"
    rm -rf "$dest"
    mkdir -p "$dest"
    curl -fL --progress-bar "$PBS_BASE/$file" | tar -xz -C "$dest"
    echo "$PBS_TAG-$PY_VER" > "$dest/STAMP"
}

HOST=$(host_platform)
TARGETS=${*:-$HOST}
# The host runtime is always needed: its pip installs packages for every target.
fetch_runtime "$HOST"
HOSTPY="$HERE/runtime/$HOST/python/bin/python3"

# Pure-Python packages are shared by all platforms (vendor/common).
# Pillow is compiled, so it is installed per platform (vendor/<platform>).
echo "vendor/common: installing packages"
rm -rf "$HERE/vendor/common"
"$HOSTPY" -m pip install --quiet --disable-pip-version-check \
    --target "$HERE/vendor/common" -r "$HERE/requirements.txt" -c "$HERE/requirements-binary.txt"
( cd "$HERE/vendor/common" && rm -rf PIL [Pp]illow* bin docs tests __pycache__ )

for plat in $TARGETS; do
    [ "$plat" = "$HOST" ] || fetch_runtime "$plat"
    echo "vendor/$plat: installing Pillow"
    rm -rf "$HERE/vendor/$plat"
    platargs=""
    for t in $(pip_tags "$plat"); do platargs="$platargs --platform $t"; done
    # shellcheck disable=SC2086
    "$HOSTPY" -m pip install --quiet --disable-pip-version-check \
        --target "$HERE/vendor/$plat" --only-binary=:all: \
        --implementation cp --python-version "$PY_MINOR" $platargs \
        -r "$HERE/requirements-binary.txt"
done

mkdir -p "$HERE/data/templates"
echo "done: $(du -sh "$HERE/runtime" "$HERE/vendor" | tr '\n' ' ')"
