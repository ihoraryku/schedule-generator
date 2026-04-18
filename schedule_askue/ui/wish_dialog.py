from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from schedule_askue.db.models import Employee, Wish

logger = logging.getLogger(__name__)


class WishDialog(QDialog):
    WISH_OPTIONS = [
        ("Відпустка", "vacation"),
        ("Бажаний / обов'язковий вихідний", "day_off"),
        ("Бажаний / обов'язковий робочий день", "work_day"),
    ]
    PRIORITY_OPTIONS = [
        ("Обов'язково виконати", "mandatory"),
        ("Бажано врахувати", "desired"),
    ]
    WISH_HINTS = {
        "vacation": "Система сприймає це як відпустку і ставить код 'О'.",
        "day_off": "Система сприймає це як вихідний і ставить код 'В'.",
        "work_day": "Система сприймає це як робочий день або чергування. За потреби в коментарі можна уточнити код 'Р' або 'Д'.",
    }

    def __init__(
        self,
        employees: list[Employee],
        year: int,
        month: int,
        selected_employee_id: int | None = None,
        selected_day: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Нове побажання")
        self.employees = employees
        self.year = year
        self.month = month

        self.employee_combo = QComboBox(self)
        for employee in employees:
            self.employee_combo.addItem(employee.short_name, employee.id)

        self.wish_type = QComboBox(self)
        for label, value in self.WISH_OPTIONS:
            self.wish_type.addItem(label, value)
        self.wish_help = QLabel(self)
        self.wish_help.setWordWrap(True)
        self.wish_help.setStyleSheet("color: #5B6573;")

        self.date_from = QSpinBox(self)
        self.date_from.setRange(1, 31)
        self.date_to = QSpinBox(self)
        self.date_to.setRange(1, 31)
        self.priority = QComboBox(self)
        for label, value in self.PRIORITY_OPTIONS:
            self.priority.addItem(label, value)
        self.use_extra_day_off = QCheckBox("Використати додатковий вихідний", self)
        self.comment = QLineEdit(self)
        self.comment.setPlaceholderText("Наприклад: Р, Д або уточнення до побажання")

        self.wish_type.currentIndexChanged.connect(self._update_hint)

        form = QFormLayout()
        form.addRow("Співробітник", self.employee_combo)
        form.addRow("Тип побажання", self.wish_type)
        form.addRow("Пояснення", self.wish_help)
        form.addRow("З дня", self.date_from)
        form.addRow("По день", self.date_to)
        form.addRow("Пріоритет", self.priority)
        form.addRow("", self.use_extra_day_off)
        form.addRow("Коментар", self.comment)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if selected_employee_id is not None:
            index = self.employee_combo.findData(selected_employee_id)
            if index >= 0:
                self.employee_combo.setCurrentIndex(index)
        if selected_day is not None:
            self.date_from.setValue(selected_day)
            self.date_to.setValue(selected_day)

        self._update_hint()

    def _current_wish_type(self) -> str:
        return str(self.wish_type.currentData())

    def _current_priority(self) -> str:
        return str(self.priority.currentData())

    def _update_hint(self) -> None:
        self.wish_help.setText(self.WISH_HINTS.get(self._current_wish_type(), ""))

    def get_wish(self) -> Wish:
        return Wish(
            id=None,
            employee_id=int(self.employee_combo.currentData()),
            year=self.year,
            month=self.month,
            wish_type=self._current_wish_type(),
            date_from=self.date_from.value(),
            date_to=self.date_to.value(),
            priority=self._current_priority(),
            use_extra_day_off=self.use_extra_day_off.isChecked(),
            comment=self.comment.text().strip(),
        )

