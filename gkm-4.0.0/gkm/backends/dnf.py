# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""dnf backend: Fedora, Nobara and RHEL-family (Rocky, Alma, CentOS Stream).

Kernels are install-only packages: several versions coexist, so every row is a
specific build (name + version-release) and the helper is handed NAME=EVR."""
import glob
import re
from functools import cmp_to_key

from ..hardware import level_num
from ..hostenv import run_host
from ..model import KernelPackage, Provider, RepoOffer, VersionOption
from ..vercmp import evr_vercmp
from .base import Backend, fmt_bytes, title_flavor
from .rpm_common import (PART_LABEL, PART_ORDER, evr_of, locked_names_dnf, rpm_installed,
                         running_owner, split_part)

ALLOWED_PARTS = {"core", "modules-core", "modules", "modules-extra", "devel", "devel-matched"}
_BASE_RE = re.compile(
    r"^kernel(?:-(?:rt|64k|cachyos[a-z0-9-]*|xanmod[a-z0-9-]*|longterm[a-z0-9.-]*|lts[a-z0-9-]*|lt|ml|nobara|surface))?$"
)


def kernel_base(name):
    """-> (base, part) if `name` is a kernel package we manage, else None."""
    base, part = split_part(name, ALLOWED_PARTS)
    return (base, part) if _BASE_RE.match(base) else None


def provider_for_base(base):
    if base.startswith("kernel-cachyos"):
        return "cachyos"
    if base.startswith("kernel-xanmod"):
        return "xanmod"
    if base.startswith(("kernel-longterm", "kernel-lts", "kernel-lt", "kernel-ml")) and base != "kernel-lts-x":
        return "longterm"
    return "distro"


def flavor_for_base(base):
    if base == "kernel":
        return "Standard"
    if base == "kernel-rt":
        return "Real-Time"
    if base == "kernel-64k":
        return "64k pages"
    for prefix in ("kernel-cachyos", "kernel-xanmod", "kernel-longterm", "kernel-lts"):
        if base.startswith(prefix):
            rest = base[len(prefix):].strip("-")
            return title_flavor(rest) if rest else {"kernel-cachyos": "Default", "kernel-xanmod": "Main",
                                                    "kernel-longterm": "Longterm", "kernel-lts": "LTS"}[prefix]
    if base == "kernel-ml":
        return "Mainline (ELRepo)"
    if base == "kernel-lt":
        return "Longterm (ELRepo)"
    return title_flavor(base[len("kernel-"):])


class DnfBackend(Backend):
    family = "fedora"
    pm_name = "dnf"
    pm_binary = "dnf"
    supports_purge = False
    supports_multiversion = True
    has_versions = True

    def version_scope(self, row, all_rows):
        return [r for r in all_rows if r.provider == row.provider and r.flavor == row.flavor]

    def list_versions(self, scope):
        """Older builds still offered by the enabled repositories. Kernels are install-only, so an older build
        installs next to the current one. `--showduplicates` lists every build, not just the latest."""
        names = sorted({r.name for r in scope})
        if not names:
            return [], []
        rc, out = run_host(["dnf", "-q", "repoquery", "--available", "--showduplicates", "--queryformat",
                            "%{name}|%{version}-%{release}|%{arch}\n"] + names, timeout=240)
        avail = {n: set() for n in names}
        for line in out.splitlines():
            p = line.strip().split("|")
            if len(p) == 3 and p[0] in avail and p[2] in (self.hw.arch, "noarch"):
                avail[p[0]].add(p[1])
        notes = [] if rc == 0 or any(avail.values()) else \
            ["Could not read repository metadata (dnf repoquery failed). Try Refresh first."]
        installed = {}
        for r in scope:
            if r.installed:
                installed.setdefault(r.name, set()).add(r.version)
        everywhere = set.intersection(*avail.values())
        built = set.intersection(*[installed.get(n, set()) for n in names])
        options = [VersionOption(version=v, sources=(["installed"] if v in built else []) + (["repo"] if v in everywhere else []),
                                 installed=v in built, specs=[f"{n}={v}" for n in names])
                   for v in sorted(everywhere | built, key=cmp_to_key(evr_vercmp), reverse=True)[:40]]
        if len(options) <= 1:
            notes.append("Only the current build is offered. Fedora's updates repository normally keeps just the latest build; "
                         "older ones appear only if an enabled repository still has them.")
        return options, notes

    def providers(self):
        title = "RHEL" if self.distro.rhel_clone else ("Nobara" if self.distro.id == "nobara" else "Fedora")
        out = [Provider("distro", title, hint=f"{title} kernels. Each card is one build: Core + Modules + "
                        "Devel. Install Devel too if you use DKMS/akmods drivers.")]
        if self.hw.is_x86_64:
            out.append(Provider("cachyos", "CachyOS", show_when_empty=True,
                                hint="CachyOS kernels from the bieszczaders COPR. They need x86-64-v3 "
                                     "(the -lts variants run on v2). If SELinux is enforcing run: "
                                     "sudo setsebool -P domain_kernel_load_modules on"))
            out.append(Provider("xanmod", "XanMod", show_when_empty=False,
                                hint="XanMod kernels from a community COPR (not official XanMod)."))
            out.append(Provider("longterm", "Longterm / ML", show_when_empty=False,
                                hint="Longterm and mainline kernels (ELRepo kernel-lt/kernel-ml, kernel-longterm COPRs)."))
        return out

    @staticmethod
    def _repo_files_mention(*needles):
        for f in glob.glob("/etc/yum.repos.d/*.repo"):
            try:
                text = open(f, errors="replace").read().lower()
            except OSError:
                continue
            if any(n in text for n in needles):
                return True
        return False

    def repos(self):
        if not self.hw.is_x86_64:
            return []
        out = [RepoOffer("copr-cachyos", "CachyOS (COPR)", ["cachyos"], "add-repo-copr-cachyos",
                         lambda: self._repo_files_mention("bieszczaders:kernel-cachyos", "bieszczaders/kernel-cachyos"),
                         description="Enables the bieszczaders/kernel-cachyos COPR (GCC-built CachyOS kernels).",
                         warning="COPR repositories are community-maintained and unofficial. "
                                 "Requires an x86-64-v3 CPU for the default kernel.")]
        if self.distro.id in ("fedora", "nobara"):
            out.append(RepoOffer("copr-xanmod", "XanMod (COPR)", ["xanmod"], "add-repo-copr-xanmod",
                                 lambda: self._repo_files_mention("rmnscnce:kernel-xanmod", "rmnscnce/kernel-xanmod"),
                                 description="Enables the rmnscnce/kernel-xanmod COPR.",
                                 warning="This is a community COPR, not an official XanMod repository."))
        return out

    def version_cmp(self, a, b):
        return evr_vercmp(a, b)

    def _available(self, refresh):
        cmd = ["dnf", "-q", "repoquery", "--available", "--latest-limit", "1",
               "--queryformat", "%{name}|%{version}-%{release}|%{arch}\n", "kernel*"]
        if refresh:
            cmd.insert(2, "--refresh")
        rc, out = run_host(cmd, timeout=240)
        rows = []
        for line in out.splitlines():
            p = line.strip().split("|")
            if len(p) == 3 and p[0] and p[1]:
                rows.append(p)
        if rc != 0 and not rows:
            self.warnings.append("Could not read repository metadata (dnf repoquery failed). Installed kernels "
                                 "are shown; click Refresh to retry.")
        return rows

    def collect(self, refresh=False):
        self.warnings = []
        arch = self.hw.arch
        level = level_num(self.hw.psabi or "")
        locked = locked_names_dnf()
        active = running_owner(self.running_release(), ALLOWED_PARTS)
        rows, seen = [], set()

        def make(name, evr, size, installed):
            kb = kernel_base(name)
            if not kb:
                return None
            base, part = kb
            prov = provider_for_base(base)
            r = KernelPackage(
                name=name, version=evr, provider=prov, installed=installed,
                active=installed and (base, evr) in active, held=installed and name in locked,
                size=fmt_bytes(size) if size else "—", kgroup=evr, group_label=evr,
                flavor=flavor_for_base(base), role=PART_LABEL.get(part, part), spec=f"{name}={evr}")
            if not installed and prov == "cachyos":
                need = "v2" if "-lts" in base else "v3"
                if level and level < level_num(need):
                    r.blocked_reason = f"needs x86-64-{need}; CPU supports up to v{level}"
            return r

        for ir in rpm_installed("kernel*"):
            r = make(ir["name"], evr_of(ir), ir["size"], True)
            if r:
                rows.append(r)
                seen.add((r.name, r.version))
        for name, evr, a in self._available(refresh):
            if a not in (arch, "noarch") or (name, evr) in seen:
                continue
            r = make(name, evr, 0, False)
            if r:
                rows.append(r)
        order = {label: i for i, label in enumerate(PART_LABEL[p] for p in PART_ORDER)}
        rows.sort(key=lambda r: (r.flavor, order.get(r.role, 9), r.name))
        return rows
