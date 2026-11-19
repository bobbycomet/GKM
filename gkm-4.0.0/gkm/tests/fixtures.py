# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Realistic command output used to exercise backends that cannot run in CI."""
from gkm.distro import detect_distro
from gkm.hardware import HardwareInfo


def hw(level="v3", gpus=("nvidia",), arch="x86_64", zen4=False):
    return HardwareInfo(arch=arch, psabi=level, cpu_vendor="AuthenticAMD", zen4=zen4, gpus=set(gpus))


def distro(**osr):
    return detect_distro(osr, check_ro=False, ostree_marker="/nonexistent")


class FakeRun:
    """Callable replacing run_host: maps a command prefix to (rc, stdout)."""
    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, cmd, timeout=120, input_text=None, merge_stderr=False):
        self.calls.append(list(cmd))
        best = None
        for prefix, result in self.table.items():
            p = prefix.split()
            if list(cmd[:len(p)]) == p and (best is None or len(p) > len(best[0])):
                best = (p, result)
        return best[1] if best else (127, "")


PACMAN_SL = """\
core linux 6.12.5.arch1-1 [installed]
core linux-headers 6.12.5.arch1-1 [installed]
core linux-lts 6.12.4-1
core linux-lts-headers 6.12.4-1
extra linux-zen 6.12.5.zen1-1
extra linux-zen-headers 6.12.5.zen1-1
extra nvidia-lts 565.57.01-5
extra linux-api-headers 6.10-1
core linux-firmware 20241210-1
extra linux-docs 6.12.5.arch1-1
cachyos linux-cachyos 6.12.5-2 [installed]
cachyos linux-cachyos-headers 6.12.5-2 [installed]
cachyos linux-cachyos-nvidia-open 565.57.01-2 [installed]
cachyos linux-cachyos-lts 6.6.65-1
cachyos linux-cachyos-lts-headers 6.6.65-1
cachyos-v3 linux-cachyos 6.12.5-2
cachyos-v4 linux-cachyos-rt-bore 6.12.5-1
cachyos-v4 linux-cachyos-rt-bore-headers 6.12.5-1
chaotic-aur linux-xanmod 6.12.5-1
chaotic-aur linux-xanmod-headers 6.12.5-1
"""
PACMAN_Q = """\
linux 6.12.5.arch1-1
linux-headers 6.12.5.arch1-1
linux-cachyos 6.12.5-2
linux-cachyos-headers 6.12.5-2
linux-cachyos-nvidia-open 565.57.01-2
linux-tkg-bore 6.11.1-1
linux-tkg-bore-headers 6.11.1-1
bash 5.2-1
"""
PACMAN_SI = """\
Repository      : core
Name            : linux-lts
Version         : 6.12.4-1
Installed Size  : 140.50 MiB

Repository      : cachyos
Name            : linux-cachyos-lts
Version         : 6.6.65-1
Installed Size  : 150.00 MiB

Repository      : cachyos-v4
Name            : linux-cachyos-rt-bore
Version         : 6.12.5-1
Installed Size  : 160.00 MiB
"""
PACMAN_QI = """\
Name            : linux
Version         : 6.12.5.arch1-1
Installed Size  : 141.25 MiB

Name            : linux-cachyos
Version         : 6.12.5-2
Installed Size  : 152.00 MiB
"""

