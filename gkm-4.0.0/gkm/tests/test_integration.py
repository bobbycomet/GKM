# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from gkm import HELPER_PROTOCOL, privilege

PKG = Path(__file__).resolve().parent.parent
HELPER = PKG / "resources" / "gkm-helper"


def helper_subcommands():
    """Subcommands handled by the dispatcher (top-level `case "$cmd"` arms)."""
    text = HELPER.read_text()
    body = text[text.index('case "$cmd" in'):]
    subs = set()
    for m in re.finditer(r"(?m)^  ([a-z][a-z0-9|-]*)\)", body):
        subs.update(m.group(1).split("|"))
    return subs


class HelperContract(unittest.TestCase):
    def test_every_subcommand_the_gui_can_send_exists_in_the_helper(self):
        subs = helper_subcommands()
        used = set()
        for f in list((PKG / "ui").glob("*.py")) + list((PKG / "backends").glob("*.py")):
            src = f.read_text()
            used.update(re.findall(r'_priv_cmd\("([a-z][a-z0-9-]*)"', src))
            used.update(re.findall(r'"(add-repo-[a-z0-9-]+)"', src))
            used.update(re.findall(r'_hold_or_unhold\("([a-z]+)"\)', src))   # sent via _priv_cmd(action, ...)
        used.add("version")           # privilege.installed_protocol
        self.assertTrue({"install", "remove", "hold", "unhold", "update-sources", "dkms-autoinstall",
                         "reboot", "update-bootloader", "add-repo-xanmod"} <= used, used)
        self.assertEqual(used - subs, set(), "GUI sends subcommands the helper does not implement")

    def test_helper_protocol_matches_gui(self):
        self.assertIn(f"readonly HELPER_PROTOCOL={HELPER_PROTOCOL}", HELPER.read_text())

    def test_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(HELPER)]).returncode, 0)

    def test_rejects_hostile_arguments(self):
        for sub, arg in [("install", "-oAPT::Update::Pre-Invoke::=id"), ("install", "a;id"), ("install", "x=$(id)"),
                         ("remove", "--force-all"), ("hold", "a b"), ("unhold", "../x"),
                         ("dkms-autoinstall", "6.8;id"), ("install", "pkg=--allow-unauthenticated")]:
            with self.subTest(sub=sub, arg=arg):
                r = subprocess.run(["bash", str(HELPER), sub, arg], capture_output=True, text=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("rejected", r.stderr)

    def test_unknown_subcommand_and_version(self):
        r = subprocess.run(["bash", str(HELPER), "rm-rf"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        r = subprocess.run(["bash", str(HELPER), "version"], capture_output=True, text=True)
        self.assertIn(f"protocol {HELPER_PROTOCOL}", r.stdout)


class PrivilegeBootstrap(unittest.TestCase):
    def test_policy_points_at_the_installed_helper_path(self):
        policy = (PKG / "resources" / privilege.POLICY_NAME).read_text()
        self.assertIn(f">{privilege.SYSTEM_HELPER}<", policy)
        self.assertIn("com.griffin.kernel.manager.helper", policy)

    def test_install_script_is_valid_and_checksummed(self):
        script = privilege.build_install_script()
        with tempfile.NamedTemporaryFile("w", suffix=".sh") as f:
            f.write(script)
            f.flush()
            self.assertEqual(subprocess.run(["sh", "-n", f.name]).returncode, 0)
        self.assertIn(privilege.sha256(PKG / "resources" / "gkm-helper"), script)
        self.assertIn("/usr/lib/gkm/gkm-helper", script)

    def test_install_script_places_files_correctly(self):
        """Run the real script against a sandbox root by rewriting absolute targets."""
        script = privilege.build_install_script()
        with tempfile.TemporaryDirectory() as root:
            for p in ("/usr/lib/gkm", "/usr/share/polkit-1/actions", "/usr/share/icons/hicolor/256x256/apps"):
                script = script.replace(p, root + p)
            script = script.replace("-o root -g root", "").replace("restorecon", "true #")
            r = subprocess.run(["sh", "-s"], input=script, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            h = Path(root + "/usr/lib/gkm/gkm-helper")
            self.assertTrue(os.access(h, os.X_OK))
            self.assertEqual(privilege.sha256(h), privilege.sha256(HELPER))
            self.assertEqual(privilege.sha256(root + "/usr/share/polkit-1/actions/" + privilege.POLICY_NAME),
                             privilege.sha256(PKG / "resources" / privilege.POLICY_NAME))

    def test_tampered_payload_is_refused(self):
        script = privilege.build_install_script()
        bad = script.replace(privilege.sha256(PKG / "resources" / "gkm-helper"), "0" * 64)
        with tempfile.TemporaryDirectory() as root:
            for p in ("/usr/lib/gkm", "/usr/share/polkit-1/actions", "/usr/share/icons/hicolor/256x256/apps"):
                bad = bad.replace(p, root + p)
            bad = bad.replace("-o root -g root", "")
            r = subprocess.run(["sh", "-s"], input=bad, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("checksum mismatch", r.stderr)
            self.assertFalse(Path(root + "/usr/lib/gkm/gkm-helper").exists())


try:
    from PyQt6.QtWidgets import QApplication, QToolButton
    HAVE_QT = True
except Exception:       # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not available")
class GuiWithEveryBackend(unittest.TestCase):
    """Drives the real window, tabs and cards with each family's fixture data."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(["gkm-test"])
        cls.app.setProperty("gkm_smoke", True)

    def run_family(self, backend, patch_ctx):
        from PyQt6.QtCore import QEventLoop, QTimer
        from gkm.ui.window import KernelManagerWindow
        with patch_ctx:
            win = KernelManagerWindow(backend, backend.distro, backend.hw)
            m = win.manager
            items = m.collect_sync()
            m._on_kernels_loaded(items)
        for _ in range(3):
            loop = QEventLoop()
            QTimer.singleShot(250, loop.quit)
            loop.exec()
            for b in win.findChildren(QToolButton):
                if b.text() == "▸":
                    b.click()
        return win, m, items

    def test_pacman_cachyos(self):
        from .test_rpm_arch import Patch
        import gkm.backends.pacman as pm
        from . import fixtures as fx
        table = {"pacman -Sl": (0, fx.PACMAN_SL), "pacman -Q": (0, fx.PACMAN_Q), "pacman -Qi": (0, fx.PACMAN_QI),
                 "pacman -Si": (0, fx.PACMAN_SI), "pacman-conf": (0, "")}
        b = pm.PacmanBackend(fx.distro(ID="cachyos", ID_LIKE="arch"), fx.hw())
        b._running_base = lambda: "linux-cachyos"
        win, m, items = self.run_family(b, Patch(pm, table=table))
        shown = {u.provider.id: len(u.rows) for u in m.providers.values()}
        self.assertGreater(shown["cachyos"], 0)
        self.assertFalse(m.btn_autorm.isVisibleTo(win), "no 'old kernels' on a rolling distro")
        self.assertTrue(m.stack.isTabVisible(m.providers["cachyos"].tab_index))
        # selecting an available, hardware-compatible kernel enables Install; blocked ones stay unselectable
        row = next(r for r in items if r.name == "linux-zen")
        row.is_selected = True
        m._update_buttons()
        self.assertTrue(m.btn_install.isEnabled())
        self.assertEqual(m._get_selected_packages(only_installed=False), ["linux-zen"])
        blocked = next(r for r in items if r.name == "linux-cachyos-rt-bore")     # needs v4, CPU is v3
        self.assertTrue(blocked.blocked_reason)
        blocked.is_selected = True            # even if forced programmatically it must never reach the helper
        self.assertEqual(m._get_selected_packages(only_installed=False), ["linux-zen"])

    def test_dnf_fedora(self):
        from .test_rpm_arch import Patch
        import gkm.backends.dnf as dm
        import gkm.backends.rpm_common as rc
        from . import fixtures as fx
        table = {"rpm -qa": (0, fx.RPM_QA_DNF), "rpm -qf": (0, "kernel-core\t6.11.8-300.fc41\n"),
                 "dnf -q repoquery": (0, fx.DNF_REPOQUERY)}
        b = dm.DnfBackend(fx.distro(ID="fedora"), fx.hw())
        b.running_release = lambda: "6.11.8-300.fc41.x86_64"
        win, m, items = self.run_family(b, Patch(dm, rc, table=table))
        self.assertTrue(m.btn_autorm.isVisibleTo(win))
        newest = next(r for r in items if r.name == "kernel-core" and r.version == "6.12.5-200.fc41")
        newest.is_selected = True
        self.assertEqual(m._get_selected_packages(only_installed=False), ["kernel-core=6.12.5-200.fc41"])

    def test_zypper_opensuse(self):
        from .test_rpm_arch import Patch
        import gkm.backends.zypper as zm
        import gkm.backends.rpm_common as rc
        from . import fixtures as fx
        table = {"zypper --xmlout": (0, fx.ZYPPER_XML), "rpm -qa": (0, fx.RPM_QA_SUSE),
                 "rpm -qf": (0, "kernel-default\t6.12.0-1.1\n")}
        b = zm.ZypperBackend(fx.distro(ID="opensuse-tumbleweed", ID_LIKE="opensuse suse"), fx.hw())
        b.running_release = lambda: "6.12.0-1-default"
        win, m, items = self.run_family(b, Patch(zm, rc, table=table))
        self.assertEqual([u.provider.id for u in m.providers.values()], ["opensuse"])

    def test_apt_debian_with_xanmod_hardware_blocking(self):
        from .test_apt import AptCollect
        from .test_rpm_arch import Patch
        import gkm.backends.apt as am
        from . import fixtures as fx
        b = am.AptBackend(fx.distro(ID="debian"), fx.hw("v3", ("amd",)))
        b.running_release = lambda: "6.8.0-31-generic"
        win, m, items = self.run_family(b, Patch(am, table={"apt-cache dumpavail": (0, AptCollect.DUMP),
                                                            "dpkg-query": (0, AptCollect.DPKG)}))
        v4 = next(r for r in items if "x64v4" in r.name)
        self.assertTrue(v4.blocked_reason)
        self.assertGreater(len(m.providers["xanmod"].rows), 0)

    def test_preflight_runs_in_a_thread_and_gates_the_install(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from gkm.model import PreflightResult
        import gkm.backends.apt as am
        from gkm.ui.window import KernelManagerWindow
        from . import fixtures as fx
        b = am.AptBackend(fx.distro(ID="ubuntu"), fx.hw())
        win = KernelManagerWindow(b, b.distro, b.hw)
        m = win.manager
        errors, started = [], []
        m._error_dialog = lambda title, msg: errors.append((title, msg))

        def wait_for(cond, ms=3000):
            loop = QEventLoop()
            t = QTimer()
            t.setInterval(20)
            t.timeout.connect(lambda: loop.quit() if cond() else None)
            QTimer.singleShot(ms, loop.quit)
            t.start()
            loop.exec()
            t.stop()

        # 1. clean simulation -> the install proceeds with exactly the surviving packages
        b.preflight = lambda specs: PreflightResult(ok=True, packages=list(specs))
        m._preflight_then(["linux-image-1"], lambda final: started.append(final))
        wait_for(lambda: started)
        self.assertEqual(started, [["linux-image-1"]])
        self.assertFalse(m.busy)

        # 2. impossible selection -> a clear error, and the install is NOT started (no password prompt)
        started.clear()
        b.preflight = lambda specs: PreflightResult(ok=False, message="E: Unable to correct problems",
                                                    dropped=[("linux-modules-nvidia-580-open-6.17.0-42-generic", "Depends: x")])
        m._preflight_then(["linux-image-1"], lambda final: started.append(final))
        wait_for(lambda: errors)
        self.assertEqual(started, [])
        self.assertIn("can't be installed", errors[0][0])
        self.assertIn("nvidia-580-open", errors[0][1])
        self.assertFalse(m.busy)

        # 3. backends without a simulation (pacman/dnf/zypper) go straight through
        started.clear()
        m.backend = type("NoSim", (), {"has_preflight": False})()
        m._preflight_then(["x"], lambda final: started.append(final))
        self.assertEqual(started, [["x"]])


class RebrandCompatibility(unittest.TestCase):
    def test_legacy_pacman_hold_block_is_read_and_migrated(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / "pacman.conf"
            conf.write_text("[options]\nIgnorePkg = firefox\n"
                            "# BEGIN XKM HOLD (managed by XKM - do not edit)\nIgnorePkg = linux-lts\n# END XKM HOLD\n\n[core]\n")
            helper = Path(d) / "h.sh"
            helper.write_text(HELPER.read_text().replace("readonly PACMAN_CONF=/etc/pacman.conf",
                                                         f"readonly PACMAN_CONF={conf}"))
            bin_dir = Path(d) / "bin"
            bin_dir.mkdir()
            for tool in ("awk", "sed", "tr", "sort", "grep", "cp", "cat", "mktemp", "readlink", "bash", "dirname", "rm"):
                src = shutil.which(tool)
                if src:
                    (bin_dir / tool).symlink_to(src)
            fake = bin_dir / "pacman"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            env = {"PATH": str(bin_dir)}
            r = subprocess.run(["bash", str(helper), "hold", "linux-cachyos"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = conf.read_text()
            self.assertIn("# BEGIN GKM HOLD", text)
            self.assertNotIn("XKM", text)                              # legacy block migrated, not duplicated
            self.assertIn("IgnorePkg = linux-cachyos linux-lts", text)  # the old hold survived the migration
            self.assertIn("IgnorePkg = firefox", text)                 # the user's own line is untouched

    def test_config_is_migrated_from_the_xkm_directory(self):
        import gkm.config as cfg
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d) / "xanmod-kernel-manager", Path(d) / "griffin-kernel-manager"
            old.mkdir()
            (old / "config.json").write_text('{"dark_mode": false, "auto_check_hours": 12}')
            saved = (cfg.LEGACY_CONFIG_DIR, cfg.CONFIG_DIR, cfg.CONFIG_FILE)
            cfg.LEGACY_CONFIG_DIR, cfg.CONFIG_DIR, cfg.CONFIG_FILE = old, new, new / "config.json"
            try:
                got = cfg.load_config()
                self.assertFalse(got["dark_mode"])
                self.assertEqual(got["auto_check_hours"], 12)
                self.assertTrue((old / "config.json").exists(), "old settings must be left in place")
                (new / "config.json").write_text('{"dark_mode": true}')
                self.assertTrue(cfg.load_config()["dark_mode"], "an existing GKM config must never be overwritten")
            finally:
                cfg.LEGACY_CONFIG_DIR, cfg.CONFIG_DIR, cfg.CONFIG_FILE = saved

    def test_no_old_brand_in_user_facing_code(self):
        offenders = []
        for f in list(PKG.rglob("*.py")) + [HELPER, PKG / "resources" / privilege.POLICY_NAME]:
            if f.name == "test_integration.py":
                continue
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if re.search(r"xkm|XKM", line) and "XKM-Multi-Kernel-Manager" not in line and "legacy" not in line.lower() and "rename" not in line.lower() \
                        and "XKM 3" not in line and "XKM HOLD" not in line and "xkm_" not in line.lower().replace("gkm_", ""):
                    offenders.append(f"{f.name}:{n}: {line.strip()[:80]}")
        self.assertEqual(offenders, [])


def fstring_reuse_violations(path):
    """f-strings that reuse their own quote inside a replacement field. That is
    only legal from Python 3.12 (PEP 701) and is a SyntaxError on 3.10/3.11,
    which the .deb and source installs must still support."""
    import io
    import tokenize
    bad, stack = [], []
    for tok in tokenize.generate_tokens(io.StringIO(Path(path).read_text()).readline):
        if tok.type == getattr(tokenize, "FSTRING_START", -1):
            opener = tok.string.lstrip("rRbBfF")
            if opener in stack:
                bad.append(tok.start[0])
            stack.append(opener)
        elif tok.type == getattr(tokenize, "FSTRING_END", -1):
            stack.pop()
        elif tok.type == tokenize.STRING and stack:
            body = tok.string.lstrip("rRbBfFuU")
            opener = body[:3] if body[:3] in ('"""', "'''") else body[:1]
            if opener == stack[-1]:
                bad.append(tok.start[0])
    return sorted(set(bad))


class OlderPythonCompatibility(unittest.TestCase):
    def test_no_python_312_only_fstring_nesting(self):
        import sys
        if sys.version_info < (3, 12):
            self.skipTest("an older interpreter would already have failed to import the code")
        offenders = {f.name: v for f in PKG.rglob("*.py") if (v := fstring_reuse_violations(f))}
        self.assertEqual(offenders, {})

    def test_the_check_itself_catches_the_original_bug(self):
        import sys
        if sys.version_info < (3, 12):
            self.skipTest("needs 3.12 tokenizer")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("x = ', '.join(f'{r}={'a' if r else 'b'}' for r in [1])\n")
        try:
            self.assertEqual(fstring_reuse_violations(f.name), [1])
        finally:
            os.unlink(f.name)

class LicenseCompliance(unittest.TestCase):
    """GKM is GPL-3.0-only. Keep every file marked and the licence text present."""
    SPDX = "SPDX-License-Identifier: GPL-3.0-only"

    def sources(self):
        root = PKG.parent
        files = list(PKG.rglob("*.py")) + [HELPER, PKG / "resources" / privilege.POLICY_NAME]
        for extra in ("gkm.py", "packaging/appimage/build-appimage.sh", "packaging/appimage/AppRun",
                      "packaging/appimage/prune_qt.py", "packaging/appimage/verify-glibc.py",
                      "packaging/debian/gkm", "packaging/debian/postinst", "packaging/debian/postrm"):
            if (root / extra).exists():          # only present in a source checkout
                files.append(root / extra)
        return files

    def test_every_source_file_declares_the_licence(self):
        missing = [str(f.relative_to(PKG.parent)) for f in self.sources() if self.SPDX not in f.read_text()]
        self.assertEqual(missing, [])

    def test_licence_text_is_the_gplv3(self):
        candidates = [PKG.parent / "LICENSE", Path(os.environ.get("APPDIR", "/nonexistent")) / "usr/share/licenses/gkm/LICENSE"]
        found = next((c for c in candidates if c.exists()), None)
        if found is None:
            self.skipTest("LICENSE is not shipped with this install layout")
        text = found.read_text()
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 3, 29 June 2007", text)
        self.assertIn("END OF TERMS AND CONDITIONS", text)

    def test_debian_copyright_matches(self):
        f = PKG.parent / "packaging/debian/copyright"
        if not f.exists():
            self.skipTest("source checkout only")
        self.assertIn("License: GPL-3", f.read_text())
        self.assertNotIn("proprietary", f.read_text())


if __name__ == "__main__":
    unittest.main()
