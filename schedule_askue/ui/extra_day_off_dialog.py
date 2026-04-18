from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from schedule_askue.db.models import Employee

logger = logging.getLogger(__name__)


class ExtraDayOffDialog(QDialog):
    ACTION_OPTIONS = [
        ("Нарахування", "credit"),
        ("Списання", "debit"),
    ]

    def __init__(self, employees: list[Employee], year: int, month: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Операція додаткового вихідного")

        self.employee_combo = QComboBox(self)
        for employee in employees:
            if employee.id is not None:
                self.employee_combo.addItem(employee.short_name, employee.id)

        self.action_combo = QComboBox(self)
        for label, value in self.ACTION_OPTIONS:
            self.action_combo.addItem(label, value)

        self.days_spin = QSpinBox(self)
        self.days_spin.setRange(1, 30)
        self.days_spin.setValue(1)

        self.description_edit = QLineEdit(self)
        self.description_edit.setPlaceholderText("Наприклад: компенсація за чергування у святковий день")

        form = QFormLayout()
        form.addRow("Працівник", self.employee_combo)
        form.addRow("Місяць", QLabel(f"{month:02d}.{year}", self))
        form.addRow("Тип операції", self.action_combo)
        form.addRow("Кількість днів", self.days_spin)
        form.addRow("Опис", self.description_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def get_payload(self) -> dict[str, object]:
        action = str(self.action_combo.currentData())
        days = self.days_spin.value()
        signed_days = days if action == "credit" else -days
        return {
            "employee_id": int(self.employee_combo.currentData()),
            "action": action,
            "days_count": signed_days,
            "description": self.description_edit.text().strip(),
        }
