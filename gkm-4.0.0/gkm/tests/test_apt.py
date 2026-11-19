# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import unittest

from gkm.backends.apt import (AptBackend, extract_kernel_flavor, extract_kernel_version, gpu_relevant,
                              is_generic_kernel_name, is_liquorix_name, is_mainline_meta, is_xanmod_name,
                              xanmod_branch, xanmod_flavor)
from gkm.model import KernelPackage
from .fixtures import FakeRun, distro, hw


class AptNames(unittest.TestCase):
    def test_versions_and_flavors(self):
        cases = [
            ("linux-image-6.14.0-37-generic", "6.14.0-37", "Generic"),
            ("linux-headers-6.14.0-37", "6.14.0-37", "Generic"),
            ("linux-image-6.14.0-1015-aws", "6.14.0-1015", "AWS"),
            ("linux-image-6.8.0-31-lowlatency", "6.8.0-31", "Low Latency"),
            ("linux-image-6.8.0-31-generic-64k", "6.8.0-31", "Generic (64k pages)"),
            ("linux-modules-nvidia-570-6.8.0-31-generic", "6.8.0-31", "Generic"),
            ("linux-modules-nvidia-570-server-open-6.8.0-31-generic", "6.8.0-31", "Generic"),
            ("linux-image-unsigned-6.14.0-37-generic", "6.14.0-37", "Generic"),
            ("linux-modules-extra-6.14.0-37-generic", "6.14.0-37", "Generic"),
            ("linux-image-6.1.0-18-amd64", "6.1.0-18", "Generic"),
            ("linux-image-6.1.0-18-rt-amd64", "6.1.0-18", "Real-Time"),
            ("linux-image-6.12.48+deb13-amd64", "6.12.48+deb13", "Generic"),
            ("linux-image-6.12.48+deb13-cloud-amd64", "6.12.48+deb13", "Cloud"),
            ("linux-image-6.1.0-0.deb11.17-amd64", "6.1.0-0.deb11.17", "Generic"),
            ("linux-headers-6.1.0-18-common", "6.1.0-18", "Generic"),
            ("linux-image-6.12.34+rpt-rpi-v8", "6.12.34+rpt", "Raspberry Pi"),
        ]
        for name, kver, fl in cases:
            with self.subTest(name):
                self.assertEqual((extract_kernel_version(name), extract_kernel_flavor(name)), (kver, fl))

    def test_meta_packages(self):
        for name, fl in [("linux-generic", "Generic"), ("linux-image-amd64", "Generic"),
                         ("linux-image-rt-amd64", "Real-Time"), ("linux-headers-cloud-amd64", "Cloud"),
                         ("linux-oem-24.04", "OEM"), ("linux-generic-hwe-24.04", "Generic (HWE 24.04)")]:
            with self.subTest(name):
                self.assertTrue(is_mainline_meta(name))
                self.assertEqual(extract_kernel_flavor(name), fl)

    def test_cloud_helper_packages_not_listed(self):
        for n in ("linux-aws-6.11-headers-6.11.0-1014", "linux-azure-tools-6.8.0-1005", "linux-image-6.8.0-31-generic-dbg"):
            self.assertFalse(is_mainline_meta(n) or is_generic_kernel_name(n), n)

    def test_third_party_classification(self):
        self.assertTrue(is_xanmod_name("linux-image-6.18.3-x64v3-xanmod1"))
        self.assertTrue(is_xanmod_name("linux-xanmod-lts-x64v3"))
        self.assertTrue(is_liquorix_name("linux-image-6.9.7-1-liquorix-amd64"))   # versioned: 3.0.x missed these
        self.assertFalse(is_generic_kernel_name("linux-image-6.9.7-1-liquorix-amd64"))
        self.assertEqual(xanmod_flavor("linux-xanmod-lts-x64v3"), "v3")
        self.assertEqual(xanmod_flavor("linux-xanmod-edge"), "edge")
        self.assertEqual(xanmod_branch("linux-xanmod-lts-x64v3"), "LTS")

    def test_gpu_relevance(self):
        self.assertFalse(gpu_relevant("linux-modules-nvidia-570-6.8.0-31-generic", {"amd"}))
        self.assertTrue(gpu_relevant("linux-modules-nvidia-570-6.8.0-31-generic", {"nvidia"}))
        self.assertTrue(gpu_relevant("linux-image-6.8.0-31-generic", set()))


