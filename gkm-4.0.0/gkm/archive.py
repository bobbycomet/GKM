# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Where older versions of an Arch package can come from: the local pacman cache and the
Arch Linux Archive (https://archive.archlinux.org). Pure helpers, so they are easy to test;
the privileged side (gkm-helper `restore-version`) builds the same URL itself from a validated
name and version and never accepts a URL from the GUI.

Archive layout: packages/<first letter>/<name>/<name>-<pkgver>-<pkgrel>-<arch>.pkg.tar.zst
(+ a detached .sig that pacman downloads and verifies itself when given the URL)."""
import os
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import unquote

from .vercmp import evr_vercmp

ARCHIVE_HOST = "https://archive.archlinux.org"
DEFAULT_CACHE_DIR = "/var/cache/pacman/pkg"
_VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9._+~-]*$")      # no epoch (':'): kernels don't use one


def archive_dir_url(name):
    return f"{ARCHIVE_HOST}/packages/{name[0]}/{name}/"


def archive_file_url(name, version, arch, ext="zst"):
    return f"{archive_dir_url(name)}{name}-{version}-{arch}.pkg.tar.{ext}"


def _version_from_filename(filename, name, arch):
    """'linux-6.12.5.arch1-1-x86_64.pkg.tar.zst' -> '6.12.5.arch1-1' for name 'linux'.
    Rejects look-alikes: for 'linux', 'linux-lts-6.12-1-...' and 'linux-headers-...' are other packages."""
    m = re.fullmatch(re.escape(name) + r"-(.+)-" + re.escape(arch) + r"\.pkg\.tar\.(?:zst|xz)", filename)
    if not m:
        return None
    version = m.group(1)
    return version if _VERSION_RE.match(version) else None


def parse_cache_listing(filenames, name, arch):
    seen = {_version_from_filename(f, name, arch) for f in filenames}
    return sorted(seen - {None}, key=_cmp_key, reverse=True)


def list_cached_versions(name, arch, cache_dir=DEFAULT_CACHE_DIR):
    try:
        return parse_cache_listing(os.listdir(cache_dir), name, arch)
    except OSError:
        return []


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(v for k, v in attrs if k == "href" and v)


def parse_archive_index(html, name, arch):
    links = _Links()
    links.feed(html)
    files = [unquote(h.rsplit("/", 1)[-1]) for h in links.hrefs if not h.endswith(".sig")]
    return parse_cache_listing(files, name, arch)


def fetch_archive_versions(name, arch, timeout=12, opener=urllib.request.urlopen):
    """Versions the Archive holds for `name`. Raises OSError (URLError is one) when unreachable."""
    req = urllib.request.Request(archive_dir_url(name), headers={"User-Agent": "GKM (Griffin Kernel Manager)"})
    with opener(req, timeout=timeout) as resp:
        return parse_archive_index(resp.read().decode("utf-8", "replace"), name, arch)


def _cmp_key(version):
    from functools import cmp_to_key
    return cmp_to_key(evr_vercmp)(version)
