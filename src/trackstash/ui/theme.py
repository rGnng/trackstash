"""Shared selection colors for the Qt views.

Only widgets that display a selection should receive this palette. Setting it on
``QApplication`` would also override style-owned roles such as ``AlternateBase``
and break the Tracks table's alternating row colors.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

SELECTION_HIGHLIGHT = "#314F78"
SELECTION_TEXT = "#FFFFFF"


def apply_selection_palette(widget: QWidget) -> None:
    """Apply the shared selection colors without touching the application palette."""
    palette = widget.palette()
    highlight = QColor(SELECTION_HIGHLIGHT)
    text = QColor(SELECTION_TEXT)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Highlight, highlight)
        palette.setColor(group, QPalette.ColorRole.HighlightedText, text)
    widget.setPalette(palette)
    if isinstance(widget, QAbstractScrollArea):
        widget.viewport().setPalette(palette)
    widget.update()
