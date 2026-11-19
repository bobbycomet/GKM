# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Dialog listing the restorable versions of one kernel."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
                             QVBoxLayout)

_SOURCE_TEXT = {"installed": "● installed", "cache": "local pacman cache", "archive": "Arch Linux Archive",
                "repo": "repository"}


class VersionsDialog(QDialog):
    def __init__(self, parent, title, default_hold=False, hold_text="Hold these packages so they aren't upgraded again"):
        super().__init__(parent)
        self.setWindowTitle("Kernel versions")
        self.setMinimumSize(560, 420)
        self.chosen = None
        self.hold = False
        self._options = []
        v = QVBoxLayout(self)
        head = QLabel(f"<b>{title}</b>")
        head.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(head)
        self.status = QLabel("Looking up versions…")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.list = QListWidget()
        self.list.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))   # aligned columns
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _i: self._accept_if_ok())
        v.addWidget(self.list, 1)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet("color: gray; font-size: 9pt;")
        v.addWidget(self.notes)
        self.chk_hold = QCheckBox(hold_text)
        self.chk_hold.setChecked(default_hold)
        v.addWidget(self.chk_hold)
        self.buttons = QDialogButtonBox()
        self.btn_install = self.buttons.addButton("Install this version", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_install.setEnabled(False)
        self.buttons.accepted.connect(self._accept_if_ok)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)

    def set_result(self, result):
        """`result` is (options, notes) from Backend.list_versions, or an Exception."""
        if isinstance(result, Exception):
            self.status.setText(f"Could not look up versions: {result}")
            return
        options, notes = result
        self._options = list(options)
        self.list.clear()
        for opt in self._options:
            label = ", ".join(_SOURCE_TEXT.get(s, s) for s in opt.sources) or "available"
            item = QListWidgetItem(f"{opt.version:<18}{label}")
            if opt.installed:
                item.setForeground(Qt.GlobalColor.gray)
            self.list.addItem(item)
        self.status.setText(f"{len(self._options)} version(s) found." if self._options else "No versions found.")
        self.notes.setText("\n".join(notes))
        self._update_buttons()

    def _current(self):
        row = self.list.currentRow()
        return self._options[row] if 0 <= row < len(self._options) else None

    def _update_buttons(self):
        opt = self._current()
        self.btn_install.setEnabled(opt is not None and not opt.installed)

    def _accept_if_ok(self):
        opt = self._current()
        if opt is not None and not opt.installed:
            self.chosen, self.hold = opt, self.chk_hold.isChecked()
            self.accept()
