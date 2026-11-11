#!/bin/sh
# Oh-Brother build script.
# Populates the portable folder: a standalone CPython runtime per platform,
# and vendored Python packages. Fonts are kept in the repo (app/fonts). Needs network access.
#
# Usage:  sh build.sh                 # build for the current machine
#         sh build.sh macos-arm64 ... # add runtimes for other platforms
#         sh build.sh --newest        # the newest packages, not the pinned ones
#
# Platforms: linux-x86_64 linux-aarch64 macos-arm64 macos-x86_64
# Only the host platform is tested; others are downloaded the same way.
#
# Everything downloaded is checked against a SHA-256 kept in this repository:
# the runtime's below, each package's in the requirements files. A download
# that doesn't match stops the build. Each folder is built beside the one it
# replaces and swapped in once complete, so a build that fails, or runs with
# no network, leaves the last working one in place.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)

# --newest installs the newest version of every package, for the monthly
# check in .github/workflows/upstream.yml. Those have no checksums to match.
NEWEST=""
if [ "${1:-}" = "--newest" ]; then
    NEWEST=1
    shift
fi

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

# platform -> SHA-256 of its runtime archive, from the SHA256SUMS file of the
# release. Change these together with PBS_TAG and PY_VER.
pbs_sha256() {
    case "$1" in
        linux-x86_64)  echo df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7 ;;
        linux-aarch64) echo 578d9da1983463ffb0c8c98ab0da2f18177f44069328eb0af847860c1eb05c3e ;;
        macos-arm64)   echo 8392b6ea51d94391befb2c31ebe75463f045d0b69dfcf5e1bb3234e1f5fa3405 ;;
        macos-x86_64)  echo 7412c19d896c99431b74a18a5643e110449a7f9590fbab179c3e5ab27b9aa9e3 ;;
    esac
}

# Linux has sha256sum, macOS has shasum
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
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
    # Downloaded whole and checked before any of it is unpacked
    new="$dest.new"
    rm -rf "$new"
    mkdir -p "$new"
    curl -fL --progress-bar -o "$new/$file" "$PBS_BASE/$file" || { rm -rf "$new"; exit 1; }
    want=$(pbs_sha256 "$plat")
    got=$(sha256_of "$new/$file")
    if [ "$got" != "$want" ]; then
        echo "runtime/$plat: $file doesn't match its checksum, so it isn't used" >&2
        echo "  expected $want" >&2
        echo "  received $got" >&2
        rm -rf "$new"
        exit 1
    fi
    tar -xzf "$new/$file" -C "$new"
    rm "$new/$file"
    echo "$PBS_TAG-$PY_VER" > "$new/STAMP"
    swap_in "$new" "$dest"
}

# Put a finished folder in the place of the one it replaces
swap_in() {
    rm -rf "$2"
    mv "$1" "$2"
}

# pip install, with every package checked against its SHA-256 unless --newest
pip_install() {
    if [ -n "$NEWEST" ]; then
        "$HOSTPY" -m pip install --quiet --disable-pip-version-check "$@"
    else
        # --require-hashes refuses a package with no checksum listed, where pip
        # alone would only check those that have one. --build-constraint does
        # the same for what pip fetches to build a source-only package.
        "$HOSTPY" -m pip install --quiet --disable-pip-version-check \
            --require-hashes --build-constraint "$HERE/requirements-build.txt" "$@"
    fi
}

HOST=$(host_platform)
TARGETS=${*:-$HOST}
# The host runtime is always needed: its pip installs packages for every target.
fetch_runtime "$HOST"
HOSTPY="$HERE/runtime/$HOST/python/bin/python3"

# The requirements files as they are, or for --newest, copies with the
# versions and checksums taken out
REQS="$HERE"
if [ -n "$NEWEST" ]; then
    REQS=$(mktemp -d)
    trap 'rm -rf "$REQS"' EXIT
    for f in requirements.txt requirements-binary.txt; do
        sed -E -e '/^ *--hash=/d' -e 's/==.*$//' "$HERE/$f" > "$REQS/$f"
    done
fi

# Pure-Python packages are shared by all platforms (vendor/common).
# Pillow is compiled, so it is installed per platform (vendor/<platform>).
echo "vendor/common: installing packages"
rm -rf "$HERE/vendor/common.new"
pip_install --target "$HERE/vendor/common.new" -r "$REQS/requirements.txt" -c "$REQS/requirements-binary.txt"
( cd "$HERE/vendor/common.new" && rm -rf PIL [Pp]illow* bin docs tests __pycache__ )
swap_in "$HERE/vendor/common.new" "$HERE/vendor/common"

for plat in $TARGETS; do
    [ "$plat" = "$HOST" ] || fetch_runtime "$plat"
    echo "vendor/$plat: installing Pillow"
    rm -rf "$HERE/vendor/$plat.new"
    platargs=""
    for t in $(pip_tags "$plat"); do platargs="$platargs --platform $t"; done
    # shellcheck disable=SC2086
    pip_install --target "$HERE/vendor/$plat.new" --only-binary=:all: \
        --implementation cp --python-version "$PY_MINOR" $platargs \
        -r "$REQS/requirements-binary.txt"
    swap_in "$HERE/vendor/$plat.new" "$HERE/vendor/$plat"
done

mkdir -p "$HERE/data/templates"
echo "done: $(du -sh "$HERE/runtime" "$HERE/vendor" | tr '\n' ' ')"
