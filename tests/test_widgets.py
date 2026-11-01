"""Shared widget interaction tests."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from trackstash.ui.widgets import NoWheelComboBox, NoWheelSpinBox


def _wheel_event() -> QWheelEvent:
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_spin_box_wheel_requires_focus(qtbot: QtBot) -> None:
    spin = NoWheelSpinBox()
    qtbot.addWidget(spin)
    spin.setRange(0, 10)
    spin.setValue(5)
    spin.show()
    spin.clearFocus()

    QApplication.sendEvent(spin, _wheel_event())
    assert spin.value() == 5

    spin.setFocus()
    qtbot.wait(10)
    assert spin.hasFocus()
    QApplication.sendEvent(spin, _wheel_event())
    assert spin.value() == 6


def test_combo_box_wheel_requires_focus(qtbot: QtBot) -> None:
    combo = NoWheelComboBox()
    qtbot.addWidget(combo)
    combo.addItems(["One", "Two", "Three"])
    combo.setCurrentIndex(1)
    combo.show()
    combo.clearFocus()

    QApplication.sendEvent(combo, _wheel_event())
    assert combo.currentIndex() == 1

    combo.setFocus()
    qtbot.wait(10)
    assert combo.hasFocus()
    QApplication.sendEvent(combo, _wheel_event())
    assert combo.currentIndex() == 0
