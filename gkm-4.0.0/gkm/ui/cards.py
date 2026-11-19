# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Expandable kernel cards (version -> flavor -> package rows) with one-click group selection.

Selection state lives on the KernelPackage rows, so a group click works even
before a card's rows have been built (they are created lazily on first expand,
which keeps the widget count - and theme-switch cost - low).
"""
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .widgets import ClickableFrame

_FOREGROUND_RE = re.compile(r"foreground='([^']+)'")


def _to_richtext(markup):
    """Row/label markup was authored for Pango (foreground='green'); Qt rich
    text wants style='color:green'."""
    return _FOREGROUND_RE.sub(r"style='color:\1'", markup)


class CardsMixin:
    def _split_group_targets(self, rows):
        """Split a group of rows into (need_install, need_removal) — i.e.
        packages that aren't installed yet vs. installed-but-inactive ones."""
        need_install = [r for r in rows if (not r.blocked_reason) and not r.is_active and not r.is_installed
                        and not r.opt_in]
        need_removal = [r for r in rows if (not r.blocked_reason) and not r.is_active and r.is_installed]
        return need_install, need_removal

    def _group_click_targets(self, rows):
        """What a single click on a group header should select: the
        not-yet-installed packages if there are any (so one click installs
        exactly what's missing and never re-touches anything already
        installed); otherwise the installed/inactive ones, so the same
        click is still useful for a one-shot removal once everything in
        the group is already installed."""
        need_install, need_removal = self._split_group_targets(rows)
        return need_install if need_install else need_removal

    def _update_group_tristate(self, rows, check_map, grp_check):
        target = self._group_click_targets(rows)
        if not target:
            grp_check.setCheckState(Qt.CheckState.Unchecked)
            return
        n_sel = sum(1 for r in target if r.is_selected)
        if n_sel == 0:
            grp_check.setCheckState(Qt.CheckState.Unchecked)
        elif n_sel == len(target):
            grp_check.setCheckState(Qt.CheckState.Checked)
        else:
            grp_check.setCheckState(Qt.CheckState.PartiallyChecked)

    def _make_group_header_click(self, rows, check_map, grp_check):
        def _on_click():
            target = self._group_click_targets(rows)
            if not target:
                return
            new_state = not all(r.is_selected for r in target)
            for r in target:
                r.is_selected = new_state
                chk = check_map.get(r)
                if chk is not None:
                    chk.blockSignals(True)
                    try:
                        chk.setChecked(new_state)
                    finally:
                        chk.blockSignals(False)
            self._update_group_tristate(rows, check_map, grp_check)
            self._update_buttons()
        return _on_click

    def _group_tooltip(self, label, rows):
        need_install, need_removal = self._split_group_targets(rows)
        cats = sorted({r.role for r in rows if r.role})
        cat_text = " + ".join(cats) if cats else "packages"
        if need_install:
            return (
                f"{label}\nClick to select {len(need_install)} package(s) not yet "
                f"installed ({cat_text}).\nAlready-installed packages are left alone."
            )
        if need_removal:
            return (
                f"{label}\nEverything here is already installed.\n"
                f"Click to select all {len(need_removal)} package(s) for removal."
            )
        return f"{label}\nNothing to install or remove — this is up to date."

    def _build_version_card(self, kver: str, visible_rows: list, all_rows: list) -> QFrame:
        """
        Build a single versioned kernel card (e.g. 6.14.0-37).

        Packages sharing this numeric version can still be entirely
        different installable kernels — generic vs low-latency vs OEM vs
        AWS/Azure/GCP vs an HWE point release. So instead of dumping every
        Image/Headers/Modules row for the whole version into one flat list,
        this groups them by *flavor* (see extract_kernel_flavor) into its
        own collapsible section. Clicking a flavor's header selects/installs
        exactly the packages for THAT flavor that aren't already installed
        — never everything under the version number.

        IMPORTANT — this is also the fix for the multi-second lag when
        toggling light/dark mode: with a real mainline archive (which keeps
        years of historical builds), eagerly building every flavor's package
        rows for every version — even hidden ones — can add up to tens of
        thousands of live widgets. Hidden widgets still get touched by Qt's
        style repolish on every theme switch, so the cost scaled with total
        widget count regardless of what was actually visible. Both the
        flavor sub-groups AND their package rows below are now built lazily,
        the first time each is expanded, and cached after that — so a
        collapsed Mainline tab stays down to a handful of widgets per
        version no matter how many historical kernels are listed.
        """
        frame = QFrame()
        frame.setObjectName("card")
        frame.setContentsMargins(0, 8, 0, 2)

        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # ── Header row: chevron (expand/collapse) + clickable select area ──
        header_row = QWidget()
        header_row_lay = QHBoxLayout(header_row)
        header_row_lay.setContentsMargins(0, 0, 0, 0)
        header_row_lay.setSpacing(0)

        chevron_btn = QToolButton()
        chevron_btn.setText("▸")
        chevron_btn.setToolTip("Expand to show kernel flavors (Generic, Low Latency, OEM, …)")
        chevron_btn.setAutoRaise(True)
        chevron_btn.setStyleSheet("QToolButton { border: none; font-size: 11pt; padding: 0 8px; }")
        header_row_lay.addWidget(chevron_btn)

        header_btn = ClickableFrame()
        header_inner = QHBoxLayout(header_btn)
        header_inner.setContentsMargins(0, 10, 12, 10)
        header_inner.setSpacing(12)

        grp_check = QCheckBox()
        grp_check.setEnabled(False)  # visual indicator only — header click drives selection
        # Disabled widgets never receive mouse events in Qt, and critically
        # those events do NOT bubble up to the parent ClickableFrame either —
        # they are simply dropped. Without this, clicking directly on the
        # checkbox glyph (the most natural place to click) silently does
        # nothing, even though clicking the label right next to it works.
        # Making it transparent for mouse events lets clicks (and tooltip
        # hover) fall through to header_btn underneath.
        grp_check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        grp_check.setTristate(True)
        header_inner.addWidget(grp_check)

        ver_label = QLabel()
        ver_label.setTextFormat(Qt.TextFormat.RichText)
        any_active    = any(r.is_active    for r in all_rows)
        any_installed = any(r.is_installed for r in all_rows)

        # Flavor badges — so "which of these is OEM vs Azure vs Generic?"
        # is answered right here in the collapsed header, instead of
        # requiring the user to expand the card and search through it.
        flavor_labels = sorted(
            {r.flavor for r in all_rows},
            key=self._flavor_sort_key
        )
        # Strip the "(HWE 22.04)" / "(64k pages)" parenthetical for the
        # badge line — it's still visible in the flavor sub-section itself,
        # but at a glance "Generic, Generic, OEM" from two HWE variants
        # reads worse than just "Generic, OEM".
        badge_bases = list(dict.fromkeys(re.sub(r"\s*\(.*?\)", "", f) for f in flavor_labels))
        badges_html = " · ".join(badge_bases)

        if any_active:
            ver_label.setText(_to_richtext(
                f"<b>Kernel {kver}</b>  "
                f"<span style='color:green'><b>[Active]</b></span>"
                f"  <small>({len(all_rows)} packages · {badges_html})</small>"
            ))
        elif any_installed:
            ver_label.setText(_to_richtext(
                f"<b>Kernel {kver}</b>  "
                f"<span style='color:gray'>[Installed]</span>"
                f"  <small>({len(all_rows)} packages · {badges_html})</small>"
            ))
        else:
            ver_label.setText(_to_richtext(
                f"<b>Kernel {kver}</b>  "
                f"<span style='color:#88cc88'>[Available]</span>"
                f"  <small>({len(all_rows)} packages · {badges_html})</small>"
            ))
        header_inner.addWidget(ver_label, 1)

        gpu_rows = [r for r in all_rows if r.blocked_reason]
        if gpu_rows:
            gpu_hint = QLabel("⚠ Some packages not usable on this hardware")
            gpu_hint.setStyleSheet("color: orange; font-size: 9pt;")
            header_inner.addWidget(gpu_hint)

        header_row_lay.addWidget(header_btn, 1)
        vbox.addWidget(header_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        vbox.addWidget(sep)

        # ── Body: one collapsible section per kernel flavor — built lazily ──
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        vbox.addWidget(body)
        body.setVisible(False)  # collapsed by default — expand via chevron

        pkg_check_map = {}  # ALL rows in this card, for the version-level header
        state = {"built": False}

        def _build_flavor_groups():
            if state["built"]:
                return
            state["built"] = True

            flavors = {}
            for r in visible_rows:
                flavors.setdefault(r.flavor, []).append(r)
            ordered_flavors = sorted(flavors.keys(), key=self._flavor_sort_key)

            for flavor in ordered_flavors:
                frows = flavors[flavor]
                body_lay.addWidget(self._build_flavor_section(kver, flavor, frows, all_rows, pkg_check_map, grp_check))

        def _toggle_body(checked=False):
            _build_flavor_groups()
            expand = not body.isVisible()
            body.setVisible(expand)
            chevron_btn.setText("▾" if expand else "▸")
            chevron_btn.setToolTip(
                "Collapse" if expand else
                "Expand to show kernel flavors (Generic, Low Latency, OEM, …)"
            )
        chevron_btn.clicked.connect(_toggle_body)

        # ── Version-level header click selects across ALL flavors at once ──
        # (Works correctly even before the body is expanded/built: selection
        # state lives on the KernelRow objects themselves, not the widgets —
        # any not-yet-built checkboxes simply pick up r.is_selected once
        # they're eventually created.)
        header_btn.clicked.connect(
            self._make_group_header_click(all_rows, pkg_check_map, grp_check)
        )
        _kver_tip = self._group_tooltip(f"Kernel {kver} — every flavor below", all_rows)
        header_btn.setToolTip(_kver_tip)
        grp_check.setToolTip(_kver_tip)  # belt-and-braces alongside WA_TransparentForMouseEvents
        self._update_group_tristate(all_rows, pkg_check_map, grp_check)

        return frame

    def _build_flavor_section(self, kver, flavor, frows, all_rows, pkg_check_map, grp_check) -> QWidget:
        """One collapsible flavor sub-group (Generic / Low Latency / OEM / …)
        within a version card. Its package rows are themselves built lazily,
        the first time this flavor is expanded."""
        flavor_any_active = any(r.is_active for r in frows)

        flavor_section = QWidget()
        flavor_lay = QVBoxLayout(flavor_section)
        flavor_lay.setContentsMargins(0, 0, 0, 0)
        flavor_lay.setSpacing(0)

        f_header_row = QWidget()
        f_header_lay = QHBoxLayout(f_header_row)
        f_header_lay.setContentsMargins(24, 6, 12, 6)
        f_header_lay.setSpacing(8)

        f_chevron = QToolButton()
        f_chevron.setText("▸")
        f_chevron.setAutoRaise(True)
        f_chevron.setToolTip("Show the individual packages in this flavor")
        f_chevron.setStyleSheet("QToolButton { border: none; }")
        f_header_lay.addWidget(f_chevron)

        f_grp_check = QCheckBox()
        f_grp_check.setEnabled(False)
        # See the matching comment in _build_version_card — disabled widgets
        # swallow mouse events instead of passing them to the parent frame.
        f_grp_check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        f_grp_check.setTristate(True)
        f_header_lay.addWidget(f_grp_check)

        f_header_btn = ClickableFrame()
        f_inner = QHBoxLayout(f_header_btn)
        f_inner.setContentsMargins(0, 0, 0, 0)
        f_inner.setSpacing(8)

        status_tag = ""
        if flavor_any_active:
            status_tag = "  <span style='color:green'><b>[Active]</b></span>"
        elif all(r.is_installed for r in frows):
            status_tag = "  <span style='color:gray'>[Installed]</span>"
        f_name_lbl = QLabel()
        f_name_lbl.setTextFormat(Qt.TextFormat.RichText)
        f_name_lbl.setText(_to_richtext(
            f"<b>{flavor}</b>{status_tag}  <small>({len(frows)} packages)</small>"
        ))
        f_inner.addWidget(f_name_lbl, 1)
        f_header_lay.addWidget(f_header_btn, 1)

        flavor_lay.addWidget(f_header_row)

        # Package rows — built lazily, the first time this flavor is expanded.
        f_rows_container = QWidget()
        f_rows_lay = QVBoxLayout(f_rows_container)
        f_rows_lay.setContentsMargins(0, 0, 0, 0)
        f_rows_lay.setSpacing(0)
        f_rows_container.setVisible(False)
        flavor_lay.addWidget(f_rows_container)

        flavor_check_map = {}
        state = {"built": False}

        CAT_ORDER = [
            "Image", "Image (unsigned/uc)", "Image (OEM)",
            "Headers", "Modules", "Modules Extra",
            "Modules Extra (GEP)", "Modules NVIDIA", "Cloud Tools", "Meta", "Other"
        ]

        def _build_pkg_rows():
            if state["built"]:
                return
            state["built"] = True
            cats = {}
            for r in frows:
                cats.setdefault(r.role, []).append(r)
            ordered_cats = sorted(cats.keys(), key=lambda c: CAT_ORDER.index(c) if c in CAT_ORDER else 99)

            for cat in ordered_cats:
                cat_label = QLabel(cat)
                cat_label.setStyleSheet("color: gray; font-size: 8pt; margin-left: 16px; margin-top: 6px;")
                f_rows_lay.addWidget(cat_label)

                for r in cats[cat]:
                    pkg_widget = QWidget()
                    pkg_box = QHBoxLayout(pkg_widget)
                    pkg_box.setContentsMargins(24, 4, 12, 4)
                    pkg_box.setSpacing(10)

                    chk = QCheckBox()
                    chk.setChecked(r.is_selected)
                    flavor_check_map[r] = chk
                    pkg_check_map[r] = chk

                    tip = (
                        f"{r.name}\n{r.version or ''}\n"
                        f"{'Installed' if r.is_installed else 'Not installed'}"
                        + (" (running)" if r.is_active else "")
                        + ("\nHeld — won't auto-upgrade" if r.is_held else "")
                    )

                    def _on_pkg_check(checked, row=r, fcm=flavor_check_map, fgc=f_grp_check,
                                       acm=pkg_check_map, agc=grp_check, arows=all_rows, frows_=frows):
                        row.is_selected = checked
                        self._update_group_tristate(frows_, fcm, fgc)
                        self._update_group_tristate(arows, acm, agc)
                        self._update_buttons()

                    chk.toggled.connect(_on_pkg_check)
                    chk.setToolTip(tip)
                    pkg_box.addWidget(chk)

                    name_lbl = QLabel()
                    name_lbl.setTextFormat(Qt.TextFormat.RichText)
                    name_lbl.setToolTip(tip)
                    if r.blocked_reason:
                        name_lbl.setText(_to_richtext(
                            f"<span style='color:gray'><s>{r.name}</s></span>"
                            f"  <small><span style='color:orange'>{r.blocked_reason}</span></small>"
                        ))
                        chk.setEnabled(False)
                    else:
                        name_lbl.setText(_to_richtext(r.markup))
                    pkg_box.addWidget(name_lbl, 1)

                    size_lbl = QLabel(r.size)
                    size_lbl.setStyleSheet("color: gray; font-size: 9pt;")
                    pkg_box.addWidget(size_lbl)

                    status_lbl = QLabel(r.status)
                    status_lbl.setStyleSheet("font-size: 9pt;")
                    pkg_box.addWidget(status_lbl)

                    f_rows_lay.addWidget(pkg_widget)

        def _toggle_flavor(checked=False, *, container=f_rows_container, btn=f_chevron):
            _build_pkg_rows()
            expand = not container.isVisible()
            container.setVisible(expand)
            btn.setText("▾" if expand else "▸")
            btn.setToolTip("Hide packages" if expand else "Show the individual packages in this flavor")
        f_chevron.clicked.connect(_toggle_flavor)

        f_header_btn.clicked.connect(
            self._make_group_header_click(frows, flavor_check_map, f_grp_check)
        )
        _flavor_tip = self._group_tooltip(f"{flavor} — kernel {kver}", frows)
        f_header_btn.setToolTip(_flavor_tip)
        f_grp_check.setToolTip(_flavor_tip)  # belt-and-braces alongside WA_TransparentForMouseEvents
        self._update_group_tristate(frows, flavor_check_map, f_grp_check)

        return flavor_section

    def _build_simple_group_card(self, title_html: str, rows: list, tooltip: str) -> QFrame:
        """
        A card with one clickable header (selects what's needed with a
        single click) and a flat list of package rows below. Used for the
        Mainline meta-package card, and for XanMod/Liquorix groups — those
        don't need a second level of flavor nesting the way Mainline version
        cards do, because each group here already IS one specific,
        installable combination (e.g. "XanMod 6.18.3 [v3]" or "Liquorix
        6.9-1").

        Collapsed by default, with the package rows built lazily on first
        expand — same as _build_version_card, and for the same reason: with
        a large local Meta/XanMod/Liquorix set, eagerly building every
        row for every group (most of which the user will never open) is
        what made switching tabs and toggling light/dark mode noticeably
        laggy. Collapsed, a tab full of these cards costs one header widget
        each instead of a header-plus-N-rows.
        """
        frame = QFrame()
        frame.setObjectName("card")
        frame.setContentsMargins(0, 8, 0, 2)

        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # ── Header row: chevron (expand/collapse) + clickable select area ──
        header_row = QWidget()
        header_row_lay = QHBoxLayout(header_row)
        header_row_lay.setContentsMargins(0, 0, 0, 0)
        header_row_lay.setSpacing(0)

        chevron_btn = QToolButton()
        chevron_btn.setText("▸")
        chevron_btn.setToolTip("Expand to show individual packages")
        chevron_btn.setAutoRaise(True)
        chevron_btn.setStyleSheet("QToolButton { border: none; font-size: 11pt; padding: 0 8px; }")
        header_row_lay.addWidget(chevron_btn)

        header_btn = ClickableFrame()
        header_inner = QHBoxLayout(header_btn)
        header_inner.setContentsMargins(0, 10, 12, 10)
        header_inner.setSpacing(12)

        grp_check = QCheckBox()
        grp_check.setEnabled(False)
        # See the matching comment in _build_version_card — disabled widgets
        # swallow mouse events instead of passing them to the parent frame.
        grp_check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        grp_check.setTristate(True)
        header_inner.addWidget(grp_check)

        hdr_label = QLabel()
        hdr_label.setTextFormat(Qt.TextFormat.RichText)
        hdr_label.setText(_to_richtext(title_html))
        header_inner.addWidget(hdr_label, 1)

        header_row_lay.addWidget(header_btn, 1)
        vbox.addWidget(header_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        vbox.addWidget(sep)

        # ── Body: package rows, built lazily on first expand ──────────────
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        vbox.addWidget(body)
        body.setVisible(False)  # collapsed by default — expand via chevron

        pkg_check_map = {}
        state = {"built": False}

        def _build_rows():
            if state["built"]:
                return
            state["built"] = True

            for r in rows:
                pkg_widget = QWidget()
                pkg_box = QHBoxLayout(pkg_widget)
                pkg_box.setContentsMargins(24, 4, 12, 4)
                pkg_box.setSpacing(10)

                chk = QCheckBox()
                chk.setChecked(r.is_selected)
                if r.blocked_reason:           # would not boot / no matching hardware
                    chk.setEnabled(False)
                    chk.setChecked(False)
                    r.is_selected = False
                pkg_check_map[r] = chk
                tip = (
                    f"{r.name}\n{r.version or ''}\n"
                    f"{'Installed' if r.is_installed else 'Not installed'}"
                    + (" (running)" if r.is_active else "")
                    + ("\nHeld — won't auto-upgrade" if r.is_held else "")
                )
                chk.setToolTip(tip)

                def _on_check(checked, row=r, check_map=pkg_check_map, grp_chk=grp_check, rs=rows):
                    row.is_selected = checked
                    self._update_group_tristate(rs, check_map, grp_chk)
                    self._update_buttons()

                chk.toggled.connect(_on_check)
                pkg_box.addWidget(chk)

                name_lbl = QLabel()
                name_lbl.setTextFormat(Qt.TextFormat.RichText)
                name_lbl.setText(_to_richtext(r.markup) + (
                    f"  <small><span style='color:orange'>{r.blocked_reason}</span></small>" if r.blocked_reason else ""))
                name_lbl.setToolTip(tip + (f"\nUnavailable: {r.blocked_reason}" if r.blocked_reason else ""))
                pkg_box.addWidget(name_lbl, 1)

                size_lbl = QLabel(r.size)
                size_lbl.setStyleSheet("color: gray; font-size: 9pt;")
                pkg_box.addWidget(size_lbl)

                status_lbl = QLabel(r.status)
                status_lbl.setStyleSheet("font-size: 9pt;")
                pkg_box.addWidget(status_lbl)

                body_lay.addWidget(pkg_widget)

            # Any checkbox states set programmatically (e.g. via a group
            # click) before this card was ever expanded need to be applied
            # to the checkboxes we just built.
            for r, chk in pkg_check_map.items():
                chk.blockSignals(True)
                try:
                    chk.setChecked(r.is_selected)
                finally:
                    chk.blockSignals(False)

        def _toggle_body(checked=False):
            _build_rows()
            expand = not body.isVisible()
            body.setVisible(expand)
            chevron_btn.setText("▾" if expand else "▸")
            chevron_btn.setToolTip("Collapse" if expand else "Expand to show individual packages")
        chevron_btn.clicked.connect(_toggle_body)

        # ── Header click selects across the whole group at once — works
        # correctly even before the body is expanded/built, since selection
        # state lives on the KernelRow objects, not the widgets.
        header_btn.clicked.connect(
            self._make_group_header_click(rows, pkg_check_map, grp_check)
        )
        header_btn.setToolTip(tooltip)
        grp_check.setToolTip(tooltip)  # belt-and-braces alongside WA_TransparentForMouseEvents
        self._update_group_tristate(rows, pkg_check_map, grp_check)
        return frame

    def _build_meta_card(self, meta_rows: list) -> QFrame:
        """Meta/tracking packages (linux-generic, linux-lowlatency, etc.) as
        a single card at the top of the Mainline grouped view."""
        title = (
            f"<b>Meta / Tracking packages</b>"
            f"  <small><span style='color:#88aaff'>install once, upgrade automatically</span>"
            f"  ({len(meta_rows)} packages)</small>"
        )
        return self._build_simple_group_card(
            title, meta_rows, self._group_tooltip("Meta / Tracking packages", meta_rows)
        )

    # ── XanMod / Liquorix grouped UI ──────────────────────────────────────────
    #
    # Both were previously a flat, individually-checkable list (SimpleListPanel)
    # with no way to install "one whole kernel" in a single click — and for
    # XanMod specifically, packages that merely share a kernel NUMBER but are
    # actually different builds (different x86-64-vN level, edge/lts/rt) could
    # never be told apart by version number alone. Grouping by the package's
    # own (version, flavor) — using the real apt version string, not a
    # name-guessing regex — fixes both: each card is one exact, installable
    # kernel, and its header selects only what that exact kernel needs.
