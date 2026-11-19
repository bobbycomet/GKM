# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Small reusable Qt widgets: main-thread dispatcher, clickable rows, toasts."""
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget


class MainThreadDispatcher(QObject):
    _sig = pyqtSignal(object, tuple, dict)

    def __init__(self):
        super().__init__()
        self._sig.connect(self._exec, Qt.ConnectionType.QueuedConnection)

    def _exec(self, fn, args, kwargs):
        fn(*args, **kwargs)

    def call(self, fn, *args, **kwargs):
        """Schedule fn(*args, **kwargs) to run on the GUI thread."""
        self._sig.emit(fn, args, kwargs)


# ─── Clickable card/header widget (stand-in for Gtk.Button.set_child) ───────

class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ClickableRow(QWidget):
    """A package row that toggles its checkbox when clicked anywhere on the
    row — mirrors the GTK ListView 'activate' behaviour on row click."""
    def __init__(self, checkbox, *a, **kw):
        super().__init__(*a, **kw)
        self._checkbox = checkbox
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._checkbox is not None and self._checkbox.isEnabled():
            self._checkbox.setChecked(not self._checkbox.isChecked())
        super().mouseReleaseEvent(event)


# ─── Toast overlay (stand-in for Adw.ToastOverlay / Adw.Toast) ──────────────

class ToastWidget(QFrame):
    def __init__(self, message, button_label=None, on_button=None, parent=None):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setStyleSheet(
            "QFrame#toast { background-color: #2a2a2a; border-radius: 8px; }"
            "QFrame#toast QLabel { color: #f0f0f0; }"
            "QFrame#toast QPushButton { color: #66c0f4; font-weight: bold; }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        lay.setSpacing(10)
        lbl = QLabel(message)
        lay.addWidget(lbl)
        if button_label and on_button:
            btn = QPushButton(button_label)
            btn.setFlat(True)
            btn.clicked.connect(on_button)
            lay.addWidget(btn)
        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setStyleSheet("QToolButton { color: #aaaaaa; border: none; }")
        close_btn.clicked.connect(self.deleteLater)
        lay.addWidget(close_btn)


class ToastOverlay(QWidget):
    """Wraps a content widget and floats dismissible toast notifications over
    its bottom edge, similar to Adw.ToastOverlay.

    NOTE: an earlier version of this class stacked a full-window-sized
    "toast layer" on top of the content via QStackedLayout and relied on
    WA_TransparentForMouseEvents to let clicks pass through the empty parts
    of it. That attribute turns out to suppress mouse delivery to the ENTIRE
    subtree it's set on — including the toast's own buttons — so any toast
    with a button (e.g. the "Open" button on the update-available toast)
    became unclickable, and a persistent toast (timeout=0) blocked the whole
    window until dismissed.

    Instead, the toast layer here is a manually-positioned floating child
    that is always resized to exactly its own content's sizeHint (via
    _reposition). With zero toasts its height collapses to ~0, so it never
    overlaps — let alone blocks — the rest of the UI, and no click-through
    hack is needed at all: toast buttons are ordinary, fully clickable
    widgets.
    """
    def __init__(self, content_widget, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content_widget)

        self._toast_layer = QWidget(self)
        self._toast_layer.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        toast_layout = QVBoxLayout(self._toast_layer)
        toast_layout.setContentsMargins(24, 0, 24, 24)
        toast_layout.setSpacing(8)
        self._toast_vbox = toast_layout
        self._toast_layer.show()
        self._reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self):
        """Shrink-wrap the toast layer to its current content and pin it to
        the bottom, then ensure it's painted above the main content."""
        # With zero toasts, QVBoxLayout.sizeHint() still includes the
        # layout's own margins (top+bottom = 0+24 = 24px here), so the
        # "empty" toast layer doesn't actually collapse to 0 height — it
        # sits as an invisible strip over whatever is at the bottom of the
        # content widget (e.g. the status bar), silently eating clicks on
        # the portion of it that overlaps. Force a true 0 when there are no
        # toasts instead of trusting sizeHint() here.
        if self._toast_vbox.count() == 0:
            h = 0
        else:
            h = self._toast_layer.sizeHint().height()
        self._toast_layer.setGeometry(0, max(0, self.height() - h), self.width(), h)
        self._toast_layer.raise_()

    def add_toast(self, message, timeout=3000, button_label=None, on_button=None):
        toast = ToastWidget(message, button_label, on_button)
        self._toast_vbox.addWidget(toast, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._reposition()
        if timeout and timeout > 0:
            QTimer.singleShot(timeout, lambda: self._remove_toast(toast))
        return toast

    def _remove_toast(self, toast):
        toast.setParent(None)
        toast.deleteLater()
        QTimer.singleShot(0, self._reposition)


# ─── Simple list panel (stand-in for Gtk.ListView + factory, XanMod/Liquorix) ─
