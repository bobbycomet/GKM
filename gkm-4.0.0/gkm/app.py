# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Command-line entry: GUI plus a few non-GUI maintenance/diagnostic flags."""
import sys

from . import APP_VERSION, privilege

APP_ID = "com.griffin.kernel.manager"

HELP = f"""Griffin Kernel Manager {APP_VERSION}

  gkm                      start the GUI
  gkm --info               print detected distribution / hardware / kernel sources
  gkm --install-helper     install the privileged helper + polkit policy (asks for admin rights)
  gkm --uninstall-helper   remove them again
  gkm --test               run the built-in unit tests
  gkm --smoke-test         headless GUI start-up check (used for build verification)
  gkm --version

License: GPL-3.0-only. This program comes with ABSOLUTELY NO WARRANTY; see the LICENSE file.
"""


def _info():
    from .backends import create_backend
    from .distro import detect_distro
    from .hardware import detect_hardware
    d, hw = detect_distro(), detect_hardware()
    print(f"Distribution : {d.pretty_name}  (id={d.id}, family={d.family}, base={d.base}, chain={' > '.join(d.chain)})")
    print(f"Hardware     : {hw.summary()}  [{hw.cpu_model}]")
    try:
        b = create_backend(d, hw)
        print(f"Backend      : {type(b).__name__} ({b.pm_name})")
        print(f"Kernel tabs  : {', '.join(p.title for p in b.providers())}")
        repos = ", ".join("%s=%s" % (r.id, "present" if r.present() else "absent") for r in b.repos())
        print("Repositories : " + (repos or "—"))
    except RuntimeError as e:
        print(f"Backend      : {e}")
    print(f"Helper       : {privilege.helper_path()}  ({privilege.helper_state(d).value})")
    print(f"AppImage     : {'yes' if privilege.is_appimage() else 'no'}")
    return 0


def _run_tests():
    import unittest
    suite = unittest.defaultTestLoader.loadTestsFromName("gkm.tests")
    suite = unittest.defaultTestLoader.discover(str(__import__("pathlib").Path(__file__).parent / "tests"),
                                                top_level_dir=str(__import__("pathlib").Path(__file__).parent.parent))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if res.wasSuccessful() else 1


def _root_script_cli(script):
    return privilege.run_privileged_script(script, lambda l: print(l, end=""))


def main(argv=None):
    args = (sys.argv if argv is None else argv)[1:]
    if "--version" in args:
        print(APP_VERSION)
        return 0
    if "--help" in args or "-h" in args:
        print(HELP)
        return 0
    if "--test" in args:
        sys.exit(_run_tests())
    if "--info" in args:
        sys.exit(_info())
    if "--install-helper" in args:
        sys.exit(_root_script_cli(privilege.build_install_script()))
    if "--uninstall-helper" in args:
        sys.exit(_root_script_cli(privilege.build_uninstall_script()))
    smoke = "--smoke-test" in args
    if smoke:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from .backends import backend_tool_missing, create_backend
    from .distro import detect_distro
    from .hardware import detect_hardware
    from .ui.window import KernelManagerWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_ID)
    app.setDesktopFileName("gkm")
    app.setProperty("gkm_smoke", smoke)
    icon = QIcon(str(privilege.bundled("gkm-512.png")))
    app.setWindowIcon(icon)

    distro, hw = detect_distro(), detect_hardware()
    try:
        backend = create_backend(distro, hw)
        missing = backend_tool_missing(distro)
        if missing:
            raise RuntimeError(f"'{missing}' was not found on this system, but it is required to manage "
                               f"{distro.pretty_name} kernels.")
    except RuntimeError as e:
        if smoke:
            print(f"SMOKE FAIL: {e}")
            return 2
        QMessageBox.critical(None, "GKM", str(e))
        return 1

    win = KernelManagerWindow(backend, distro, hw)
    win.setWindowIcon(icon)
    if not smoke:
        win.show()
        return app.exec()
    return _smoke(app, win)


def _smoke(app, win):
    """Headless: load real data, build every tab, expand every card, exit 0."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QToolButton
    import time
    t0 = time.time()
    m = win.manager
    items = m.collect_sync()
    t1 = time.time()
    m._on_kernels_loaded(items)
    print(f"[smoke] collect {t1 - t0:.1f}s, populate {time.time() - t1:.1f}s", flush=True)

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
    pump(1500)
    expanded = 0
    for _ in range(3):                       # nested cards reveal flavor chevrons on expand
        for btn in win.findChildren(QToolButton):
            if btn.text() == "▸" and expanded < 40:
                btn.click()
                expanded += 1
        pump(300)
    # exercise selection + button state + theme toggle
    for r in list(m._all_rows())[:3]:
        r.is_selected = True
    m._update_buttons()
    win.apply_color_scheme()
    print(f"SMOKE OK: distro={m.distro.id} backend={type(m.backend).__name__} rows={len(items)} "
          f"tabs={[(u.provider.title, len(u.rows)) for u in m.providers.values()]} expanded={expanded}")
    return 0
