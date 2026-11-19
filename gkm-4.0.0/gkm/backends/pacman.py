# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""pacman backend: Arch and derivatives (CachyOS, Manjaro, EndeavourOS, Garuda,
Artix, ...).

Kernels are discovered generically: any package `X` that has a matching
`X-headers` package in the sync databases (or installed) is a kernel. That
picks up linux, linux-lts, linux-zen, linux-hardened, linux-rt, the CachyOS
family (linux-cachyos-bore, -lts, -rt-bore, ...), linux-xanmod*, linux-clear*,
linux-tkg-*, Manjaro's linux612 ... without a hard-coded list that goes stale.
"""
import re
from functools import cmp_to_key
from pathlib import Path

from ..archive import fetch_archive_versions, list_cached_versions
from ..catalog import load_kernel_catalog
from ..hardware import level_num
from ..hostenv import run_host
from ..model import KernelPackage, Provider, RepoOffer, VersionOption
from ..vercmp import evr_vercmp
from .base import Backend, fmt_bytes, title_flavor

OFFICIAL_ARCH_BASES = {"linux", "linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts"}
_OFFICIAL_LABELS = {"linux": "Stable", "linux-lts": "LTS", "linux-zen": "Zen",
                    "linux-hardened": "Hardened", "linux-rt": "Real-Time", "linux-rt-lts": "Real-Time LTS"}

_MODULE_SUFFIX_RE = re.compile(
    r"(?:nvidia(?:-open)?(?:-\d+xx)?(?:-open)?|nvidia-[a-z0-9-]+|zfs|r8168|r8125|r8152|broadcom-wl|"
    r"virtualbox-(?:host|guest)-modules|acpi_call|vhba-module|bbswitch|tp_smapi|v4l2loopback|xpadneo|openrazer)"
)
_SIZE_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}


def kernel_bases(names):
    bases = set()
    for n in names:
        if n.startswith("linux") and n.endswith("-headers"):
            b = n[:-len("-headers")]
            if b in names:
                bases.add(b)
    return bases


def module_packages(base, names):
    out = set()
    prefix = base + "-"
    for n in names:
        if n.startswith(prefix) and _MODULE_SUFFIX_RE.fullmatch(n[len(prefix):]):
            out.add(n)
    short = base[len("linux-"):] if base.startswith("linux-") else ""
    for cand in ((f"nvidia-{short}", f"nvidia-open-{short}") if short else ("nvidia", "nvidia-open")):
        if cand in names:
            out.add(cand)
    return out


def provider_for_base(base):
    if base.startswith("linux-cachyos"):
        return "cachyos"
    if base.startswith("linux-xanmod"):
        return "xanmod"
    if base.startswith("linux-clear"):
        return "clear"
    if base.startswith("linux-lqx"):
        return "liquorix"
    if re.match(r"linux(?:-lts)?-tkg", base):
        return "tkg"
    if re.fullmatch(r"linux\d{2,3}(?:-rt)?", base):
        return "manjaro"
    if base in OFFICIAL_ARCH_BASES:
        return "arch"
    return "other"


def flavor_for_base(base, provider):
    if provider == "arch":
        return _OFFICIAL_LABELS.get(base, title_flavor(base[6:]))
    if provider == "manjaro":
        m = re.fullmatch(r"linux(\d)(\d+)(-rt)?", base)
        return f"{m.group(1)}.{m.group(2)}" + (" RT" if m.group(3) else "") if m else base
    for prefix in ("linux-cachyos", "linux-xanmod", "linux-clear"):
        if base.startswith(prefix):
            rest = base[len(prefix):].strip("-")
            return title_flavor(rest) if rest else "Default"
    return title_flavor(base[6:]) if base.startswith("linux-") else base


def module_kind(name, base):
    """What kind of module package this is, independent of the kernel it is for:
    linux-cachyos-nvidia-open -> 'nvidia-open', nvidia-open-lts (base linux-lts) -> 'nvidia-open'.
    Different kinds conflict with each other, so only the kind you already use is auto-selected."""
    if name.startswith(base + "-"):
        return name[len(base) + 1:]
    short = base[len("linux-"):] if base.startswith("linux-") else ""
    return name[:-(len(short) + 1)] if short and name.endswith("-" + short) else name


def repo_required_level(repo):
    """CachyOS ships the same package names in generic and CPU-optimised repos
    (cachyos-v3, cachyos-v4, cachyos-znver4); returns ('v3'|'v4'|'znver4'|'')."""
    m = re.search(r"(?:^|-)(v[234]|znver4)$", repo or "")
    return m.group(1) if m else ""


def parse_size(text):
    m = re.match(r"([\d.]+)\s*(B|KiB|MiB|GiB)", text or "")
    return int(float(m.group(1)) * _SIZE_UNITS[m.group(2)]) if m else 0


def parse_pacman_info(text):
    out = {}
    for stanza in text.split("\n\n"):
        f = {}
        for line in stanza.splitlines():
            if line[:1] in (" ", "\t"):
                continue
            m = re.match(r"^([^:]+?)\s*:\s*(.*)$", line)
            if m and m.group(1) not in f:
                f[m.group(1)] = m.group(2)
        if "Name" in f:
            out.setdefault(f["Name"], f)
    return out


class PacmanBackend(Backend):
    family = "arch"
    pm_name = "pacman"
    pm_binary = "pacman"
    supports_purge = True
    purge_label = "Remove + configs"
    purge_help = "Remove + configs: also deletes saved configuration backups (pacman -Rn)."
    supports_multiversion = False     # rolling: one build of each kernel, no "old kernels"
    has_versions = True
    restores_after_failed_upgrade = True

    def version_scope(self, row, all_rows):
        # Kernel + headers move together (they depend on each other by exact version). Module packages
        # (nvidia, zfs ...) are tied to a kernel version too but are not rolled back automatically.
        return [r for r in all_rows if r.provider == row.provider and r.kgroup == row.kgroup
                and r.role in ("Kernel", "Headers")]

    def _cache_dir(self):
        rc, out = run_host(["pacman-conf", "CacheDir"])
        first = out.split("\n", 1)[0].strip() if rc == 0 else ""
        return first.rstrip("/") or "/var/cache/pacman/pkg"

    def list_versions(self, scope):
        notes = []
        if self.hw.arch != "x86_64":
            return [], ["Older versions come from the Arch Linux Archive, which only carries x86_64 packages."]
        names = [r.name for r in scope]
        if not names:
            return [], []
        cache_dir = self._cache_dir()
        cached, archived, reachable = {}, {}, True
        for n in names:
            cached[n] = set(list_cached_versions(n, self.hw.arch, cache_dir))
            try:
                archived[n] = set(fetch_archive_versions(n, self.hw.arch))
            except OSError:
                archived[n], reachable = set(), False
        if not reachable:
            notes.append("The Arch Linux Archive could not be reached, so only versions in your local pacman cache are listed.")
        # A version is restorable if EVERY package has it in the cache, or EVERY package has it in the archive
        # (exactly how the helper restores them: one transaction, from one source).
        from_cache = set.intersection(*cached.values())
        from_archive = set.intersection(*archived.values())
        installed_at = {r.name: r.version for r in scope if r.installed}
        current = installed_at[names[0]] if all(n in installed_at for n in names) and \
            len({installed_at[n] for n in names}) == 1 else None
        versions = from_cache | from_archive | ({current} if current else set())
        options = []
        for v in sorted(versions, key=cmp_to_key(evr_vercmp), reverse=True)[:40]:
            srcs = (["installed"] if v == current else []) + (["cache"] if v in from_cache else []) + \
                   (["archive"] if v in from_archive else [])
            options.append(VersionOption(version=v, sources=srcs, installed=(v == current),
                                         specs=[f"{n}={v}" for n in names]))
        if len(options) <= 1:
            notes.append("No other version of this kernel is in the pacman cache or the Arch Linux Archive.")
        modules = sorted({r.name for r in getattr(self, "_last_rows", [])
                          if scope and r.kgroup == scope[0].kgroup and r.role == "Modules" and r.installed})
        if modules:
            notes.append("Driver module packages tied to this kernel (" + ", ".join(modules[:4]) +
                         (" …" if len(modules) > 4 else "") + ") are NOT rolled back. If pacman reports a dependency "
                         "problem, restore them too, or use a DKMS driver.")
        return options, notes

    def providers(self):
        d = self.distro
        out = []
        if d.has("manjaro"):
            out.append(Provider("manjaro", "Manjaro", hint="Manjaro kernel series (linuxNN). Each series ships with "
                                "its own headers and matching driver modules.", show_when_empty=True))
        else:
            out.append(Provider("arch", "Arch", hint="Official Arch kernels. Install the matching -headers "
                                "package so DKMS drivers can build.", show_when_empty=True,
                                flavor_order=list(_OFFICIAL_LABELS.values())))
        if self.hw.is_x86_64:
            out.append(Provider("cachyos", "CachyOS", show_when_empty=d.has("cachyos"),
                                hint="CachyOS kernels (BORE/EEVDF, LTO, RT ...). Packages come from the "
                                     "cachyos repositories — or Chaotic-AUR."))
            out.append(Provider("xanmod", "XanMod", show_when_empty=False,
                                hint="XanMod kernels as pre-built in Chaotic-AUR."))
            out.append(Provider("clear", "Clear", show_when_empty=False,
                                hint="Clear Linux-patched kernels (linux-clear). Intel ended Clear Linux "
                                     "distribution support in 2025; this kernel is community-maintained."))
            out.append(Provider("liquorix", "Liquorix", show_when_empty=False,
                                hint="Liquorix (linux-lqx): Zen-based low-latency desktop kernel."))
            out.append(Provider("tkg", "TKG", show_when_empty=False,
                                hint="linux-tkg kernels: customisable builds (PDS, BMQ and other schedulers)."))
        out.append(Provider("other", "Other", show_when_empty=False,
                            hint="Other kernels found in your repositories or installed locally "
                                 "(linux-tkg, linux-zen variants, AUR builds, ...)."))
        return out

    def _chaotic_present(self):
        rc, out = run_host(["pacman-conf", "--repo-list"])
        if rc == 0:
            return "chaotic-aur" in out.split()
        try:
            return "[chaotic-aur]" in Path("/etc/pacman.conf").read_text(errors="replace")
        except OSError:
            return False

    def repos(self):
        if not self.hw.is_x86_64:
            return []
        return [RepoOffer(
            "chaotic-aur", "Chaotic-AUR", ["cachyos", "xanmod", "clear", "liquorix", "tkg", "other"],
            "add-repo-chaotic-aur", self._chaotic_present, then_upgrade=True,
            description="Chaotic-AUR pre-builds many AUR kernels (linux-cachyos*, linux-xanmod*, linux-tkg ...).",
            warning=("Chaotic-AUR is an unofficial third-party repository. GKM will import its signing key, "
                     "install chaotic-keyring and chaotic-mirrorlist, and append a [chaotic-aur] section to "
                     "/etc/pacman.conf. Only do this if you trust that project.\n\n"
                     "Afterwards GKM automatically runs a FULL SYSTEM UPGRADE (pacman -Syu), which upgrades every "
                     "package, not just kernels, because Arch expects that after syncing a new repository. If the "
                     "upgrade fails and a kernel was changed, GKM restores the previous kernel from your pacman cache "
                     "or the Arch Linux Archive.")),
        ]

    def version_cmp(self, a, b):
        return evr_vercmp(a, b)

    # ── collection ───────────────────────────────────────────────────────────
    def _running_base(self):
        rel = self.running_release()
        try:
            return Path(f"/usr/lib/modules/{rel}/pkgbase").read_text().strip()
        except OSError:
            pass
        rc, out = run_host(["pacman", "-Qqo", f"/usr/lib/modules/{rel}/vmlinuz"])
        return out.strip().splitlines()[0] if rc == 0 and out.strip() else ""

    def _held(self):
        rc, out = run_host(["pacman-conf", "IgnorePkg"])
        if rc == 0:
            return {x.strip() for x in out.split() if x.strip()}
        held = set()
        try:
            for line in Path("/etc/pacman.conf").read_text(errors="replace").splitlines():
                m = re.match(r"^\s*IgnorePkg\s*=\s*(.*)$", line)
                if m:
                    held.update(m.group(1).split())
        except OSError:
            pass
        return held

    def collect(self, refresh=False):
        self.warnings = []
        rc, out = run_host(["pacman", "-Sl"], timeout=60)
        sync = {}
        for line in out.splitlines():
            p = line.split()
            if len(p) >= 3 and p[1] not in sync:       # first repo wins = pacman's precedence
                sync[p[1]] = (p[0], p[2])
        if not sync:
            self.warnings.append("pacman sync databases are empty or unreadable — click Refresh.")
        rc, out = run_host(["pacman", "-Q"], timeout=60)
        installed = {}
        for line in out.splitlines():
            p = line.split()
            if len(p) == 2:
                installed[p[0]] = p[1]

        names = set(sync) | set(installed)
        catalog = load_kernel_catalog()
        wanted, headers_of = {}, {}
        # Generic discovery (a package with a -headers sibling) plus anything the catalogue names:
        # that is how a kernel with an unusual headers package, or none, can still be managed.
        for base in kernel_bases(names) | {n for n in catalog if n in names}:
            entry = catalog.get(base, {})
            prov = entry.get("provider") or provider_for_base(base)
            headers = entry.get("headers") or base + "-headers"
            headers_of[base] = headers
            for n in {base, headers} | module_packages(base, names):
                if n in names:
                    wanted[n] = (base, prov)

        sync_info = parse_pacman_info(run_host(["pacman", "-Si"] + sorted(n for n in wanted if n in sync))[1]) \
            if any(n in sync for n in wanted) else {}
        inst_names = sorted(n for n in wanted if n in installed)
        inst_info = parse_pacman_info(run_host(["pacman", "-Qi"] + inst_names)[1]) if inst_names else {}

        held = self._held()
        run_base = self._running_base()
        gpus = self.hw.gpus
        level = level_num(self.hw.psabi or "")
        rows = []
        for name, (base, prov) in wanted.items():
            is_inst = name in installed
            repo, sver = sync.get(name, ("local", ""))
            version = installed.get(name) or sver
            info = inst_info.get(name) if is_inst else sync_info.get(name)
            size = fmt_bytes(parse_size((info or {}).get("Installed Size", "")))
            if name == base:
                role = "Kernel"
            elif name == headers_of.get(base):
                role = "Headers"
            else:
                role = "Modules"
            row = KernelPackage(
                name=name, version=version, provider=prov, installed=is_inst,
                active=is_inst and bool(run_base) and base == run_base, held=name in held and is_inst,
                size=size, kgroup=base, flavor=flavor_for_base(base, prov), role=role, repo=repo,
                description=(catalog.get(base, {}).get("description") if role == "Kernel" else "")
                or (info or {}).get("Description", ""))
            if role == "Modules" and "nvidia" in name and "nvidia" not in gpus and not is_inst:
                row.blocked_reason = "no matching GPU"
            need = repo_required_level(repo)
            if not is_inst and need:
                if need == "znver4" and not self.hw.zen4:
                    row.blocked_reason = "repo is built for AMD Zen 4/5 (znver4)"
                elif need in ("v3", "v4") and level < level_num(need):
                    row.blocked_reason = f"repo needs x86-64-{need}; CPU supports up to v{level}"
            req = catalog.get(base, {}).get("requires", {})
            if not is_inst and not row.blocked_reason:
                if req.get("zen4") and not self.hw.zen4:
                    row.blocked_reason = "built for AMD Zen 4/5 (znver4) CPUs"
                elif req.get("psabi") and level < level_num(req["psabi"]):
                    row.blocked_reason = f"needs x86-64-{req['psabi']}; CPU supports up to v{level}"
            rows.append(row)
        # Module packages of different kinds (nvidia, nvidia-open, zfs ...) conflict with each other, so a
        # group click picks only the kind you already have installed for some kernel; the rest are opt-in.
        installed_kinds = {module_kind(r.name, r.kgroup) for r in rows if r.role == "Modules" and r.installed}
        for r in rows:
            if r.role == "Modules" and not r.installed:
                r.opt_in = module_kind(r.name, r.kgroup) not in installed_kinds
        # Group label carries the kernel package's own version.
        kver = {r.kgroup: r.version for r in rows if r.role == "Kernel"}
        for r in rows:
            r.group_label = f"{r.kgroup} {kver.get(r.kgroup, '')}".strip()
        order = {"Kernel": 0, "Headers": 1, "Modules": 2}
        rows.sort(key=lambda r: (r.kgroup, order.get(r.role, 9), r.name))
        self._last_rows = rows
        return rows
