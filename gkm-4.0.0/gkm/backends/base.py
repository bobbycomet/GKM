# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Backend interface. A backend turns one package-manager family into a flat
list of KernelPackage rows plus the metadata the UI needs (providers = tabs,
repositories that can be added, what the family supports)."""
import os
import platform
from functools import cmp_to_key

from ..model import PreflightResult


def fmt_bytes(n):
    if not n or n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            s = f"{n:.1f}"
            return f"{s[:-2] if s.endswith('.0') else s} {unit}"
        n /= 1024
    s = f"{n:.1f}"
    return f"{s[:-2] if s.endswith('.0') else s} TB"


def list_module_dirs():
    for d in ("/usr/lib/modules", "/lib/modules"):
        if os.path.isdir(d):
            return set(os.listdir(d))
    return set()


class Backend:
    family = ""
    pm_name = ""
    pm_binary = ""
    supports_purge = False
    purge_label = "Purge"
    purge_help = "Purge: removes packages and deletes all associated configuration files."
    supports_multiversion = True     # several versions of one kernel coexist => "old kernels" exist
    unique_per_name = True           # one installed version per package name

    def __init__(self, distro, hw):
        self.distro = distro
        self.hw = hw
        self.warnings = []

    # ── to override ──────────────────────────────────────────────────────────
    def providers(self):
        raise NotImplementedError

    def repos(self):
        return []

    def collect(self, refresh=False):
        raise NotImplementedError

    def version_cmp(self, a, b):
        raise NotImplementedError

    has_preflight = False
    has_versions = False             # can offer older versions of a kernel (see list_versions)
    restores_after_failed_upgrade = False   # rolling distro: a failed upgrade can be undone from the cache/archive

    def version_scope(self, row, all_rows):
        """The packages that must move together when this row's kernel changes version."""
        return [r for r in all_rows if r.provider == row.provider and r.kgroup == row.kgroup]

    def list_versions(self, scope):
        """-> (list[VersionOption], list[str] notes). Default: no version history."""
        return [], []

    def preflight(self, specs):
        """Simulate installing `specs` without privileges. Default: no check."""
        return PreflightResult(ok=True, packages=list(specs))

    # ── shared ───────────────────────────────────────────────────────────────
    def running_release(self):
        return platform.uname().release

    def sorted_newest_first(self, versions):
        return sorted(versions, key=cmp_to_key(lambda a, b: -self.version_cmp(a, b)))

    def auto_remove_candidates(self, rows):
        """Old kernels to remove: per (provider, flavor) series keep the running
        kernel's build plus the two newest builds; never touch meta packages,
        held packages or anything outside installed rows."""
        if not self.supports_multiversion:
            return []
        series = {}
        for r in rows:
            if r.installed and not r.is_meta and r.kgroup:
                series.setdefault((r.provider, r.flavor), {}).setdefault(r.kgroup, []).append(r)
        out = []
        for groups in series.values():
            rep = {}
            for kg, members in groups.items():
                best = members[0].version
                for m in members[1:]:
                    if self.version_cmp(m.version, best) > 0:
                        best = m.version
                rep[kg] = best
            ordered = sorted(groups, key=cmp_to_key(lambda a, b: -self.version_cmp(rep[a], rep[b])))
            keep = set(ordered[:2])
            for kg, members in groups.items():
                if any(m.active for m in members):
                    keep.add(kg)
            for kg, members in groups.items():
                if kg not in keep:
                    out.extend(m for m in members if not m.held and not m.active)
        return out


def title_flavor(token_string):
    """'rt-bore' -> 'RT BORE'; used to label exotic kernel variants."""
    special = {"lts": "LTS", "rt": "RT", "lto": "LTO", "bore": "BORE", "eevdf": "EEVDF",
               "bmq": "BMQ", "rc": "RC", "tkg": "TKG", "ck": "CK", "lqx": "Liquorix",
               "pf": "PF", "zen": "Zen", "uki": "UKI", "pds": "PDS", "amd": "AMD"}
    parts = [p for p in token_string.replace("_", "-").split("-") if p]
    return " ".join(special.get(p, p.capitalize()) for p in parts)