class AptCollect(unittest.TestCase):
    DUMP = """Package: linux-image-6.8.0-31-generic
Version: 6.8.0-31.31
Installed-Size: 14000

Package: linux-image-6.8.0-35-generic
Version: 6.8.0-35.35
Installed-Size: 14100

Package: linux-image-6.8.0-35-generic
Version: 6.8.0-35.35+1
Installed-Size: 14200

Package: linux-image-6.18.3-x64v4-xanmod1
Version: 6.18.3-0xanmod1
Installed-Size: 90000

Package: linux-image-6.18.3-x64v3-xanmod1
Version: 6.18.3-0xanmod1
Installed-Size: 90000

Package: linux-modules-nvidia-570-6.8.0-35-generic
Version: 6.8.0-35.35
Installed-Size: 100
"""
    DPKG = ("linux-image-6.8.0-31-generic\t6.8.0-31.31\tii \t14000\n"
            "linux-image-6.8.0-35-generic\t6.8.0-35.35\thi \t14100\n"
            "linux-generic\t6.8.0.35.35\tii \t30\n")

    def collect(self, gpus=("amd",), level="v3"):
        import gkm.backends.apt as mod
        fake = FakeRun({"apt-cache dumpavail": (0, self.DUMP), "dpkg-query": (0, self.DPKG)})
        orig = mod.run_host
        mod.run_host = fake
        try:
            b = AptBackend(distro(ID="ubuntu"), hw(level, gpus))
            b.running_release = lambda: "6.8.0-31-generic"
            return b, {r.name: r for r in b.collect()}
        finally:
            mod.run_host = orig

    def test_state_active_held_and_newest(self):
        b, rows = self.collect()
        self.assertTrue(rows["linux-image-6.8.0-31-generic"].active)
        self.assertFalse(rows["linux-image-6.8.0-35-generic"].active)
        self.assertTrue(rows["linux-image-6.8.0-35-generic"].held)
        self.assertEqual(rows["linux-image-6.8.0-35-generic"].version, "6.8.0-35.35+1")   # newest wins
        self.assertTrue(rows["linux-generic"].is_meta)

    def test_hardware_blocking(self):
        _, rows = self.collect(gpus=("amd",), level="v3")
        self.assertIn("v3", rows["linux-image-6.18.3-x64v4-xanmod1"].blocked_reason)
        self.assertEqual(rows["linux-image-6.18.3-x64v3-xanmod1"].blocked_reason, "")
        self.assertEqual(rows["linux-modules-nvidia-570-6.8.0-35-generic"].blocked_reason, "no matching GPU")
        _, rows = self.collect(gpus=("nvidia",), level="v4")
        self.assertEqual(rows["linux-image-6.18.3-x64v4-xanmod1"].blocked_reason, "")
        self.assertEqual(rows["linux-modules-nvidia-570-6.8.0-35-generic"].blocked_reason, "")

    def test_installed_packages_are_never_blocked(self):
        """A kernel the CPU can't run (or a driver for a GPU that's gone) must stay removable."""
        import gkm.backends.apt as mod
        dpkg = self.DPKG + ("linux-image-6.18.3-x64v4-xanmod1\t6.18.3-0xanmod1\tii \t90000\n"
                           "linux-modules-nvidia-570-6.8.0-35-generic\t6.8.0-35.35\tii \t100\n")
        orig = mod.run_host
        mod.run_host = FakeRun({"apt-cache dumpavail": (0, self.DUMP), "dpkg-query": (0, dpkg)})
        try:
            b = AptBackend(distro(ID="ubuntu"), hw("v3", ("amd",)))
            b.running_release = lambda: "6.8.0-31-generic"
            rows = {r.name: r for r in b.collect()}
        finally:
            mod.run_host = orig
        self.assertTrue(rows["linux-image-6.18.3-x64v4-xanmod1"].installed)
        self.assertEqual(rows["linux-image-6.18.3-x64v4-xanmod1"].blocked_reason, "")
        self.assertEqual(rows["linux-modules-nvidia-570-6.8.0-35-generic"].blocked_reason, "")

    def test_providers_follow_hardware(self):
        self.assertEqual([p.id for p in AptBackend(distro(ID="debian"), hw(arch="aarch64", level=None)).providers()],
                         ["mainline"])
        self.assertEqual([p.title for p in AptBackend(distro(ID="debian"), hw()).providers()],
                         ["Debian", "XanMod", "Liquorix"])
        self.assertEqual(AptBackend(distro(ID="linuxmint", ID_LIKE="ubuntu debian"), hw()).providers()[0].title, "Ubuntu")


