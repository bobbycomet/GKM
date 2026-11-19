# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import shutil

from ..distro import package_manager_binary


def create_backend(distro, hw):
    """Pick the backend for the detected distro family; falls back to whichever
    package manager is actually installed."""
    from .apt import AptBackend
    from .dnf import DnfBackend
    from .pacman import PacmanBackend
    from .zypper import ZypperBackend
    table = {"debian": AptBackend, "arch": PacmanBackend, "fedora": DnfBackend, "suse": ZypperBackend}
    cls = table.get(distro.family)
    if cls is None:
        raise RuntimeError(
            f"Unsupported distribution: {distro.pretty_name}. GKM supports Debian/Ubuntu, "
            "Arch, Fedora/RHEL and openSUSE families (and their derivatives)."
        )
    return cls(distro, hw)


def backend_tool_missing(distro):
    b = package_manager_binary(distro)
    return b if b and not shutil.which(b) else ""
