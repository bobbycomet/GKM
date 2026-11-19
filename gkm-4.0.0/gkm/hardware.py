# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Hardware detection: CPU architecture / x86-64 psABI level, GPUs, cloud VM."""
import os
import platform
import re
from dataclasses import dataclass, field

from .hostenv import capture


def level_num(label):
    m = re.fullmatch(r"v([1-4])", label or "")
    return int(m.group(1)) if m else 0


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_cpuinfo(text):
    flags, vendor, model = set(), "", ""
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if k in ("flags", "Features") and not flags:
            flags = set(v.split())
        elif k == "vendor_id" and not vendor:
            vendor = v
        elif k == "model name" and not model:
            model = v
    return flags, vendor, model


def psabi_level_from_flags(flags):
    """Highest x86-64 psABI level (v1-v4) implied by /proc/cpuinfo flags — the
    same flag sets glibc/gcc use to define the levels. None if no flags."""
    if not flags:
        return None
    has_lzcnt = "abm" in flags or "lzcnt" in flags
    v2 = {"cx16", "popcnt", "sse4_1", "sse4_2", "ssse3"} <= flags
    v3 = v2 and has_lzcnt and {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "movbe"} <= flags
    v4 = v3 and {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"} <= flags
    return "v4" if v4 else "v3" if v3 else "v2" if v2 else "v1"


_GPU_IDS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}


def detect_gpus(drm_root="/sys/class/drm"):
    gpus = set()
    try:
        for entry in os.listdir(drm_root):
            if re.fullmatch(r"card\d+", entry):
                vid = _read(os.path.join(drm_root, entry, "device", "vendor")).strip().lower()
                if vid in _GPU_IDS:
                    gpus.add(_GPU_IDS[vid])
    except OSError:
        pass
    if not gpus:  # e.g. headless probing or odd sysfs: fall back to lspci
        for line in capture(["lspci"], timeout=10).splitlines():
            l = line.lower()
            if "vga" in l or "3d" in l or "display" in l:
                if "nvidia" in l:
                    gpus.add("nvidia")
                if "amd" in l or "radeon" in l or "advanced micro" in l:
                    gpus.add("amd")
                if "intel" in l:
                    gpus.add("intel")
    return gpus


def detect_cloud(dmi_root="/sys/class/dmi/id"):
    """Best-effort cloud-VM detection from DMI strings: aws/azure/gcp/oracle/''."""
    vendor = _read(os.path.join(dmi_root, "sys_vendor")).strip().lower()
    product = _read(os.path.join(dmi_root, "product_name")).strip().lower()
    bios = _read(os.path.join(dmi_root, "bios_vendor")).strip().lower()
    tag = _read(os.path.join(dmi_root, "chassis_asset_tag")).strip().lower()
    if "amazon" in vendor or "amazon" in bios or "ec2" in product:
        return "aws"
    if "microsoft" in vendor and "virtual" in product or tag.startswith("7783-7084-3265"):
        return "azure"
    if "google" in vendor or "google compute" in product:
        return "gcp"
    if "oraclecloud" in tag:
        return "oracle"
    return ""


@dataclass
class HardwareInfo:
    arch: str = ""
    psabi: object = None
    cpu_vendor: str = ""
    cpu_model: str = ""
    zen4: bool = False
    gpus: set = field(default_factory=set)
    cloud: str = ""

    @property
    def is_x86_64(self):
        return self.arch == "x86_64"

    def summary(self):
        bits = [self.arch]
        if self.psabi:
            bits.append(f"x86-64-{self.psabi}")
        if self.gpus:
            bits.append("+".join(sorted(g.upper() for g in self.gpus)))
        if self.cloud:
            bits.append(f"{self.cloud.upper()} VM")
        return " · ".join(b for b in bits if b)


def detect_hardware(cpuinfo_path="/proc/cpuinfo"):
    arch = platform.machine()
    flags, vendor, model = parse_cpuinfo(_read(cpuinfo_path))
    psabi = psabi_level_from_flags(flags) if arch == "x86_64" else None
    zen4 = vendor == "AuthenticAMD" and "avx512_bf16" in flags
    return HardwareInfo(arch=arch, psabi=psabi, cpu_vendor=vendor, cpu_model=model, zen4=zen4,
                        gpus=detect_gpus(), cloud=detect_cloud())
