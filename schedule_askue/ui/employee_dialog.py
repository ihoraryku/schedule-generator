from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from schedule_askue.db.models import (
    SHIFT_TYPE_FULL_R,
    SHIFT_TYPE_MIXED,
    SHIFT_TYPE_SPLIT_CH,
    Employee,
)

logger = logging.getLogger(__name__)


class EmployeeDialog(QDialog):
    SHIFT_OPTIONS = [
        ("Гнучкий розподіл (Р/Д)", SHIFT_TYPE_MIXED),
        ("Переважно робочий день 'Р'", SHIFT_TYPE_FULL_R),
        ("Переважно чергування 'Д'", SHIFT_TYPE_SPLIT_CH),
    ]

    SHIFT_HINTS = {
        SHIFT_TYPE_MIXED: "Працівник може отримувати як робочі дні 'Р', так і чергування 'Д'. Це універсальний варіант.",
        SHIFT_TYPE_FULL_R: "Працівник орієнтований на робочі дні 'Р'.",
        SHIFT_TYPE_SPLIT_CH: "Працівник орієнтований на чергування 'Д'.",
    }

    def __init__(self, employee: Employee | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Співробітник")
        self.employee = employee

        self.full_name = QLineEdit(self)
        self.short_name = QLineEdit(self)
        self.shift_type = QComboBox(self)
        for label, value in self.SHIFT_OPTIONS:
            self.shift_type.addItem(label, value)
        self.shift_help = QLabel(self)
        self.shift_help.setWordWrap(True)
        self.shift_help.setStyleSheet("color: #5B6573;")
        self.rate = QDoubleSpinBox(self)
        self.rate.setRange(0.1, 2.0)
        self.rate.setSingleStep(0.1)
        self.rate.setValue(1.0)
        self.position = QLineEdit(self)

        self.full_name.setPlaceholderText("Повне ПІБ працівника")
        self.short_name.setPlaceholderText("Короткий запис для таблиці графіка")
        self.rate.setToolTip(
            "1.0 = повна ставка, 0.5 = пів ставки, 1.5 = півтори ставки."
        )
        self.position.setPlaceholderText("Наприклад: інженер АСКОЕ")
        self.shift_type.currentIndexChanged.connect(self._update_shift_help)

        form = QFormLayout()
        form.addRow("ПІБ", self.full_name)
        form.addRow("Коротке ім'я", self.short_name)
        form.addRow("Тип зміни", self.shift_type)
        form.addRow("Пояснення", self.shift_help)
        form.addRow("Ставка", self.rate)
        form.addRow("Посада", self.position)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if employee is not None:
            self.full_name.setText(employee.full_name)
            self.short_name.setText(employee.short_name)
            index = self.shift_type.findData(employee.shift_type)
            if index >= 0:
                self.shift_type.setCurrentIndex(index)
            self.rate.setValue(employee.rate)
            self.position.setText(employee.position)

        self._update_shift_help()

    def _current_shift_type(self) -> str:
        return str(self.shift_type.currentData())

    def _update_shift_help(self) -> None:
        self.shift_help.setText(self.SHIFT_HINTS.get(self._current_shift_type(), ""))

    def get_employee(self) -> Employee:
        base = self.employee
        return Employee(
            id=base.id if base is not None else None,
            full_name=self.full_name.text().strip(),
            short_name=self.short_name.text().strip() or self.full_name.text().strip(),
            shift_type=self._current_shift_type(),
            rate=float(self.rate.value()),
            position=self.position.text().strip(),
            is_active=True if base is None else base.is_active,
            sort_order=0 if base is None else base.sort_order,
        )
