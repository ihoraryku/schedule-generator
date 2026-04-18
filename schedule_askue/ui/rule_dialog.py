from __future__ import annotations

import json

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
    QWidget,
    QVBoxLayout,
)

from schedule_askue.db.models import Employee, Rule

logger = logging.getLogger(__name__)


class RuleDialog(QDialog):
    RULE_OPTIONS = [
        ("Мінімум людей у зміні", "min_staff"),
        ("Обов'язково працює", "must_work"),
        ("Обов'язково вихідний", "must_off"),
        ("Інше правило", "custom"),
    ]

    RULE_HINTS = {
        "min_staff": "Задає мінімальну кількість людей, які мають працювати в обраний день або щодня. Значення задається окремим числовим полем нижче.",
        "must_work": "Примусово вимагає робочий день для всіх або для вибраного працівника. Додаткові JSON-параметри не потрібні.",
        "must_off": "Примусово вимагає вихідний для всіх або для вибраного працівника. Додаткові JSON-параметри не потрібні.",
        "custom": "Технічний режим для нестандартних правил. Використовуйте лише коли типове поле не покриває ваш сценарій.",
    }

    RULE_PLACEHOLDERS = {
        "min_staff": '{"value": 2}',
        "must_work": '{}',
        "must_off": '{}',
        "custom": '{}',
    }

    def __init__(
        self,
        employees: list[Employee],
        year: int,
        month: int,
        rule: Rule | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редагувати правило" if rule is not None else "Нове правило")
        self.employees = employees
        self._base_rule = rule

        self.rule_type = QComboBox(self)
        for label, value in self.RULE_OPTIONS:
            self.rule_type.addItem(label, value)
        self.rule_help = QLabel(self)
        self.rule_help.setWordWrap(True)
        self.rule_help.setStyleSheet("color: #5B6573;")
        self.scope = QComboBox(self)
        self.scope.addItem("Усі співробітники", "all")
        for employee in employees:
            if employee.id is not None:
                self.scope.addItem(employee.short_name, f"employee:{employee.id}")
        self.duration_type = QComboBox(self)
        self.duration_type.addItem("Одноразове (на цей місяць)", "one_time")
        self.duration_type.addItem("За замовчуванням (всі місяці)", "default")
        
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(2024, 2035)
        self.year_spin.setValue(year)
        self.month_spin = QSpinBox(self)
        self.month_spin.setRange(1, 12)
        self.month_spin.setValue(month)
        self.day_spin = QSpinBox(self)
        self.day_spin.setRange(0, 31)
        self.day_spin.setSpecialValueText("Усі дні")
        self.priority_spin = QSpinBox(self)
        self.priority_spin.setRange(0, 100000)
        self.priority_spin.setValue(100)
        self.min_staff_spin = QSpinBox(self)
        self.min_staff_spin.setRange(1, 100)
        self.min_staff_spin.setValue(2)
        self.min_staff_container = QWidget(self)
        min_staff_layout = QFormLayout(self.min_staff_container)
        min_staff_layout.setContentsMargins(0, 0, 0, 0)
        min_staff_layout.addRow("Мінімум людей", self.min_staff_spin)
        self.params_edit = QLineEdit(self)
        self.params_label = QLabel("Параметри JSON", self)
        self.description = QLineEdit(self)
        self.description.setPlaceholderText("Коротке пояснення для себе")
        self.is_active = QCheckBox("Правило активне", self)
        self.is_active.setChecked(True)

        self.rule_type.currentIndexChanged.connect(self._update_hint)
        self.duration_type.currentIndexChanged.connect(self._on_duration_changed)

        form = QFormLayout()
        form.addRow("Тип правила", self.rule_type)
        form.addRow("Пояснення", self.rule_help)
        form.addRow("Застосувати до", self.scope)
        form.addRow("Тривалість", self.duration_type)
        form.addRow("Рік", self.year_spin)
        form.addRow("Місяць", self.month_spin)
        form.addRow("День", self.day_spin)
        form.addRow("Пріоритет", self.priority_spin)
        form.addRow("", self.min_staff_container)
        form.addRow(self.params_label, self.params_edit)
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

        self._update_hint()
        self._load_rule()

    def _current_rule_type(self) -> str:
        return str(self.rule_type.currentData())

    def _update_hint(self) -> None:
        rule_type = self._current_rule_type()
        self.rule_help.setText(self.RULE_HINTS.get(rule_type, ""))
        self.params_edit.setPlaceholderText(self.RULE_PLACEHOLDERS.get(rule_type, '{}'))
        is_min_staff = rule_type == "min_staff"
        is_custom = rule_type == "custom"
        self.min_staff_container.setVisible(is_min_staff)
        self.params_label.setVisible(is_custom)
        self.params_edit.setVisible(is_custom)

    def _on_duration_changed(self) -> None:
        is_one_time = self.duration_type.currentData() == "one_time"
        self.year_spin.setEnabled(is_one_time)
        self.month_spin.setEnabled(is_one_time)

    def _load_rule(self) -> None:
        if self._base_rule is None:
            return
        index = self.rule_type.findData(self._base_rule.rule_type)
        if index >= 0:
            self.rule_type.setCurrentIndex(index)
        scope_index = self.scope.findData(self._base_rule.scope)
        if scope_index >= 0:
            self.scope.setCurrentIndex(scope_index)
        is_default = self._base_rule.year is None or self._base_rule.month is None
        self.duration_type.setCurrentIndex(1 if is_default else 0)
        if self._base_rule.year is not None:
            self.year_spin.setValue(self._base_rule.year)
        if self._base_rule.month is not None:
            self.month_spin.setValue(self._base_rule.month)
        self.day_spin.setValue(self._base_rule.day or 0)
        self.priority_spin.setValue(self._base_rule.priority)
        self.params_edit.setText(self._base_rule.params)
        self.description.setText(self._base_rule.description)
        self.is_active.setChecked(self._base_rule.is_active)
        self._load_structured_params(self._base_rule.rule_type, self._base_rule.params)
        self._on_duration_changed()

    def _load_structured_params(self, rule_type: str, params: str) -> None:
        if rule_type != "min_staff":
            return
        try:
            payload = json.loads(params or "{}")
        except json.JSONDecodeError:
            payload = {}
        value = payload.get("value", 2)
        try:
            self.min_staff_spin.setValue(max(1, int(value)))
        except (TypeError, ValueError):
            self.min_staff_spin.setValue(2)

    def _build_params_payload(self) -> str:
        rule_type = self._current_rule_type()
        if rule_type == "min_staff":
            return json.dumps({"value": self.min_staff_spin.value()}, ensure_ascii=False)
        if rule_type in {"must_work", "must_off"}:
            return "{}"
        raw = self.params_edit.text().strip() or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Некоректний JSON у полі параметрів: {exc.msg}") from exc
        return json.dumps(parsed, ensure_ascii=False)

    def get_rule(self) -> Rule:
        day_value = self.day_spin.value() or None
        is_default = self.duration_type.currentData() == "default"
        params = self._build_params_payload()
        return Rule(
            id=None if self._base_rule is None else self._base_rule.id,
            rule_type=self._current_rule_type(),
            scope=str(self.scope.currentData()),
            year=None if is_default else self.year_spin.value(),
            month=None if is_default else self.month_spin.value(),
            day=day_value,
            params=params,
            is_active=self.is_active.isChecked(),
            priority=self.priority_spin.value(),
            sort_order=0 if self._base_rule is None else self._base_rule.sort_order,
            description=self.description.text().strip(),
        )

    def accept(self) -> None:
        try:
            self._build_params_payload()
        except ValueError as exc:
            self.rule_help.setText(str(exc))
            self.rule_help.setStyleSheet("color: #B54708;")
            return
        self.rule_help.setStyleSheet("color: #5B6573;")
        self._update_hint()
        super().accept()
