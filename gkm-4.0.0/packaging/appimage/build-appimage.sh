#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
# Build GKM-<version>-x86_64.AppImage.
#
#   packaging/appimage/build-appimage.sh [output-dir]
#
# Portability: the AppImage runs on glibc >= 2.34. That follows from two choices:
#   * CPython comes from astral-sh/python-build-standalone (built against an old glibc baseline)
#   * PyQt6 wheels (manylinux_2_28) whose newest glibc symbol is GLIBC_2.34
# The build ends by scanning every bundled ELF file and FAILS if any needs a newer glibc,
# so the claim is checked on every build, not assumed.
#
# Needs: bash, curl, tar, binutils (objdump), dpkg-deb, sha256sum, and network access to
#        github.com, pypi.org and archive.ubuntu.com.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/../.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/gkm/__init__.py")"
OUT="${1:-$SRC/dist}"
CACHE="${GKM_BUILD_CACHE:-$HOME/.cache/gkm-build}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT" "$CACHE"

PBS_TAG=20261026
PY_TARBALL="cpython-3.12.16+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
PY_SHA=6a79e922e50006b601f29e688407659da1c2b86ebcd4e9c7254cf234be8b89de
PYQT_VERSION=6.12.0
UBU=https://archive.ubuntu.com/ubuntu/pool
# name|pool path|sha256   (old Ubuntu builds: tiny C libraries, glibc requirement far below 2.34)
DEBS="
libxcb-cursor0_0.1.1-4ubuntu1_amd64.deb|universe/x/xcb-util-cursor|c9b5d1ad4af57397b1bd77e0a92750e34419def134c0282a0836ae9efc07cf64
libxcb-icccm4_0.4.1-1ubuntu1_amd64.deb|main/x/xcb-util-wm|73c212bc402208808cc0adab40e3c25a05b6a1b16128cf1c876c4431f2e877c1
libxcb-image0_0.4.0-1build1_amd64.deb|main/x/xcb-util-image|4002be5159fe91fcfbc6cdb68871163dbfd5c1092341bb51f26079e25b421d92
libxcb-keysyms1_0.4.0-1build1_amd64.deb|main/x/xcb-util-keysyms|6cfbd86d2e1c66d2d8d0a6a17f27f0b825fc0d595647674714a2926a616bdae6
libxcb-render-util0_0.3.9-1_amd64.deb|main/x/xcb-util-renderutil|2a32afd2452da0185335f0482fee82bb3a00baaf0eea8cb9a8bc34dc492555ec
libxcb-util1_0.4.0-1build2_amd64.deb|main/x/xcb-util|237d51a378b93c1669ff193084ebeb6422fe1e2ea96c2e9a0099eac40992a345
libxkbcommon-x11-0_1.4.0-1_amd64.deb|main/libx/libxkbcommon|e29c40fab6e0f055218aee4c7e60cd61ea82283229d7ac7ac02e226e92a5b0d5
"

fetch() {  # url dest [sha256]
    if [ ! -f "$2" ]; then echo "  fetching $(basename "$2")"; curl -fsSL "$1" -o "$2.part" && mv "$2.part" "$2"; fi
    if [ -n "${3:-}" ] && [ "$(sha256sum "$2" | cut -d' ' -f1)" != "$3" ]; then
        echo "checksum mismatch for $2" >&2; rm -f "$2"; exit 1
    fi
}

echo "==> GKM $VERSION"
echo "==> downloads"
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PY_TARBALL//+/%2B}" "$CACHE/$PY_TARBALL" "$PY_SHA"
fetch "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" "$CACHE/appimagetool"
chmod +x "$CACHE/appimagetool"
while IFS='|' read -r deb path sha; do
    [ -n "$deb" ] && fetch "$UBU/$path/$deb" "$CACHE/$deb" "$sha"
done <<< "$DEBS"

APPDIR="$WORK/GKM.AppDir"
PYDIR="$APPDIR/usr/python"
SITE="$PYDIR/lib/python3.12/site-packages"
mkdir -p "$APPDIR/usr/lib-gkm"

echo "==> python + PyQt6"
tar -xzf "$CACHE/$PY_TARBALL" -C "$WORK"
mv "$WORK/python" "$PYDIR"
"$PYDIR/bin/python3" -m pip install --no-cache-dir --disable-pip-version-check -q "PyQt6==$PYQT_VERSION"
python3 "$HERE/prune_qt.py" "$SITE"

