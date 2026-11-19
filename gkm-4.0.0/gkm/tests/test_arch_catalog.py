# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import gkm.backends.pacman as pm
from gkm.backends.pacman import PacmanBackend, module_kind
from gkm.catalog import load_kernel_catalog
from gkm.ui.cards import CardsMixin
from . import fixtures as fx
from .test_rpm_arch import Patch

HELPER = Path(__file__).resolve().parent.parent / "resources" / "gkm-helper"


class CatalogLoading(unittest.TestCase):
    def write(self, d, name, data):
        p = Path(d) / name
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def test_builtin_catalogue_covers_official_and_community_kernels(self):
        cat = load_kernel_catalog(user="/nonexistent")
        for name in ("linux", "linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts", "linux-xanmod",
                     "linux-xanmod-lts", "linux-cachyos", "linux-clear", "linux-lqx", "linux-tkg-pds",
                     "linux-lts-tkg-bmq", "linux-ck", "linux-amd", "linux-nitrous"):
            self.assertIn(name, cat)
            self.assertTrue(cat[name]["description"])
        self.assertEqual(cat["linux-amd"]["requires"], {"zen4": True})
        self.assertEqual(cat["linux-nitrous"]["requires"], {"psabi": "v3"})
        self.assertEqual(cat["linux-lqx"]["provider"], "liquorix")

    def test_user_file_extends_and_overrides_field_by_field(self):
        with tempfile.TemporaryDirectory() as d:
            user = self.write(d, "kernels.json", {"kernels": [
                {"name": "linux-weird", "headers": "linux-weird-hdrs", "description": "mine", "provider": "tkg"},
                {"name": "linux-zen", "description": "my zen"}]})
            cat = load_kernel_catalog(user=user)
        self.assertEqual(cat["linux-weird"]["headers"], "linux-weird-hdrs")
        self.assertEqual(cat["linux-zen"]["description"], "my zen")
        self.assertEqual(cat["linux-zen"]["provider"], "arch")        # untouched fields survive the override

    def test_hand_edited_garbage_is_ignored_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self.write(d, "kernels.json", {"kernels": [
                {"name": "../etc/passwd"}, {"name": "-oEvil"}, {"name": "ok-one", "provider": "nonsense",
                 "requires": {"psabi": "v9", "zen4": "yes"}, "headers": "bad name"}, 42, "x", {"nope": 1}]})
            cat = load_kernel_catalog(user=bad)
            self.assertNotIn("../etc/passwd", cat)
            self.assertNotIn("-oEvil", cat)
            self.assertEqual(cat["ok-one"], {"name": "ok-one"})          # every bad field dropped, entry kept
            self.assertIn("linux-lts", cat)                              # built-ins unaffected
            for broken in ("{not json", "[]", '{"kernels": "nope"}'):
                self.assertIn("linux", load_kernel_catalog(user=self.write(d, "k2.json", broken)))


