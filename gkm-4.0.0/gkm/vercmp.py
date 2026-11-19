# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Pure-Python version comparison for the three package-version schemes GKM
meets (python-apt is deliberately not used: it cannot be bundled)."""
import re


# ── Debian (dpkg) ────────────────────────────────────────────────────────────

def _deb_order(c):
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256


def _deb_verrevcmp(a, b):
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _deb_order(a[i]) if i < len(a) else 0
            bc = _deb_order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def _deb_split(v):
    v = (v or "0").strip()
    epoch = 0
    if ":" in v:
        e, v = v.split(":", 1)
        epoch = int(e) if e.isdigit() else 0
    if "-" in v:
        upstream, rev = v.rsplit("-", 1)
    else:
        upstream, rev = v, ""
    return epoch, upstream, rev


def deb_vercmp(a, b):
    ea, ua, ra = _deb_split(a)
    eb, ub, rb = _deb_split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    for x, y in ((ua, ub), (ra, rb)):
        r = _deb_verrevcmp(x, y)
        if r:
            return -1 if r < 0 else 1
    return 0


# ── RPM / pacman (rpmvercmp) ─────────────────────────────────────────────────

def rpmvercmp(a, b):
    if a == b:
        return 0
    i = j = 0
    la, lb = len(a), len(b)

    def skip(s, k, n):
        while k < n and not s[k].isalnum() and s[k] not in "~^":
            k += 1
        return k

    while i < la or j < lb:
        i = skip(a, i, la)
        j = skip(b, j, lb)
        ta = i < la and a[i] == "~"
        tb = j < lb and b[j] == "~"
        if ta or tb:
            if not ta:
                return 1
            if not tb:
                return -1
            i += 1
            j += 1
            continue
        ca = i < la and a[i] == "^"
        cb = j < lb and b[j] == "^"
        if ca or cb:
            if i >= la:
                return -1
            if j >= lb:
                return 1
            if not ca:
                return 1
            if not cb:
                return -1
            i += 1
            j += 1
            continue
        if not (i < la and j < lb):
            break
        si, sj = i, j
        if a[i].isdigit():
            while i < la and a[i].isdigit():
                i += 1
            while j < lb and b[j].isdigit():
                j += 1
            isnum = True
        else:
            while i < la and a[i].isalpha():
                i += 1
            while j < lb and b[j].isalpha():
                j += 1
            isnum = False
        seg1, seg2 = a[si:i], b[sj:j]
        if not seg1:
            return -1
        if not seg2:
            return 1 if isnum else -1
        if isnum:
            seg1, seg2 = seg1.lstrip("0"), seg2.lstrip("0")
            if len(seg1) != len(seg2):
                return 1 if len(seg1) > len(seg2) else -1
        if seg1 != seg2:
            return 1 if seg1 > seg2 else -1
    if i >= la and j >= lb:
        return 0
    return 1 if i < la else -1


def _evr_split(v):
    v = (v or "0").strip()
    epoch = 0
    m = re.match(r"^(\d+):(.*)$", v)
    if m:
        epoch, v = int(m.group(1)), m.group(2)
    if "-" in v:
        ver, rel = v.rsplit("-", 1)
    else:
        ver, rel = v, ""
    return epoch, ver, rel


def evr_vercmp(a, b):
    """Compare [epoch:]version[-release] strings (rpm, zypper, pacman)."""
    ea, va, ra = _evr_split(a)
    eb, vb, rb = _evr_split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    r = rpmvercmp(va, vb)
    if r:
        return r
    if ra and rb:
        return rpmvercmp(ra, rb)
    return 0


def version_newer(remote, local):
    """True if dotted-numeric `remote` is strictly newer than `local` (used by
    the GitHub release check)."""
    def to_tuple(v):
        try:
            return tuple(int(x) for x in re.split(r"[.\-]", v) if x.isdigit())
        except Exception:
            return (0,)
    return to_tuple(remote) > to_tuple(local)
