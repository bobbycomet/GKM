# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow

from ..config import load_config, save_config
from .manager import KernelManager
from .theme import DARK_QSS, LIGHT_QSS, build_palette


class KernelManagerWindow(QMainWindow):
    def __init__(self, backend, distro, hw):
        super().__init__()
        self.setWindowTitle("Griffin Kernel Manager")
        w, h = load_config().get("win_size", [1080, 680])
        self.resize(w, h)
        self.manager = KernelManager(self, backend, distro, hw)
        self.setCentralWidget(self.manager.toast_overlay)
        self.apply_color_scheme()
        QTimer.singleShot(0, self._on_window_realized)

    def _on_window_realized(self):
        first = next(iter(self.manager.providers.values()))
        loading = QLabel("Loading package cache…")
        loading.setStyleSheet("margin-top: 40px;")
        loading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        first.box.insertWidget(0, loading)
        if QApplication.instance().property("gkm_smoke"):
            return          # headless verification: no data thread, no modal dialogs
        self.manager._reload_kernels_async()
        QTimer.singleShot(0, self.manager.check_helper_at_startup)
        QTimer.singleShot(400, self.manager._maybe_offer_add_repos)
        QTimer.singleShot(3000, self.manager._check_for_app_update)

    def apply_color_scheme(self):
        # Palette for base colours, class-selector QSS only: a bare "QWidget {}"
        # rule would make Qt re-polish every widget on each theme switch.
        dark = load_config().get("dark_mode", True)
        app = QApplication.instance()
        app.setPalette(build_palette(dark))
        app.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)

    def closeEvent(self, event):
        cfg = load_config()
        cfg["win_size"] = [self.width(), self.height()]
        cfg["auto_remove_after_install"] = self.manager.chk_auto_rm.isChecked()
        cfg["auto_rollback"] = self.manager.chk_rollback.isChecked()
        save_config(cfg)
        self.manager._end_log_session()
        super().closeEvent(event)
