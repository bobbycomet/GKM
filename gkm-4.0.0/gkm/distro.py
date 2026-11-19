# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Distro detection from /etc/os-release, resolving derivatives to the
family (and root distro) they are built on."""
import os
import shutil
from dataclasses import dataclass, field

_FAMILY_BY_ID = {}
for _fam, _ids in {
    "debian": "debian ubuntu raspbian linuxmint lmde pop elementary zorin neon kali parrot devuan mx "
              "deepin tuxedo pureos kubuntu xubuntu lubuntu ubuntu-core steamos-debian",
    "arch": "arch archarm manjaro manjaro-arm endeavouros cachyos garuda artix arcolinux archcraft "
            "rebornos biglinux blendos steamos snigdhaos",
    "fedora": "fedora rhel centos rocky almalinux ol nobara amzn scientific eurolinux",
    "suse": "opensuse opensuse-leap opensuse-tumbleweed opensuse-slowroll opensuse-microos sles sled suse",
}.items():
    for _i in _ids.split():
        _FAMILY_BY_ID[_i] = _fam

_ROOT_DISTROS = ("ubuntu", "debian", "arch", "fedora", "rhel", "opensuse-tumbleweed",
                 "opensuse-leap", "opensuse", "sles", "suse", "centos")

_PM_BY_FAMILY = {"debian": "apt-get", "arch": "pacman", "fedora": "dnf", "suse": "zypper"}
_IMMUTABLE_VARIANTS = {"silverblue", "kinoite", "sericea", "onyx", "coreos", "iot", "atomic",
                       "micro", "aeon", "kalpa", "holo", "bazzite"}


@dataclass
class DistroInfo:
    id: str = "linux"
    name: str = "Linux"
    pretty_name: str = "Linux"
    version_id: str = ""
    id_like: list = field(default_factory=list)
    family: str = "unknown"          # debian | arch | fedora | suse | unknown
    base: str = ""                   # nearest root distro (ubuntu, debian, arch, fedora, ...)
    chain: list = field(default_factory=list)
    codename: str = ""
    immutable: bool = False
    immutable_reason: str = ""

    def has(self, ident):
        return ident in self.chain

    @property
    def rhel_clone(self):
        return self.family == "fedora" and any(c in self.chain for c in ("rhel", "centos")) \
            and self.id not in ("fedora", "nobara")

    def summary(self):
        parts = [self.pretty_name]
        if self.base and self.base != self.id:
            parts.append(f"based on {self.base}")
        return " · ".join(parts)


def read_os_release(path="/etc/os-release"):
    data = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def _root_is_readonly(mountinfo="/proc/self/mountinfo"):
    try:
        with open(mountinfo) as fh:
            for line in fh:
                f = line.split()
                if len(f) > 5 and f[4] == "/":
                    return "ro" in f[5].split(",")
    except OSError:
        pass
    return False


def detect_distro(os_release=None, path="/etc/os-release", which=shutil.which,
                  ostree_marker="/run/ostree-booted", check_ro=True):
    osr = os_release if os_release is not None else read_os_release(path)
    did = osr.get("ID", "linux").lower()
    like = [x.lower() for x in osr.get("ID_LIKE", "").split()]
    chain = [did] + [x for x in like if x != did]

    family = "unknown"
    for ident in chain:
        if ident in _FAMILY_BY_ID:
            family = _FAMILY_BY_ID[ident]
            break
    if family == "unknown":
        for fam, binary in (("debian", "apt-get"), ("arch", "pacman"),
                            ("suse", "zypper"), ("fedora", "dnf")):
            if which(binary):
                family = fam
                break

    base = ""
    for ident in chain:
        if ident in _ROOT_DISTROS:
            base = ident
            break
    # Nobara and friends list "rhel centos fedora": the useful base is Fedora.
    if did == "nobara" or (did not in ("rhel", "centos", "rocky", "almalinux", "ol")
                           and "fedora" in chain and base in ("rhel", "centos")):
        base = "fedora"
    if not base:
        base = did

    codename = osr.get("UBUNTU_CODENAME") if "ubuntu" in chain else ""
    codename = codename or osr.get("DEBIAN_CODENAME") or osr.get("VERSION_CODENAME", "")

    immutable, reason = False, ""
    if os.path.exists(ostree_marker):
        immutable, reason = True, "ostree-based immutable system (rpm-ostree)"
    elif osr.get("VARIANT_ID", "").lower() in _IMMUTABLE_VARIANTS:
        immutable, reason = True, f"immutable variant ({osr.get('VARIANT_ID')})"
    elif check_ro and _root_is_readonly():
        immutable, reason = True, "read-only root filesystem"

    return DistroInfo(
        id=did, name=osr.get("NAME", did), pretty_name=osr.get("PRETTY_NAME", osr.get("NAME", did)),
        version_id=osr.get("VERSION_ID", ""), id_like=like, family=family, base=base,
        chain=chain, codename=codename, immutable=immutable, immutable_reason=reason,
    )


def package_manager_binary(distro):
    return _PM_BY_FAMILY.get(distro.family, "")
