# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""APT backend: Debian, Ubuntu and derivatives (Mint, Pop!_OS, Zorin, MX, Kali,
Raspberry Pi OS, ...). Reads package state through apt-cache / dpkg-query (no
python-apt, so it works from an AppImage)."""
import re
from pathlib import Path

from ..hardware import level_num
from ..hostenv import run_host
from ..model import KernelPackage, PreflightResult, Provider, RepoOffer
from ..vercmp import deb_vercmp
from .base import Backend, fmt_bytes

# ── GPU relevance ────────────────────────────────────────────────────────────
NVIDIA_PKG_PATTERNS = ("linux-modules-nvidia", "linux-modules-extra-nvidia", "linux-modules-extra-gep")
AMD_PKG_PATTERNS = ("linux-modules-amd",)
INTEL_PKG_PATTERNS = ("linux-modules-intel",)


def gpu_relevant(pkg_name, gpus):
    n = pkg_name.lower()
    if any(p in n for p in NVIDIA_PKG_PATTERNS) and "nvidia" not in gpus:
        return False
    if any(p in n for p in AMD_PKG_PATTERNS) and "amd" not in gpus:
        return False
    if any(p in n for p in INTEL_PKG_PATTERNS) and "intel" not in gpus:
        return False
    return True


# ── Classification ───────────────────────────────────────────────────────────

def is_liquorix_name(name):
    n = name.lower()
    return n.startswith(("linux-image-", "linux-headers-", "linux-modules-")) and "liquorix" in n


def is_xanmod_name(name):
    """XanMod ships meta packages (linux-xanmod-x64v3, linux-xanmod-lts-x64v3 ...)
    and versioned ones (linux-image-6.18.3-x64v3-xanmod1) where 'xanmod' is an
    infix, not a prefix."""
    n = name.lower()
    if n.startswith(("linux-xanmod", "linux-image-xanmod", "linux-headers-xanmod", "linux-modules-xanmod")):
        return True
    return n.startswith(("linux-image-", "linux-headers-")) and "xanmod" in n


XANMOD_FLAVORS = ["any", "v1", "v2", "v3", "v4", "edge", "lts", "rt"]

XANMOD_FLAVOR_INFO = {
    "v1": ("x86-64-v1 — baseline (circa 2003+)",
           "Runs on essentially any 64-bit x86 CPU: AMD K8/K10/Barcelona, Intel Pentium 4/Xeon "
           "(Nocona) through Core 2, and everything since. The safe default if you're not sure "
           "what your CPU supports."),
    "v2": ("x86-64-v2 (circa 2009+)",
           "Needs SSE4.2/POPCNT support: AMD Bobcat/Jaguar/Bulldozer through Steamroller, Intel "
           "Nehalem through Ivy Bridge, and Silvermont/Goldmont-family Atoms."),
    "v3": ("x86-64-v3 (circa 2015+)",
           "Needs AVX2/BMI2/FMA support: AMD Excavator and Zen through Zen 3, Intel Haswell "
           "through 14th-gen (Raptor Lake Refresh). This is the best match for most modern "
           "desktop/laptop CPUs from the last decade."),
    "v4": ("x86-64-v4 / AVX-512",
           "Needs AVX-512 support (Zen 4/5, Ice/Cascade/Cooper/Tiger/Sapphire/Emerald Rapids "
           "Xeons, some Skylake-X chips). AVX-512 mostly benefits specific userspace workloads, "
           "not the kernel itself — on most consumer CPUs this gives no real advantage over v3, "
           "and some chips even downclock when AVX-512 is used. Only pick this if you have a "
           "specific, confirmed reason to."),
    "edge": ("Edge — bleeding-edge",
             "Tracks the newest upstream kernel changes before they've had time to mature. Expect "
             "more frequent updates and a higher chance of regressions or driver/module "
             "incompatibilities."),
    "lts": ("LTS — long-term support",
            "Tracks an upstream long-term-support kernel branch: slower-moving and more "
            "conservative. Generally the safest choice for a stable daily-driver system."),
    "rt": ("RT — PREEMPT_RT real-time",
           "Real-time preemption patches for low, predictable latency. Mainly useful for audio "
           "production, industrial control, or other latency-sensitive workloads."),
    "generic": ("Generic", "XanMod's main variant with no specific CPU optimization level."),
}


def xanmod_flavor(pkg_name):
    """CPU optimisation level (or branch) of an XanMod package; the level wins
    over the branch: linux-xanmod-lts-x64v3 -> 'v3'."""
    n = pkg_name.lower()
    for token, mapped in (("x64v4", "v4"), ("x64v3", "v3"), ("x64v2", "v2"), ("x64v1", "v1"),
                          ("-edge", "edge"), ("-lts", "lts"), ("-rt", "rt"),
                          ("-v4", "v4"), ("-v3", "v3"), ("-v2", "v2"), ("-v1", "v1")):
        if token in n:
            return mapped
    return "generic"


def xanmod_branch(pkg_name):
    n = pkg_name.lower()
    for token, label in (("-edge", "Edge"), ("-lts", "LTS"), ("-rt", "RT")):
        if token in n:
            return label
    return ""


_MAINLINE_PREFIXES = (
    "linux-image-", "linux-headers-", "linux-modules-", "linux-cloud-tools-",
    "linux-generic", "linux-lowlatency", "linux-virtual", "linux-oem-",
    "linux-aws", "linux-azure", "linux-gcp", "linux-oracle", "linux-ibm",
    "linux-kvm", "linux-gke", "linux-gkeop", "linux-intel-iotg", "linux-nvidia",
    "linux-raspi", "linux-realtime",
)

_PREFIX_RE = re.compile(
    r"^(?:linux-image-unsigned-|linux-image-uc-|linux-image-oem-|linux-image-|linux-headers-|"
    r"linux-modules-extra-gep-|linux-modules-extra-|linux-modules-nvidia-[a-z0-9-]*?-(?=\d)|"
    r"linux-modules-(?:ipu6|ivsc|iwlwifi|usbio)-|linux-modules-|linux-cloud-tools-)"
)
# A build always has a patch number (6.17.0-42). A bare "6.17" is a series tag, which makes the
# package a tracking (meta) package, e.g. linux-modules-nvidia-595-open-aws-6.17.
# Ubuntu 6.14.0-37-generic | Debian 6.1.0-18-amd64 | Debian 13 6.12.48+deb13-amd64 |
# backports 6.1.0-0.deb11.17-amd64 | Raspberry Pi 6.12.34+rpt-rpi-v8
_KVER_RE = re.compile(
    r"^(?P<kver>\d+\.\d+\.\d+(?:\+[A-Za-z]+\d*|-\d+(?:\.[a-z]+\d+\.\d+)?)?)(?:-(?P<suffix>[A-Za-z].*))?$"
)
_ARCH_TOKENS = {"amd64", "arm64", "armmp", "armmp-lpae", "686", "686-pae", "powerpc64le", "ppc64el",
                "s390x", "riscv64", "loong64", "mips64el", "i386"}


def split_mainline_name(name):
    """-> (kver, suffix) for versioned packages, or None for tracking/meta names."""
    m = _PREFIX_RE.match(name.lower())
    if not m:
        return None
    km = _KVER_RE.match(name.lower()[m.end():])
    if not km:
        return None
    return km.group("kver"), km.group("suffix") or ""


def extract_kernel_version(pkg_name):
    r = split_mainline_name(pkg_name)
    return r[0] if r else None


def is_generic_kernel_name(name):
    if is_xanmod_name(name) or is_liquorix_name(name) or name.endswith("-dbg"):
        return False
    return name.startswith(_MAINLINE_PREFIXES) and extract_kernel_version(name) is not None


_EMBEDDED_VERSION_RE = re.compile(r"\d+\.\d+\.\d+-\d+")


def is_mainline_meta(name):
    """Tracking packages (linux-generic, linux-oem-24.04, linux-image-amd64 ...).
    Names that embed a full build number but that we cannot parse as one of
    the managed image/headers/modules packages (e.g. linux-aws-6.11-headers-
    6.11.0-1014, linux-azure-tools-6.8.0-1005) are cloud/tooling helpers and
    are deliberately not listed."""
    if is_xanmod_name(name) or is_liquorix_name(name) or name.endswith("-dbg"):
        return False
    return (name.startswith(_MAINLINE_PREFIXES) and extract_kernel_version(name) is None
            and not _EMBEDDED_VERSION_RE.search(name))


FLAVOR_ORDER = [
    "Generic", "Generic (64k pages)", "Low Latency", "Real-Time", "OEM", "Virtual", "Cloud",
    "AWS", "Azure", "GCP", "Oracle", "IBM", "KVM", "GKE", "GKE OP", "Intel IoTG", "NVIDIA",
    "VMware", "Raspberry Pi", "Other",
]


def _flavor_sort_key(label):
    for i, base in enumerate(FLAVOR_ORDER):
        if label.startswith(base):
            return i
    return len(FLAVOR_ORDER)


def extract_kernel_flavor(pkg_name):
    """Human-readable flavor: Generic / Low Latency / Real-Time / OEM / AWS ...,
    with an HWE suffix where present. Works for Ubuntu and Debian naming."""
    n = pkg_name.lower()
    r = split_mainline_name(n)
    if r:
        suffix = r[1]
    else:
        suffix = n
        for prefix in ("linux-image-unsigned-", "linux-image-uc-", "linux-image-", "linux-headers-",
                       "linux-cloud-tools-", "linux-modules-", "linux-"):
            if suffix.startswith(prefix):
                suffix = suffix[len(prefix):]
                break
    if n.startswith("linux-modules-nvidia-"):
        # The driver series ("nvidia-580-server-open-") is not part of the kernel flavor:
        # linux-modules-nvidia-580-server-open-vmware-6.17 is a VMware package, not an NVIDIA one.
        suffix = re.sub(r"^nvidia-\d+(?:-(?:server|open|vgpu-guest|vgpu|guest))*-", "", suffix)
    toks = [t for t in suffix.split("-") if t]
    # Drop Debian architecture tokens (also the two-token "armmp-lpae"/"686-pae" forms).
    joined = "-".join(toks)
    for a in sorted(_ARCH_TOKENS, key=len, reverse=True):
        joined = re.sub(rf"(^|-){re.escape(a)}(?=-|$)", "", joined)
    s = joined.strip("-")
    tokset = set(s.split("-")) if s else set()
    tokset -= {"unsigned", "common", "uc"}

    if "64k" in s:
        base = "Generic (64k pages)"
    elif not tokset or "generic" in s:
        base = "Generic"
    elif "lowlatency" in s:
        base = "Low Latency"
    elif "rt" in tokset or "realtime" in s:
        base = "Real-Time"
    elif "oem" in s:
        base = "OEM"
    elif "virtual" in s:
        base = "Virtual"
    elif "cloud" in tokset:
        base = "Cloud"
    elif "aws" in s:
        base = "AWS"
    elif "azure" in s:
        base = "Azure"
    elif "gcp" in s:
        base = "GCP"
    elif "oracle" in s:
        base = "Oracle"
    elif "ibm" in s:
        base = "IBM"
    elif "gkeop" in s:
        base = "GKE OP"
    elif "gke" in s:
        base = "GKE"
    elif "iotg" in s:
        base = "Intel IoTG"
    elif "nvidia" in s:
        base = "NVIDIA"
    elif "kvm" in s:
        base = "KVM"
    elif "vmware" in s:
        base = "VMware"
    elif "raspi" in s or "rpi" in tokset:
        base = "Raspberry Pi"
    else:
        base = s.split("-")[0].replace("_", " ").title() or "Other"
    hwe = re.search(r"hwe-(\d+\.\d+)", s)
    if hwe:
        base += f" (HWE {hwe.group(1)})"
    return base


def nvidia_module_series(name):
    """Driver series of a prebuilt NVIDIA module package:
    linux-modules-nvidia-580-open-6.17.0-42-generic -> '580-open'. None for anything else."""
    prefix = "linux-modules-nvidia-"
    if not name.startswith(prefix):
        return None
    r = split_mainline_name(name)
    if not r:
        return None
    i = name[len(prefix):].find("-" + r[0])
    return name[len(prefix):][:i] if i > 0 else None


def pkg_category(pkg_name):
    n = pkg_name.lower()
    if "linux-image-unsigned-" in n or "linux-image-uc-" in n:
        return "Image (unsigned/uc)"
    if "linux-image-oem-" in n:
        return "Image (OEM)"
    if "linux-image-" in n:
        return "Image"
    if "linux-headers-" in n:
        return "Headers"
    if "linux-modules-extra-gep" in n:
        return "Modules Extra (GEP)"
    if "linux-modules-nvidia" in n:
        return "Modules NVIDIA"
    if "linux-modules-extra" in n:
        return "Modules Extra"
    if "linux-modules-" in n:
        return "Modules"
    if "linux-cloud-tools-" in n:
        return "Cloud Tools"
    return "Other"


def mainline_flavor_matches(label, filt):
    if filt == "Any":
        return True
    if filt == "Other":
        return not any(label.startswith(b) for b in FLAVOR_ORDER[:-1])
    return label.startswith(filt)


class AptBackend(Backend):
    family = "debian"
    pm_name = "APT"
    pm_binary = "apt-get"
    supports_purge = True
    purge_help = "Purge: removes packages and deletes all associated configuration files."

    XANMOD_KEYRINGS = ("/etc/apt/keyrings/xanmod-archive-keyring.gpg",
                       "/usr/share/keyrings/xanmod-archive-keyring.gpg")
    XANMOD_SOURCES = ("/etc/apt/sources.list.d/xanmod-release.list",
                      "/etc/apt/sources.list.d/xanmod-release.sources",
                      "/etc/apt/sources.list.d/xanmod-kernel.list")
    LIQUORIX_FILES = ("/etc/apt/sources.list.d/damentz-liquorix.sources",
                      "/etc/apt/sources.list.d/damentz-liquorix.list",
                      "/etc/apt/sources.list.d/liquorix.list",
                      "/etc/apt/sources.list.d/liquorix.sources")

    def __init__(self, distro, hw):
        super().__init__(distro, hw)
        self._seen_names = set()

    # ── metadata ─────────────────────────────────────────────────────────────
    def version_cmp(self, a, b):
        return deb_vercmp(a, b)

    def providers(self):
        base = "Ubuntu" if self.distro.has("ubuntu") else "Debian"
        cloud = {"aws": "AWS", "azure": "Azure", "gcp": "GCP", "oracle": "Oracle"}.get(self.hw.cloud, "")
        out = [Provider(
            id="mainline", title=base, layout="nested",
            hint=(f"Official {base} kernels. Generic is the standard kernel — pick a cloud/OEM/"
                  "real-time flavor only if you specifically need it."),
            default_flavor=cloud or "Generic", flavor_order=FLAVOR_ORDER,
        )]
        if self.hw.is_x86_64:
            out.append(Provider(id="xanmod", title="XanMod", card_prefix="XanMod ",
                                hint="v1=baseline · v2=SSE4 · v3=AVX2 · v4=AVX-512 · edge=latest",
                                flavor_order=XANMOD_FLAVORS[1:]))
            out.append(Provider(id="liquorix", title="Liquorix", card_prefix="Liquorix ",
                                hint="Zen-based desktop/gaming kernel (x86-64 only)."))
        return out

    def _xanmod_present(self):
        if any(Path(p).exists() for p in self.XANMOD_SOURCES):
            return True
        return self._sources_mention(("deb.xanmod.org",))

    def _liquorix_present(self):
        if any(Path(p).exists() for p in self.LIQUORIX_FILES):
            return True
        if self._sources_mention(("damentz/liquorix", "liquorix.net")):
            return True
        return any(is_liquorix_name(n) for n in self._seen_names)

    @staticmethod
    def _sources_mention(patterns):
        try:
            files = [Path("/etc/apt/sources.list")] + list(Path("/etc/apt/sources.list.d").glob("*"))
        except OSError:
            return False
        for f in files:
            try:
                text = f.read_text(errors="replace").lower()
            except OSError:
                continue
            if any(p in text for p in patterns):
                return True
        return False

    def repos(self):
        if not self.hw.is_x86_64:
            return []
        return [
            RepoOffer("xanmod", "XanMod", ["xanmod"], "add-repo-xanmod", self._xanmod_present,
                      offer_on_start=True,
                      description="Adds the official XanMod apt repository (deb.xanmod.org) and its signing key."),
            RepoOffer("liquorix", "Liquorix", ["liquorix"], "add-repo-liquorix", self._liquorix_present,
                      offer_on_start=True,
                      description=("Adds the Liquorix repository: the damentz/liquorix PPA on Ubuntu-based "
                                   "systems, liquorix.net/debian on Debian-based ones.")),
        ]

    # ── data collection ──────────────────────────────────────────────────────
    @staticmethod
    def classify(name):
        if is_xanmod_name(name):
            return "xanmod"
        if is_liquorix_name(name):
            return "liquorix"
        if is_generic_kernel_name(name) or is_mainline_meta(name):
            return "mainline"
        return None

    def _dumpavail(self):
        """One pass over `apt-cache dumpavail` (about a second even on a full
        Ubuntu archive; per-package `apt-cache show` took minutes). Keeps the
        newest available version of every linux-* package — the candidate,
        except when apt pinning says otherwise."""
        rc, out = run_host(["apt-cache", "dumpavail"], timeout=180)
        info = {}
        for stanza in out.split("\n\n"):
            if not stanza.startswith("Package: linux-"):
                continue
            f = {}
            for line in stanza.splitlines():
                if line[:1] in (" ", "\t") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                if k in ("Package", "Version", "Installed-Size"):
                    f[k] = v.strip()
            name = f.get("Package")
            if not name or not self.classify(name):
                continue
            cur = info.get(name)
            if cur is None or deb_vercmp(f.get("Version", ""), cur.get("Version", "")) > 0:
                info[name] = f
        return rc, info

    def _dpkg_status(self):
        rc, out = run_host(["dpkg-query", "-W", "-f",
                            "${Package}\t${Version}\t${db:Status-Abbrev}\t${Installed-Size}\n"])
        status = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[0].startswith("linux-"):
                ab = parts[2]
                # Second status letter: i installed, U unpacked, F half-configured, H half-installed, W/t trigger
                # states. A package a failed install left half-done counts as installed: it can be removed.
                status[parts[0]] = (len(ab) > 1 and ab[1] in "iUFHWt", ab[:1] == "h", parts[1], parts[3])
        return status

    has_preflight = True
    _CULPRIT_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9+._-]*) : (Depends|PreDepends|Conflicts|Breaks): (\S+)[^\n]*", re.M)
    _NO_CANDIDATE_RES = (re.compile(r"E: Unable to locate package (\S+)"),
                         re.compile(r"E: Package '([^']+)' has no installation candidate"))
    _CONFLICT_MARKERS = ("unmet dependencies", "Unable to locate package", "no installation candidate",
                         "held broken packages", "Unable to correct problems")

    @staticmethod
    def _removed_packages(out):
        removed, grab = [], False
        for line in out.splitlines():
            if line.startswith("The following packages will be REMOVED"):
                grab = True
                continue
            if grab:
                if line.startswith("  "):
                    removed.extend(line.split())
                else:
                    grab = False
        return removed

    def preflight(self, specs):
        """`apt-get -s install` (needs no root). If the selection cannot be installed
        together, leave out the selected packages apt names as the problem and try
        again, so a bad combination (e.g. several NVIDIA driver series) becomes a clear
        question instead of an apt wall of text. Rules that keep this safe:
          * of two selected packages that CONFLICT, only the later one is dropped;
          * a selection that contained a kernel image never ends up without one;
          * an inconclusive simulation never blocks the real install."""
        remaining, dropped, out = list(specs), [], ""
        had_image = any(sp.startswith("linux-image-") for sp in specs)
        for _ in range(10):
            rc, out = run_host(["apt-get", "-s", "-o", "Debug::NoLocking=1", "install"] + remaining,
                               timeout=240, merge_stderr=True)
            if rc == 0:
                if had_image and not any(sp.startswith("linux-image-") for sp in remaining):
                    return PreflightResult(ok=False, dropped=dropped, output=out, message=(
                        "The kernel image itself can't be installed here, so installing only its "
                        "headers/modules would leave you with nothing to boot."))
                return PreflightResult(ok=True, packages=remaining, dropped=dropped,
                                       removals=self._removed_packages(out), output=out)
            if not any(m in out for m in self._CONFLICT_MARKERS):
                return PreflightResult(ok=True, packages=list(specs), output=out)     # inconclusive
            order = {sp.split("=")[0]: i for i, sp in enumerate(remaining)}
            blamed = {}
            for m in self._CULPRIT_RE.finditer(out):
                name, relation, target = m.group(1), m.group(2), m.group(3)
                if name not in order:
                    continue
                if relation in ("Conflicts", "Breaks") and target in order and order[target] < order[name]:
                    blamed.setdefault(name, m.group(0).split(" : ", 1)[1].strip())   # keep the earlier one
                elif relation in ("Conflicts", "Breaks") and target in order:
                    continue                                                         # the other side will be dropped
                else:
                    blamed.setdefault(name, m.group(0).split(" : ", 1)[1].strip())
            for rx in self._NO_CANDIDATE_RES:
                for name in rx.findall(out):
                    if name in order:
                        blamed.setdefault(name, "not available in your repositories")
            bad = [sp for sp in remaining if sp.split("=")[0] in blamed]
            if not bad:
                return PreflightResult(ok=False, message=self._summarise(out), dropped=dropped, output=out)
            dropped.extend((sp, blamed[sp.split("=")[0]][:140]) for sp in bad)
            remaining = [sp for sp in remaining if sp not in bad]
            if not remaining:
                return PreflightResult(ok=False, dropped=dropped, output=out,
                                       message="None of the selected packages can be installed on this system.")
        return PreflightResult(ok=False, dropped=dropped, output=out, message=self._summarise(out))

    @staticmethod
    def _summarise(out):
        keep = [l for l in out.splitlines() if l.startswith("E:") or " : Depends:" in l or "unmet" in l]
        return "\n".join(keep[:12]) or out[-600:]

    def collect(self, refresh=False):
        self.warnings = []
        rc, details = self._dumpavail()
        if rc != 0 and not details:
            raise RuntimeError("apt-cache failed. Try running 'sudo apt-get update' in a terminal, then Refresh.")
        status = self._dpkg_status()
        # NVIDIA driver series that already have prebuilt modules installed. Only those are picked
        # automatically for a new kernel; every other series is opt-in (they conflict with each other).
        installed_series = {nvidia_module_series(n) for n, v in status.items() if v[0]} - {None}
        self._seen_names = set(details) | set(status)
        wanted = sorted(n for n in self._seen_names if self.classify(n))
        run = self.running_release()
        gpus = self.hw.gpus
        level = level_num(self.hw.psabi or "")

        rows = []
        for name in wanted:
            d = details.get(name)
            inst, held, inst_ver, inst_size = status.get(name, (False, False, "", ""))
            if d is None and not inst:
                continue
            cand = (d or {}).get("Version", "")
            version = cand or inst_ver
            prov = self.classify(name)
            try:
                size = fmt_bytes(int((d or {}).get("Installed-Size") or inst_size or "0") * 1024)
            except ValueError:
                size = "—"
            active = inst and name.endswith("-" + run)
            row = KernelPackage(name=name, version=version, provider=prov, installed=inst,
                                active=active, held=held and inst, size=size)
            if prov == "mainline":
                if is_mainline_meta(name):
                    row.is_meta, row.role = True, "Meta"
                else:
                    row.kgroup = extract_kernel_version(name)
                    row.role = pkg_category(name)
                row.flavor = extract_kernel_flavor(name)
            elif prov == "xanmod":
                row.flavor = xanmod_flavor(name)
                row.kgroup = version
                branch = xanmod_branch(name)
                row.group_label = f"{version}" + (f" · {branch}" if branch else "")
                need = level_num(row.flavor)
                if need and level and need > level:
                    row.blocked_reason = f"needs x86-64-{row.flavor}; CPU supports up to v{level}"
            else:  # liquorix
                row.kgroup = version
            if not gpu_relevant(name, gpus):
                row.blocked_reason = "no matching GPU"
            if name.startswith("linux-modules-nvidia-") and not row.installed:
                series = nvidia_module_series(name)
                row.opt_in = series is None or series not in installed_series   # tracking pkgs: always opt-in
            if row.installed:
                row.blocked_reason = ""     # never trap an installed package: it must stay removable
            rows.append(row)

        # Ubuntu ships the kernel image three ways that CONFLICT with each other (signed, unsigned, uc).
        # A group click picks the signed one; the others are opt-in unless no signed twin exists.
        names = {r.name for r in rows}
        for r in rows:
            if r.installed:
                continue
            if r.name.startswith(("linux-image-unsigned-", "linux-image-uc-")):
                r.opt_in = re.sub(r"^linux-image-(?:unsigned|uc)-", "linux-image-", r.name) in names
            elif r.role == "Cloud Tools":
                r.opt_in = True        # VM guest tooling: never part of "install this kernel"
        rows.sort(key=lambda r: ((0 if r.active else 1 if r.installed else 2),))
        return rows
