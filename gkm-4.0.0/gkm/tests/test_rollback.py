# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Rollback and version history: archive parsing, the helper's restore-version, per-family version
listings, automatic rollback after failures, and the Versions dialog."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

import gkm.backends.apt as apt_mod
import gkm.backends.dnf as dnf_mod
import gkm.backends.pacman as pm
import gkm.backends.zypper as zyp_mod
from gkm.archive import (archive_dir_url, archive_file_url, fetch_archive_versions, parse_archive_index,
                         parse_cache_listing)
from gkm.backends.apt import AptBackend
from gkm.backends.dnf import DnfBackend
from gkm.backends.pacman import PacmanBackend
from gkm.backends.zypper import ZypperBackend
from gkm.model import KernelPackage, VersionOption
from . import fixtures as fx
from .test_rpm_arch import Patch

HELPER = Path(__file__).resolve().parent.parent / "resources" / "gkm-helper"


class ArchiveParsing(unittest.TestCase):
    INDEX = '''<html><body><a href="../">../</a>
<a href="linux-6.12.5.arch1-1-x86_64.pkg.tar.zst">linux-6.12.5.arch1-1-x86_64.pkg.tar.zst</a> 09-Nov-2026 12:00
<a href="linux-6.12.5.arch1-1-x86_64.pkg.tar.zst.sig">sig</a>
<a href="linux-6.11.9.arch1-1-x86_64.pkg.tar.zst">x</a>
<a href="linux-6.9.1.arch1-1-x86_64.pkg.tar.xz">old</a>
<a href="linux-lts-6.12.4-1-x86_64.pkg.tar.zst">a different package</a>
<a href="linux-headers-6.12.5.arch1-1-x86_64.pkg.tar.zst">a different package</a></body></html>'''

    def test_index_parsing_newest_first_and_no_lookalikes(self):
        self.assertEqual(parse_archive_index(self.INDEX, "linux", "x86_64"),
                         ["6.12.5.arch1-1", "6.11.9.arch1-1", "6.9.1.arch1-1"])
        self.assertEqual(parse_archive_index(self.INDEX, "linux-lts", "x86_64"), ["6.12.4-1"])

    def test_cache_listing_rejects_other_packages_and_architectures(self):
        files = ["linux-zen-6.12.5.zen1-1-x86_64.pkg.tar.zst", "linux-zen-headers-6.12.5.zen1-1-x86_64.pkg.tar.zst",
                 "linux-zen-6.11.1.zen1-1-x86_64.pkg.tar.zst.sig", "linux-zen-6.10.2.zen1-1-aarch64.pkg.tar.zst",
                 "linux-zen-docs-6.12.5.zen1-1-x86_64.pkg.tar.zst", "unrelated.txt"]
        self.assertEqual(parse_cache_listing(files, "linux-zen", "x86_64"), ["6.12.5.zen1-1"])

    # Filenames copied from real Arch mirror listings (the Archive itself was not reachable when this was written).
    REAL = ["linux-6.17.5.arch1-1-x86_64.pkg.tar.zst", "linux-6.17.5.arch1-1-x86_64.pkg.tar.zst.sig",
            "linux-docs-6.17.5.arch1-1-x86_64.pkg.tar.zst", "linux-headers-6.17.5.arch1-1-x86_64.pkg.tar.zst",
            "linux-api-headers-6.18-1-x86_64.pkg.tar.zst", "linux-docs-6.18.3.arch1-2-x86_64.pkg.tar.zst",
            "linux-lts-6.12.63-2-x86_64.pkg.tar.zst", "linux-lts-6.12.64-1-x86_64.pkg.tar.zst",
            "linux-lts-headers-6.12.64-1-x86_64.pkg.tar.zst", "linux-lts-docs-6.12.64-1-x86_64.pkg.tar.zst",
            "linux-zen-6.18.9.zen1-1-x86_64.pkg.tar.zst", "linux-zen-headers-6.18.9.zen1-1-x86_64.pkg.tar.zst",
            "linux-zen-docs-6.18.9.zen1-1-x86_64.pkg.tar.zst", "linux-tools-meta-6.19-1-x86_64.pkg.tar.zst",
            "iptables-1:1.8.11-4-x86_64.pkg.tar.zst", "keycloak-archlinux-theme-2.0.0-1-any.pkg.tar.zst",
            "util-linux-2.41.3-2-x86_64.pkg.tar.zst"]

    def test_real_filenames_resolve_to_the_right_package(self):
        self.assertEqual(parse_cache_listing(self.REAL, "linux", "x86_64"), ["6.17.5.arch1-1"])
        self.assertEqual(parse_cache_listing(self.REAL, "linux-lts", "x86_64"), ["6.12.64-1", "6.12.63-2"])
        self.assertEqual(parse_cache_listing(self.REAL, "linux-zen", "x86_64"), ["6.18.9.zen1-1"])
        self.assertEqual(parse_cache_listing(self.REAL, "linux-headers", "x86_64"), ["6.17.5.arch1-1"])
        self.assertEqual(parse_cache_listing(self.REAL, "linux-lts-headers", "x86_64"), ["6.12.64-1"])
        self.assertEqual(parse_cache_listing(self.REAL, "linux-api-headers", "x86_64"), ["6.18-1"])
        self.assertEqual(parse_cache_listing(self.REAL, "iptables", "x86_64"), [])     # epoch versions are out of scope

    def test_urls_are_built_from_name_and_version_only(self):
        self.assertEqual(archive_dir_url("linux-cachyos"), "https://archive.archlinux.org/packages/l/linux-cachyos/")
        self.assertEqual(archive_file_url("linux", "6.12.5.arch1-1", "x86_64"),
                         "https://archive.archlinux.org/packages/l/linux/linux-6.12.5.arch1-1-x86_64.pkg.tar.zst")

    def test_fetch_uses_the_directory_listing_and_reports_network_failure(self):
        class Resp:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def read(self_):
                return ArchiveParsing.INDEX.encode()
        seen = []
        got = fetch_archive_versions("linux", "x86_64", opener=lambda req, timeout: seen.append(req.full_url) or Resp())
        self.assertEqual(seen, ["https://archive.archlinux.org/packages/l/linux/"])
        self.assertEqual(got[0], "6.12.5.arch1-1")

        def boom(req, timeout):
            raise URLError("offline")
        with self.assertRaises(OSError):
            fetch_archive_versions("linux", "x86_64", opener=boom)


