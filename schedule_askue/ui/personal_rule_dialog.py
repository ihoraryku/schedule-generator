from __future__ import annotations

import calendar

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

from schedule_askue.core.personal_rule_periods import is_weekend_indexed_personal_rule
from schedule_askue.db.models import Employee, PersonalRule

logger = logging.getLogger(__name__)


class PersonalRuleDialog(QDialog):
    RULE_OPTIONS = [
        (
            "Примусовий Р у вихідні/святкові",
            "weekend_force_r",
            "Р",
            "У межах календарного періоду: у будні ставиться Р, у вихідні/святкові теж примусово ставиться Р.",
        ),
        (
            "Без Д у вихідні/святкові",
            "weekend_no_ch",
            "Р",
            "У межах календарного періоду: у будні ставиться Р, у вихідні/святкові ставиться В.",
        ),
        (
            "У вихідні/святкові дозволити В або Д",
            "weekend_allow_ch",
            "Р",
            "У межах календарного періоду: у будні ставиться Р, у вихідні/святкові дозволені тільки В або Д.",
        ),
    ]

    def __init__(
        self,
        employees: list[Employee],
        year: int,
        month: int,
        rule: PersonalRule | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "Редагувати персональне правило"
            if rule is not None
            else "Нове персональне правило"
        )
        self.employees = [employee for employee in employees if employee.id is not None]
        self.year = year
        self.month = month
        self.month_days = calendar.monthrange(year, month)[1]
        self._base_rule = rule

        self.employee_combo = QComboBox(self)
        for employee in self.employees:
            self.employee_combo.addItem(employee.short_name, employee.id)

        self.rule_type = QComboBox(self)
        for label, value, shift_code, hint in self.RULE_OPTIONS:
            self.rule_type.addItem(
                label, {"rule_type": value, "shift_code": shift_code, "hint": hint}
            )

        self.duration_type = QComboBox(self)
        self.duration_type.addItem("Одноразове (на цей місяць)", "one_time")
        self.duration_type.addItem("За замовчуванням (всі місяці)", "default")

        self.shift_code_label = QLabel(self)
        self.shift_code_label.setStyleSheet("font-weight: 600; color: #1F2933;")
        self.help_label = QLabel(self)
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet("color: #5B6573;")
        self.period_hint_label = QLabel(self)
        self.period_hint_label.setWordWrap(True)
        self.period_hint_label.setStyleSheet("color: #5B6573;")

        self.start_day = QSpinBox(self)
        self.start_day.setRange(1, self.month_days)
        self.start_day.setValue(1)
        self.end_day = QSpinBox(self)
        self.end_day.setRange(1, self.month_days)
        self.end_day.setValue(self.month_days)
        self.priority_spin = QSpinBox(self)
        self.priority_spin.setRange(0, 100000)
        self.priority_spin.setValue(100)

        self.description = QLineEdit(self)
        self.description.setPlaceholderText(
            "Наприклад: У вихідні першої половини місяця без Д"
        )
        self.is_active = QCheckBox("Правило активне", self)
        self.is_active.setChecked(True)

        self.rule_type.currentIndexChanged.connect(self._update_labels)
        self.duration_type.currentIndexChanged.connect(self._on_duration_changed)
        self.start_day.valueChanged.connect(self._sync_days)
        self.end_day.valueChanged.connect(self._sync_days)

        form = QFormLayout()
        form.addRow("Працівник", self.employee_combo)
        form.addRow("Тривалість", self.duration_type)
        self.month_label = QLabel(f"{month:02d}.{year}", self)
        form.addRow("Місяць", self.month_label)
        form.addRow("Тип персонального правила", self.rule_type)
        form.addRow("Базовий тип", self.shift_code_label)
        form.addRow("Пояснення", self.help_label)
        form.addRow("Логіка періоду", self.period_hint_label)
        form.addRow("З дня", self.start_day)
        form.addRow("По день", self.end_day)
        form.addRow("Пріоритет", self.priority_spin)
        form.addRow("Опис", self.description)
        form.addRow("", self.is_active)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._update_labels()
        self._load_rule()

    def _current_meta(self) -> dict[str, str]:
        value = self.rule_type.currentData()
        return (
            value
            if isinstance(value, dict)
            else {"rule_type": "weekend_no_ch", "shift_code": "Р", "hint": ""}
        )

    def _update_labels(self) -> None:
        meta = self._current_meta()
        rule_type = str(meta.get("rule_type", ""))
        self.shift_code_label.setText(str(meta.get("shift_code", "-")))
        self.help_label.setText(str(meta.get("hint", "")))
        if is_weekend_indexed_personal_rule(rule_type):
            self.period_hint_label.setText(
                "Для цього правила 'З дня' / 'По день' означають календарні дні місяця. У межах цього діапазону будні обробляються як Р, а вихідні/святкові — за спеціальною логікою вибраного правила."
            )
        else:
            self.period_hint_label.setText(
                "Для цього правила 'З дня' / 'По день' означають календарні дні місяця."
            )

    def _sync_days(self) -> None:
        if self.start_day.value() > self.end_day.value():
            self.end_day.setValue(self.start_day.value())

    def _on_duration_changed(self) -> None:
        is_one_time = self.duration_type.currentData() == "one_time"
        self.month_label.setEnabled(is_one_time)

    def _load_rule(self) -> None:
        if self._base_rule is None:
            return
        employee_index = self.employee_combo.findData(self._base_rule.employee_id)
        if employee_index >= 0:
            self.employee_combo.setCurrentIndex(employee_index)
        for index in range(self.rule_type.count()):
            meta = self.rule_type.itemData(index)
            if (
                isinstance(meta, dict)
                and meta.get("rule_type") == self._base_rule.rule_type
            ):
                self.rule_type.setCurrentIndex(index)
                break
        is_default = self._base_rule.year is None or self._base_rule.month is None
        self.duration_type.setCurrentIndex(1 if is_default else 0)
        self.start_day.setValue(self._base_rule.start_day)
        self.end_day.setValue(self._base_rule.end_day)
        self.priority_spin.setValue(self._base_rule.priority)
        self.description.setText(self._base_rule.description)
        self.is_active.setChecked(self._base_rule.is_active)
        self._on_duration_changed()
        self._update_labels()

    def get_rule(self) -> PersonalRule:
        meta = self._current_meta()
        is_default = self.duration_type.currentData() == "default"
        return PersonalRule(
            id=None if self._base_rule is None else self._base_rule.id,
            employee_id=int(self.employee_combo.currentData()),
            year=None if is_default else self.year,
            month=None if is_default else self.month,
            start_day=self.start_day.value(),
            end_day=self.end_day.value(),
            shift_code=str(meta.get("shift_code", "-")),
            rule_type=str(meta.get("rule_type", "weekend_no_ch")),
            is_active=self.is_active.isChecked(),
            priority=self.priority_spin.value(),
            sort_order=0 if self._base_rule is None else self._base_rule.sort_order,
            description=self.description.text().strip(),
        )
