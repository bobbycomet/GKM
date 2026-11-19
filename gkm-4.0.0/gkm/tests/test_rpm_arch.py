# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import unittest

import gkm.backends.dnf as dnf_mod
import gkm.backends.pacman as pac_mod
import gkm.backends.rpm_common as rpm_mod
import gkm.backends.zypper as zyp_mod
from gkm.backends.dnf import DnfBackend, kernel_base as dnf_base
from gkm.backends.pacman import (PacmanBackend, flavor_for_base, kernel_bases, module_packages,
                                 parse_pacman_info, provider_for_base, repo_required_level)
from gkm.backends.zypper import ZypperBackend
from . import fixtures as fx


class Patch:
    def __init__(self, *mods, table):
        self.mods, self.fake = mods, fx.FakeRun(table)
        self.saved = []

    def __enter__(self):
        for m in self.mods:
            self.saved.append(m.run_host)
            m.run_host = self.fake
        return self.fake

    def __exit__(self, *a):
        for m, o in zip(self.mods, self.saved):
            m.run_host = o


class PacmanTests(unittest.TestCase):
    def test_generic_kernel_discovery(self):
        names = {l.split()[1] for l in fx.PACMAN_SL.splitlines()} | {"linux-tkg-bore", "linux-tkg-bore-headers"}
        bases = kernel_bases(names)
        self.assertEqual(bases, {"linux", "linux-lts", "linux-zen", "linux-cachyos", "linux-cachyos-lts",
                                 "linux-cachyos-rt-bore", "linux-xanmod", "linux-tkg-bore"})
        self.assertNotIn("linux-api", bases)          # linux-api-headers is not a kernel
        self.assertEqual(module_packages("linux-lts", names), {"nvidia-lts"})
        self.assertEqual(module_packages("linux-cachyos", names), {"linux-cachyos-nvidia-open"})

    def test_provider_and_flavor_labels(self):
        self.assertEqual(provider_for_base("linux-cachyos-bore"), "cachyos")
        self.assertEqual(provider_for_base("linux-xanmod-lts"), "xanmod")
        self.assertEqual(provider_for_base("linux-clear"), "clear")
        self.assertEqual(provider_for_base("linux612"), "manjaro")
        self.assertEqual(provider_for_base("linux-zen"), "arch")
        self.assertEqual(provider_for_base("linux-tkg-bore"), "tkg")
        self.assertEqual(provider_for_base("linux-lts-tkg-bmq"), "tkg")
        self.assertEqual(provider_for_base("linux-lqx"), "liquorix")
        self.assertEqual(provider_for_base("linux-ck"), "other")
        self.assertEqual(flavor_for_base("linux-cachyos-rt-bore", "cachyos"), "RT BORE")
        self.assertEqual(flavor_for_base("linux-cachyos", "cachyos"), "Default")
        self.assertEqual(flavor_for_base("linux612-rt", "manjaro"), "6.12 RT")
        self.assertEqual(flavor_for_base("linux-amd", "other"), "AMD")
        self.assertEqual(flavor_for_base("linux-lts-tkg-bmq", "tkg"), "LTS TKG BMQ")
        self.assertEqual(repo_required_level("cachyos-v3"), "v3")
        self.assertEqual(repo_required_level("cachyos-extra-znver4"), "znver4")
        self.assertEqual(repo_required_level("core"), "")

    def collect(self, level="v3", gpus=("nvidia",), base="linux-cachyos", **osr):
        table = {"pacman -Sl": (0, fx.PACMAN_SL), "pacman -Q": (0, fx.PACMAN_Q), "pacman -Qi": (0, fx.PACMAN_QI),
                 "pacman -Si": (0, fx.PACMAN_SI), "pacman-conf IgnorePkg": (0, "linux-cachyos linux-cachyos-headers\n")}
        with Patch(pac_mod, table=table):
            b = PacmanBackend(fx.distro(**(osr or dict(ID="cachyos", ID_LIKE="arch"))), fx.hw(level, gpus))
            b.running_release = lambda: "6.12.5-2-cachyos"
            b._running_base = lambda: base
            return b, {r.name: r for r in b.collect()}

    def test_collect(self):
        b, rows = self.collect()
        self.assertTrue(rows["linux-cachyos"].active and rows["linux-cachyos-headers"].active)
        self.assertTrue(rows["linux-cachyos-nvidia-open"].active)          # module package follows its kernel
        self.assertFalse(rows["linux"].active)
        self.assertTrue(rows["linux-cachyos"].held)
        self.assertEqual(rows["linux-cachyos"].size, "152 MB")
        self.assertEqual(rows["linux-cachyos"].repo, "cachyos")            # first repo wins, not cachyos-v3
        self.assertTrue(rows["linux-tkg-bore"].installed)                  # locally built AUR kernel is managed
        self.assertEqual(rows["linux-tkg-bore"].provider, "tkg")
        self.assertEqual(rows["linux-lts"].spec, "linux-lts")
        self.assertEqual(rows["linux-cachyos"].group_label, "linux-cachyos 6.12.5-2")

    def test_hardware_rules(self):
        _, rows = self.collect(level="v3")
        self.assertIn("v4", rows["linux-cachyos-rt-bore"].blocked_reason)   # from cachyos-v4 repo, CPU is v3
        _, rows = self.collect(level="v4")
        self.assertEqual(rows["linux-cachyos-rt-bore"].blocked_reason, "")
        _, rows = self.collect(gpus=("amd",))
        self.assertEqual(rows["nvidia-lts"].blocked_reason, "no matching GPU")

    def test_no_old_kernels_on_rolling_distro(self):
        b, rows = self.collect()
        self.assertFalse(b.supports_multiversion)
        self.assertEqual(b.auto_remove_candidates(list(rows.values())), [])

    def test_tabs(self):
        self.assertEqual([p.id for p in PacmanBackend(fx.distro(ID="manjaro", ID_LIKE="arch"), fx.hw()).providers()][:1],
                         ["manjaro"])
        ids = [p.id for p in PacmanBackend(fx.distro(ID="arch"), fx.hw()).providers()]
        self.assertEqual(ids, ["arch", "cachyos", "xanmod", "clear", "liquorix", "tkg", "other"])
        self.assertEqual(PacmanBackend(fx.distro(ID="arch"), fx.hw(arch="aarch64", level=None)).repos(), [])

    def test_parse_info_ignores_continuation_lines(self):
        info = parse_pacman_info("Name : a\nVersion : 1\nDescription : x\n  more text : still\n\nName : b\n")
        self.assertEqual(set(info), {"a", "b"})


