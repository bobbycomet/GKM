# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Data-driven kernel catalogue.

Discovery in the backends is generic. The catalogue adds what a package list can't tell you:
a description, which tab a kernel belongs on, the repository it normally comes from and the
hardware it needs. A built-in file ships with GKM; users can extend or override it with
``~/.config/griffin-kernel-manager/kernels.json`` (same format) to teach GKM a kernel without
touching code, for example one whose headers package has an unusual name.

Entry: {"name", "headers"?, "description"?, "provider"?, "repository"?, "requires"?: {"psabi": "v3", "zen4": true}}
"""
import json
import re
from pathlib import Path

from .config import CONFIG_DIR
from .privilege import resource_dir

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._@-]*$")
_PROVIDERS = {"arch", "manjaro", "cachyos", "xanmod", "clear", "liquorix", "tkg", "other"}
_LEVELS = {"v1", "v2", "v3", "v4"}


def _clean(entry):
    """Validate one entry from a file that may be hand-edited; None if unusable."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    out = {"name": name}
    headers = entry.get("headers")
    if isinstance(headers, str) and _NAME_RE.match(headers):
        out["headers"] = headers
    if isinstance(entry.get("description"), str):
        out["description"] = entry["description"][:300]
    if entry.get("provider") in _PROVIDERS:
        out["provider"] = entry["provider"]
    if isinstance(entry.get("repository"), str) and _NAME_RE.match(entry["repository"]):
        out["repository"] = entry["repository"]
    req = entry.get("requires")
    if isinstance(req, dict):
        clean_req = {}
        if req.get("psabi") in _LEVELS:
            clean_req["psabi"] = req["psabi"]
        if req.get("zen4") is True:
            clean_req["zen4"] = True
        if clean_req:
            out["requires"] = clean_req
    return out


def load_kernel_catalog(builtin=None, user=None):
    """name -> entry. A user entry overrides the built-in one field by field."""
    catalog = {}
    for path in (builtin or resource_dir() / "kernels-arch.json", user or CONFIG_DIR / "kernels.json"):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kernels = data.get("kernels", []) if isinstance(data, dict) else []
        for raw in kernels if isinstance(kernels, list) else []:
            entry = _clean(raw)
            if entry:
                catalog[entry["name"]] = {**catalog.get(entry["name"], {}), **entry}
    return catalog
