# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Shared helpers for the RPM families (Fedora/RHEL -> dnf, openSUSE -> zypper)."""
import re

from ..hostenv import run_host

PARTS = ["modules-internal", "modules-extra", "modules-core", "devel-matched", "uki-virt",
         "modules", "devel", "core", "base", "extra", "optional"]
PART_LABEL = {"": "Meta", "core": "Core", "modules-core": "Modules Core", "modules": "Modules",
              "modules-extra": "Modules Extra", "devel": "Devel", "devel-matched": "Devel (matched)",
              "base": "Base", "extra": "Extra", "optional": "Optional"}
PART_ORDER = ["", "core", "base", "modules-core", "modules", "modules-extra", "extra", "optional",
              "devel", "devel-matched"]


def split_part(name, allowed_parts):
    """'kernel-cachyos-lto-devel-matched' -> ('kernel-cachyos-lto', 'devel-matched')."""
    for part in PARTS:
        if part in allowed_parts and name.endswith("-" + part):
            return name[: -len(part) - 1], part
    return name, ""


def rpm_installed(glob):
    """Installed packages matching a name glob -> list of dicts. Real rpm query,
    so every installed version of an install-only kernel is listed."""
    rc, out = run_host(["rpm", "-qa", "--qf",
                        "%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SIZE}\n", glob])
    rows = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) == 6:
            rows.append({"name": p[0], "epoch": p[1], "version": p[2], "release": p[3],
                         "arch": p[4], "size": int(p[5]) if p[5].isdigit() else 0})
    return rows


def evr_of(r):
    return f"{r['version']}-{r['release']}"


def running_owner(release, allowed_parts):
    """(base, evr) pairs for the package(s) owning the running kernel's module dir."""
    found = set()
    for path in (f"/usr/lib/modules/{release}", f"/lib/modules/{release}"):
        rc, out = run_host(["rpm", "-qf", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\n", path])
        if rc == 0:
            for line in out.splitlines():
                p = line.split("\t")
                if len(p) == 2:
                    found.add((split_part(p[0], allowed_parts)[0], p[1]))
            if found:
                break
    return found


def locked_names_dnf():
    """Names locked via dnf versionlock (dnf4 list file and dnf5 toml)."""
    names = set()
    try:
        for line in open("/etc/dnf/plugins/versionlock.list", errors="replace"):
            m = re.match(r"^([A-Za-z0-9+._-]+?)-\d+:", line.strip())
            if m:
                names.add(m.group(1))
    except OSError:
        pass
    try:
        text = open("/etc/dnf/versionlock.toml", errors="replace").read()
        names.update(re.findall(r'(?m)^\s*name\s*=\s*"([^"]+)"', text))
    except OSError:
        pass
    return names


def locked_names_zypper():
    names = set()
    try:
        for line in open("/etc/zypp/locks", errors="replace"):
            m = re.match(r"^\s*solvable_name:\s*(\S+)", line)
            if m:
                names.add(m.group(1))
    except OSError:
        pass
    return names