class RestoreVersionHelper(unittest.TestCase):
    """The real helper against stub pacman/pacman-conf/uname."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin, self.cache = self.dir / "bin", self.dir / "cache"
        self.bin.mkdir()
        self.cache.mkdir()
        self.log = self.dir / "calls.log"
        for tool in ("bash", "dirname", "head", "grep", "sed", "cat", "tr", "awk"):
            src = shutil.which(tool)
            if src:
                (self.bin / tool).symlink_to(src)
        self.put("uname", 'echo "${FAKE_ARCH:-x86_64}"')
        self.put("pacman-conf", f'echo "{self.cache}/"')
        self.put("pacman", f'echo "pacman $*" >> "{self.log}"\n'
                           'if [ -n "$FAIL_ON" ]; then case "$*" in *$FAIL_ON*) exit 1;; esac; fi\nexit 0')

    def put(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def cached(self, *names):
        for n in names:
            (self.cache / n).write_text("x")

    def run_helper(self, *args, **env):
        r = subprocess.run(["bash", str(HELPER), "restore-version", *args], capture_output=True, text=True,
                           env={"PATH": str(self.bin), **env})
        return r, (self.log.read_text().splitlines() if self.log.exists() else [])

    def test_everything_cached_installs_offline_in_one_transaction(self):
        self.cached("linux-6.12.4.arch1-1-x86_64.pkg.tar.zst", "linux-headers-6.12.4.arch1-1-x86_64.pkg.tar.zst")
        r, calls = self.run_helper("linux=6.12.4.arch1-1", "linux-headers=6.12.4.arch1-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [f"pacman -U --noconfirm {self.cache}/linux-6.12.4.arch1-1-x86_64.pkg.tar.zst "
                                 f"{self.cache}/linux-headers-6.12.4.arch1-1-x86_64.pkg.tar.zst"])

    def test_not_cached_comes_from_the_archive_with_urls_built_by_the_helper(self):
        r, calls = self.run_helper("linux=6.12.4.arch1-1", "linux-headers=6.12.4.arch1-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, ["pacman -U --noconfirm "
                                 "https://archive.archlinux.org/packages/l/linux/linux-6.12.4.arch1-1-x86_64.pkg.tar.zst "
                                 "https://archive.archlinux.org/packages/l/linux-headers/linux-headers-6.12.4.arch1-1-x86_64.pkg.tar.zst"])

    def test_partly_cached_uses_one_source_for_everything(self):
        self.cached("linux-6.12.4.arch1-1-x86_64.pkg.tar.zst")          # headers missing from the cache
        r, calls = self.run_helper("linux=6.12.4.arch1-1", "linux-headers=6.12.4.arch1-1")
        self.assertEqual(len(calls), 1)
        self.assertIn("archive.archlinux.org", calls[0])
        self.assertNotIn(str(self.cache), calls[0])

    def test_a_failing_cache_install_falls_back_to_the_archive(self):
        self.cached("linux-6.12.4.arch1-1-x86_64.pkg.tar.zst")
        r, calls = self.run_helper("linux=6.12.4.arch1-1", FAIL_ON="*cache/*")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn(str(self.cache), calls[0])
        self.assertIn("archive.archlinux.org", calls[1])

    def test_old_packages_use_the_xz_extension_when_zst_is_not_there(self):
        r, calls = self.run_helper("linux=5.4.1.arch1-1", FAIL_ON="*.zst*")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c.rsplit(".", 1)[-1] for c in calls], ["zst", "xz"])

    def test_total_failure_is_an_error(self):
        r, calls = self.run_helper("linux=6.12.4.arch1-1", FAIL_ON="*")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not restore", r.stderr)

    def test_hostile_or_malformed_arguments_are_rejected_before_pacman_runs(self):
        for args, why in [(["linux"], "needs NAME=VERSION"), (["linux=1:2.0-1"], "epoch"), (["linux=abc"], "must start"),
                          (["linux=6.1;id"], "invalid"), (["-oEvil=1.0"], "invalid"), (["a b=1.0"], "invalid"),
                          (["linux=../../x"], "invalid")]:
            with self.subTest(args=args):
                r, calls = self.run_helper(*args)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(calls, [])

    def test_only_x86_64_and_only_on_pacman_systems(self):
        r, calls = self.run_helper("linux=6.12.4-1", FAKE_ARCH="aarch64")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("x86_64", r.stderr)
        self.assertEqual(calls, [])
        (self.bin / "pacman").unlink()
        self.put("apt-get", "exit 0")
        r, _ = self.run_helper("linux=6.12.4-1")
        self.assertIn("only available on pacman", r.stderr)


def krow(name, version, role="Kernel", installed=True, provider="arch", kgroup="linux", flavor="Stable", spec=None):
    return KernelPackage(name=name, version=version, provider=provider, installed=installed, kgroup=kgroup,
                         flavor=flavor, role=role, spec=spec or name)


class VersionListings(unittest.TestCase):
    def pacman(self, cached, archived, reachable=True, last_rows=()):
        b = PacmanBackend(fx.distro(ID="arch"), fx.hw())
        b._cache_dir = lambda: "/cache"
        b._last_rows = list(last_rows)
        orig = (pm.list_cached_versions, pm.fetch_archive_versions)
        pm.list_cached_versions = lambda n, arch, d: cached.get(n, [])

        def fetch(n, arch):
            if not reachable:
                raise URLError("offline")
            return archived.get(n, [])
        pm.fetch_archive_versions = fetch
        self.addCleanup(lambda: setattr(pm, "list_cached_versions", orig[0]) or setattr(pm, "fetch_archive_versions", orig[1]))
        scope = [krow("linux", "6.12.5.arch1-1"), krow("linux-headers", "6.12.5.arch1-1", role="Headers")]
        return b, b.list_versions(scope)

    def test_pacman_only_offers_versions_every_package_has_from_one_source(self):
        _, (opts, notes) = self.pacman(
            cached={"linux": ["6.12.4.arch1-1"], "linux-headers": ["6.12.4.arch1-1"]},
            archived={"linux": ["6.12.5.arch1-1", "6.12.4.arch1-1", "6.11.9.arch1-1", "6.10.1.arch1-1"],
                      "linux-headers": ["6.12.5.arch1-1", "6.12.4.arch1-1", "6.11.9.arch1-1"]})   # 6.10.1: no headers
        self.assertEqual([o.version for o in opts], ["6.12.5.arch1-1", "6.12.4.arch1-1", "6.11.9.arch1-1"])
        by = {o.version: o for o in opts}
        self.assertEqual(by["6.12.5.arch1-1"].sources, ["installed", "archive"])
        self.assertTrue(by["6.12.5.arch1-1"].installed)
        self.assertEqual(by["6.12.4.arch1-1"].sources, ["cache", "archive"])
        self.assertEqual(by["6.11.9.arch1-1"].sources, ["archive"])
        self.assertEqual(by["6.12.4.arch1-1"].specs, ["linux=6.12.4.arch1-1", "linux-headers=6.12.4.arch1-1"])

    def test_offline_still_lists_cached_versions_and_says_so(self):
        _, (opts, notes) = self.pacman(cached={"linux": ["6.12.4.arch1-1"], "linux-headers": ["6.12.4.arch1-1"]},
                                       archived={}, reachable=False)
        self.assertEqual([o.version for o in opts], ["6.12.5.arch1-1", "6.12.4.arch1-1"])
        self.assertTrue(any("could not be reached" in n for n in notes))

    def test_driver_modules_are_called_out_not_silently_ignored(self):
        mod = krow("linux-cachyos-nvidia-open", "565-2", role="Modules", kgroup="linux")
        _, (opts, notes) = self.pacman(cached={}, archived={}, last_rows=[mod])
        self.assertTrue(any("NOT rolled back" in n and "nvidia-open" in n for n in notes))

    def test_scope_is_kernel_plus_headers_only_on_arch(self):
        rows = [krow("linux", "1"), krow("linux-headers", "1", role="Headers"),
                krow("nvidia", "5", role="Modules"), krow("linux-lts", "1", kgroup="linux-lts")]
        b = PacmanBackend(fx.distro(ID="arch"), fx.hw())
        self.assertEqual({r.name for r in b.version_scope(rows[0], rows)}, {"linux", "linux-headers"})

    def test_dnf_lists_older_builds_still_in_the_repositories(self):
        out = ("kernel-core|6.12.5-200.fc41|x86_64\nkernel-core|6.11.8-300.fc41|x86_64\nkernel-core|6.10.2-100.fc41|x86_64\n"
               "kernel-modules|6.12.5-200.fc41|x86_64\nkernel-modules|6.11.8-300.fc41|x86_64\n")        # 6.10.2: modules gone
        scope = [krow("kernel-core", "6.12.5-200.fc41", provider="distro", kgroup="6.12.5-200.fc41", flavor="Standard"),
                 krow("kernel-modules", "6.12.5-200.fc41", provider="distro", kgroup="6.12.5-200.fc41", flavor="Standard")]
        with Patch(dnf_mod, table={"dnf -q repoquery": (0, out)}) as fake:
            opts, notes = DnfBackend(fx.distro(ID="fedora"), fx.hw()).list_versions(scope)
        self.assertIn("--showduplicates", fake.calls[0])
        self.assertEqual([o.version for o in opts], ["6.12.5-200.fc41", "6.11.8-300.fc41"])
        self.assertEqual(opts[1].specs, ["kernel-core=6.11.8-300.fc41", "kernel-modules=6.11.8-300.fc41"])
        self.assertEqual(opts[0].sources, ["installed", "repo"])

    def test_dnf_explains_why_only_one_build_is_offered(self):
        scope = [krow("kernel-core", "6.12.5-200.fc41", provider="distro", flavor="Standard")]
        with Patch(dnf_mod, table={"dnf -q repoquery": (0, "kernel-core|6.12.5-200.fc41|x86_64\n")}):
            opts, notes = DnfBackend(fx.distro(ID="fedora"), fx.hw()).list_versions(scope)
        self.assertEqual(len(opts), 1)
        self.assertTrue(any("normally keeps just the latest" in n for n in notes))

    def test_zypper_lists_every_edition_the_repos_offer(self):
        xml = ('<stream><search-result><solvable-list>'
               '<solvable status="not-installed" name="kernel-default" edition="6.13.0-1.1" arch="x86_64" repository="repo-oss"/>'
               '<solvable status="not-installed" name="kernel-default" edition="6.12.2-1.1" arch="x86_64" repository="repo-oss"/>'
               '<solvable status="installed" name="kernel-default" edition="6.12.0-1.1" arch="x86_64" repository="@System"/>'
               '<solvable status="not-installed" name="kernel-default" edition="6.12.2-1.1" arch="aarch64" repository="repo-oss"/>'
               '</solvable-list></search-result></stream>')
        scope = [krow("kernel-default", "6.12.0-1.1", provider="opensuse", flavor="Default")]
        with Patch(zyp_mod, table={"zypper --xmlout": (0, xml)}):
            opts, _ = ZypperBackend(fx.distro(ID="opensuse-tumbleweed", ID_LIKE="opensuse suse"), fx.hw()).list_versions(scope)
        self.assertEqual([o.version for o in opts], ["6.13.0-1.1", "6.12.2-1.1", "6.12.0-1.1"])
        self.assertTrue(opts[2].installed)
        self.assertEqual(opts[0].specs, ["kernel-default=6.13.0-1.1"])

    def test_apt_has_no_picker_because_every_abi_is_its_own_package(self):
        self.assertFalse(AptBackend(fx.distro(ID="ubuntu"), fx.hw()).has_versions)
        self.assertEqual(AptBackend(fx.distro(ID="ubuntu"), fx.hw()).list_versions([]), ([], []))

    def test_only_a_rolling_distro_restores_after_a_failed_upgrade(self):
        self.assertTrue(PacmanBackend(fx.distro(ID="arch"), fx.hw()).restores_after_failed_upgrade)
        for b in (DnfBackend(fx.distro(ID="fedora"), fx.hw()), AptBackend(fx.distro(ID="ubuntu"), fx.hw()),
                  ZypperBackend(fx.distro(ID="opensuse-tumbleweed", ID_LIKE="opensuse suse"), fx.hw())):
            self.assertFalse(b.restores_after_failed_upgrade)

    def test_half_installed_packages_count_as_installed_so_a_failed_install_can_be_cleaned(self):
        dpkg = ("linux-image-6.17.0-20-generic\t6.17.0-20.20\tiF \t1\nlinux-headers-6.17.0-20-generic\t6.17.0-20.20\tiU \t1\n"
                "linux-modules-6.17.0-20-generic\t6.17.0-20.20\trc \t1\nlinux-generic\t6.17.0.20\tii \t1\n")
        orig, apt_mod.run_host = apt_mod.run_host, fx.FakeRun({"dpkg-query": (0, dpkg)})
        try:
            st = AptBackend(fx.distro(ID="ubuntu"), fx.hw())._dpkg_status()
        finally:
            apt_mod.run_host = orig
        self.assertTrue(st["linux-image-6.17.0-20-generic"][0])        # half-configured
        self.assertTrue(st["linux-headers-6.17.0-20-generic"][0])      # unpacked
        self.assertFalse(st["linux-modules-6.17.0-20-generic"][0])     # only config files left
        self.assertTrue(st["linux-generic"][0])


try:
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except Exception:       # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not available")
class RollbackFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(["gkm-test"])
        cls.app.setProperty("gkm_smoke", True)

    def setUp(self):
        from gkm.ui.window import KernelManagerWindow
        self.backend = PacmanBackend(fx.distro(ID="arch"), fx.hw())
        self.win = KernelManagerWindow(self.backend, self.backend.distro, self.backend.hw)
        m = self.m = self.win.manager
        self.sent, self.errors, self.toasts, self.rc, self.collects = [], [], [], {}, 0
        self.after = []
        self.before_rows = [krow("linux", "6.12.4-1"), krow("linux-headers", "6.12.4-1", role="Headers"),
                            krow("linux-lts", "6.12.4-1", kgroup="linux-lts")]
        self.after_rows = list(self.before_rows)
        m._on_kernels_loaded(list(self.before_rows))
        m._require_helper = lambda proceed: proceed()
        m._stream_subprocess = self._stream
        m._async = lambda fn, cb: cb(self._safe(fn))
        m._reload_kernels_async = lambda refresh=None: None
        m._error_dialog = lambda title, msg: self.errors.append((title, msg))
        m._show_toast = lambda msg, timeout=3: self.toasts.append(msg)
        m._run_bootloader_refresh = lambda on_complete=None: self.after.append("bootloader")
        m._dkms_for_new_kernels_then_reboot = lambda: self.after.append("dkms")
        self.backend.collect = self._collect

    def _safe(self, fn):
        try:
            return fn()
        except Exception as e:      # noqa: BLE001
            return e

    def _collect(self, refresh=False):
        self.collects += 1
        return self.after_rows

    def _stream(self, cmd, done):
        self.sent.append(cmd[2:])
        done(self.rc.get(cmd[2], 0), "")

    # ── automatic upgrade after adding Chaotic-AUR ───────────────────────────
    def test_adding_chaotic_aur_runs_the_full_upgrade_on_its_own(self):
        offer = next(o for o in self.m.offers if o.id == "chaotic-aur")
        self.assertTrue(offer.then_upgrade)
        self.assertIn("FULL SYSTEM UPGRADE", offer.warning)            # the dialog that asks for consent says so
        self.m._add_repos([offer])
        self.assertEqual(self.sent, [["add-repo-chaotic-aur"], ["upgrade-system"]])
        self.assertEqual(self.errors, [])
        self.assertTrue(any("upgraded" in t for t in self.toasts))
        self.assertIsNone(self.m._log_handle)                           # log session closed at the end

    def test_a_failed_repo_add_does_not_upgrade(self):
        self.rc["add-repo-chaotic-aur"] = 1
        self.m._add_repos([next(o for o in self.m.offers if o.id == "chaotic-aur")])
        self.assertEqual(self.sent, [["add-repo-chaotic-aur"]])
        self.assertEqual(self.errors[0][0], "Failed to add Chaotic-AUR")

    def test_other_repositories_never_trigger_an_upgrade(self):
        from gkm.model import RepoOffer
        self.m._add_repos([RepoOffer("x", "X", ["arch"], "add-repo-xanmod", lambda: False)])
        self.assertEqual(self.sent, [["add-repo-xanmod"]])

    # ── automatic restore after a failed upgrade (Arch) ──────────────────────
    def upgrade_fails_and_kernel_changed(self):
        self.rc["upgrade-system"] = 1
        self.after_rows = [krow("linux", "6.12.5-1"), krow("linux-headers", "6.12.5-1", role="Headers"),
                           krow("linux-lts", "6.12.4-1", kgroup="linux-lts")]       # lts unchanged

    def test_failed_upgrade_restores_only_the_kernels_that_changed(self):
        self.upgrade_fails_and_kernel_changed()
        self.m._add_repos([next(o for o in self.m.offers if o.id == "chaotic-aur")])
        self.assertEqual(self.sent[-1], ["restore-version", "linux=6.12.4-1", "linux-headers=6.12.4-1"])
        self.assertEqual(self.after, ["bootloader"])
        self.assertEqual(self.errors[-1][0], "Upgrade failed, rolled back")
        self.assertIn("linux=6.12.4-1", self.errors[-1][1])

    def test_failed_upgrade_that_changed_nothing_restores_nothing(self):
        self.rc["upgrade-system"] = 1
        self.m._add_repos([next(o for o in self.m.offers if o.id == "chaotic-aur")])
        self.assertEqual([c[0] for c in self.sent], ["add-repo-chaotic-aur", "upgrade-system"])
        self.assertIn("unchanged", self.errors[-1][1])

    def test_a_kernel_removed_by_the_failed_upgrade_is_restored_too(self):
        self.rc["upgrade-system"] = 1
        self.after_rows = [krow("linux-lts", "6.12.4-1", kgroup="linux-lts")]        # linux + headers vanished
        self.m._add_repos([next(o for o in self.m.offers if o.id == "chaotic-aur")])
        self.assertEqual(self.sent[-1], ["restore-version", "linux=6.12.4-1", "linux-headers=6.12.4-1"])

    def test_rollback_can_be_switched_off(self):
        self.upgrade_fails_and_kernel_changed()
        self.m.chk_rollback.setChecked(False)
        self.m._add_repos([next(o for o in self.m.offers if o.id == "chaotic-aur")])
        self.assertNotIn("restore-version", [c[0] for c in self.sent])
        self.assertEqual(self.collects, 0)
        self.assertIn("switched off", self.errors[-1][1])

    def test_a_rollback_that_itself_fails_gives_manual_instructions(self):
        self.upgrade_fails_and_kernel_changed()
        self.rc["restore-version"] = 1
        self.m._add_repos([next(o for o in self.m.offers if o.id == "chaotic-aur")])
        self.assertIn("did not complete", self.errors[-1][0])
        self.assertIn("pacman -U", self.errors[-1][1])
        self.assertEqual(self.after, [])

    # ── cleanup after a failed install (all families) ────────────────────────
    def test_failed_install_removes_what_it_left_behind(self):
        self.after_rows = [krow("linux-zen", "6.12.5-1", kgroup="linux-zen"), krow("linux-zen-headers", "6.12.5-1", role="Headers", installed=False)]
        self.m._on_install_done(1, "", ["linux-zen", "linux-zen-headers"])
        self.assertEqual(self.sent, [["remove", "linux-zen"]])            # only the one that actually got installed
        self.assertEqual(self.errors[-1][0], "Install failed, rolled back")

    def test_failed_install_that_left_nothing_just_reports_the_failure(self):
        self.after_rows = [krow("linux-zen", "6.12.5-1", installed=False)]
        self.m._on_install_done(1, "", ["linux-zen"])
        self.assertEqual(self.sent, [])
        self.assertIn("Nothing was left behind", self.errors[-1][1])

    def test_failed_install_cleanup_respects_the_setting(self):
        self.m.chk_rollback.setChecked(False)
        self.m._on_install_done(1, "", ["linux-zen"])
        self.assertEqual((self.sent, self.collects), ([], 0))
        self.assertEqual(self.errors[-1][0], "Install failed")

    def test_successful_install_is_untouched(self):
        self.m._post_install = lambda: self.after.append("post")
        self.m._on_install_done(0, "", ["linux-zen"])
        self.assertEqual((self.sent, self.collects, self.after), ([], 0, ["post"]))

    # ── Versions… ────────────────────────────────────────────────────────────
    def fake_dialog(self, chosen, hold):
        import gkm.ui.manager as mgr
        outer = self

        class FakeDialog:
            def __init__(d, parent, title, default_hold=False):
                outer.title, outer.default_hold = title, default_hold
                d.chosen, d.hold = chosen, hold

            def set_result(d, result):
                outer.listed = result

            def exec(d):
                return 0
        orig = mgr.VersionsDialog
        mgr.VersionsDialog = FakeDialog
        self.addCleanup(lambda: setattr(mgr, "VersionsDialog", orig))

    def pick(self, name):
        next(r for r in self.m._all_rows() if r.name == name).is_selected = True

    def test_versions_without_a_selection_explains_itself(self):
        self.m._show_versions()
        self.assertIn("Tick a kernel", self.toasts[-1])

    def test_versions_needs_one_kernel_at_a_time(self):
        self.pick("linux")
        self.pick("linux-lts")
        self.m._show_versions()
        self.assertIn("one kernel at a time", self.toasts[-1])

    def test_restoring_a_version_on_arch_uses_restore_version_then_holds_then_post_steps(self):
        opt = VersionOption("6.12.3-1", ["archive"], False, ["linux=6.12.3-1", "linux-headers=6.12.3-1"])
        self.fake_dialog(opt, hold=True)
        self.backend.list_versions = lambda scope: ([opt], [])
        self.pick("linux")
        self.m._show_versions()
        self.assertEqual(self.sent, [["restore-version", "linux=6.12.3-1", "linux-headers=6.12.3-1"],
                                     ["hold", "linux=6.12.3-1", "linux-headers=6.12.3-1"]])
        self.assertTrue(self.default_hold)                               # holding is the sensible default on Arch
        self.assertEqual(self.after, ["bootloader"])
        self.assertIn("linux", self.title)

    def test_restoring_without_hold_and_a_refused_install(self):
        opt = VersionOption("6.12.3-1", ["cache"], False, ["linux=6.12.3-1", "linux-headers=6.12.3-1"])
        self.fake_dialog(opt, hold=False)
        self.backend.list_versions = lambda scope: ([opt], [])
        self.pick("linux")
        self.m._show_versions()
        self.assertEqual([c[0] for c in self.sent], ["restore-version"])
        self.sent.clear()
        self.after.clear()
        self.rc["restore-version"] = 1
        self.m._show_versions()
        self.assertEqual(self.after, [])                                 # nothing downstream after a refusal
        self.assertEqual(self.errors[-1][0], "Could not install that version")

    def test_cancelling_the_dialog_changes_nothing(self):
        self.fake_dialog(None, hold=False)
        self.backend.list_versions = lambda scope: ([], [])
        self.pick("linux")
        self.m._show_versions()
        self.assertEqual(self.sent, [])

    def test_on_fedora_an_older_build_is_a_plain_install_and_never_auto_removed(self):
        from gkm.ui.window import KernelManagerWindow
        b = DnfBackend(fx.distro(ID="fedora"), fx.hw())
        win = KernelManagerWindow(b, b.distro, b.hw)
        m = win.manager
        rows = [krow("kernel-core", "6.12.5-200.fc41", provider="distro", kgroup="6.12.5-200.fc41", flavor="Standard", spec="kernel-core=6.12.5-200.fc41")]
        m._on_kernels_loaded(rows)
        sent, after = [], []
        m._require_helper = lambda p: p()
        m._stream_subprocess = lambda cmd, done: (sent.append(cmd[2:]), done(0, ""))
        m._reload_kernels_async = lambda refresh=None: None
        m._run_bootloader_refresh = lambda on_complete=None: after.append("bootloader")
        m.chk_auto_rm.setChecked(True)                                   # must NOT remove the older build we just installed
        auto = []
        m._auto_remove_old_kernels = lambda *a, **k: auto.append(1)
        opt = VersionOption("6.11.8-300.fc41", ["repo"], False, ["kernel-core=6.11.8-300.fc41"])
        m._restore_version(opt, hold=False)
        self.assertEqual(sent, [["install", "kernel-core=6.11.8-300.fc41"]])
        self.assertEqual((auto, after), ([], ["bootloader"]))


@unittest.skipUnless(HAVE_QT, "PyQt6 not available")
class VersionsDialogWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(["gkm-test"])

    def test_selection_rules(self):
        from gkm.ui.versions import VersionsDialog
        d = VersionsDialog(None, "Versions of linux", default_hold=True)
        self.assertTrue(d.chk_hold.isChecked())
        self.assertFalse(d.btn_install.isEnabled())
        opts = [VersionOption("6.12.5-1", ["installed", "archive"], True, ["linux=6.12.5-1"]),
                VersionOption("6.12.4-1", ["cache", "archive"], False, ["linux=6.12.4-1"])]
        d.set_result((opts, ["a note"]))
        self.assertEqual(d.list.count(), 2)
        self.assertIn("installed", d.list.item(0).text())
        d.list.setCurrentRow(0)
        self.assertFalse(d.btn_install.isEnabled())                      # the version you already run can't be "restored"
        d._accept_if_ok()
        self.assertIsNone(d.chosen)
        d.list.setCurrentRow(1)
        self.assertTrue(d.btn_install.isEnabled())
        d.chk_hold.setChecked(False)
        d._accept_if_ok()
        self.assertEqual((d.chosen.version, d.hold), ("6.12.4-1", False))

    def test_errors_are_shown_not_raised(self):
        from gkm.ui.versions import VersionsDialog
        d = VersionsDialog(None, "t")
        d.set_result(OSError("boom"))
        self.assertIn("boom", d.status.text())


if __name__ == "__main__":
    unittest.main()
