# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Palette and stylesheets (Griffin dark / light)."""
from PyQt6.QtGui import QPalette, QColor


def build_palette(dark: bool) -> QPalette:
    """Base window/text/button colors, applied via QPalette instead of a
    stylesheet so theme switches stay cheap regardless of widget count."""
    pal = QPalette()
    if dark:
        window, base, text = QColor("#1b2838"), QColor("#2a475e"), QColor("#c7d5e0")
        button, highlight, disabled = QColor("#2a475e"), QColor("#355978"), QColor("#6a7f8f")
    else:
        window, base, text = QColor("#f4f6f8"), QColor("#ffffff"), QColor("#1c1c1c")
        button, highlight, disabled = QColor("#e8ebee"), QColor("#3a7bd5"), QColor("#a0a0a0")
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, window)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.ToolTipBase, base)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a9aa8" if dark else "#8a8a8a"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return pal


# Only widget-CLASS selectors here (QPushButton, QLineEdit, ...) — never a
# bare "QWidget { ... }" rule. Class selectors only match instances of that
# class, so re-polishing on theme switch stays cheap no matter how many
# widgets the Mainline tab has built.
DARK_QSS = """
QLineEdit, QTextEdit, QComboBox { background-color: #2a475e; color: #c7d5e0;
    border: 1px solid #3a5a75; border-radius: 4px; padding: 3px; }
QPushButton { background-color: #2a475e; color: #c7d5e0; border: 1px solid #3a5a75;
    border-radius: 4px; padding: 5px 10px; }
QPushButton:hover { background-color: #355978; }
QPushButton:disabled { color: #6a7f8f; }
QTabWidget::pane { border-top: 1px solid #3a5a75; }
QTabBar::tab { background: #1b2838; color: #c7d5e0; padding: 6px 14px; }
QTabBar::tab:selected { background: #2a475e; }
QFrame#card { background-color: #22384a; border: 1px solid #3a5a75; border-radius: 6px; }
QToolButton#flavorHeader { background-color: #2a475e; border: 1px solid #3a5a75; border-radius: 4px; }
QToolButton#flavorHeader:hover { background-color: #355978; }
QCheckBox { spacing: 6px; }
"""

LIGHT_QSS = """
QLineEdit, QTextEdit, QComboBox { background-color: #ffffff; color: #1c1c1c;
    border: 1px solid #b8c0c8; border-radius: 4px; padding: 3px; }
QPushButton { background-color: #e8ebee; color: #1c1c1c; border: 1px solid #b8c0c8;
    border-radius: 4px; padding: 5px 10px; }
QPushButton:hover { background-color: #d8dee4; }
QPushButton:disabled { color: #a0a0a0; }
QTabWidget::pane { border-top: 1px solid #b8c0c8; }
QTabBar::tab { background: #e8ebee; color: #1c1c1c; padding: 6px 14px; }
QTabBar::tab:selected { background: #ffffff; }
QFrame#card { background-color: #ffffff; border: 1px solid #b8c0c8; border-radius: 6px; }
QToolButton#flavorHeader { background-color: #eef1f4; border: 1px solid #b8c0c8; border-radius: 4px; }
QToolButton#flavorHeader:hover { background-color: #dfe4e8; }
QCheckBox { spacing: 6px; }
"""