RPM_QA_DNF = (
    "kernel-core\t0\t6.11.4\t301.fc41\tx86_64\t79000000\n"
    "kernel-modules-core\t0\t6.11.4\t301.fc41\tx86_64\t30000000\n"
    "kernel-modules\t0\t6.11.4\t301.fc41\tx86_64\t60000000\n"
    "kernel-core\t0\t6.11.8\t300.fc41\tx86_64\t79500000\n"
    "kernel-modules\t0\t6.11.8\t300.fc41\tx86_64\t60500000\n"
    "kernel-devel\t0\t6.11.8\t300.fc41\tx86_64\t90000000\n"
    "kernel-headers\t0\t6.11.8\t300.fc41\tx86_64\t6000000\n"
    "kernel-tools\t0\t6.11.8\t300.fc41\tx86_64\t3000000\n"
)
DNF_REPOQUERY = (
    "kernel-core|6.12.5-200.fc41|x86_64\nkernel-modules|6.12.5-200.fc41|x86_64\n"
    "kernel-modules-core|6.12.5-200.fc41|x86_64\nkernel-devel|6.12.5-200.fc41|x86_64\n"
    "kernel-headers|6.12.5-200.fc41|x86_64\nkernel-tools|6.12.5-200.fc41|x86_64\n"
    "kernel-core|6.11.8-300.fc41|x86_64\n"
    "kernel-cachyos|6.12.4-cachyos1.fc41|x86_64\nkernel-cachyos-lts|6.6.64-cachyos1.fc41|x86_64\n"
    "kernel-debug-core|6.12.5-200.fc41|x86_64\nkernel-uki-virt|6.12.5-200.fc41|x86_64\n"
    "kernel-modules-internal|6.12.5-200.fc41|x86_64\n"
)

ZYPPER_XML = """<?xml version='1.0'?>
<stream><search-result version="0.0"><solvable-list>
<solvable status="installed" name="kernel-default" kind="package" edition="6.12.0-1.1" arch="x86_64" repository="@System"/>
<solvable status="not-installed" name="kernel-default" kind="package" edition="6.12.2-1.1" arch="x86_64" repository="repo-oss"/>
<solvable status="not-installed" name="kernel-default" kind="package" edition="6.13.0-1.1" arch="x86_64" repository="Kernel_stable_Backport"/>
<solvable status="not-installed" name="kernel-default-devel" kind="package" edition="6.13.0-1.1" arch="x86_64" repository="Kernel_stable_Backport"/>
<solvable status="not-installed" name="kernel-preempt" kind="package" edition="6.12.2-1.1" arch="x86_64" repository="repo-oss"/>
<solvable status="not-installed" name="kernel-default" kind="package" edition="6.12.2-1.1" arch="aarch64" repository="repo-oss"/>
<solvable status="not-installed" name="kernel-source" kind="package" edition="6.12.2-1.1" arch="noarch" repository="repo-oss"/>
<solvable status="not-installed" name="kernel-syms" kind="package" edition="6.12.2-1.1" arch="x86_64" repository="repo-oss"/>
</solvable-list></search-result></stream>
"""
RPM_QA_SUSE = (
    "kernel-default\t0\t6.12.0\t1.1\tx86_64\t200000000\n"
    "kernel-default-devel\t0\t6.12.0\t1.1\tx86_64\t50000000\n"
    "kernel-devel\t0\t6.12.0\t1.1\tnoarch\t90000000\n"
)


# Real lines from an `apt-get install` that failed on Ubuntu 24.04 when a whole kernel group, including
# every NVIDIA driver series, was selected. (Excerpt of a user's GKM log.)
APT_UNMET_NVIDIA = """\
Reading package lists...
Building dependency tree...
Reading state information...
Some packages could not be installed. This may mean that you have
requested an impossible situation or if you are using the unstable
distribution that some required packages have not yet been created
or been moved out of Incoming.
The following information may help to resolve the situation:

The following packages have unmet dependencies:
 linux-modules-nvidia-580-open-6.17.0-42-generic : Depends: nvidia-kernel-common-580 (<= 580.173.02-1) but 580.178.04-0ubuntu0.24.04.1 is to be installed
 linux-modules-nvidia-595-open-aws-6.17 : Depends: nvidia-kernel-common-595 (>= 595.84) but it is not installable
 linux-modules-nvidia-595-server-open-6.17.0-42-generic : Depends: nvidia-kernel-common-595-server (<= 595.71.05-1) but it is not installable
                                                          Depends: nvidia-kernel-common-595-server (>= 595.71.05) but it is not installable
 nvidia-kernel-common-610 : Depends: nvidia-kernel-common-615 but it is not installable
E: Unable to correct problems, you have held broken packages.
"""
APT_SIM_OK = "Reading package lists...\nThe following NEW packages will be installed:\n  linux-image-6.17.0-42-generic\nInst linux-image-6.17.0-42-generic (6.17.0-42.42 Ubuntu:24.04/noble-updates [amd64])\n"
