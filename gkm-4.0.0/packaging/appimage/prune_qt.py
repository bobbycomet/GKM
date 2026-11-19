#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Trim the PyQt6 wheel to what GKM imports (QtCore/QtGui/QtWidgets) plus the
plugins a desktop needs; Qt libraries are kept by dependency closure."""
import os
import re
import shutil
import subprocess
import sys

site = sys.argv[1]
pq = os.path.join(site, "PyQt6")
qt = os.path.join(pq, "Qt6")
KEEP_MODULES = {"QtCore", "QtGui", "QtWidgets"}
KEEP_PLUGINS = {
    "platforms": {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"},
    "platformthemes": None, "xcbglintegrations": None, "wayland-decoration-client": None,
    "wayland-graphics-integration-client": None, "wayland-shell-integration": None,
    "platforminputcontexts": None, "iconengines": None,
    "imageformats": {"libqgif.so", "libqico.so", "libqjpeg.so", "libqsvg.so"},
}


def needed(path):
    out = subprocess.run(["objdump", "-p", path], capture_output=True, text=True).stdout
    return re.findall(r"NEEDED\s+(\S+)", out)


# 1. python extension modules / stubs / bindings
for f in os.listdir(pq):
    m = re.match(r"(Qt\w+)\.(abi3\.so|pyi)$", f)
    if m and m.group(1) not in KEEP_MODULES:
        os.remove(os.path.join(pq, f))
for d in ("bindings", "uic", "lupdate"):
    shutil.rmtree(os.path.join(pq, d), ignore_errors=True)

# 2. plugins
pdir = os.path.join(qt, "plugins")
for d in os.listdir(pdir):
    keep = KEEP_PLUGINS.get(d, set())
    full = os.path.join(pdir, d)
    if d not in KEEP_PLUGINS:
        shutil.rmtree(full)
    elif keep is not None:
        for f in os.listdir(full):
            if f not in keep:
                os.remove(os.path.join(full, f))

# 3. other Qt payload we never use
for d in ("qml", "translations", "libexec", "metatypes", "modules", "resources", "lib/cmake"):
    shutil.rmtree(os.path.join(qt, d), ignore_errors=True)

# 4. libraries: closure of what the kept binaries need
libdir = os.path.join(qt, "lib")
have = {f: os.path.join(libdir, f) for f in os.listdir(libdir)}
queue = [os.path.join(pq, f) for f in os.listdir(pq) if f.endswith(".abi3.so")]
for dp, _dn, fn in os.walk(pdir):
    queue += [os.path.join(dp, f) for f in fn if f.endswith(".so")]
keep = set()
while queue:
    cur = queue.pop()
    for n in needed(cur):
        if n in have and n not in keep:
            keep.add(n)
            queue.append(os.path.realpath(have[n]))
removed = 0
for f, p in have.items():
    if f not in keep and not os.path.isdir(p):
        # keep real files that kept names are symlinks to
        if any(os.path.realpath(have[k]) == os.path.realpath(p) for k in keep):
            continue
        os.remove(p)
        removed += 1
print(f"pruned Qt: kept {len(keep)} libs, removed {removed}")
