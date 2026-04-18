from __future__ import annotations

import calendar
from datetime import date
from typing import Callable

import holidays
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractScrollArea,
)

from schedule_askue.core.calendar_rules import special_days_for_month
from schedule_askue.core.personal_rule_periods import (
    covered_days_for_personal_rule,
    is_weekend_indexed_personal_rule,
)
from schedule_askue.db.models import PersonalRule, Rule
from schedule_askue.db.repository import Repository
from schedule_askue.ui.personal_rule_dialog import PersonalRuleDialog
from schedule_askue.ui.rule_dialog import RuleDialog
from schedule_askue.ui.table_widgets import GridTableWidget

logger = logging.getLogger(__name__)


class RulesTab(QWidget):
    MONTH_NAMES_UA = {
        1: "Січень",
        2: "Лютий",
        3: "Березень",
        4: "Квітень",
        5: "Травень",
        6: "Червень",
        7: "Липень",
        8: "Серпень",
        9: "Вересень",
        10: "Жовтень",
        11: "Листопад",
        12: "Грудень",
    }
    RULE_LABELS = {
        "min_staff": "Мінімум людей у зміні",
        "must_work": "Обов'язково працює",
        "must_off": "Обов'язково вихідний",
        "custom": "Інше правило",
    }
    PERSONAL_RULE_LABELS = {
        "weekend_force_r": "Примусовий Р у вихідні/святкові",
        "weekend_no_ch": "Без Д у вихідні/святкові",
        "weekend_allow_ch": "У вихідні/святкові дозволити В або Д",
        "strict": "Фіксований код на період",
        "prohibit_ch": "Без Д на період",
    }

    def __init__(
        self, repository: Repository, on_changed: Callable[[], None] | None = None
    ) -> None:
        super().__init__()
        self.repository = repository
        self.on_changed = on_changed or (lambda: None)
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.table = GridTableWidget(self)
        self.month_label = QLabel(self)
        self.category_filter = QComboBox(self)
        self.active_filter = QComboBox(self)
        self.employee_filter = QComboBox(self)
        self.filter_summary_label = QLabel(self)
        self.detail_label = QLabel(self)

        self._build_ui()
        self.reload_data()
        self._restore_auto_layout()
        
        # Підключити auto-save
        self.table.set_auto_save_callback(self._save_auto_layout)

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("Правила", self)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        self.month_label.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #1F2933;"
        )
        hint = QLabel(
            "Тут зібрані загальні та персональні правила на поточний місяць. Додавання, редагування, увімкнення/вимкнення та видалення одразу зберігаються в базу даних. Пріоритет визначає, яке правило перемагає в конфлікті; drag&drop змінює лише порядок відображення.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(3)
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(3)
        add_button = QPushButton("Додати", self)
        add_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        edit_button = QPushButton("Редагувати", self)
        edit_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        add_personal_button = QPushButton("Додати персональне", self)
        add_personal_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
        )
        toggle_active_button = QPushButton("Активне", self)
        toggle_active_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        move_up_button = QPushButton("↑", self)
        move_up_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        )
        move_down_button = QPushButton("↓", self)
        move_down_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        delete_button = QPushButton("Видалити", self)
        delete_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        for button in (
            add_button,
            edit_button,
            add_personal_button,
            toggle_active_button,
            move_up_button,
            move_down_button,
            delete_button,
        ):
            button.setMinimumHeight(26)
            button.setMaximumHeight(26)
        for button in (move_up_button, move_down_button):
            button.setMaximumWidth(40)

        add_button.setToolTip("Додати загальне правило")
        edit_button.setToolTip("Редагувати вибране правило")
        add_personal_button.setToolTip("Додати персональне правило")
        toggle_active_button.setToolTip("Увімкнути або вимкнути вибране правило")
        move_up_button.setToolTip("Перемістити правило вгору")
        move_down_button.setToolTip("Перемістити правило вниз")
        delete_button.setToolTip("Видалити правило")
        add_button.clicked.connect(self.add_rule)
        edit_button.clicked.connect(self.edit_rule)
        add_personal_button.clicked.connect(self.add_personal_rule)
        toggle_active_button.clicked.connect(self.toggle_rule_active)
        move_up_button.clicked.connect(lambda: self._move_selected_rule(-1))
        move_down_button.clicked.connect(lambda: self._move_selected_rule(1))
        delete_button.clicked.connect(self.delete_rule)

        self.category_filter.addItem("Усі категорії", "all")
        self.category_filter.addItem("Лише загальні", "rule")
        self.category_filter.addItem("Лише персональні", "personal_rule")
        self.active_filter.addItem("Усі стани", "all")
        self.active_filter.addItem("Лише активні", "active")
        self.active_filter.addItem("Лише неактивні", "inactive")
        self.employee_filter.addItem("Усі працівники", "all")
        self.category_filter.currentIndexChanged.connect(self.reload_data)
        self.active_filter.currentIndexChanged.connect(self.reload_data)
        self.employee_filter.currentIndexChanged.connect(self.reload_data)

        controls.addWidget(self.month_label)
        controls.addStretch()
        controls.addWidget(add_button)
        controls.addWidget(edit_button)
        controls.addWidget(add_personal_button)
        controls.addWidget(toggle_active_button)
        controls.addWidget(move_up_button)
        controls.addWidget(move_down_button)
        controls.addWidget(delete_button)

        filters.addWidget(QLabel("Категорія", self))
        filters.addWidget(self.category_filter)
        filters.addWidget(QLabel("Стан", self))
        filters.addWidget(self.active_filter)
        filters.addWidget(QLabel("Працівник", self))
        filters.addWidget(self.employee_filter)
        filters.addStretch()

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.use_content_height(False)
        self.table.setStyleSheet(
            "QTableWidget { background: #FFFFFF; gridline-color: #D6D9DE; border: 1px solid #D6D9DE; selection-background-color: #D9E8F5; }"
            "QHeaderView::section { background: #F7F5EF; color: #24303F; border: 1px solid #D6D9DE; padding: 6px 4px; }"
        )
        self.table.enable_row_reorder(self._on_rules_reordered)
        self.filter_summary_label.setWordWrap(True)
        self.filter_summary_label.setStyleSheet(
            "padding: 4px 6px; background: #F4F7FB; border: 1px solid #CFD9E6; border-radius: 4px; color: #465467; font-size: 10px;"
        )
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #465467; font-size: 10px;"
        )
        self.table.itemSelectionChanged.connect(self._update_rule_details)

        layout.addWidget(title)
        layout.addLayout(controls)
        layout.addWidget(hint)
        layout.addLayout(filters)
        layout.addWidget(self.filter_summary_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.table)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_table_proportions()

    def _apply_table_proportions(self) -> None:
        """Застосувати пропорційні ширини з урахуванням розміру екрану."""
        width = self.width()
        
        # Адаптивні мінімальні ширини
        if width < 1280:
            # Компактні мінімуми для малих екранів
            min_widths = {
                0: 70,   # Категорія
                1: 120,  # Тип
                2: 110,  # Кого стосується
                3: 90,   # Період
                4: 90,   # Базовий тип
                5: 150,  # Пояснення
                6: 60,   # Пріоритет
                7: 60,   # Активне
                8: 130,  # Опис
            }
        else:
            # Стандартні мінімуми для нормальних екранів
            min_widths = {
                0: 90,
                1: 140,
                2: 130,
                3: 110,
                4: 110,
                5: 180,
                6: 80,
                7: 80,
                8: 160,
            }
        
        self.table.apply_proportional_widths(
            weights={0: 10, 1: 16, 2: 16, 3: 12, 4: 12, 5: 22, 6: 6, 7: 6, 8: 20},
            min_widths=min_widths
        )

    def _save_auto_layout(self) -> None:
        """Автоматично зберегти ширину колонок."""
        self.repository.auto_save_table_widths("rulesTab", "main", self.table.get_column_widths())
        self.table.reset_to_stretch()

    def _restore_auto_layout(self) -> None:
        """Відновити ширину колонок."""
        widths = self.repository.get_auto_table_widths("rulesTab", "main")
        if widths:
            self.table.set_column_widths(widths)
            self.table.enable_resize_mode()

    def set_period(self, year: int, month: int) -> None:
        if self.current_year == year and self.current_month == month:
            return
        self.current_year = year
        self.current_month = month
        self.reload_data()

    def reload_data(self) -> None:
        self.month_label.setText(
            f"{self.MONTH_NAMES_UA[self.current_month]} {self.current_year}"
        )
        rules = self.repository.list_rules(self.current_year, self.current_month)
        personal_rules = self.repository.list_personal_rules(
            self.current_year, self.current_month
        )
        employee_list = self.repository.list_employees(include_archived=True)
        employees = {employee.id: employee.short_name for employee in employee_list}
        self._reload_employee_filter(employee_list)
        category_filter = str(self.category_filter.currentData())
        active_filter = str(self.active_filter.currentData())
        employee_filter = self.employee_filter.currentData()

        headers = [
            "Категорія",
            "Тип",
            "Кого стосується",
            "Період",
            "Базовий тип",
            "Пояснення",
            "Пріоритет",
            "Активне",
            "Опис",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        rows: list[dict[str, object]] = []
        for rule in rules:
            if category_filter == "personal_rule":
                continue
            if active_filter == "active" and not rule.is_active:
                continue
            if active_filter == "inactive" and rule.is_active:
                continue
            if (
                isinstance(employee_filter, int)
                and rule.scope != f"employee:{employee_filter}"
            ):
                continue
            rows.append(
                {
                    "kind": "rule",
                    "id": int(rule.id or 0),
                    "sort_order": int(rule.sort_order),
                    "values": [
                        "Загальне",
                        self._format_rule_type(rule.rule_type),
                        self._format_scope(rule.scope, employees),
                        self._format_rule_period(rule.year, rule.day),
                        self._format_rule_code(rule.rule_type),
                        self._format_params(rule.rule_type, rule.params),
                        str(rule.priority),
                        "Так" if rule.is_active else "Ні",
                        rule.description or "-",
                    ],
                    "tooltip": self._build_rule_tooltip(
                        rule.rule_type, rule.scope, rule.params, employees
                    ),
                }
            )
        for rule in personal_rules:
            if category_filter == "rule":
                continue
            if active_filter == "active" and not rule.is_active:
                continue
            if active_filter == "inactive" and rule.is_active:
                continue
            if isinstance(employee_filter, int) and rule.employee_id != employee_filter:
                continue
            employee_name = employees.get(
                rule.employee_id, f"Співробітник {rule.employee_id}"
            )
            rows.append(
                {
                    "kind": "personal_rule",
                    "id": int(rule.id or 0),
                    "sort_order": int(rule.sort_order),
                    "values": [
                        "Персональне",
                        self._format_personal_rule_type(rule.rule_type),
                        employee_name,
                        self._format_personal_rule_period(
                            rule.year,
                            rule.start_day,
                            rule.end_day,
                            rule.rule_type,
                        ),
                        self._format_personal_rule_code(
                            rule.rule_type, rule.shift_code
                        ),
                        self._format_personal_rule_hint(rule.rule_type),
                        str(rule.priority),
                        "Так" if rule.is_active else "Ні",
                        rule.description or "-",
                    ],
                    "tooltip": self._build_personal_rule_tooltip(
                        rule.rule_type, employee_name, rule
                    ),
                }
            )

        rows.sort(key=lambda row: (int(row["sort_order"]), int(row["id"])))

        self.table.setRowCount(len(rows))
        for row_index, row_data in enumerate(rows):
            for column_index, value in enumerate(row_data["values"]):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(row_data["tooltip"]))
                if column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row_data["id"]))
                    item.setData(Qt.ItemDataRole.UserRole + 1, str(row_data["kind"]))
                self.table.setItem(row_index, column_index, item)

        self.table.sync_row_headers()
        self._apply_table_proportions()
        self._update_filter_summary(len(rows))
        self._update_rule_details()

    def _reload_employee_filter(self, employees: list[object]) -> None:
        current_value = self.employee_filter.currentData()
        self.employee_filter.blockSignals(True)
        self.employee_filter.clear()
        self.employee_filter.addItem("Усі працівники", "all")
        for employee in employees:
            if employee.id is not None:
                self.employee_filter.addItem(employee.short_name, employee.id)
        restore_index = self.employee_filter.findData(current_value)
        self.employee_filter.setCurrentIndex(restore_index if restore_index >= 0 else 0)
        self.employee_filter.blockSignals(False)

    def _update_filter_summary(self, row_count: int) -> None:
        category_text = self.category_filter.currentText()
        active_text = self.active_filter.currentText()
        employee_text = self.employee_filter.currentText()
        if row_count == 0:
            self.filter_summary_label.setText(
                f"За поточними фільтрами правил не знайдено. Категорія: {category_text}; стан: {active_text}; працівник: {employee_text}."
            )
            return
        self.filter_summary_label.setText(
            f"Знайдено правил: {row_count}. Поточні фільтри — категорія: {category_text}; стан: {active_text}; працівник: {employee_text}."
        )

    def _update_rule_details(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.detail_label.setText(
                "Прев'ю правила: виберіть рядок у таблиці, щоб побачити охоплення і можливі конфлікти."
            )
            return
        item = self.table.item(row, 0)
        if item is None:
            self.detail_label.setText("Прев'ю правила: рядок не містить даних.")
            return
        rule_id = item.data(Qt.ItemDataRole.UserRole)
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(rule_id, int) or not isinstance(kind, str):
            self.detail_label.setText(
                "Прев'ю правила: не вдалося визначити тип вибраного правила."
            )
            return
        employees = {
            employee.id: employee.short_name
            for employee in self.repository.list_employees(include_archived=True)
        }
        if kind == "personal_rule":
            current = next(
                (
                    rule
                    for rule in self.repository.list_personal_rules(
                        self.current_year, self.current_month
                    )
                    if rule.id == rule_id
                ),
                None,
            )
            if current is None:
                self.detail_label.setText("Прев'ю правила: правило не знайдено.")
                return
            self.detail_label.setText(
                self._build_personal_rule_preview(current, employees)
            )
            return
        current = next(
            (
                rule
                for rule in self.repository.list_rules(
                    self.current_year, self.current_month
                )
                if rule.id == rule_id
            ),
            None,
        )
        if current is None:
            self.detail_label.setText("Прев'ю правила: правило не знайдено.")
            return
        self.detail_label.setText(self._build_rule_preview(current, employees))

    def _build_rule_preview(self, rule: Rule, employees: dict[int | None, str]) -> str:
        scope_text = self._format_scope(rule.scope, employees)
        period_text = self._format_rule_period(rule.year, rule.day)
        params_text = self._format_params(rule.rule_type, rule.params)
        same_type_conflicts = []
        for other in self.repository.list_rules(self.current_year, self.current_month):
            if other.id == rule.id or not other.is_active:
                continue
            if other.rule_type != rule.rule_type:
                continue
            if other.day != rule.day:
                continue
            if other.scope != rule.scope:
                continue
            same_type_conflicts.append(other)
        must_conflict = None
        if rule.rule_type in {"must_work", "must_off"}:
            opposite_type = "must_off" if rule.rule_type == "must_work" else "must_work"
            must_conflict = next(
                (
                    other
                    for other in self.repository.list_rules(
                        self.current_year, self.current_month
                    )
                    if other.id != rule.id
                    and other.is_active
                    and other.rule_type == opposite_type
                    and other.day == rule.day
                    and other.scope == rule.scope
                ),
                None,
            )
        lines = [
            f"Прев'ю: {self._format_rule_type(rule.rule_type)}",
            f"Кого стосується: {scope_text}",
            f"Період: {period_text}",
            f"Параметри: {params_text}",
            f"Пріоритет: {rule.priority}",
        ]
        if same_type_conflicts:
            lines.append(
                f"Можливий дубль: знайдено {len(same_type_conflicts)} активне(их) правило(а) того ж типу з тим самим днем і scope."
            )
        if must_conflict is not None:
            lines.append(
                "Можливий конфлікт: є активне протилежне правило must_work/must_off для того ж дня і того ж scope."
            )
        if not same_type_conflicts and must_conflict is None:
            lines.append("Явних конфліктів за типом/днем/scope не знайдено.")
        return "\n".join(lines)

    def _build_personal_rule_preview(
        self, rule: PersonalRule, employees: dict[int | None, str]
    ) -> str:
        employee_name = employees.get(
            rule.employee_id, f"Співробітник {rule.employee_id}"
        )
        month_days = self._current_month_days()
        special_days = self._special_days_for_current_month()
        covered_days = covered_days_for_personal_rule(
            rule,
            month_days=month_days,
            special_days=special_days,
        )
        covered_days_set = set(covered_days)
        conflicts = []
        for other in self.repository.list_personal_rules(
            self.current_year, self.current_month
        ):
            if other.id == rule.id or not other.is_active:
                continue
            if other.employee_id != rule.employee_id:
                continue
            other_days = set(
                covered_days_for_personal_rule(
                    other,
                    month_days=month_days,
                    special_days=special_days,
                )
            )
            if covered_days_set & other_days and other.rule_type != rule.rule_type:
                conflicts.append(other)
        lines = [
            f"Прев'ю: {self._format_personal_rule_type(rule.rule_type)}",
            f"Працівник: {employee_name}",
            f"Період: {self._format_personal_rule_period(rule.year, rule.start_day, rule.end_day, rule.rule_type)}",
            f"Код/режим: {self._format_personal_rule_code(rule.rule_type, rule.shift_code)}",
            f"Пріоритет: {rule.priority}",
        ]
        if is_weekend_indexed_personal_rule(rule.rule_type):
            covered_text = (
                ", ".join(str(day) for day in covered_days)
                if covered_days
                else "немає днів у цьому місяці"
            )
            special_subset = [day for day in covered_days if day in special_days]
            special_subset_text = (
                ", ".join(str(day) for day in special_subset)
                if special_subset
                else "немає вихідних/святкових у цьому діапазоні"
            )
            lines.append(f"Календарне покриття цього місяця: {covered_text}.")
            lines.append(
                f"Вихідні/святкові в межах цього періоду: {special_subset_text}."
            )
        if conflicts:
            lines.append(
                f"Можливий конфлікт: знайдено {len(conflicts)} активне(их) персональне(их) правило(а) з перетином по днях для цього працівника."
            )
        else:
            lines.append(
                "Явних конфліктів по періоду для цього працівника не знайдено."
            )
        return "\n".join(lines)

    def _format_rule_type(self, rule_type: str) -> str:
        return self.RULE_LABELS.get(rule_type, rule_type)

    def _format_personal_rule_type(self, rule_type: str) -> str:
        return self.PERSONAL_RULE_LABELS.get(rule_type, rule_type)

    def _format_personal_rule_code(self, rule_type: str, shift_code: str) -> str:
        if rule_type in {"weekend_force_r", "weekend_no_ch", "weekend_allow_ch"}:
            return "Лише вихідні/святкові"
        return shift_code or "-"

    def _format_scope(self, scope: str, employees: dict[int | None, str]) -> str:
        if scope == "all":
            return "Усі працівники"
        if scope.startswith("employee:"):
            try:
                employee_id = int(scope.split(":", 1)[1])
            except ValueError:
                return scope
            employee_name = employees.get(employee_id, f"Співробітник {employee_id}")
            return f"Працівник: {employee_name}"
        return scope

    def _format_rule_period(self, year: int | None, day: int | None) -> str:
        base = "Усі дні" if day is None else f"день {day}"
        if year is None:
            return f"За замовчуванням ({base})"
        return base

    def _format_personal_rule_period(
        self,
        year: int | None,
        start_day: int,
        end_day: int,
        rule_type: str,
    ) -> str:
        base = f"з {start_day} по {end_day}"
        if year is None:
            return f"За замовчуванням ({base})"
        return base

    def _current_month_days(self) -> int:
        return calendar.monthrange(self.current_year, self.current_month)[1]

    def _special_days_for_current_month(self) -> set[int]:
        settings = self.repository.get_settings()
        martial_law = str(settings.get("martial_law", "1")) == "1"
        return special_days_for_month(
            self.current_year,
            self.current_month,
            martial_law=martial_law,
            ua_holidays=holidays.Ukraine(years=[self.current_year]),
        )

    def _format_rule_code(self, rule_type: str) -> str:
        if rule_type == "must_work":
            return "Р/Д"
        if rule_type == "must_off":
            return "В"
        return "-"

    def _format_params(self, rule_type: str, params: str) -> str:
        cleaned = (params or "{}").strip()
        if rule_type == "min_staff":
            value = self._extract_param_value(cleaned)
            return (
                f"Мінімум: {value} люд."
                if value is not None
                else "Мінімум людей у зміні"
            )
        if cleaned in {"", "{}"}:
            if rule_type in {"must_work", "must_off"}:
                return "Без додаткових параметрів"
            return "Параметри не задані"
        return cleaned

    def _extract_param_value(self, params: str) -> str | None:
        marker = '"value"'
        if marker not in params:
            return None
        tail = params.split(marker, 1)[1]
        if ":" not in tail:
            return None
        value_part = tail.split(":", 1)[1].strip()
        digits = []
        for char in value_part:
            if char.isdigit():
                digits.append(char)
            elif digits:
                break
        return "".join(digits) or None

    def _format_personal_rule_hint(self, rule_type: str) -> str:
        hints = {
            "weekend_force_r": "Лише у вихідні/святкові: Р.",
            "weekend_no_ch": "Лише у вихідні/святкові: В.",
            "weekend_allow_ch": "Лише у вихідні/святкові: В або Д.",
            "strict": "Фіксований код на кожен день періоду",
            "prohibit_ch": "Д заборонено на кожен день періоду",
        }
        return hints.get(rule_type, "Персональне правило")

    def _build_rule_tooltip(
        self, rule_type: str, scope: str, params: str, employees: dict[int | None, str]
    ) -> str:
        return (
            f"Тип правила: {self._format_rule_type(rule_type)}\n"
            f"Кого стосується: {self._format_scope(scope, employees)}\n"
            f"Параметри: {self._format_params(rule_type, params)}"
        )

    def _build_personal_rule_tooltip(
        self, rule_type: str, employee_name: str, rule: PersonalRule
    ) -> str:
        return (
            f"Тип правила: {self._format_personal_rule_type(rule_type)}\n"
            f"Працівник: {employee_name}\n"
            f"Період: з {rule.start_day} по {rule.end_day}\n"
            f"Пріоритет: {rule.priority}\n"
            f"Логіка: {self._format_personal_rule_hint(rule_type)}"
        )

    def add_rule(self) -> None:
        employees = self.repository.list_employees(include_archived=True)
        dialog = RuleDialog(
            employees, self.current_year, self.current_month, parent=self
        )
        if dialog.exec():
            self.repository.create_rule(dialog.get_rule())
            self.reload_data()
            self.on_changed()

    def add_personal_rule(self) -> None:
        employees = self.repository.list_employees(include_archived=True)
        dialog = PersonalRuleDialog(
            employees, self.current_year, self.current_month, parent=self
        )
        if dialog.exec():
            self.repository.create_personal_rule(dialog.get_rule())
            self.reload_data()
            self.on_changed()

    def edit_rule(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Правила", "Оберіть правило для редагування.")
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        rule_id = item.data(Qt.ItemDataRole.UserRole)
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(rule_id, int) or not isinstance(kind, str):
            return
        employees = self.repository.list_employees(include_archived=True)
        if kind == "personal_rule":
            current = next(
                (
                    rule
                    for rule in self.repository.list_personal_rules(
                        self.current_year, self.current_month
                    )
                    if rule.id == rule_id
                ),
                None,
            )
            if current is None:
                return
            dialog = PersonalRuleDialog(
                employees,
                self.current_year,
                self.current_month,
                rule=current,
                parent=self,
            )
            if dialog.exec():
                self.repository.update_personal_rule(dialog.get_rule())
        else:
            current = next(
                (
                    rule
                    for rule in self.repository.list_rules(
                        self.current_year, self.current_month
                    )
                    if rule.id == rule_id
                ),
                None,
            )
            if current is None:
                return
            dialog = RuleDialog(
                employees,
                self.current_year,
                self.current_month,
                rule=current,
                parent=self,
            )
            if dialog.exec():
                self.repository.update_rule(dialog.get_rule())
        self.reload_data()
        self.on_changed()

    def delete_rule(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Правила", "Оберіть правило для видалення.")
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        rule_id = item.data(Qt.ItemDataRole.UserRole)
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(rule_id, int) or not isinstance(kind, str):
            return

        confirm = QMessageBox.question(self, "Видалення", "Видалити вибране правило?")
        if confirm != QMessageBox.StandardButton.Yes:
            return

        if kind == "personal_rule":
            self.repository.delete_personal_rule(rule_id)
        else:
            self.repository.delete_rule(rule_id)
        self.reload_data()
        self.on_changed()

    def toggle_rule_active(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Правила", "Оберіть правило для зміни стану.")
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        rule_id = item.data(Qt.ItemDataRole.UserRole)
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(rule_id, int) or not isinstance(kind, str):
            return
        if kind == "personal_rule":
            current = next(
                (
                    rule
                    for rule in self.repository.list_personal_rules(
                        self.current_year, self.current_month
                    )
                    if rule.id == rule_id
                ),
                None,
            )
            if current is None:
                return
            current.is_active = not current.is_active
            self.repository.update_personal_rule(current)
        else:
            current = next(
                (
                    rule
                    for rule in self.repository.list_rules(
                        self.current_year, self.current_month
                    )
                    if rule.id == rule_id
                ),
                None,
            )
            if current is None:
                return
            current.is_active = not current.is_active
            self.repository.update_rule(current)
        self.reload_data()
        self.on_changed()

    def _on_rules_reordered(self, ordered_ids: list[int]) -> None:
        self._persist_current_visual_order()
        self.reload_data()
        self.on_changed()

    def _move_selected_rule(self, direction: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Правила", "Оберіть правило для переміщення.")
            return
        target_row = row + direction
        if target_row < 0 or target_row >= self.table.rowCount():
            return
        ordered_rows = self._current_rule_rows()
        if len(ordered_rows) != self.table.rowCount():
            return
        ordered_rows[row], ordered_rows[target_row] = (
            ordered_rows[target_row],
            ordered_rows[row],
        )
        self._persist_rule_rows(ordered_rows)
        self.reload_data()
        self.table.setCurrentCell(target_row, 0)
        self.on_changed()

    def _persist_current_visual_order(self) -> None:
        self._persist_rule_rows(self._current_rule_rows())

    def _current_rule_rows(self) -> list[tuple[int, str]]:
        rows: list[tuple[int, str]] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            row_id = item.data(Qt.ItemDataRole.UserRole)
            kind = item.data(Qt.ItemDataRole.UserRole + 1)
            if isinstance(row_id, int) and isinstance(kind, str):
                rows.append((row_id, kind))
        return rows

    def _persist_rule_rows(self, rows: list[tuple[int, str]]) -> None:
        for visual_index, (row_id, kind) in enumerate(rows, start=1):
            if kind == "personal_rule":
                self.repository.set_personal_rule_sort_order(row_id, visual_index)
            else:
                self.repository.set_rule_sort_order(row_id, visual_index)