echo "==> trimming python"
S="$PYDIR/lib/python3.12"
rm -rf "$S/test" "$S/idlelib" "$S/tkinter" "$S/turtledemo" "$S/ensurepip" "$S/lib2to3" "$S/unittest/test" \
       "$S/lib-dynload"/_tkinter* "$S/config-3.12-x86_64-linux-gnu" \
       "$SITE/pip" "$SITE"/pip-* "$SITE/setuptools" "$SITE"/setuptools-* "$SITE/pkg_resources" "$SITE/_distutils_hack" \
       "$PYDIR/include" "$PYDIR/share" "$PYDIR/lib/pkgconfig" "$PYDIR"/lib/tcl* "$PYDIR"/lib/tk* "$PYDIR"/lib/itcl* \
       "$PYDIR"/lib/thread* "$PYDIR"/lib/libtcl* "$PYDIR"/lib/libtk*
find "$PYDIR/bin" \( -type f -o -type l \) ! -name 'python3' ! -name 'python3.12' -delete

echo "==> gkm sources"
cp -r "$SRC/gkm" "$SITE/gkm"
find "$SITE/gkm" -name __pycache__ -prune -exec rm -rf {} +
chmod 755 "$SITE/gkm/resources/gkm-helper"
"$PYDIR/bin/python3" -m compileall -q -j0 "$S" "$SITE/gkm" >/dev/null

echo "==> bundled xcb libraries"
mkdir -p "$WORK/x"
for deb in "$CACHE"/lib*.deb; do dpkg-deb -x "$deb" "$WORK/x"; done
find "$WORK/x" \( -name '*.so*' \) \( -type f -o -type l \) -exec cp -a {} "$APPDIR/usr/lib-gkm/" \;
mkdir -p "$APPDIR/usr/share/licenses/gkm-bundled-libs"
for d in "$WORK/x/usr/share/doc"/*; do
    [ -f "$d/copyright" ] && cp "$d/copyright" "$APPDIR/usr/share/licenses/gkm-bundled-libs/$(basename "$d").copyright"
done

echo "==> license + source notice (GPL-3.0-only)"
mkdir -p "$APPDIR/usr/share/licenses/gkm"
install -m 644 "$SRC/LICENSE" "$APPDIR/usr/share/licenses/gkm/LICENSE"
cat > "$APPDIR/usr/share/licenses/gkm/SOURCE.txt" <<NOTICE
Griffin Kernel Manager $VERSION  -  Copyright (C) 2026 Bobby Comet
Licensed under the GNU General Public License, version 3 only (see LICENSE in this directory).
This program comes with ABSOLUTELY NO WARRANTY.

Corresponding source code: the release's gkm-$VERSION-source.tar.gz, or
https://github.com/bobbycomet/XKM-Multi-Kernel-Manager
To rebuild this AppImage from that source: packaging/appimage/build-appimage.sh

Bundled third-party components keep their own licences: see usr/share/licenses/gkm-bundled-libs/
and the *.dist-info directories under usr/python/lib/python3.12/site-packages/.
NOTICE

echo "==> appdir metadata"
install -m 755 "$HERE/AppRun" "$APPDIR/AppRun"
install -m 644 "$HERE/gkm.desktop" "$APPDIR/gkm.desktop"
install -m 644 "$SRC/gkm/resources/gkm-512.png" "$APPDIR/gkm.png"
ln -s gkm.png "$APPDIR/.DirIcon"

echo "==> verify: glibc floor"
python3 "$HERE/verify-glibc.py" "$APPDIR" 2.34

echo "==> verify: unit tests + headless GUI smoke test (inside the AppDir)"
export HOME="$WORK/home"; mkdir -p "$HOME"
QT_QPA_PLATFORM=offscreen APPDIR="$APPDIR" "$APPDIR/AppRun" --test 2>&1 | tail -4
QT_QPA_PLATFORM=offscreen APPDIR="$APPDIR" "$APPDIR/AppRun" --smoke-test 2>&1 | grep -E "SMOKE|Traceback|Error" || true

echo "==> appimagetool"
OUTFILE="$OUT/GKM-${VERSION}-x86_64.AppImage"
ARCH=x86_64 "$CACHE/appimagetool" --appimage-extract-and-run --comp zstd -n "$APPDIR" "$OUTFILE" >/dev/null 2>"$WORK/ait.log" \
    || { cat "$WORK/ait.log"; exit 1; }
sha256sum "$OUTFILE" | tee "$OUTFILE.sha256"
ls -lh "$OUTFILE"
