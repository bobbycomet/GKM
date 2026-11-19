# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""zypper backend: openSUSE Tumbleweed / Leap / Slowroll and SUSE Linux Enterprise.

openSUSE keeps several kernel-<flavor> builds installed side by side
(multiversion), so rows are specific builds and the helper gets NAME=EVR."""
import re
import xml.etree.ElementTree as ET
from functools import cmp_to_key

from ..hostenv import run_host
from ..model import KernelPackage, Provider, VersionOption
from ..vercmp import evr_vercmp
from .base import Backend, fmt_bytes
from .rpm_common import (PART_LABEL, PART_ORDER, evr_of, locked_names_zypper, rpm_installed,
                         running_owner, split_part)

ALLOWED_PARTS = {"base", "devel", "extra", "optional"}
_FLAVORS = {"default": "Default", "preempt": "Preempt", "rt": "Real-Time", "vanilla": "Vanilla",
            "kvmsmall": "KVM small", "azure": "Azure", "64kb": "64k pages",
            "longterm": "Longterm", "stable": "Stable"}
_BASE_RE = re.compile(r"^kernel-(?:default|preempt|rt|vanilla|kvmsmall|azure|64kb|longterm|stable)$")
_REPO_TAGS = (("kernel_stable", "Kernel:stable"), ("kernel:stable", "Kernel:stable"),
              ("kernel_head", "Kernel:HEAD"), ("kernel:head", "Kernel:HEAD"),
              ("kernel_longterm", "Kernel:longterm"), ("kernel:longterm", "Kernel:longterm"))


def kernel_base(name):
    base, part = split_part(name, ALLOWED_PARTS)
    return (base, part) if _BASE_RE.match(base) else None


def repo_tag(alias):
    a = (alias or "").lower()
    for needle, label in _REPO_TAGS:
        if needle in a:
            return label
    return ""


class ZypperBackend(Backend):
    family = "suse"
    pm_name = "zypper"
    pm_binary = "zypper"
    supports_purge = False
    supports_multiversion = True
    has_versions = True

    def version_scope(self, row, all_rows):
        return [r for r in all_rows if r.provider == row.provider and r.flavor == row.flavor]

    def list_versions(self, scope):
        """Every edition of the group's packages that the repositories offer (multiversion kernels install side by side)."""
        names = sorted({r.name for r in scope})
        if not names:
            return [], []
        rc, out = run_host(["zypper", "--xmlout", "--non-interactive", "--no-refresh", "search", "--details",
                            "--type", "package", "--match-exact"] + names, timeout=120)
        avail = {n: set() for n in names}
        try:
            root = ET.fromstring(out[out.index("<"):]) if "<" in out else None
        except ET.ParseError:
            root = None
        if root is not None:
            for sol in root.iter("solvable"):
                n, repo = sol.get("name", ""), sol.get("repository", "")
                if n in avail and not repo.startswith("@") and sol.get("arch") in (self.hw.arch, "noarch"):
                    avail[n].add(sol.get("edition", ""))
        notes = [] if root is not None else ["Could not read zypper repository data. Try Refresh first."]
        installed = {}
        for r in scope:
            if r.installed:
                installed.setdefault(r.name, set()).add(r.version)
        everywhere = set.intersection(*avail.values()) - {""}
        built = set.intersection(*[installed.get(n, set()) for n in names])
        options = [VersionOption(version=v, sources=(["installed"] if v in built else []) + (["repo"] if v in everywhere else []),
                                 installed=v in built, specs=[f"{n}={v}" for n in names])
                   for v in sorted(everywhere | built, key=cmp_to_key(evr_vercmp), reverse=True)[:40]]
        if len(options) <= 1:
            notes.append("Only the current build is offered by your repositories.")
        return options, notes

    def providers(self):
        return [Provider("opensuse", "openSUSE", hint=(
            "openSUSE kernels. Default is the standard kernel; Preempt and Real-Time trade throughput for "
            "latency. Several builds can stay installed side by side; purge-kernels trims old ones."))]

    def version_cmp(self, a, b):
        return evr_vercmp(a, b)

    def _available(self):
        rc, out = run_host(["zypper", "--xmlout", "--non-interactive", "--no-refresh", "search",
                            "--details", "--type", "package", "kernel-*"], timeout=120)
        latest = {}
        try:
            root = ET.fromstring(out[out.index("<"):]) if "<" in out else None
        except ET.ParseError:
            root = None
        if root is None:
            self.warnings.append("Could not read zypper repository data. Installed kernels are shown; "
                                 "click Refresh to retry.")
            return []
        for s in root.iter("solvable"):
            name, edition, arch = s.get("name", ""), s.get("edition", ""), s.get("arch", "")
            repo = s.get("repository", "")
            if repo.startswith("@") or s.get("status") == "installed":
                continue
            if arch not in (self.hw.arch, "noarch") or not kernel_base(name):
                continue
            cur = latest.get(name)
            if cur is None or evr_vercmp(edition, cur[0]) > 0:
                latest[name] = (edition, repo)
        return [(n, e, r) for n, (e, r) in latest.items()]

    def collect(self, refresh=False):
        self.warnings = []
        locked = locked_names_zypper()
        active = running_owner(self.running_release(), ALLOWED_PARTS)
        rows, seen = [], set()

        def make(name, evr, size, installed, repo=""):
            kb = kernel_base(name)
            if not kb:
                return None
            base, part = kb
            flavor = _FLAVORS.get(base[len("kernel-"):], base[len("kernel-"):].title())
            tag = repo_tag(repo)
            return KernelPackage(
                name=name, version=evr, provider="opensuse", installed=installed,
                active=installed and (base, evr) in active, held=installed and name in locked,
                size=fmt_bytes(size) if size else "—", kgroup=evr, group_label=evr + (f" · {tag}" if tag else ""),
                flavor=flavor, role=PART_LABEL.get(part, part), repo=repo, spec=f"{name}={evr}")

        for ir in rpm_installed("kernel-*"):
            r = make(ir["name"], evr_of(ir), ir["size"], True)
            if r:
                rows.append(r)
                seen.add((r.name, r.version))
        for name, evr, repo in self._available():
            if (name, evr) not in seen:
                r = make(name, evr, 0, False, repo)
                if r:
                    rows.append(r)
        order = {label: i for i, label in enumerate(PART_LABEL[p] for p in PART_ORDER)}
        rows.sort(key=lambda r: (r.flavor, order.get(r.role, 9), r.name))
        return rows