class ArchCatalogIntegration(unittest.TestCase):
    SL = """\
core linux 6.12.5.arch1-1
core linux-headers 6.12.5.arch1-1
core linux-lts 6.12.4-1
core linux-lts-headers 6.12.4-1
extra linux-lts-nvidia 565-1
extra linux-lts-nvidia-open 565-1
extra nvidia-lts 565-5
extra nvidia-open-lts 565-5
cachyos linux-cachyos 6.12.5-2
cachyos linux-cachyos-headers 6.12.5-2
cachyos linux-cachyos-nvidia-open 565-2
chaotic-aur linux-amd 6.12.5-1
chaotic-aur linux-amd-headers 6.12.5-1
chaotic-aur linux-nitrous 6.12.5-1
chaotic-aur linux-nitrous-headers 6.12.5-1
chaotic-aur linux-lqx 6.12.5-1
chaotic-aur linux-lqx-headers 6.12.5-1
chaotic-aur linux-weird 6.12.5-1
chaotic-aur linux-weird-hdrs 6.12.5-1
chaotic-aur linux-unlisted 6.12.5-1
chaotic-aur linux-unlisted-headers 6.12.5-1
"""
    Q = "linux 6.12.5.arch1-1\nlinux-headers 6.12.5.arch1-1\nlinux-cachyos 6.12.5-2\nlinux-cachyos-headers 6.12.5-2\nlinux-cachyos-nvidia-open 565-2\n"
    SI = ("Repository : chaotic-aur\nName : linux-unlisted\nVersion : 6.12.5-1\nDescription : A kernel only the package db knows about\n"
          "Installed Size : 100.00 MiB\n\n")

    def collect(self, level="v3", zen4=False, user_catalog=None):
        table = {"pacman -Sl": (0, self.SL), "pacman -Q": (0, self.Q), "pacman -Qi": (0, ""), "pacman -Si": (0, self.SI),
                 "pacman-conf": (0, "")}
        cat = load_kernel_catalog(user="/nonexistent")
        cat.update(user_catalog or {})
        orig = pm.load_kernel_catalog
        pm.load_kernel_catalog = lambda: cat
        try:
            with Patch(pm, table=table):
                b = PacmanBackend(fx.distro(ID="cachyos", ID_LIKE="arch"), fx.hw(level, ("nvidia",), zen4=zen4))
                b._running_base = lambda: "linux-cachyos"
                return {r.name: r for r in b.collect()}
        finally:
            pm.load_kernel_catalog = orig

    def test_module_kinds(self):
        self.assertEqual(module_kind("linux-cachyos-nvidia-open", "linux-cachyos"), "nvidia-open")
        self.assertEqual(module_kind("linux-lts-nvidia", "linux-lts"), "nvidia")
        self.assertEqual(module_kind("nvidia-open-lts", "linux-lts"), "nvidia-open")     # Arch's own naming
        self.assertEqual(module_kind("nvidia-lts", "linux-lts"), "nvidia")
        self.assertEqual(module_kind("nvidia-open", "linux"), "nvidia-open")

    def test_conflicting_module_kinds_are_not_all_picked_by_a_group_click(self):
        """Same bug class as the Ubuntu NVIDIA failure: nvidia and nvidia-open modules conflict."""
        rows = self.collect()
        lts = [r for r in rows.values() if r.kgroup == "linux-lts"]
        self.assertFalse(rows["linux-lts-nvidia-open"].opt_in)       # nvidia-open is what you already use
        self.assertTrue(rows["linux-lts-nvidia"].opt_in)
        self.assertFalse(rows["nvidia-open-lts"].opt_in)
        self.assertTrue(rows["nvidia-lts"].opt_in)
        picked = {r.name for r in CardsMixin._split_group_targets(None, lts)[0]}
        self.assertEqual(picked, {"linux-lts", "linux-lts-headers", "linux-lts-nvidia-open", "nvidia-open-lts"})

    def test_catalogue_adds_what_generic_discovery_cannot(self):
        rows = self.collect(user_catalog={"linux-weird": {"name": "linux-weird", "headers": "linux-weird-hdrs",
                                                           "provider": "tkg", "description": "mine"}})
        self.assertEqual(rows["linux-weird"].provider, "tkg")
        self.assertEqual(rows["linux-weird-hdrs"].role, "Headers")       # a headers package with an unusual name
        self.assertEqual(rows["linux-weird"].description, "mine")
        self.assertNotIn("linux-weird", self.collect())                  # without the catalogue entry it isn't a kernel

    def test_descriptions_come_from_the_catalogue_then_the_package_manager(self):
        rows = self.collect()
        self.assertIn("BORE", rows["linux-cachyos"].description)
        self.assertEqual(rows["linux-unlisted"].description, "A kernel only the package db knows about")
        self.assertEqual(rows["linux-lqx"].provider, "liquorix")

    def test_hardware_requirements_from_the_catalogue(self):
        rows = self.collect(level="v3", zen4=False)
        self.assertIn("Zen 4", rows["linux-amd"].blocked_reason)
        self.assertIn("Zen 4", rows["linux-amd-headers"].blocked_reason)
        self.assertEqual(rows["linux-nitrous"].blocked_reason, "")
        self.assertEqual(self.collect(level="v3", zen4=True)["linux-amd"].blocked_reason, "")
        self.assertIn("v3", self.collect(level="v2")["linux-nitrous"].blocked_reason)

    def test_installed_kernels_are_never_blocked(self):
        orig = ArchCatalogIntegration.Q
        ArchCatalogIntegration.Q = orig + "linux-amd 6.12.5-1\nlinux-amd-headers 6.12.5-1\n"
        try:
            rows = self.collect(level="v1", zen4=False)
        finally:
            ArchCatalogIntegration.Q = orig
        self.assertTrue(rows["linux-amd"].installed)
        self.assertEqual(rows["linux-amd"].blocked_reason, "")