class DnfTests(unittest.TestCase):
    def test_package_recognition(self):
        self.assertEqual(dnf_base("kernel-core"), ("kernel", "core"))
        self.assertEqual(dnf_base("kernel-modules-extra"), ("kernel", "modules-extra"))
        self.assertEqual(dnf_base("kernel-cachyos-lto-devel-matched"), ("kernel-cachyos-lto", "devel-matched"))
        self.assertEqual(dnf_base("kernel"), ("kernel", ""))
        self.assertEqual(dnf_base("kernel-rt-core"), ("kernel-rt", "core"))
        self.assertEqual(dnf_base("kernel-lt-core"), ("kernel-lt", "core"))
        for junk in ("kernel-headers", "kernel-tools", "kernel-debug-core", "kernel-uki-virt",
                     "kernel-modules-internal", "kernel-srpm-macros", "kernel-doc"):
            self.assertIsNone(dnf_base(junk), junk)

    def collect(self, level="v3", **kw):
        table = {"rpm -qa": (0, fx.RPM_QA_DNF), "rpm -qf": (0, "kernel-core\t6.11.8-300.fc41\nkernel-modules\t6.11.8-300.fc41\n"),
                 "dnf -q repoquery": (0, fx.DNF_REPOQUERY)}
        with Patch(dnf_mod, rpm_mod, table=table):
            b = DnfBackend(fx.distro(ID="fedora"), fx.hw(level))
            b.running_release = lambda: "6.11.8-300.fc41.x86_64"
            import gkm.backends.dnf as m
            m.locked_names_dnf = lambda: {"kernel-core"}
            return b, b.collect(**kw)

    def test_multi_version_rows_and_state(self):
        b, rows = self.collect()
        by = {(r.name, r.version): r for r in rows}
        self.assertTrue(by[("kernel-core", "6.11.8-300.fc41")].active)
        self.assertFalse(by[("kernel-core", "6.11.4-301.fc41")].active)
        self.assertTrue(by[("kernel-core", "6.11.8-300.fc41")].held)
        self.assertTrue(by[("kernel-modules", "6.11.8-300.fc41")].active)    # same build, sibling part
        self.assertTrue(by[("kernel-devel", "6.11.8-300.fc41")].active)       # every part of the running build is protected
        self.assertFalse(by[("kernel-devel", "6.11.4-301.fc41")].active if ("kernel-devel", "6.11.4-301.fc41") in by else False)
        self.assertFalse(by[("kernel-core", "6.12.5-200.fc41")].installed)    # newer, available
        self.assertEqual(by[("kernel-core", "6.12.5-200.fc41")].spec, "kernel-core=6.12.5-200.fc41")
        self.assertNotIn(("kernel-core", "6.11.8-300.fc41", "avail"), by)
        self.assertEqual(sum(1 for r in rows if r.name == "kernel-core" and r.version == "6.11.8-300.fc41"), 1)
        self.assertFalse(any(r.name in ("kernel-headers", "kernel-tools", "kernel-uki-virt") for r in rows))

    def test_cachyos_cpu_requirement(self):
        _, rows = self.collect(level="v2")
        cy = {r.name: r for r in rows if r.provider == "cachyos"}
        self.assertIn("v3", cy["kernel-cachyos"].blocked_reason)
        self.assertEqual(cy["kernel-cachyos-lts"].blocked_reason, "")          # LTS variant runs on v2

    def test_old_builds_selected_for_auto_remove(self):
        b, rows = self.collect()
        old = {(r.name, r.version) for r in b.auto_remove_candidates(rows)}
        self.assertEqual(old, set())      # only 2 builds installed -> keep both

    def test_providers_and_repos(self):
        b = DnfBackend(fx.distro(ID="rocky", ID_LIKE="rhel centos fedora"), fx.hw())
        self.assertEqual(b.providers()[0].title, "RHEL")
        self.assertEqual([r.id for r in b.repos()], ["copr-cachyos"])
        b = DnfBackend(fx.distro(ID="fedora"), fx.hw())
        self.assertEqual([r.id for r in b.repos()], ["copr-cachyos", "copr-xanmod"])
        self.assertFalse(b.supports_purge)


