# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import unittest

from gkm.distro import detect_distro
from gkm.hardware import psabi_level_from_flags, parse_cpuinfo
from gkm.vercmp import deb_vercmp, evr_vercmp, rpmvercmp, version_newer


class VersionCompare(unittest.TestCase):
    def test_deb(self):
        self.assertLess(deb_vercmp("1.0~rc1", "1.0"), 0)
        self.assertGreater(deb_vercmp("1:0.9", "2.0"), 0)
        self.assertGreater(deb_vercmp("6.14.0-37.37", "6.14.0-9.9"), 0)
        self.assertLess(deb_vercmp("6.8.0-31.31~22.04.1", "6.8.0-31.31"), 0)
        self.assertEqual(deb_vercmp("6.8.0-31.31", "6.8.0-31.31"), 0)

    def test_rpm_and_pacman(self):
        self.assertGreater(evr_vercmp("6.12.10-200.fc41", "6.12.8-201.fc41"), 0)
        self.assertGreater(evr_vercmp("1:1.0-1", "2.0-1"), 0)
        self.assertLess(rpmvercmp("1.0~rc1", "1.0"), 0)
        self.assertGreater(rpmvercmp("1.0^git1", "1.0"), 0)
        self.assertLess(rpmvercmp("6.12.9.arch1-1", "6.12.10.arch1-1"), 0)
        self.assertEqual(rpmvercmp("1.0", "1.0"), 0)

    def test_release_check(self):
        self.assertTrue(version_newer("3.1.1", "3.1.0"))
        self.assertFalse(version_newer("3.1.0", "3.1.0"))
        self.assertTrue(version_newer("3.10.0", "3.9.9"))


class DistroDetection(unittest.TestCase):
    def d(self, **o):
        return detect_distro(o, check_ro=False, ostree_marker="/nonexistent")

    def test_derivatives_resolve_to_family_and_base(self):
        cases = [
            (dict(ID="linuxmint", ID_LIKE="ubuntu debian", UBUNTU_CODENAME="noble"), "debian", "ubuntu"),
            (dict(ID="pop", ID_LIKE="ubuntu debian"), "debian", "ubuntu"),
            (dict(ID="debian"), "debian", "debian"),
            (dict(ID="kali", ID_LIKE="debian"), "debian", "debian"),
            (dict(ID="cachyos", ID_LIKE="arch"), "arch", "arch"),
            (dict(ID="manjaro", ID_LIKE="arch"), "arch", "arch"),
            (dict(ID="endeavouros", ID_LIKE="arch"), "arch", "arch"),
            (dict(ID="garuda", ID_LIKE="arch"), "arch", "arch"),
            (dict(ID="fedora"), "fedora", "fedora"),
            (dict(ID="nobara", ID_LIKE="rhel centos fedora"), "fedora", "fedora"),
            (dict(ID="rocky", ID_LIKE="rhel centos fedora"), "fedora", "rhel"),
            (dict(ID="opensuse-tumbleweed", ID_LIKE="opensuse suse"), "suse", "opensuse-tumbleweed"),
            (dict(ID="opensuse-leap", ID_LIKE="suse opensuse"), "suse", "opensuse-leap"),
            (dict(ID="sles", ID_LIKE="suse opensuse"), "suse", "sles"),
        ]
        for osr, fam, base in cases:
            with self.subTest(osr["ID"]):
                got = self.d(**osr)
                self.assertEqual((got.family, got.base), (fam, base))

    def test_codename_prefers_ubuntu_for_ubuntu_derivatives(self):
        self.assertEqual(self.d(ID="linuxmint", ID_LIKE="ubuntu debian", UBUNTU_CODENAME="noble",
                                VERSION_CODENAME="xia").codename, "noble")
        self.assertEqual(self.d(ID="linuxmint", ID_LIKE="debian", DEBIAN_CODENAME="bookworm",
                                VERSION_CODENAME="faye").codename, "bookworm")

    def test_immutable_markers(self):
        d = detect_distro({"ID": "fedora", "VARIANT_ID": "silverblue"}, check_ro=False, ostree_marker="/nonexistent")
        self.assertTrue(d.immutable)
        self.assertFalse(self.d(ID="fedora").immutable)


class Hardware(unittest.TestCase):
    V2 = set("cx16 popcnt sse4_1 sse4_2 ssse3".split())
    V3 = V2 | set("avx avx2 bmi1 bmi2 f16c fma movbe abm".split())
    V4 = V3 | set("avx512f avx512bw avx512cd avx512dq avx512vl".split())

    def test_psabi(self):
        self.assertEqual(psabi_level_from_flags({"sse2"}), "v1")
        self.assertEqual(psabi_level_from_flags(self.V2), "v2")
        self.assertEqual(psabi_level_from_flags(self.V3), "v3")
        self.assertEqual(psabi_level_from_flags(self.V4), "v4")
        self.assertIsNone(psabi_level_from_flags(set()))

    def test_cpuinfo_parse(self):
        flags, vendor, model = parse_cpuinfo("vendor_id\t: AuthenticAMD\nmodel name\t: Ryzen\nflags\t\t: a b c\n")
        self.assertEqual((flags, vendor, model), ({"a", "b", "c"}, "AuthenticAMD", "Ryzen"))
