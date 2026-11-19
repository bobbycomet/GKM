#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Scan every ELF under a directory and report the highest GLIBC_x.y symbol version required."""
import os, re, subprocess, sys
root = sys.argv[1]
limit = tuple(int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "2.34").split("."))
worst = {}
nfiles = 0
for dp, dn, fn in os.walk(root):
    for f in fn:
        p = os.path.join(dp, f)
        if os.path.islink(p) or not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as fh:
                if fh.read(4) != b"\x7fELF":
                    continue
        except OSError:
            continue
        nfiles += 1
        out = subprocess.run(["objdump", "-T", p], capture_output=True, text=True).stdout
        mx = (0, 0)
        for m in re.finditer(r"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?", out):
            v = (int(m.group(1)), int(m.group(2)))
            mx = max(mx, v)
        if mx > (0, 0):
            worst[p] = mx
bad = {p: v for p, v in worst.items() if v > limit}
top = sorted(worst.items(), key=lambda kv: kv[1], reverse=True)[:5]
print(f"ELF files scanned: {nfiles}; with glibc deps: {len(worst)}")
print("highest requirements:")
for p, v in top:
    print(f"  GLIBC_{v[0]}.{v[1]}  {os.path.relpath(p, root)}")
print(f"files exceeding GLIBC_{limit[0]}.{limit[1]}: {len(bad)}")
for p, v in sorted(bad.items()):
    print(f"  !! GLIBC_{v[0]}.{v[1]}  {os.path.relpath(p, root)}")
sys.exit(1 if bad else 0)