class AutoRemove(unittest.TestCase):
    def rows(self):
        mk = lambda n, v, **k: KernelPackage(name=n, version=v, provider="mainline", installed=True,
                                              kgroup=v.split(".")[0] + v, flavor="Generic", **k)
        out = []
        for v in ("6.8.0-20", "6.8.0-25", "6.8.0-31", "6.8.0-35"):
            out += [mk(f"linux-image-{v}-generic", v + ".1"), mk(f"linux-headers-{v}-generic", v + ".1")]
        out.append(KernelPackage(name="linux-generic", version="6.8.0.35", provider="mainline", installed=True,
                                 is_meta=True, flavor="Generic"))
        # another flavor with a single build must be left alone
        out.append(KernelPackage(name="linux-image-6.5.0-1-lowlatency", version="6.5.0-1.1", provider="mainline",
                                 installed=True, kgroup="6.5.0-1", flavor="Low Latency"))
        return out

    def test_keeps_running_and_two_newest_per_flavor_and_never_meta(self):
        b = AptBackend(distro(ID="ubuntu"), hw())
        rows = self.rows()
        next(r for r in rows if r.name == "linux-image-6.8.0-20-generic").active = True
        names = {r.name for r in b.auto_remove_candidates(rows)}
        self.assertEqual(names, {"linux-image-6.8.0-25-generic", "linux-headers-6.8.0-25-generic"})

    def test_held_is_protected(self):
        b = AptBackend(distro(ID="ubuntu"), hw())
        rows = self.rows()
        for r in rows:
            if "6.8.0-20" in r.name:
                r.held = True
        names = {r.name for r in b.auto_remove_candidates(rows)}
        self.assertFalse(any("6.8.0-20" in n for n in names))
        self.assertTrue(any("6.8.0-25" in n for n in names))


class SeqRun:
    """run_host stand-in returning a different (rc, output) on each call."""
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, cmd, timeout=120, input_text=None, merge_stderr=False):
        self.calls.append(list(cmd))
        return self.results.pop(0)


class NvidiaTrackingAndSeries(unittest.TestCase):
    """The failure from a real log: tracking packages ending in -6.17 were taken for a kernel
    build called "6.17", so one click selected NVIDIA packages for aws, azure, vmware ..."""

    def test_series_tags_are_tracking_packages_not_builds(self):
        for n, fl in [("linux-modules-nvidia-595-open-aws-6.17", "AWS"),
                      ("linux-modules-nvidia-580-server-open-vmware-6.17", "VMware"),
                      ("linux-modules-nvidia-595-open-generic-6.17", "Generic"),
                      ("linux-modules-nvidia-595-open-nvidia-6.17", "NVIDIA")]:
            with self.subTest(n):
                self.assertIsNone(extract_kernel_version(n))
                self.assertTrue(is_mainline_meta(n))
                self.assertEqual(extract_kernel_flavor(n), fl)

    def test_real_builds_still_parse(self):
        self.assertEqual(extract_kernel_version("linux-modules-nvidia-580-open-6.17.0-42-generic"), "6.17.0-42")
        self.assertEqual(extract_kernel_flavor("linux-modules-nvidia-580-server-open-6.17.0-1032-nvidia"), "NVIDIA")
        self.assertEqual(extract_kernel_flavor("linux-modules-nvidia-535-vgpu-guest-6.17.0-1004-vmware"), "VMware")

    def test_driver_series(self):
        from gkm.backends.apt import nvidia_module_series
        self.assertEqual(nvidia_module_series("linux-modules-nvidia-580-open-6.17.0-42-generic"), "580-open")
        self.assertEqual(nvidia_module_series("linux-modules-nvidia-580-server-open-6.17.0-1032-nvidia"), "580-server-open")
        self.assertIsNone(nvidia_module_series("linux-image-6.17.0-42-generic"))
        self.assertIsNone(nvidia_module_series("linux-modules-nvidia-595-open-generic-6.17"))

    def test_only_the_installed_driver_series_is_selected_with_a_new_kernel(self):
        import gkm.backends.apt as mod
        dump = "".join(f"Package: {n}\nVersion: 6.17.0-42.42\nInstalled-Size: 100\n\n" for n in (
            "linux-image-6.17.0-42-generic", "linux-modules-nvidia-580-open-6.17.0-42-generic",
            "linux-modules-nvidia-595-open-6.17.0-42-generic", "linux-modules-nvidia-580-server-6.17.0-42-generic",
            "linux-modules-nvidia-595-open-generic-6.17"))
        dpkg = ("linux-image-6.17.0-41-generic\t6.17.0-41.41\tii \t1\n"
                "linux-modules-nvidia-580-open-6.17.0-41-generic\t6.17.0-41.41\tii \t1\n")
        orig = mod.run_host
        mod.run_host = FakeRun({"apt-cache dumpavail": (0, dump), "dpkg-query": (0, dpkg)})
        try:
            b = AptBackend(distro(ID="ubuntu"), hw("v3", ("nvidia",)))
            b.running_release = lambda: "6.17.0-41-generic"
            rows = {r.name: r for r in b.collect()}
        finally:
            mod.run_host = orig
        self.assertFalse(rows["linux-modules-nvidia-580-open-6.17.0-42-generic"].opt_in)    # matches what you run
        self.assertTrue(rows["linux-modules-nvidia-595-open-6.17.0-42-generic"].opt_in)
        self.assertTrue(rows["linux-modules-nvidia-580-server-6.17.0-42-generic"].opt_in)
        self.assertTrue(rows["linux-modules-nvidia-595-open-generic-6.17"].opt_in)
        self.assertFalse(rows["linux-image-6.17.0-42-generic"].opt_in)
        # a group click installs the image and the matching module, never the other driver series
        from gkm.ui.cards import CardsMixin
        install, _ = CardsMixin._split_group_targets(None, [r for r in rows.values() if r.kgroup == "6.17.0-42"])
        self.assertEqual({r.name for r in install}, {"linux-image-6.17.0-42-generic",
                                                      "linux-modules-nvidia-580-open-6.17.0-42-generic"})