class StubbedHelper(unittest.TestCase):
    """Run the real helper against stub package managers and bootloader tools."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.mark = self.dir / "calls.log"
        for tool in ("awk", "sed", "tr", "sort", "grep", "cp", "cat", "mktemp", "readlink", "bash", "dirname", "rm"):
            src = shutil.which(tool)
            if src:
                (self.bin / tool).symlink_to(src)
        self.addCleanup(self.tmp.cleanup)

    def stub(self, name, rc=0):
        p = self.bin / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.mark}"\nexit {rc}\n')
        p.chmod(0o755)

    def run_helper(self, *args, helper=None):
        r = subprocess.run(["bash", str(helper or HELPER), *args], env={"PATH": str(self.bin)},
                           capture_output=True, text=True)
        calls = self.mark.read_text().splitlines() if self.mark.exists() else []
        return r, calls

    def test_systemd_boot_entries_are_generated_with_sdboot_manage(self):
        self.stub("pacman")
        self.stub("sdboot-manage")
        r, calls = self.run_helper("update-bootloader")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, ["sdboot-manage gen"])
        self.assertIn("Generating systemd-boot entries", r.stdout)

    def test_a_failing_entry_tool_is_reported(self):
        self.stub("pacman")
        self.stub("sdboot-manage", rc=1)
        r, _ = self.run_helper("update-bootloader")
        self.assertEqual(r.returncode, 1)
        self.assertIn("reported a problem", r.stdout)

    def test_systemd_boot_without_an_entry_tool_says_so_honestly(self):
        self.stub("pacman")
        self.stub("bootctl")             # `bootctl is-installed` succeeds
        r, _ = self.run_helper("update-bootloader")
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemd-boot is installed but no entry generator", r.stdout)

    def test_nothing_to_do_is_not_an_error(self):
        self.stub("pacman")
        r, calls = self.run_helper("update-bootloader")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(calls, [])
        self.assertIn("No bootloader refresh was needed", r.stdout)

    def test_upgrade_system_is_pacman_only_and_takes_no_arguments(self):
        r = subprocess.run(["bash", str(HELPER), "upgrade-system", "x"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("takes no arguments", r.stderr)
        self.stub("pacman")
        r, calls = self.run_helper("upgrade-system")
        self.assertEqual(calls, ["pacman -Syu --noconfirm"])
        # on a non-pacman system it refuses before running anything
        self.mark.unlink()
        shutil.rmtree(self.bin)
        self.bin.mkdir()
        for tool in ("bash", "dirname"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.stub("apt-get")
        r, calls = self.run_helper("upgrade-system")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only available on pacman", r.stderr)
        self.assertEqual(calls, [])

    def test_chaotic_aur_setup_follows_the_published_steps(self):
        conf = self.dir / "pacman.conf"
        conf.write_text("[options]\nHoldPkg = pacman\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n")
        helper = self.dir / "h.sh"
        helper.write_text(HELPER.read_text().replace("readonly PACMAN_CONF=/etc/pacman.conf", f"readonly PACMAN_CONF={conf}"))
        self.stub("pacman")
        self.stub("pacman-key")
        r, calls = self.run_helper("add-repo-chaotic-aur", helper=helper)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(calls, [
            "pacman-key --recv-key 3056513887B78AEB --keyserver keyserver.ubuntu.com",
            "pacman-key --lsign-key 3056513887B78AEB",
            "pacman -U --noconfirm https://cdn-mirror.chaotic.cx/chaotic-aur/chaotic-keyring.pkg.tar.zst "
            "https://cdn-mirror.chaotic.cx/chaotic-aur/chaotic-mirrorlist.pkg.tar.zst",
            "pacman -Syy --noconfirm",           # forced refresh of the new repo; the upgrade is a separate, confirmed step
        ])
        text = conf.read_text()
        self.assertTrue(text.rstrip().endswith("[chaotic-aur]\nInclude = /etc/pacman.d/chaotic-mirrorlist"))   # bottom: official repos win
        self.assertTrue(text.startswith("[options]\nHoldPkg = pacman"))                                      # nothing else touched
        # idempotent: a second run changes nothing and runs no commands
        self.mark.unlink()
        r, calls = self.run_helper("add-repo-chaotic-aur", helper=helper)
        self.assertEqual((r.returncode, calls), (0, []))
        self.assertEqual(conf.read_text().count("[chaotic-aur]"), 1)


if __name__ == "__main__":
    unittest.main()
