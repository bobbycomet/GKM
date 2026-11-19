# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Data model shared by backends and the UI."""
from dataclasses import dataclass, field
from typing import Callable, List


@dataclass(eq=False)
class KernelPackage:
    """One installable/removable package row. Identity-hashed so UI widgets can
    key dicts on it; selection state lives here, not in widgets."""
    name: str
    version: str = ""
    provider: str = ""
    installed: bool = False
    active: bool = False
    held: bool = False
    size: str = "—"
    kgroup: str = ""          # grouping key (kernel version / base package / evr)
    group_label: str = ""     # display text for the group card (defaults to kgroup)
    flavor: str = ""
    role: str = ""            # Image / Headers / Modules / Core / Meta ...
    is_meta: bool = False
    blocked_reason: str = ""  # non-empty: cannot be selected on this hardware
    repo: str = ""
    spec: str = ""            # what is handed to the helper: NAME or NAME=VERSION
    opt_in: bool = False      # never picked by a group click (e.g. a driver series that is not installed)
    description: str = ""     # one-line description (catalogue or the package manager's own)
    is_selected: bool = False

    def __post_init__(self):
        if not self.spec:
            self.spec = self.name

    # Aliases used by the card/button code.
    @property
    def is_installed(self):
        return self.installed

    @property
    def is_active(self):
        return self.active

    @property
    def is_held(self):
        return self.held

    @property
    def markup(self):
        held = "  <span foreground='orange'><b>[Held]</b></span>" if self.held else ""
        optional = "  <small><span foreground='gray'>optional: tick it yourself</span></small>" \
            if self.opt_in and not self.installed else ""
        ver = f" <small>({self.version})</small>" if self.version else ""
        if self.active:
            return f"<b>{self.name}</b>{ver}  <span foreground='green'><b>[Active]</b></span>{held}"
        if self.installed:
            return f"<span foreground='gray'>{self.name}{ver}  [Installed]</span>{held}"
        return f"<b>{self.name}</b>{ver}  <span foreground='#88cc88'>[Available]</span>{held}{optional}"

    @property
    def status(self):
        if self.active:
            return "Active"
        if self.held and self.installed:
            return "Held"
        return "Installed" if self.installed else "Available"


@dataclass
class Provider:
    id: str
    title: str
    layout: str = "flat"            # "flat" (one card per build) | "nested" (version -> flavor)
    hint: str = ""
    default_flavor: str = "Any"
    flavor_order: List[str] = field(default_factory=list)
    card_prefix: str = ""
    show_when_empty: bool = True


@dataclass
class RepoOffer:
    id: str
    title: str
    providers: List[str]            # tabs that show the "add repository" banner
    subcommand: str                 # gkm-helper subcommand
    present: Callable[[], bool]
    offer_on_start: bool = False
    then_upgrade: bool = False      # a full system upgrade should follow (Arch: new repo => sync + upgrade)
    description: str = ""
    warning: str = ""


@dataclass
class PreflightResult:
    """Outcome of simulating an install before any privileged command runs."""
    ok: bool = True
    packages: List[str] = field(default_factory=list)   # specs that can really be installed
    dropped: list = field(default_factory=list)         # [(spec, reason)] left out: cannot be installed here
    removals: List[str] = field(default_factory=list)   # packages the package manager would also REMOVE
    message: str = ""                                    # why nothing can be installed (ok is False)
    output: str = ""                                     # full simulation output, for the log


@dataclass
class VersionOption:
    """One restorable version of a kernel group (Arch: from the cache or the Arch Linux Archive;
    Fedora/openSUSE: an older build still available in the repositories)."""
    version: str
    sources: List[str] = field(default_factory=list)    # "installed" | "cache" | "archive" | "repo"
    installed: bool = False
    specs: List[str] = field(default_factory=list)      # NAME=VERSION for every package of the group