class AptPreflight(unittest.TestCase):
    SELECTION = ["linux-image-6.17.0-42-generic", "linux-headers-6.17.0-42-generic",
                 "linux-modules-nvidia-580-open-6.17.0-42-generic", "linux-modules-nvidia-595-open-aws-6.17",
                 "linux-modules-nvidia-595-server-open-6.17.0-42-generic"]

    def run_pre(self, *results):
        import gkm.backends.apt as mod
        seq = SeqRun(*results)
        orig, mod.run_host = mod.run_host, seq
        try:
            return AptBackend(distro(ID="ubuntu"), hw()).preflight(self.SELECTION), seq
        finally:
            mod.run_host = orig

    def test_the_real_failure_leaves_out_only_what_apt_blames(self):
        from .fixtures import APT_SIM_OK, APT_UNMET_NVIDIA
        res, seq = self.run_pre((100, APT_UNMET_NVIDIA), (0, APT_SIM_OK))
        self.assertTrue(res.ok)
        self.assertEqual(res.packages, ["linux-image-6.17.0-42-generic", "linux-headers-6.17.0-42-generic"])
        self.assertEqual({sp for sp, _ in res.dropped}, {"linux-modules-nvidia-580-open-6.17.0-42-generic",
                                                          "linux-modules-nvidia-595-open-aws-6.17",
                                                          "linux-modules-nvidia-595-server-open-6.17.0-42-generic"})
        self.assertTrue(all(why.startswith("Depends:") for _, why in res.dropped))
        # simulation only, never the real thing, and never takes a lock
        self.assertTrue(all(c[:2] == ["apt-get", "-s"] and "Debug::NoLocking=1" in c for c in seq.calls))
        self.assertEqual(len(seq.calls), 2)
        self.assertNotIn("linux-modules-nvidia-580-open-6.17.0-42-generic", seq.calls[1])   # retried without them

    def test_inconclusive_simulation_never_blocks_the_install(self):
        res, _ = self.run_pre((100, "E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)"))
        self.assertTrue(res.ok)
        self.assertEqual(res.packages, self.SELECTION)

    def test_removals_are_reported(self):
        out = "The following packages will be REMOVED:\n  nvidia-driver-610 nvidia-dkms-610\n  libnvidia-gl-610\nThe following NEW packages will be installed:\n  x\n"
        res, _ = self.run_pre((0, out))
        self.assertTrue(res.ok)
        self.assertEqual(res.removals, ["nvidia-driver-610", "nvidia-dkms-610", "libnvidia-gl-610"])

    def test_nothing_installable(self):
        log = "The following packages have unmet dependencies:\n " + "\n ".join(
            f"{n.split('=')[0]} : Depends: nvidia-kernel-common (>= 1) but it is not installable" for n in self.SELECTION)
        res, _ = self.run_pre((100, log))
        self.assertFalse(res.ok)
        self.assertEqual(len(res.dropped), len(self.SELECTION))

    def test_problem_outside_the_selection_is_reported_not_guessed(self):
        log = ("The following packages have unmet dependencies:\n"
               " nvidia-kernel-common-610 : Depends: nvidia-kernel-common-615 but it is not installable\n"
               "E: Unable to correct problems, you have held broken packages.\n")
        res, _ = self.run_pre((100, log))
        self.assertFalse(res.ok)
        self.assertIn("nvidia-kernel-common-615", res.message)

    def test_missing_package_is_dropped(self):
        res, _ = self.run_pre((100, "E: Unable to locate package linux-modules-nvidia-595-open-aws-6.17\n"),
                              (0, "ok\n"))
        self.assertTrue(res.ok)
        self.assertNotIn("linux-modules-nvidia-595-open-aws-6.17", res.packages)


