# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""KernelManager: the application logic and the provider-tab UI."""
import re
import subprocess
import threading
import traceback
import json
import urllib.request
from datetime import datetime
from functools import cmp_to_key

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_VERSION, privilege
from ..backends.apt import FLAVOR_ORDER, XANMOD_FLAVOR_INFO, mainline_flavor_matches
from ..backends.base import list_module_dirs
from ..config import LOG_DIR, load_config, save_config
from ..hostenv import host_env
from ..vercmp import version_newer
from .cards import CardsMixin
from .versions import VersionsDialog
from .widgets import MainThreadDispatcher, ToastOverlay

RELEASES_API_URL = "https://api.github.com/repos/bobbycomet/XKM-Multi-Kernel-Manager/releases/latest"

_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._@-]*(=[A-Za-z0-9][A-Za-z0-9+._:~^-]*)?$")
_STATUS_RANK = {"Active": 0, "Held": 1, "Installed": 1, "Available": 2}


class ProviderUI:
    """Widgets belonging to one provider tab."""
    def __init__(self, provider):
        self.provider = provider
        self.rows = []
        self.nested = {}        # kgroup -> rows   (nested layout)
        self.metas = []         # tracking packages (nested layout)
        self.flavor_filter = provider.default_flavor
        self.combo = None
        self.box = None
        self.banner_frame = None
        self.banner_label = None
        self.banner_btn = None
        self.tab_index = -1