class ZypperTests(unittest.TestCase):
    def collect(self):
        table = {"zypper --xmlout": (0, fx.ZYPPER_XML), "rpm -qa": (0, fx.RPM_QA_SUSE),
                 "rpm -qf": (0, "kernel-default\t6.12.0-1.1\n")}
        with Patch(zyp_mod, rpm_mod, table=table):
            b = ZypperBackend(fx.distro(ID="opensuse-tumbleweed", ID_LIKE="opensuse suse"), fx.hw())
            b.running_release = lambda: "6.12.0-1-default"
            return b, b.collect()

    def test_collect(self):
        b, rows = self.collect()
        by = {(r.name, r.version): r for r in rows}
        self.assertTrue(by[("kernel-default", "6.12.0-1.1")].active)
        self.assertTrue(by[("kernel-default-devel", "6.12.0-1.1")].active)
        self.assertEqual(by[("kernel-default", "6.13.0-1.1")].group_label, "6.13.0-1.1 · Kernel:stable")
        self.assertNotIn(("kernel-default", "6.12.2-1.1"), by)       # only newest available per package
        self.assertFalse(any(r.name in ("kernel-source", "kernel-syms", "kernel-devel") for r in rows))
        self.assertEqual(sum(r.name == "kernel-default" and not r.installed for r in rows), 1)   # aarch64 build skipped
        self.assertEqual(by[("kernel-preempt", "6.12.2-1.1")].flavor, "Preempt")
        self.assertEqual(by[("kernel-default", "6.13.0-1.1")].spec, "kernel-default=6.13.0-1.1")