class ConflictingImagesAndSafety(unittest.TestCase):
    """Found by running the pre-flight against real apt: Ubuntu's signed, unsigned and uc kernel images
    conflict, and the first version of the pre-flight dropped BOTH sides of a conflict."""

    def run_pre(self, selection, *results):
        import gkm.backends.apt as mod
        seq = SeqRun(*results)
        orig, mod.run_host = mod.run_host, seq
        try:
            return AptBackend(distro(ID="ubuntu"), hw()).preflight(selection), seq
        finally:
            mod.run_host = orig

    def test_a_conflicting_pair_loses_only_the_later_package(self):
        img, uns, hdr = ("linux-image-6.17.0-20-generic", "linux-image-unsigned-6.17.0-20-generic",
                         "linux-headers-6.17.0-20-generic")
        log = ("The following packages have unmet dependencies:\n"
               f" {img} : Conflicts: {uns} but 6.17.0-20.20~24.04.1 is to be installed\n"
               f" {uns} : Conflicts: {img} but 6.17.0-20.20~24.04.1 is to be installed\n"
               "E: Unable to correct problems, you have held broken packages.\n")
        res, _ = self.run_pre([img, uns, hdr], (100, log), (0, "ok\n"))
        self.assertTrue(res.ok)
        self.assertEqual(res.packages, [img, hdr])
        self.assertEqual([sp for sp, _ in res.dropped], [uns])

    def test_never_ends_up_without_a_kernel_image(self):
        img, hdr = "linux-image-6.17.0-20-generic", "linux-headers-6.17.0-20-generic"
        log = (f"The following packages have unmet dependencies:\n {img} : Depends: libfoo (>= 2) but it is not installable\n"
               "E: Unable to correct problems, you have held broken packages.\n")
        res, _ = self.run_pre([img, hdr], (100, log), (0, "ok\n"))
        self.assertFalse(res.ok)
        self.assertIn("kernel image", res.message)

    def test_group_click_picks_the_signed_image_and_skips_vm_tooling(self):
        import gkm.backends.apt as mod
        from gkm.ui.cards import CardsMixin
        v = "6.17.0-20"
        pk = [f"linux-image-{v}-generic", f"linux-image-unsigned-{v}-generic", f"linux-image-uc-{v}-generic",
              f"linux-headers-{v}-generic", f"linux-cloud-tools-{v}-generic", f"linux-modules-{v}-generic",
              # a flavor that only ships the unsigned image: it must stay selectable
              f"linux-image-unsigned-{v}-lowlatency", f"linux-headers-{v}-lowlatency"]
        dump = "".join(f"Package: {n}\nVersion: {v}.20\nInstalled-Size: 1\n\n" for n in pk)
        orig, mod.run_host = mod.run_host, FakeRun({"apt-cache dumpavail": (0, dump), "dpkg-query": (0, "")})
        try:
            b = AptBackend(distro(ID="ubuntu"), hw())
            b.running_release = lambda: "6.8.0-1-generic"
            rows = b.collect()
        finally:
            mod.run_host = orig

        def picked(flavor):
            grp = [r for r in rows if r.flavor == flavor]
            return {r.name for r in CardsMixin._split_group_targets(None, grp)[0]}
        self.assertEqual(picked("Generic"), {f"linux-image-{v}-generic", f"linux-headers-{v}-generic",
                                              f"linux-modules-{v}-generic"})
        self.assertEqual(picked("Low Latency"), {f"linux-image-unsigned-{v}-lowlatency", f"linux-headers-{v}-lowlatency"})