class KernelManager(CardsMixin):
    def __init__(self, win, backend, distro, hw):
        self.win = win
        self.backend = backend
        self.distro = distro
        self.hw = hw
        self.kernels = []
        self.running_release = backend.running_release()
        self._pre_modules = set()
        self.busy = False
        self._log_handle = None
        self._pkexec_fail_count = 0
        self._refresh_next = False
        self._upgrade_after_repos = False
        self._helper_notice_shown = False
        self._rebuild_generation = 0
        self._dispatch = MainThreadDispatcher()
        self._search_debounce_timer = QTimer()
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.timeout.connect(self._refilter_all)

        self.providers = {p.id: ProviderUI(p) for p in backend.providers()}
        self.offers = backend.repos()
        self.helper_state = privilege.helper_state(distro)

        self.main_box = QWidget()
        self.main_layout = QVBoxLayout(self.main_box)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.toast_overlay = ToastOverlay(self.main_box)
        self._build_ui()

        hours = load_config().get("auto_check_hours", 6)
        self._periodic_timer = QTimer()
        self._periodic_timer.setInterval(int(max(1, hours)) * 3600 * 1000)
        self._periodic_timer.timeout.connect(lambda: self._reload_kernels_async())
        self._periodic_timer.start()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _all_rows(self):
        for ui in self.providers.values():
            yield from ui.rows

    def _flavor_sort_key(self, label, order=None):
        order = order or FLAVOR_ORDER
        for i, base in enumerate(order):
            if label.startswith(base):
                return i
        return len(order)

    @staticmethod
    def _version_label(v):
        return v

    def _version_cmp(self, a, b):
        return self.backend.version_cmp(a, b)

    # ── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        self.main_layout.addWidget(self._build_header())
        self._build_toolbar()
        self._build_search_bar()
        self._build_stack()
        self._build_log_panel()
        self._update_buttons()

    def _build_header(self):
        header = QFrame()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 10, 12, 10)
        badges = []
        if self.hw.psabi:
            badges.append(f"x86-64-{self.hw.psabi}")
        if self.hw.gpus:
            badges.append(" + ".join(sorted(v.upper() for v in self.hw.gpus)) + " detected")
        if badges:
            badge = QLabel("  ·  ".join(badges))
            badge.setStyleSheet("color: #6fcf6f; font-size: 9pt;")
            layout.addWidget(badge)
        layout.addStretch(1)

        title_box = QVBoxLayout()
        title_lbl = QLabel("Griffin Kernel Manager")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 13pt;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub = QLabel(f"{self.distro.pretty_name}  ·  {self.backend.pm_name}")
        sub.setStyleSheet("color: gray; font-size: 9pt;")
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub)
        layout.addLayout(title_box)
        layout.addStretch(1)

        info_btn = QToolButton()
        info_btn.setText("ⓘ System")
        info_btn.setToolTip("Detected distribution, hardware and helper status")
        info_btn.clicked.connect(self._show_system_info)
        layout.addWidget(info_btn)

        self.mode_switch = QCheckBox("Dark Mode")
        self.mode_switch.setChecked(load_config().get("dark_mode", True))
        self.mode_switch.toggled.connect(self.on_mode_toggled)
        layout.addWidget(self.mode_switch)
        return header

    def _build_toolbar(self):
        toolbar_widget = QWidget()
        tb = QHBoxLayout(toolbar_widget)
        tb.setContentsMargins(12, 8, 12, 0)
        tb.setSpacing(8)
        self.main_layout.addWidget(toolbar_widget)

        def button(text, slot, tip="", style=""):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if tip:
                b.setToolTip(tip)
            if style:
                b.setStyleSheet(style)
            tb.addWidget(b)
            return b

        hold_word = {"debian": "apt-mark hold", "arch": "IgnorePkg in pacman.conf",
                     "fedora": "dnf versionlock", "suse": "zypper addlock"}.get(self.backend.family, "hold")
        self.btn_refresh = button("↺  Refresh", self._action_check_updates)
        self.btn_install = button("⬇  Install Selected", self._install_selected, style="QPushButton { font-weight: bold; }")
        self.btn_install_hold = button(
            "⬇🔒 Install + Hold", self._install_and_hold_selected,
            f"Install selected packages and immediately hold them ({hold_word})\nso they are never auto-upgraded.")
        self.btn_remove = button("✕  Remove Selected", self._remove_selected,
                                 style="QPushButton { color: #e05050; font-weight: bold; }")
        self.btn_hold = button("🔒 Hold", self._hold_selected, f"Prevent selected packages from being upgraded ({hold_word})")
        self.btn_unhold = button("🔓 Unhold", self._unhold_selected, f"Release the hold on selected packages ({hold_word})")
        self.btn_autorm = button("Auto-Remove Old", self._auto_remove_old_kernels,
                                 "Remove old kernel builds, keeping the running one and the two newest of each kind.")
        self.btn_dkms = button("Rebuild DKMS", self._dkms_rebuild_all, "Run dkms autoinstall for every installed kernel.")
        self.chk_auto_rm = QCheckBox("Auto-remove after install")
        self.chk_auto_rm.setChecked(load_config().get("auto_remove_after_install", False))
        tb.addWidget(self.chk_auto_rm)
        if not self.backend.supports_multiversion:
            # Rolling families keep one build per kernel: there are no "old kernels".
            self.btn_autorm.setVisible(False)
            self.chk_auto_rm.setVisible(False)
            self.chk_auto_rm.setChecked(False)
        self.btn_versions = button("Versions…", self._show_versions,
                                   "Install an older version of the selected kernel (Arch: from your pacman cache or the Arch "
                                   "Linux Archive; Fedora/openSUSE: older builds still in your repositories).")
        self.btn_versions.setVisible(self.backend.has_versions)
        self.chk_rollback = QCheckBox("Roll back on failure")
        self.chk_rollback.setToolTip("If an install fails, remove what it left behind. On Arch, if the full upgrade after "
                                     "adding a repository fails, restore the previous kernel version.")
        self.chk_rollback.setChecked(load_config().get("auto_rollback", True))
        tb.addWidget(self.chk_rollback)
        tb.addStretch(1)

        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)
        self.spinner.setMaximumWidth(80)
        self.spinner.setTextVisible(False)
        self.spinner.setVisible(False)
        tb.addWidget(self.spinner)

        self._pkexec_warn_bar = QFrame()
        self._pkexec_warn_bar.setStyleSheet(
            "QFrame { background-color: #5a4a1a; border: 1px solid #a08030; border-radius: 4px; }"
            "QFrame QLabel { color: #fdf0c8; }")
        wl = QHBoxLayout(self._pkexec_warn_bar)
        wl.addWidget(QLabel("⚠  Privilege escalation (pkexec) was refused or failed repeatedly. Is a polkit "
                            "authentication agent running, and is your user allowed to administer this system?"))
        close = QToolButton()
        close.setText("✕")
        close.setStyleSheet("QToolButton { color: #fdf0c8; border: none; }")
        close.clicked.connect(lambda: self._pkexec_warn_bar.setVisible(False))
        wl.addWidget(close)
        self._pkexec_warn_bar.setVisible(False)
        self.main_layout.addWidget(self._pkexec_warn_bar)

    def _build_search_bar(self):
        w = QWidget()
        box = QHBoxLayout(w)
        box.setContentsMargins(12, 4, 12, 0)
        box.setSpacing(6)
        self.main_layout.addWidget(w)
        box.addWidget(QLabel("Filter:"))
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search all kernels…")
        self.search_entry.textChanged.connect(lambda _t: self._search_debounce_timer.start(250))
        box.addWidget(self.search_entry)

    def _build_stack(self):
        self.stack = QTabWidget()
        for ui in self.providers.values():
            ui.tab_index = self.stack.addTab(self._build_provider_tab(ui), ui.provider.title)
        self.main_layout.addWidget(self.stack, 1)

    def _build_provider_tab(self, ui):
        prov = ui.provider
        outer = QWidget()
        v = QVBoxLayout(outer)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 4)
        bl.setSpacing(6)
        bl.addWidget(QLabel("Flavor:"))
        ui.combo = QComboBox()
        ui.combo.addItems(["Any"])
        ui.combo.setMinimumWidth(180)
        ui.combo.currentIndexChanged.connect(lambda _i, u=ui: self._on_flavor_changed(u))
        bl.addWidget(ui.combo)
        hint = QLabel("ℹ  " + prov.hint if prov.hint else "")
        hint.setStyleSheet("color: gray; font-size: 9pt;")
        hint.setWordWrap(True)
        bl.addWidget(hint, 1)
        if prov.id == "xanmod" and self.hw.psabi:
            info = QToolButton()
            info.setText("ⓘ  x86-64 levels")
            info.clicked.connect(self._show_psabi_info_dialog)
            bl.addWidget(info)
        v.addWidget(bar)

        if prov.id == "xanmod" and self.hw.psabi:
            title, _d = XANMOD_FLAVOR_INFO.get(self.hw.psabi, ("", ""))
            rec = QLabel(f"★ Your CPU supports up to <b>{title}</b> — kernels marked "
                         f"<span style='color:#88cc88'>★ recommended</span> are the best match; "
                         f"higher levels are disabled because they would not boot.")
            rec.setTextFormat(Qt.TextFormat.RichText)
            rec.setStyleSheet("color: gray; font-size: 9pt; margin: 0 12px 6px 12px;")
            rec.setWordWrap(True)
            v.addWidget(rec)

        ui.banner_frame = QFrame()
        ui.banner_frame.setObjectName("card")
        bf = QHBoxLayout(ui.banner_frame)
        bf.setContentsMargins(12, 8, 12, 8)
        ui.banner_label = QLabel()
        ui.banner_label.setWordWrap(True)
        ui.banner_label.setTextFormat(Qt.TextFormat.RichText)
        bf.addWidget(ui.banner_label, 1)
        ui.banner_btn = QPushButton("Add repository")
        bf.addWidget(ui.banner_btn)
        ui.banner_frame.setVisible(False)
        v.addWidget(ui.banner_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        ui.box = QVBoxLayout(container)
        ui.box.setContentsMargins(0, 0, 0, 0)
        ui.box.addStretch(1)
        scroll.setWidget(container)
        v.addWidget(scroll, 1)
        return outer

    def _show_psabi_info_dialog(self):
        box = QMessageBox(self.win)
        box.setWindowTitle("x86-64 psABI Levels")
        box.setTextFormat(Qt.TextFormat.RichText)
        rows = [f"<p><b>{XANMOD_FLAVOR_INFO[f][0]}</b><br>{XANMOD_FLAVOR_INFO[f][1]}</p>" for f in ("v1", "v2", "v3", "v4")]
        if self.hw.psabi:
            rows.insert(0, f"<p style='color:#88cc88'><b>Your CPU supports up to: "
                           f"{XANMOD_FLAVOR_INFO[self.hw.psabi][0]}</b></p><hr>")
        box.setText("".join(rows))
        box.addButton("Close", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def _show_system_info(self):
        d, hw = self.distro, self.hw
        st = privilege.helper_state(d)
        self.helper_state = st
        lines = [
            f"<b>Distribution:</b> {d.pretty_name}",
            f"<b>Family / base:</b> {d.family} / {d.base or '—'}   <small>(chain: {' → '.join(d.chain)})</small>",
            f"<b>Package manager:</b> {self.backend.pm_name}",
            f"<b>Running kernel:</b> {self.running_release}",
            f"<b>CPU:</b> {hw.cpu_model or hw.arch} — {hw.arch}" + (f", x86-64-{hw.psabi}" if hw.psabi else ""),
            f"<b>GPU:</b> {', '.join(sorted(hw.gpus)).upper() or 'none detected'}"
            + (f"   <b>Cloud VM:</b> {hw.cloud.upper()}" if hw.cloud else ""),
            f"<b>Kernel sources shown:</b> {', '.join(p.provider.title for p in self.providers.values())}",
            f"<b>Privileged helper:</b> {privilege.helper_path()}  <small>({st.value})</small>",
            f"<b>GKM:</b> {APP_VERSION}" + ("  (AppImage)" if privilege.is_appimage() else "")
            + "  ·  GPL-3.0-only, no warranty",
        ]
        if d.immutable:
            lines.append(f"<span style='color:orange'><b>Immutable system:</b> {d.immutable_reason} — "
                         "kernels can be listed but not changed.</span>")
        box = QMessageBox(self.win)
        box.setWindowTitle("System")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText("<br>".join(lines))
        box.addButton("Close", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def _build_log_panel(self):
        cw = QWidget()
        controls = QHBoxLayout(cw)
        controls.setContentsMargins(12, 4, 12, 0)
        controls.setSpacing(8)
        self.btn_details = QPushButton("Show Details")
        self.btn_details.setCheckable(True)
        self.btn_details.toggled.connect(lambda c: self._log_container.setVisible(c))
        self.status_label = QLabel()
        controls.addWidget(self.btn_details)
        controls.addWidget(self.status_label, 1)
        self.main_layout.addWidget(cw)

        self._log_container = QWidget()
        lb = QVBoxLayout(self._log_container)
        lb.setContentsMargins(12, 4, 12, 12)
        self.textedit = QTextEdit()
        self.textedit.setReadOnly(True)
        self.textedit.setFontFamily("monospace")
        self.textedit.setMinimumHeight(180)
        lb.addWidget(self.textedit)
        self._log_container.setVisible(False)
        self.main_layout.addWidget(self._log_container)

    # ── filtering / rebuilding ───────────────────────────────────────────────
    def _on_flavor_changed(self, ui):
        txt = ui.combo.currentText()
        if txt:
            ui.flavor_filter = txt
            self._rebuild_provider(ui, self.search_entry.text())

    def _refilter_all(self):
        q = self.search_entry.text()
        for ui in self.providers.values():
            self._rebuild_provider(ui, q)

    def _flavor_matches(self, ui, label, filt):
        if filt == "Any":
            return True
        if ui.provider.layout == "nested":
            return mainline_flavor_matches(label, filt)
        return label == filt

    def _empty_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("margin-top: 40px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        return lbl

    def _rebuild_provider(self, ui, query=""):
        self._rebuild_generation += 1
        gen = self._rebuild_generation
        self._clear_layout(ui.box)
        query = (query or "").strip().lower()
        if ui.provider.layout == "nested":
            self._rebuild_nested(ui, query, gen)
        else:
            self._rebuild_flat(ui, query)

    def _clear_layout(self, layout):
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_nested(self, ui, query, gen):
        filt = ui.flavor_filter
        chunks = []
        metas = [r for r in ui.metas if self._flavor_matches(ui, r.flavor, filt)]
        metas_visible = metas if not query else [r for r in metas if query in r.name.lower()]
        if metas_visible:
            chunks.append(lambda mv=metas_visible: ui.box.insertWidget(ui.box.count() - 1, self._build_meta_card(mv)))
        for kver in self.backend.sorted_newest_first(ui.nested.keys()):
            rows = [r for r in ui.nested[kver] if self._flavor_matches(ui, r.flavor, filt)]
            if not rows:
                continue
            visible = rows if not query else [r for r in rows if query in r.name.lower() or query in kver]
            if visible:
                chunks.append(lambda kv=kver, vr=visible, allr=rows: ui.box.insertWidget(
                    ui.box.count() - 1, self._build_version_card(kv, vr, allr)))
        if not chunks:
            msg = (f"No {filt} kernels found.\nTry a different flavor filter above, or click Refresh."
                   if filt != "Any" else "No kernels found.\nTry clicking Refresh.")
            ui.box.insertWidget(ui.box.count() - 1, self._empty_label(msg))
            return
        it = iter(chunks)

        def dispatch_next():
            if gen != self._rebuild_generation and False:
                return
            try:
                next(it)()
            except StopIteration:
                return
            QTimer.singleShot(0, dispatch_next)
        QTimer.singleShot(0, dispatch_next)

    def _rebuild_flat(self, ui, query):
        filt = ui.flavor_filter
        groups = {}
        for r in ui.rows:
            if not self._flavor_matches(ui, r.flavor, filt):
                continue
            if query and query not in r.name.lower() and query not in r.kgroup.lower():
                continue
            groups.setdefault((r.kgroup, r.flavor), []).append(r)
        if not groups:
            ui.box.insertWidget(ui.box.count() - 1, self._empty_label(
                "No kernels found (or none match the current filter).\nTry clicking Refresh."))
            return
        order = ui.provider.flavor_order

        def rank(rows):
            return min(_STATUS_RANK.get(r.status, 2) for r in rows)

        def cmp(a, b):
            ra, rb = rank(groups[a]), rank(groups[b])
            if ra != rb:
                return ra - rb
            fa, fb = self._flavor_sort_key(a[1], order), self._flavor_sort_key(b[1], order)
            if fa != fb:
                return fa - fb
            c = -self._version_cmp(groups[a][0].version, groups[b][0].version)
            return c or (a[0] > b[0]) - (a[0] < b[0])

        for key in sorted(groups, key=cmp_to_key(cmp)):
            ui.box.insertWidget(ui.box.count() - 1, self._build_flat_group_card(ui, key, groups[key]))

    def _build_flat_group_card(self, ui, key, rows):
        kgroup, flavor = key
        label = rows[0].group_label or kgroup
        any_active = any(r.active for r in rows)
        any_inst = any(r.installed for r in rows)
        status = ("  <span style='color:green'><b>[Active]</b></span>" if any_active
                  else "  <span style='color:gray'>[Installed]</span>" if any_inst else "")
        warn = rec = ""
        if ui.provider.id == "xanmod":
            if flavor == "v4":
                warn = "  <span style='color:orange'>⚠ AVX-512 — usually no kernel benefit</span>"
            elif flavor == "edge":
                warn = "  <span style='color:orange'>⚠ bleeding-edge</span>"
            if flavor == self.hw.psabi:
                rec = "  <span style='color:#88cc88'>★ recommended for your CPU</span>"
        if all(r.blocked_reason for r in rows):
            warn += f"  <span style='color:orange'>⚠ {rows[0].blocked_reason}</span>"
        tag = f"  <span style='color:#88aaff'>[{flavor}]</span>" if flavor and flavor != "generic" else ""
        title = (f"<b>{ui.provider.card_prefix}{label}</b>{tag}{status}{warn}{rec}"
                 f"  <small>({len(rows)} packages)</small>")
        tooltip = self._group_tooltip(f"{ui.provider.card_prefix}{label} [{flavor}]", rows)
        desc = next((r.description for r in rows if r.role == "Kernel" and r.description), "") \
            or next((r.description for r in rows if r.description), "")
        if desc:
            tooltip = f"{desc}\n\n{tooltip}"
        info = XANMOD_FLAVOR_INFO.get(flavor) if ui.provider.id == "xanmod" else None
        if info:
            tooltip += f"\n\n{info[0]}:\n{info[1]}"
        return self._build_simple_group_card(title, rows, tooltip)

    # ── data collection ──────────────────────────────────────────────────────
    def collect_sync(self, refresh=False):
        return self.backend.collect(refresh=refresh)

    def _reload_kernels_async(self, refresh=None):
        refresh = self._refresh_next if refresh is None else refresh
        self._refresh_next = False

        def worker():
            try:
                items = self.collect_sync(refresh)
                self._dispatch.call(self._on_kernels_loaded, items)
            except Exception as e:
                self._dispatch.call(self._append_log, f"\n[ERROR] {traceback.format_exc()}\n")
                self._dispatch.call(self._error_dialog, "Could not load kernel list",
                                    "An error occurred while reading the package database.\n\n"
                                    "Click 'Show Details' for the full error, then try Refresh.\n\n"
                                    f"Summary: {type(e).__name__}: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_kernels_loaded(self, items):
        self.kernels = items
        self._populate_models(items)
        for w in self.backend.warnings:
            self._show_toast(w, timeout=8)

    def _populate_models(self, items):
        for ui in self.providers.values():
            ui.rows, ui.nested, ui.metas = [], {}, []
        for r in items:
            r.is_selected = False
            ui = self.providers.get(r.provider)
            if ui is None:
                continue
            ui.rows.append(r)
            if ui.provider.layout == "nested":
                if r.is_meta:
                    ui.metas.append(r)
                else:
                    ui.nested.setdefault(r.kgroup or "ungrouped", []).append(r)
        for ui in self.providers.values():
            self._refresh_flavor_combo(ui)
            self._refresh_banner(ui)
            missing_offer = any(ui.provider.id in o.providers and not o.present() for o in self.offers)
            visible = bool(ui.rows) or ui.provider.show_when_empty or missing_offer
            self.stack.setTabVisible(ui.tab_index, visible)
        self._refilter_all()
        self._update_buttons()

    def _refresh_flavor_combo(self, ui):
        order = ui.provider.flavor_order
        present = sorted({r.flavor for r in ui.rows if r.flavor},
                         key=lambda f: (self._flavor_sort_key(f, order or None), f))
        want = ui.flavor_filter
        ui.combo.blockSignals(True)
        ui.combo.clear()
        ui.combo.addItems(["Any"] + present)
        pick = want if want in present or want == "Any" else (
            ui.provider.default_flavor if ui.provider.default_flavor in present else "Any")
        ui.combo.setCurrentText(pick)
        ui.flavor_filter = pick
        ui.combo.blockSignals(False)
        ui.combo.setVisible(len(present) > 1 or ui.provider.layout == "nested")

    def _refresh_banner(self, ui):
        missing = [o for o in self.offers if ui.provider.id in o.providers and not o.present()]
        ui.banner_frame.setVisible(bool(missing))
        if not missing:
            return
        o = missing[0]
        ui.banner_label.setText(f"<b>{o.title}</b> is not configured on this system. {o.description}")
        try:
            ui.banner_btn.clicked.disconnect()
        except TypeError:
            pass
        ui.banner_btn.setText(f"Add {o.title}")
        ui.banner_btn.clicked.connect(lambda _=False, off=o: self._confirm_add_repo(off))

    # ── repositories ─────────────────────────────────────────────────────────
    def _maybe_offer_add_repos(self):
        if getattr(self, "_repo_offer_shown", False):
            return
        self._repo_offer_shown = True
        missing = [o for o in self.offers if o.offer_on_start and not o.present()]
        if not missing:
            return
        box = QMessageBox(self.win)
        box.setWindowTitle("Missing Kernel Repositories")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(f"<b>{' • '.join(o.title for o in missing)}</b><br><br>Add them now?")
        box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
        ok = box.addButton("Add Repositories", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is ok:
            self._add_repos(list(missing))

    def _confirm_add_repo(self, offer):
        box = QMessageBox(self.win)
        box.setWindowTitle(f"Add {offer.title}")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(offer.description + (f"\n\n⚠  {offer.warning}" if offer.warning else ""))
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        ok = box.addButton(f"Add {offer.title}", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is ok:
            self._add_repos([offer])

    def _add_repos(self, queue):
        if not queue:
            if self._upgrade_after_repos:
                self._upgrade_after_repos = False
                self._run_full_upgrade()          # same log session, still busy
                return
            self._set_busy(False)
            self._reload_kernels_async(refresh=True)
            self._end_log_session()
            return
        offer = queue.pop(0)
        if self._log_handle is None:
            self.btn_details.setChecked(True)
            self._clear_log()
            self._start_log_session("add-repo")

        def go():
            self._set_busy(True, f"Adding {offer.title}…")

            def done(rc, _o):
                if rc != 0:
                    self._set_busy(False, f"Failed to add {offer.title}.")
                    self._error_dialog(f"Failed to add {offer.title}",
                                       "See the Details log for more information. This is usually a network "
                                       "problem or an unsupported distribution release.")
                    self._reload_kernels_async()
                    self._end_log_session()
                    return
                if offer.then_upgrade:
                    self._upgrade_after_repos = True
                self._add_repos(queue)
            self._stream_subprocess(self._priv_cmd(offer.subcommand), done)
        self._require_helper(go)

    def _run_full_upgrade(self):
        """Arch: after syncing a newly added repository pacman expects a full upgrade (-Syu), so GKM runs it
        (the repository dialog said it would). The kernel versions are remembered first: if the upgrade
        fails and a kernel changed, the previous one is restored (see _after_failed_upgrade)."""
        snapshot = self._kernel_snapshot()
        self._set_busy(True, "Upgrading the system…")
        self._append_log("\n=== Full system upgrade (pacman -Syu) ===\n")

        def done(rc, _o):
            if rc == 0:
                self._set_busy(False, "System upgraded.")
                self._reload_kernels_async(refresh=True)
                self._show_toast("System upgraded. Reboot if the kernel or core libraries changed.", timeout=6)
                self._end_log_session()
            else:
                self._after_failed_upgrade(snapshot)
        self._stream_subprocess(self._priv_cmd("upgrade-system"), done)

    def _kernel_snapshot(self):
        if not self.backend.restores_after_failed_upgrade:
            return {}
        return {r.name: r.version for r in self._all_rows() if r.installed and r.role in ("Kernel", "Headers")}

    # ── rollback ─────────────────────────────────────────────────────────────
    def _after_failed_upgrade(self, snapshot):
        """The upgrade failed. Kernels that changed or vanished go back to the version they had before,
        from the local pacman cache or the Arch Linux Archive (the helper's `restore-version`)."""
        if not snapshot or not self.chk_rollback.isChecked():
            self._set_busy(False, "Upgrade failed.")
            self._error_dialog("Upgrade failed", "See the Details log for more information."
                               + ("\n\nAutomatic rollback is switched off." if snapshot else ""))
            self._reload_kernels_async(refresh=True)
            self._end_log_session()
            return
        self._set_busy(True, "Upgrade failed: checking the kernels…")
        self._append_log("\n=== Roll back: comparing kernel versions before and after ===\n")

        def look():
            now = {r.name: r.version for r in self.backend.collect() if r.installed}
            return [f"{n}={v}" for n, v in snapshot.items() if now.get(n) != v]

        def got(targets):
            if isinstance(targets, Exception) or not targets:
                self._set_busy(False, "Upgrade failed.")
                self._error_dialog("Upgrade failed", "The upgrade failed, but your kernels are unchanged, so nothing "
                                   "needed rolling back. See the Details log.")
                self._reload_kernels_async(refresh=True)
                self._end_log_session()
                return
            self._append_log("Restoring: " + ", ".join(targets) + "\n")
            self._snapshot_modules()

            def restored(rc, _o):
                if rc != 0:
                    self._set_busy(False, "Rollback failed.")
                    self._error_dialog("Upgrade failed and the rollback did not complete",
                                       "The previous kernel could not be restored automatically. Restore it by hand, for "
                                       "example:\n  sudo pacman -U /var/cache/pacman/pkg/<package>.pkg.tar.zst\n\n"
                                       "See the Details log.")
                    self._reload_kernels_async(refresh=True)
                    self._end_log_session()
                    return
                self._set_busy(False, "Rolled back.")
                self._reload_kernels_async(refresh=True)
                self._error_dialog("Upgrade failed, rolled back",
                                   "The upgrade failed. GKM restored the previous kernel:\n  " + "\n  ".join(targets))
                self._post_change()
            self._stream_subprocess(self._priv_cmd("restore-version", *targets), restored)
        self._async(look, got)

    def _after_failed_install(self, pkgs):
        """The install failed. Anything this operation left behind (it only ever installs packages that were not
        installed before) is removed again, so a failed install doesn't leave a half-installed kernel."""
        if not self.chk_rollback.isChecked():
            self._set_busy(False, "Installation failed.")
            self._error_dialog("Install failed", "See the Details log for more information.")
            self._end_log_session()
            return
        self._set_busy(True, "Installation failed: checking for leftovers…")
        self._append_log("\n=== Roll back: looking for packages the failed install left behind ===\n")

        def look():
            have = {r.spec for r in self.backend.collect() if r.installed}
            return [p for p in pkgs if p in have]

        def got(leftovers):
            if isinstance(leftovers, Exception) or not leftovers:
                self._set_busy(False, "Installation failed.")
                self._error_dialog("Install failed", "See the Details log for more information. Nothing was left "
                                   "behind, so there was nothing to roll back.")
                self._reload_kernels_async()
                self._end_log_session()
                return
            self._append_log("Removing: " + ", ".join(leftovers) + "\n")

            def removed(rc, _o):
                self._set_busy(False, "Rolled back." if rc == 0 else "Rollback failed.")
                self._reload_kernels_async()
                if rc == 0:
                    self._error_dialog("Install failed, rolled back", "The install failed. GKM removed the packages it had "
                                       "left behind:\n  " + "\n  ".join(leftovers[:12]))
                else:
                    self._error_dialog("Install failed and the rollback did not complete",
                                       "Some packages may be half-installed. See the Details log, then remove them by hand "
                                       "with your package manager.")
                self._end_log_session()
            self._stream_subprocess(self._priv_cmd("remove", *leftovers), removed)
        self._async(look, got)

    # ── versions ─────────────────────────────────────────────────────────────
    def _show_versions(self, *_):
        rows = list(self._all_rows())
        selected = [r for r in rows if r.is_selected]
        if not selected:
            self._show_toast("Tick a kernel (its card) first, then click Versions…", timeout=5)
            return
        scopes = {frozenset(r.name for r in self.backend.version_scope(r0, rows)) for r0 in selected}
        if len(scopes) > 1:
            self._show_toast("Select one kernel at a time for Versions…", timeout=5)
            return
        scope = self.backend.version_scope(selected[0], rows)
        if not scope:
            self._show_toast("No version history is available for that selection.", timeout=5)
            return
        names = ", ".join(sorted(r.name for r in scope)[:3]) + (" …" if len(scope) > 3 else "")
        dlg = VersionsDialog(self.win, f"Versions of {names}", default_hold=self.backend.restores_after_failed_upgrade)
        self._async(lambda: self.backend.list_versions(scope), dlg.set_result)
        dlg.exec()
        if dlg.chosen is not None:
            self._restore_version(dlg.chosen, dlg.hold)

    def _restore_version(self, option, hold):
        command = "restore-version" if self.backend.restores_after_failed_upgrade else "install"

        def go():
            self._snapshot_modules()
            self._begin("restore-version", f"Installing version {option.version}…")

            def done(rc, _o):
                if rc != 0:
                    self._set_busy(False, "Could not install that version.")
                    self._error_dialog("Could not install that version",
                                       "See the Details log for more information. Nothing was changed if the package "
                                       "manager refused it before starting.")
                    self._reload_kernels_async()
                    self._end_log_session()
                    return
                if not hold:
                    self._set_busy(False, f"Version {option.version} installed.")
                    self._post_change()
                    return
                self._append_log("\n=== Applying hold ===\n")

                def held(rc2, _o2):
                    self._set_busy(False, "Installed and held." if rc2 == 0 else "Installed; the hold failed.")
                    if rc2 != 0:
                        self._error_dialog("Hold failed", "The version was installed but the hold could not be applied.")
                    self._post_change()
                self._stream_subprocess(self._priv_cmd("hold", *option.specs), held)
            self._stream_subprocess(self._priv_cmd(command, *option.specs), done)
        self._require_helper(go)

    def _post_change(self):
        """After installing a specific version: bootloader, DKMS for any new module directory, reboot prompt.
        (No auto-remove: it would see this older build as an old kernel and remove it again.)"""
        self._reload_kernels_async()
        self._run_bootloader_refresh(on_complete=self._dkms_for_new_kernels_then_reboot)

    # ── privileged helper plumbing ───────────────────────────────────────────
    def _priv_cmd(self, sub, *args):
        return ["pkexec", privilege.helper_path(), sub, *args]

    def _require_helper(self, proceed):
        st = self.helper_state = privilege.helper_state(self.distro)
        if st is privilege.HelperState.OK:
            proceed()
        elif st is privilege.HelperState.UNSUPPORTED:
            why = (self.distro.immutable_reason and
                   f"This is an immutable system ({self.distro.immutable_reason}); /usr is read-only, so GKM "
                   "cannot install its helper or change kernel packages here.") or \
                  "pkexec (polkit) was not found. Install polkit and a polkit authentication agent."
            self._error_dialog("Cannot make changes on this system", why)
        elif privilege.is_appimage():
            self._offer_helper_install(proceed)
        else:
            if st is privilege.HelperState.OUTDATED and not self._helper_notice_shown:
                self._helper_notice_shown = True
                self._show_toast("The installed gkm-helper is older than this GKM version; "
                                 "update the gkm package.", timeout=8)
            proceed()

    def _offer_helper_install(self, proceed=None):
        box = QMessageBox(self.win)
        box.setWindowTitle("Install GKM helper")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(privilege.describe_install())
        box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
        ok = box.addButton("Install Helper", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self.btn_details.setChecked(True)
        self._clear_log()
        self._start_log_session("install-helper")
        self._set_busy(True, "Installing GKM helper…")

        def worker():
            script = privilege.build_install_script()
            rc = privilege.run_privileged_script(script, lambda l: self._dispatch.call(self._append_log, l))
            self._dispatch.call(self._on_helper_installed, rc, proceed)
        threading.Thread(target=worker, daemon=True).start()

    def _on_helper_installed(self, rc, proceed):
        self._set_busy(False)
        self.helper_state = privilege.helper_state(self.distro)
        ok = rc == 0 and self.helper_state is privilege.HelperState.OK
        self._set_busy(False, "Helper installed." if ok else "Helper installation failed.")
        self._end_log_session()
        if not ok:
            self._error_dialog("Helper installation failed", "See the Details log for more information.")
            return
        self._show_toast("GKM helper installed.")
        if proceed:
            proceed()

    def check_helper_at_startup(self):
        if privilege.is_appimage() and self.helper_state in (privilege.HelperState.MISSING,
                                                             privilege.HelperState.OUTDATED):
            self._offer_helper_install()
        elif self.distro.immutable:
            self._show_toast(f"Immutable system ({self.distro.immutable_reason}): kernels are listed read-only.",
                             timeout=8)

    def _async(self, fn, callback):
        """Run fn() off the Qt thread; callback(result_or_exception) runs on the Qt thread."""
        def worker():
            try:
                result = fn()
            except Exception as e:      # noqa: BLE001 - handed to the callback
                result = e
            self._dispatch.call(callback, result)
        threading.Thread(target=worker, daemon=True).start()

    # ── subprocess streaming ─────────────────────────────────────────────────
    def _stream_subprocess(self, cmd, on_done):
        def worker():
            combined = []
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        bufsize=1, env=host_env(), errors="replace")
                for line in proc.stdout:
                    combined.append(line)
                    self._dispatch.call(self._append_log, line)
                rc = proc.wait()
            except Exception as e:
                rc = 1
                combined.append(f"\nERROR: {e}\n")
                self._dispatch.call(self._append_log, combined[-1])
            if rc == 100 and self.backend.family == "debian":
                self._dispatch.call(self._append_log, "\n⚠  apt exited with code 100 — package not found or "
                                    "dependency conflict. Check the log above.\n")
            if cmd and "pkexec" in str(cmd[0]):
                if rc in (126, 127):       # dismissed / not authorised / pkexec missing
                    self._dispatch.call(self._on_pkexec_fail)
                elif rc == 0:
                    self._dispatch.call(self._on_pkexec_success)
            self._dispatch.call(on_done, rc, "".join(combined))
        threading.Thread(target=worker, daemon=True).start()

    def _on_pkexec_fail(self):
        self._pkexec_fail_count += 1
        if self._pkexec_fail_count >= 2:
            self._pkexec_warn_bar.setVisible(True)

    def _on_pkexec_success(self):
        self._pkexec_fail_count = 0
        self._pkexec_warn_bar.setVisible(False)

    # ── actions ──────────────────────────────────────────────────────────────
    def _action_check_updates(self, *_):
        def go():
            self._set_busy(True, "Updating sources…")
            self._stream_subprocess(self._priv_cmd("update-sources"), self._on_update_sources_done)
        self._require_helper(go)

    def _on_update_sources_done(self, rc, _o):
        self._set_busy(False, "Sources updated." if rc == 0 else "Update failed — see log.")
        self._reload_kernels_async(refresh=True)

    def _get_selected_packages(self, only_installed=None):
        specs, bad = [], []
        for row in self._all_rows():
            if row.is_selected and (only_installed is None or row.installed == only_installed):
                if row.blocked_reason and not row.installed:
                    continue        # never install something flagged unbootable/unusable on this hardware
                if _SPEC_RE.match(row.spec):
                    specs.append(row.spec)
                else:
                    bad.append(f"Unsafe or invalid package spec rejected: {row.spec!r}")
        if bad:
            self._error_dialog("Invalid package name(s)", "\n".join(bad))
        return list(dict.fromkeys(specs))

    def _begin(self, prefix, text):
        self.btn_details.setChecked(True)
        self._clear_log()
        self._start_log_session(prefix)
        self._set_busy(True, text)

    def _snapshot_modules(self):
        self._pre_modules = list_module_dirs()

    def _install_selected(self, *_):
        pkgs = self._get_selected_packages(only_installed=False)
        if not pkgs:
            self._error_dialog("Nothing selected", "Select kernels to install.")
            return

        def start(final):
            def go():
                self._snapshot_modules()
                self._begin("install", "Installing kernels…")
                self._stream_subprocess(self._priv_cmd("install", *final),
                                        lambda rc, o, f=final: self._on_install_done(rc, o, f))
            self._require_helper(go)
        self._preflight_then(pkgs, start)

    # ── pre-flight: simulate before asking for a password ────────────────────
    def _preflight_then(self, pkgs, proceed):
        """Where the backend can simulate an install (APT: `apt-get -s`, no root needed), do it
        first. Combinations the package manager would reject are explained, and packages it
        would silently REMOVE are shown, before any privileged command runs."""
        if not self.backend.has_preflight:
            proceed(pkgs)
            return
        self._set_busy(True, "Checking that these packages can be installed together…")

        def worker():
            res = self.backend.preflight(pkgs)
            self._dispatch.call(self._on_preflight, res, proceed)
        threading.Thread(target=worker, daemon=True).start()

    def _on_preflight(self, res, proceed):
        self._set_busy(False)
        if res.output and (res.dropped or not res.ok):
            self._append_log("\n=== Dependency check (simulation) ===\n" + res.output + "\n")
        if not res.ok:
            lines = [f"  • {sp}: {why}" for sp, why in res.dropped[:8]]
            self._error_dialog(
                "These packages can't be installed",
                (res.message or "The package manager reports a conflict.") +
                ("\n\nLeft out because they can't be installed here:\n" + "\n".join(lines) if lines else "") +
                "\n\nNothing was changed. Click 'Show Details' for the full simulation output.")
            return
        if not res.dropped and not res.removals:
            proceed(res.packages)
            return
        parts = []
        if res.dropped:
            shown = [f"  • {sp}" for sp, _w in res.dropped[:10]]
            more = f"\n  … and {len(res.dropped) - 10} more" if len(res.dropped) > 10 else ""
            parts.append(f"{len(res.dropped)} of the selected packages can't be installed on this system and will be "
                         "left out:\n" + "\n".join(shown) + more)
            if any(sp.startswith("linux-modules-nvidia") for sp, _w in res.dropped):
                parts.append("The prebuilt NVIDIA modules don't match the NVIDIA driver version you have installed. "
                             "The kernel itself installs fine; to use the NVIDIA driver with it, rely on DKMS "
                             "(install the matching headers) or update the NVIDIA driver packages.")
        if res.removals:
            parts.append("Installing this will also REMOVE these installed packages:\n  " + ", ".join(res.removals[:15]) +
                         (" …" if len(res.removals) > 15 else ""))
        box = QMessageBox(self.win)
        box.setWindowTitle("Review before installing")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("\n\n".join(parts) + f"\n\nContinue with the remaining {len(res.packages)} package(s)?")
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        go = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is go:
            proceed(res.packages)

    def _on_install_done(self, rc, _o, installed_specs=()):
        if rc != 0:
            self._after_failed_install(list(installed_specs))
            return
        self._set_busy(False, "Installation complete.")
        self._post_install()

    def _post_install(self):
        """auto-remove (optional) -> bootloader refresh -> DKMS -> reboot prompt, in order."""
        def after_cleanup():
            self._run_bootloader_refresh(on_complete=self._dkms_for_new_kernels_then_reboot)
        self._reload_kernels_async()
        if self.chk_auto_rm.isChecked():
            self._auto_remove_old_kernels(then=after_cleanup)
        else:
            after_cleanup()

    def _install_and_hold_selected(self, *_):
        pkgs = self._get_selected_packages(only_installed=False)
        if not pkgs:
            self._error_dialog("Nothing selected", "Select kernels to install and hold.")
            return

        def start(final):
            def go():
                self._snapshot_modules()
                self._begin("install-hold", "Installing kernels…")

                def on_install(rc, _o):
                    if rc != 0:
                        self._after_failed_install(list(final))
                        return
                    self._set_busy(True, f"Applying hold to {len(final)} package(s)…")
                    self._append_log(f"\n=== Applying hold to {len(final)} package(s) ===\n")

                    def on_hold(rc2, _o2):
                        ok = rc2 == 0
                        self._set_busy(False, "Install + Hold complete." if ok else "Hold failed after install.")
                        if ok:
                            self._show_toast(f"Installed and held: {', '.join(final)}")
                        else:
                            self._error_dialog("Hold failed", "Packages were installed but the hold could not be "
                                               "applied. See the Details log.")
                        self._post_install()
                    self._stream_subprocess(self._priv_cmd("hold", *final), on_hold)
                self._stream_subprocess(self._priv_cmd("install", *final), on_install)
            self._require_helper(go)
        self._preflight_then(pkgs, start)

    def _hold_or_unhold(self, action):
        pkgs = self._get_selected_packages(only_installed=True)
        if not pkgs:
            self._error_dialog(f"Nothing to {action}", f"Select installed kernels to {action}.")
            return

        def go():
            self._begin(action, "Applying hold…" if action == "hold" else "Releasing hold…")

            def done(rc, _o):
                ok = rc == 0
                if action == "hold":
                    self._set_busy(False, "Hold applied." if ok else "Hold failed.")
                    self._show_toast(f"Held: {', '.join(pkgs)}" if ok else "Hold failed — see log.")
                else:
                    self._set_busy(False, "Hold released." if ok else "Unhold failed.")
                    self._show_toast(f"Unheld: {', '.join(pkgs)}" if ok else "Unhold failed — see log.")
                self._reload_kernels_async()
                self._end_log_session()
            self._stream_subprocess(self._priv_cmd(action, *pkgs), done)
        self._require_helper(go)

    def _hold_selected(self, *_):
        self._hold_or_unhold("hold")

    def _unhold_selected(self, *_):
        self._hold_or_unhold("unhold")

    def _run_bootloader_refresh(self, on_complete=None):
        self._append_log("\n=== Refreshing bootloader (safety net) ===\n")

        def on_done(rc, _o):
            self._append_log("✓ Bootloader step completed.\n" if rc == 0
                             else "⚠ Bootloader step returned a non-zero exit code — check log.\n")
            if on_complete:
                on_complete()
        self._stream_subprocess(self._priv_cmd("update-bootloader"), on_done)

    def _ask_remove_mode(self, title, text):
        """-> 'remove' | 'purge' | 'cancel' (Purge only if the family has a distinct purge)."""
        box = QMessageBox(self.win)
        box.setWindowTitle(title)
        box.setText(text)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        b_rm = box.addButton("Remove", QMessageBox.ButtonRole.AcceptRole)
        b_pg = box.addButton(self.backend.purge_label, QMessageBox.ButtonRole.DestructiveRole) \
            if self.backend.supports_purge else None
        box.exec()
        c = box.clickedButton()
        return "remove" if c is b_rm else "purge" if (b_pg is not None and c is b_pg) else "cancel"

    def _remove_selected(self, *_):
        selected = [r for r in self._all_rows() if r.is_selected]
        if any(r.active for r in selected):
            self._error_dialog("Cannot Remove Active Kernel", "The currently running kernel cannot be removed.")
            return
        pkgs = self._get_selected_packages(only_installed=True)
        if not pkgs:
            return
        extra = ("Remove: uninstalls the packages but keeps configuration files.\n\n"
                 f"{self.backend.purge_help}\n\n" if self.backend.supports_purge else
                 "This uninstalls the selected packages.\n\n")
        mode = self._ask_remove_mode("Remove kernels?", extra + f"Packages to remove: {len(pkgs)}")
        if mode == "cancel":
            return
        self._run_removal(pkgs, mode)

    def _run_removal(self, pkgs, mode, then=None):
        def go():
            self._begin(mode, f"{'Purging' if mode == 'purge' else 'Removing'} kernels…")
            args = (["--purge"] if mode == "purge" else []) + pkgs
            self._stream_subprocess(self._priv_cmd("remove", *args), lambda rc, o: self._on_remove_done(rc, then))
        self._require_helper(go)

    def _on_remove_done(self, rc, then=None):
        self._set_busy(False, "Done." if rc == 0 else "Remove failed.")
        self._reload_kernels_async()
        if rc != 0:
            self._error_dialog("Remove failed", "See the Details log for more information.")
            self._end_log_session()
            return
        if then:
            then()
        else:
            self._run_bootloader_refresh(on_complete=self._end_log_session)

    def _auto_remove_old_kernels(self, *_, then=None):
        cand = self.backend.auto_remove_candidates(list(self._all_rows()))
        specs = list(dict.fromkeys(r.spec for r in cand if _SPEC_RE.match(r.spec)))
        if not specs:
            self._show_toast("Nothing to auto-remove.")
            if then:
                then()
            return
        mode = self._ask_remove_mode(
            "Auto-Remove Old Kernels",
            f"Found {len(specs)} package(s) belonging to old kernel builds.\n\n"
            "The running kernel, the two newest builds of each kernel type, held packages and "
            "meta packages are kept.\n\n" + ("Remove: keep config files.\nPurge: also delete config files."
                                              if self.backend.supports_purge else ""))
        if mode == "cancel":
            if then:
                then()
            return
        self._run_removal(specs, mode, then=then)

    # ── DKMS / reboot ────────────────────────────────────────────────────────
    def _dkms_for_new_kernels_then_reboot(self):
        after = list_module_dirs()
        new = sorted(k for k in (after - self._pre_modules) if k != self.running_release)
        if not new:
            self._show_reboot_dialog()
            self._end_log_session()
            return
        self._run_dkms(new, self._on_dkms_done)

    def _run_dkms(self, kvers, on_done):
        self._set_busy(True, f"Rebuilding DKMS modules for {len(kvers)} kernel(s)…")
        self._append_log(f"\n=== DKMS: processing {len(kvers)} kernel(s) ===\n" + "".join(f"  → {k}\n" for k in kvers))
        self._stream_subprocess(self._priv_cmd("dkms-autoinstall", *kvers), on_done)

    def _dkms_rebuild_all(self, *_):
        kvers = sorted(list_module_dirs())
        if not kvers:
            self._error_dialog("No kernels found", "No installed kernel module directories were found.")
            return

        def go():
            self._begin("dkms", "Rebuilding DKMS modules…")
            self._run_dkms(kvers, lambda rc, _o: (self._set_busy(False, "DKMS finished." if rc == 0 else
                                                                 "DKMS reported problems — see log."),
                                                  self._end_log_session()))
        self._require_helper(go)

    def _on_dkms_done(self, rc, _o):
        self._set_busy(False)
        if rc != 0:
            box = QMessageBox(self.win)
            box.setWindowTitle("DKMS Warning")
            box.setText("Some DKMS modules may not have built correctly.\n\nCheck the Details log for specifics.\n\n"
                        "The new kernel was installed — you can still reboot, but some driver modules "
                        "(e.g. NVIDIA) may not be available until DKMS is fixed. Make sure the matching "
                        "headers/devel package is installed.")
            box.addButton("Stay & Review Log", QMessageBox.ButtonRole.RejectRole)
            rb = box.addButton("Reboot Anyway", QMessageBox.ButtonRole.DestructiveRole)
            box.exec()
            if box.clickedButton() is rb:
                self._show_reboot_dialog()
        else:
            self._show_reboot_dialog()
        self._end_log_session()

    def _show_reboot_dialog(self):
        box = QMessageBox(self.win)
        box.setWindowTitle("Reboot Required")
        box.setText("Your new kernel is ready. Reboot now to use it?")
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        ok = box.addButton("Reboot Now", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is ok:
            self._require_helper(lambda: subprocess.Popen(self._priv_cmd("reboot"), env=host_env()))

    # ── buttons / misc ───────────────────────────────────────────────────────
    def _update_buttons(self):
        ci = cr = ch = cu = False
        for row in self._all_rows():
            if row.is_selected:
                if not row.installed:
                    ci = True
                if row.installed and not row.active:
                    cr = True
                if row.installed and not row.held:
                    ch = True
                if row.installed and row.held:
                    cu = True
        b = self.busy
        self.btn_install.setEnabled(ci and not b)
        self.btn_install_hold.setEnabled(ci and not b)
        self.btn_remove.setEnabled(cr and not b)
        self.btn_hold.setEnabled(ch and not b)
        self.btn_unhold.setEnabled(cu and not b)
        self.btn_refresh.setEnabled(not b)
        self.btn_autorm.setEnabled(not b)
        self.btn_dkms.setEnabled(not b)
        self.btn_versions.setEnabled(not b)

    def _check_for_app_update(self):
        def worker():
            try:
                req = urllib.request.Request(RELEASES_API_URL, headers={"User-Agent": f"XKM-Multi-Kernel-Manager/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
                tag = data.get("tag_name", "").lstrip("v")
                if tag and version_newer(tag, APP_VERSION):
                    self._dispatch.call(self._on_update_available, tag, data.get("html_url", ""))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_available(self, new_version, url):
        self.toast_overlay.add_toast(f"Update available: v{new_version}  —  click to open release page",
                                     timeout=0, button_label="Open", on_button=lambda: self._open_url(url))

    def _show_toast(self, message, timeout=3):
        self.toast_overlay.add_toast(message, timeout=timeout * 1000)

    @staticmethod
    def _open_url(url):
        try:
            subprocess.Popen(["xdg-open", url], env=host_env())
        except Exception:
            pass

    def on_mode_toggled(self, dark):
        cfg = load_config()
        cfg["dark_mode"] = dark
        save_config(cfg)
        self.win.apply_color_scheme()
        self.status_push(f"Switched to {'Dark' if dark else 'Light'} mode")

    def status_push(self, msg):
        self.status_label.setText(msg)

    def _append_log(self, text):
        self.textedit.moveCursor(QTextCursor.MoveOperation.End)
        self.textedit.insertPlainText(text)
        self.textedit.ensureCursorVisible()
        if self._log_handle:
            try:
                self._log_handle.write(text)
                self._log_handle.flush()
            except Exception:
                pass

    def _start_log_session(self, prefix):
        if self._log_handle:
            self._end_log_session()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fp = LOG_DIR / f"{prefix}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
        self._log_handle = open(fp, "w", encoding="utf-8")
        self._append_log(f"\n=== Log started: {fp} ===\n")

    def _end_log_session(self):
        if self._log_handle:
            self._append_log("\n=== Log ended ===\n")
            self._log_handle.close()
        self._log_handle = None

    def _clear_log(self):
        self.textedit.clear()

    def _set_busy(self, busy, text=""):
        self.busy = busy
        self.spinner.setVisible(busy)
        self.status_push(text if text else ("Working…" if busy else "Ready"))
        self._update_buttons()

    def _error_dialog(self, title, message):
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
