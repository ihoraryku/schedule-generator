from __future__ import annotations

from datetime import date
import logging
from typing import Callable

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QComboBox,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.compensation_recommendations import (
    build_compensation_recommendations,
)
from schedule_askue.core.work_norms import employee_effective_target_work
from schedule_askue.db.repository import Repository
from schedule_askue.ui.collapsible_group_box import CollapsibleGroupBox
from schedule_askue.ui.extra_day_off_dialog import ExtraDayOffDialog
from schedule_askue.ui.table_widgets import GridTableWidget

logger = logging.getLogger(__name__)


class BalanceTab(QWidget):
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
    ACTION_LABELS = {
        "credit": "Нарахування",
        "debit": "Списання",
    }
    COMPENSATION_KIND_LABELS = {
        "underwork": "Недобір",
        "overwork": "Переробка",
    }
    COMPENSATION_ACTION_LABELS = {
        "underwork_current_month_extra_off_plan": "Вихідні в цьому місяці",
        "underwork_next_month_work_adjustment": "Робота в наступному місяці",
        "overwork_next_month_extra_off_plan": "Вихідні на наступний місяць",
        "overwork_balance_credit": "Додано в баланс вихідних",
    }

    def __init__(
        self,
        repository: Repository,
        on_changed: Callable[[], None] | None = None,
        schedule_snapshot_provider: Callable[
            [int, int], dict[int, dict[int, str]] | None
        ]
        | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.on_changed = on_changed or (lambda: None)
        self.schedule_snapshot_provider = schedule_snapshot_provider or (
            lambda year, month: None
        )
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self._is_updating_plan = False
        self.month_label = QLabel(self)
        self.summary_label = QLabel(self)
        self.plan_hint_label = QLabel(self)
        self.filter_edit = QLineEdit(self)
        self.plan_status_filter = QComboBox(self)
        self.balance_table = GridTableWidget(self)
        self.plan_table = GridTableWidget(self)
        self.compensation_table = GridTableWidget(self)
        self.compensation_actions_table = GridTableWidget(self)
        self.operations_table = GridTableWidget(self)

        self._build_ui()
        self.reload_data()
        self._restore_auto_layout()

        # Підключити auto-save для всіх таблиць
        for table in [
            self.balance_table,
            self.plan_table,
            self.compensation_table,
            self.operations_table,
            self.compensation_actions_table,
        ]:
            table.set_auto_save_callback(self._save_auto_layout)

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(self._scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("Додаткові вихідні", self)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")  # Зменшено
        self.month_label.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #1F2933;"
        )  # Зменшено
        hint = QLabel(
            "Баланс додаткових вихідних і журнал операцій.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )
        hint.setVisible(False)
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "padding: 4px 6px; background: #EEF8F0; border: 1px solid #B9D9C0; border-radius: 4px; color: #245B31; font-size: 10px;"  # Зменшено
        )
        self.plan_hint_label.setWordWrap(True)
        self.plan_hint_label.setStyleSheet(
            "padding: 4px 6px; background: #F4F7FB; border: 1px solid #CFD9E6; border-radius: 4px; color: #465467; font-size: 10px;"
        )
        self.plan_hint_label.setVisible(False)
        self.compensation_hint_label = QLabel(self)
        self.compensation_hint_label.setWordWrap(True)
        self.compensation_hint_label.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )
        self.compensation_hint_label.setVisible(False)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(3)
        add_button = QPushButton("Додати", self)
        add_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        delete_button = QPushButton("Видалити", self)
        delete_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        for button in (add_button, delete_button):
            button.setMinimumHeight(26)
            button.setMaximumHeight(26)
        add_button.setToolTip("Додати операцію")
        delete_button.setToolTip("Видалити операцію")
        add_button.clicked.connect(self.add_operation)
        delete_button.clicked.connect(self.delete_operation)

        controls.addWidget(self.month_label)
        controls.addStretch()
        controls.addWidget(add_button)
        controls.addWidget(delete_button)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(3)  # Зменшено
        self.filter_edit.setPlaceholderText("Фільтр...")
        self.filter_edit.textChanged.connect(self.reload_data)
        self.plan_status_filter.addItem("Усі", "all")
        self.plan_status_filter.addItem("Є план", "planned")
        self.plan_status_filter.addItem("План > баланс", "overplanned")
        self.plan_status_filter.addItem("Факт < план", "underused")
        self.plan_status_filter.currentIndexChanged.connect(self.reload_data)
        filter_row.addWidget(QLabel("Пошук", self))
        filter_row.addWidget(self.filter_edit, stretch=1)
        filter_row.addWidget(QLabel("Стан", self))
        filter_row.addWidget(self.plan_status_filter)

        plan_actions = QHBoxLayout()
        plan_actions.setContentsMargins(0, 0, 0, 0)
        plan_actions.setSpacing(3)  # Зменшено
        add_one_button = QPushButton("+1", self)
        add_one_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        )
        add_two_button = QPushButton("+2", self)
        add_two_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        )
        clear_plan_button = QPushButton("Очистити", self)
        clear_plan_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_LineEditClearButton)
        )
        for button in (add_one_button, add_two_button, clear_plan_button):
            button.setMinimumHeight(24)
            button.setMaximumHeight(24)
        add_one_button.setToolTip("+1 вибраним")
        add_two_button.setToolTip("+2 вибраним")
        clear_plan_button.setToolTip("Очистити план вибраних")
        add_one_button.clicked.connect(lambda: self._adjust_selected_plans(1))
        add_two_button.clicked.connect(lambda: self._adjust_selected_plans(2))
        clear_plan_button.clicked.connect(self._clear_selected_plans)
        plan_actions.addWidget(add_one_button)
        plan_actions.addWidget(add_two_button)
        plan_actions.addWidget(clear_plan_button)
        plan_actions.addStretch()

        compensation_actions = QHBoxLayout()
        compensation_actions.setContentsMargins(0, 0, 0, 0)
        compensation_actions.setSpacing(3)
        apply_current_extra_off_button = QPushButton("Вихідні (поточний місяць)", self)
        apply_next_work_button = QPushButton("Робота (наступний місяць)", self)
        apply_next_extra_off_button = QPushButton("Вихідні (наступний місяць)", self)
        apply_balance_credit_button = QPushButton("Додати в баланс", self)
        for button in (
            apply_current_extra_off_button,
            apply_next_work_button,
            apply_next_extra_off_button,
            apply_balance_credit_button,
        ):
            button.setMinimumHeight(24)
            button.setMaximumHeight(24)
        apply_current_extra_off_button.setToolTip(
            "Додає вихідні до плану поточного місяця. Це змінює план, а не вже збережений графік."
        )
        apply_next_work_button.setToolTip(
            "Додає робочі дні до норми наступного місяця як компенсацію недобору."
        )
        apply_next_extra_off_button.setToolTip(
            "Додає вихідні до плану наступного місяця як компенсацію переробки."
        )
        apply_balance_credit_button.setToolTip(
            "Нараховує дні в баланс додаткових вихідних."
        )
        apply_current_extra_off_button.clicked.connect(
            self._apply_underwork_to_current_extra_off
        )
        apply_next_work_button.clicked.connect(
            self._apply_underwork_to_next_month_workdays
        )
        apply_next_extra_off_button.clicked.connect(
            self._apply_overwork_to_next_month_extra_off
        )
        apply_balance_credit_button.clicked.connect(
            self._apply_overwork_to_balance_credit
        )
        compensation_actions.addWidget(apply_current_extra_off_button)
        compensation_actions.addWidget(apply_next_work_button)
        compensation_actions.addWidget(apply_next_extra_off_button)
        compensation_actions.addWidget(apply_balance_credit_button)
        compensation_actions.addStretch()

        self._setup_table(self.balance_table)
        self._setup_table(self.plan_table, editable=True)
        self._setup_table(self.compensation_table)
        self._setup_table(self.operations_table)
        self._setup_table(self.compensation_actions_table)
        self.operations_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.operations_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.compensation_actions_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.compensation_actions_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.balance_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.plan_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.plan_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.compensation_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.compensation_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.plan_table.itemChanged.connect(self._on_plan_item_changed)

        balance_group = CollapsibleGroupBox("Баланс", self, collapsed=False)
        balance_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        balance_layout = QVBoxLayout(balance_group)
        balance_layout.setContentsMargins(4, 4, 4, 4)
        balance_layout.setSpacing(2)
        balance_layout.addWidget(self.summary_label)
        balance_layout.addWidget(self.balance_table)

        plan_group = CollapsibleGroupBox(
            "План додаткових вихідних", self, collapsed=False
        )
        plan_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        plan_layout = QVBoxLayout(plan_group)
        plan_layout.setContentsMargins(4, 4, 4, 4)
        plan_layout.setSpacing(2)
        plan_layout.addWidget(self.plan_hint_label)
        plan_layout.addLayout(plan_actions)
        plan_layout.addWidget(self.plan_table)

        compensation_group = CollapsibleGroupBox(
            "Компенсація норми", self, collapsed=True
        )
        compensation_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        compensation_layout = QVBoxLayout(compensation_group)
        compensation_layout.setContentsMargins(4, 4, 4, 4)
        compensation_layout.setSpacing(2)
        compensation_layout.addWidget(self.compensation_hint_label)
        compensation_layout.addLayout(compensation_actions)
        compensation_layout.addWidget(self.compensation_table)

        operations_group = CollapsibleGroupBox("Журнал операцій", self, collapsed=True)
        operations_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        operations_layout = QVBoxLayout(operations_group)
        operations_layout.setContentsMargins(4, 4, 4, 4)
        operations_layout.setSpacing(2)
        operations_layout.addWidget(self.operations_table)

        compensation_journal_group = CollapsibleGroupBox(
            "Журнал компенсацій", self, collapsed=True
        )
        compensation_journal_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        compensation_journal_layout = QVBoxLayout(compensation_journal_group)
        compensation_journal_layout.setContentsMargins(4, 4, 4, 4)
        compensation_journal_layout.setSpacing(2)
        compensation_journal_layout.addWidget(self.compensation_actions_table)

        compensation_group.setCollapsed(True)
        compensation_journal_group.setCollapsed(True)
        operations_group.setCollapsed(True)

        layout.addWidget(title)
        layout.addLayout(controls)
        layout.addWidget(hint)
        layout.addLayout(filter_row)
        layout.addWidget(balance_group)
        layout.addWidget(plan_group)
        layout.addWidget(compensation_group)
        layout.addWidget(compensation_journal_group)
        layout.addWidget(operations_group)

        self._scroll.setWidget(content)
        outer_layout.addWidget(self._scroll)

    def _setup_table(self, table: GridTableWidget, *, editable: bool = False) -> None:
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        table.configure_fill_width_table()
        table.use_content_height(False)
        if editable:
            table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed
                | QAbstractItemView.EditTrigger.SelectedClicked
            )
        else:
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setStyleSheet(
            "QTableWidget { background: #FFFFFF; gridline-color: #D6D9DE; border: 1px solid #D6D9DE; selection-background-color: #D9E8F5; font-size: 10px; }"
            "QHeaderView::section { background: #F7F5EF; color: #24303F; border: 1px solid #D6D9DE; padding: 3px 2px; font-size: 10px; }"
        )

    def set_period(self, year: int, month: int) -> None:
        if self.current_year == year and self.current_month == month:
            return
        self.current_year = year
        self.current_month = month
        self.reload_data()

    def resizeEvent(self, event) -> None:
        """Перерахувати пропорції таблиць при зміні розміру вікна."""
        super().resizeEvent(event)
        self._apply_table_proportions()

    def _apply_table_proportions(self) -> None:
        """Застосувати пропорційні ширини до всіх таблиць."""
        # Баланс таблиця (2 колонки)
        self.balance_table.apply_proportional_widths(
            weights={0: 75, 1: 25},
            min_widths={0: 120, 1: 80},
        )

        # План таблиця (6 колонок)
        self.plan_table.apply_proportional_widths(
            weights={0: 24, 1: 12, 2: 10, 3: 10, 4: 10, 5: 34},
            min_widths={0: 120, 1: 70, 2: 60, 3: 60, 4: 70, 5: 100},
        )

        # Компенсація таблиця (8 колонок)
        self.compensation_table.apply_proportional_widths(
            weights={0: 18, 1: 8, 2: 8, 3: 10, 4: 8, 5: 12, 6: 12, 7: 24},
            min_widths={0: 120, 1: 60, 2: 70, 3: 90, 4: 60, 5: 80, 6: 90, 7: 150},
        )

        # Журнал операцій (6 колонок)
        self.operations_table.apply_proportional_widths(
            weights={0: 24, 1: 14, 2: 8, 3: 12, 4: 28, 5: 14},
            min_widths={0: 120, 1: 80, 2: 60, 3: 80, 4: 140, 5: 100},
        )

        # Журнал компенсацій (6 колонок)
        self.compensation_actions_table.apply_proportional_widths(
            weights={0: 22, 1: 18, 2: 8, 3: 14, 4: 24, 5: 14},
            min_widths={0: 120, 1: 110, 2: 60, 3: 90, 4: 140, 5: 100},
        )

    def _save_auto_layout(self) -> None:
        """Автоматично зберегти ширину колонок всіх таблиць."""
        all_widths: dict[str, dict[int, int]] = {}
        all_widths["balance"] = self.balance_table.get_column_widths()
        all_widths["plan"] = self.plan_table.get_column_widths()
        all_widths["compensation"] = self.compensation_table.get_column_widths()
        all_widths["operations"] = self.operations_table.get_column_widths()
        all_widths["compensation_actions"] = (
            self.compensation_actions_table.get_column_widths()
        )

        self.repository.auto_save_table_widths("balance_tab", "all", all_widths)

        for table in [
            self.balance_table,
            self.plan_table,
            self.compensation_table,
            self.operations_table,
            self.compensation_actions_table,
        ]:
            table.reset_to_stretch()

    def _restore_auto_layout(self) -> None:
        """Відновити ширину колонок всіх таблиць."""
        widths = self.repository.get_auto_table_widths("balance_tab", "all")
        if not widths:
            return

        if "balance" in widths:
            self.balance_table.set_column_widths(widths["balance"])
            self.balance_table.enable_resize_mode()
        if "plan" in widths:
            self.plan_table.set_column_widths(widths["plan"])
            self.plan_table.enable_resize_mode()
        if "compensation" in widths:
            self.compensation_table.set_column_widths(widths["compensation"])
            self.compensation_table.enable_resize_mode()
        if "operations" in widths:
            self.operations_table.set_column_widths(widths["operations"])
            self.operations_table.enable_resize_mode()
        if "compensation_actions" in widths:
            self.compensation_actions_table.set_column_widths(
                widths["compensation_actions"]
            )
            self.compensation_actions_table.enable_resize_mode()

    def reload_data(self) -> None:
        self.month_label.setText(
            f"{self.MONTH_NAMES_UA[self.current_month]} {self.current_year}"
        )
        employees = {
            employee.id: employee.short_name
            for employee in self.repository.list_employees(include_archived=True)
        }
        balances = self.repository.get_extra_day_off_balances()
        planned = self.repository.get_planned_extra_days_off_map(
            self.current_year, self.current_month
        )
        workday_adjustments = self.repository.get_planned_workday_adjustments_map(
            self.current_year, self.current_month
        )
        usage_totals = self.repository.get_extra_day_off_usage_totals(
            self.current_year, self.current_month
        )
        operations = self.repository.list_extra_day_off_operations(
            self.current_year, self.current_month
        )
        compensation_actions = self.repository.list_work_norm_compensation_actions(
            self.current_year, self.current_month
        )
        visible_employee_ids = self._visible_employee_ids(
            employees, balances, planned, usage_totals
        )
        using_snapshot = (
            self.schedule_snapshot_provider(self.current_year, self.current_month)
            is not None
        )

        planned_total = sum(item.planned_days for item in planned.values())
        used_total = sum(usage_totals.values())
        available_total = sum(balances.get(employee_id, 0) for employee_id in employees)
        projected_total = available_total - planned_total
        fact_source_text = (
            "поточній чернетці" if using_snapshot else "збереженому графіку"
        )
        self.summary_label.setText(
            f"Загальний залишок: {available_total} дн. | У плані на {self.current_month:02d}.{self.current_year}: {planned_total} дн. | "
            f"Фактично враховано у {fact_source_text}: {used_total} дн. | Прогнозний залишок: {projected_total} дн."
        )
        self.plan_hint_label.setText(
            "Тут задається, скільки додаткових вихідних врахувати для працівника в графіку цього місяця. "
            "Баланс — скільки днів доступно зараз. План — скільки врахувати в графіку. "
            "Факт — скільки вже реально використано. Прогноз — що залишиться після виконання плану."
        )
        self.compensation_hint_label.setText(
            (
                "Компенсація норми рахується за поточною чернеткою графіка. "
                if using_snapshot
                else "Компенсація норми рахується за збереженим графіком поточного місяця. "
            )
            + "Скоригована норма вже враховує відпустку, заплановані вихідні та перенесені робочі дні. "
            + "Дії для наступного місяця записують план або перенос у наступний період, а не змінюють уже збережений графік автоматично."
        )

        self.balance_table.setColumnCount(2)
        self.balance_table.setHorizontalHeaderLabels(
            ["Працівник", "Баланс дод. вихідних"]
        )
        filtered_employees = [
            (employee_id, short_name)
            for employee_id, short_name in employees.items()
            if employee_id in visible_employee_ids
        ]
        self.balance_table.setRowCount(len(filtered_employees))
        for row_index, (employee_id, short_name) in enumerate(filtered_employees):
            self.balance_table.setItem(row_index, 0, QTableWidgetItem(short_name))
            balance_item = QTableWidgetItem(str(balances.get(employee_id, 0)))
            balance_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            balance_item.setBackground(
                QColor("#E9F4E8")
                if balances.get(employee_id, 0) >= 0
                else QColor("#F7D6DA")
            )
            self.balance_table.setItem(row_index, 1, balance_item)

        self._reload_plan_table(filtered_employees, balances, planned, usage_totals)
        self._reload_compensation_table(
            filtered_employees,
            balances,
            planned,
            workday_adjustments,
        )

        self.operations_table.setColumnCount(6)
        self.operations_table.setHorizontalHeaderLabels(
            ["Працівник", "Тип", "Дні", "Місяць", "Опис", "Дата створення"]
        )
        filtered_operations = [
            item
            for item in operations
            if int(item["employee_id"]) in visible_employee_ids
        ]
        self.operations_table.setRowCount(len(filtered_operations))
        for row_index, operation in enumerate(filtered_operations):
            employee_name = employees.get(
                operation["employee_id"], f"Співробітник {operation['employee_id']}"
            )
            values = [
                employee_name,
                self.ACTION_LABELS.get(operation["action"], operation["action"]),
                f"{int(operation['days_count']):+d}",
                f"{operation['schedule_month']:02d}.{operation['schedule_year']}"
                if operation["schedule_year"] and operation["schedule_month"]
                else "-",
                operation["description"] or "-",
                operation["created_at"],
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(operation["id"]))
                if column_index == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(
                        QColor("#DDF2E0")
                        if int(operation["days_count"]) >= 0
                        else QColor("#FDE2B8")
                    )
                self.operations_table.setItem(row_index, column_index, item)

        self.compensation_actions_table.setColumnCount(6)
        self.compensation_actions_table.setHorizontalHeaderLabels(
            [
                "Працівник",
                "Дія",
                "Дні",
                "Цільовий місяць",
                "Опис",
                "Дата створення",
            ]
        )
        filtered_comp_actions = [
            item
            for item in compensation_actions
            if item.employee_id in visible_employee_ids
        ]
        self.compensation_actions_table.setRowCount(len(filtered_comp_actions))
        for row_index, action in enumerate(filtered_comp_actions):
            employee_name = employees.get(
                action.employee_id, f"Співробітник {action.employee_id}"
            )
            target_period = (
                f"{action.target_month:02d}.{action.target_year}"
                if action.target_year and action.target_month
                else "-"
            )
            values = [
                employee_name,
                self.COMPENSATION_ACTION_LABELS.get(
                    action.action_type, action.action_type
                ),
                f"{action.days_count:+d}",
                target_period,
                action.description or "-",
                action.created_at,
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.compensation_actions_table.setItem(row_index, column_index, item)

    def _reload_plan_table(
        self,
        employees: list[tuple[int | None, str]],
        balances: dict[int, int],
        planned: dict[int, object],
        usage_totals: dict[int, int],
    ) -> None:
        blocker = QSignalBlocker(self.plan_table)
        self._is_updating_plan = True
        try:
            self.plan_table.setColumnCount(6)
            self.plan_table.setHorizontalHeaderLabels(
                [
                    "Працівник",
                    "Баланс",
                    "План",
                    "Факт",
                    "Прогноз",
                    "Коментар",
                ]
            )
            self.plan_table.setRowCount(len(employees))

            for row_index, (employee_id, short_name) in enumerate(employees):
                if employee_id is None:
                    continue
                planned_item = planned.get(employee_id)
                planned_days = (
                    planned_item.planned_days if planned_item is not None else 0
                )
                note = planned_item.note if planned_item is not None else ""
                balance = balances.get(employee_id, 0)
                used_days = usage_totals.get(employee_id, 0)
                projected = balance - planned_days

                name_item = QTableWidgetItem(short_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setData(Qt.ItemDataRole.UserRole, employee_id)
                self.plan_table.setItem(row_index, 0, name_item)

                balance_item = QTableWidgetItem(str(balance))
                balance_item.setFlags(
                    balance_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                balance_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                balance_item.setBackground(
                    QColor("#E9F4E8") if balance >= 0 else QColor("#F7D6DA")
                )
                self.plan_table.setItem(row_index, 1, balance_item)

                plan_item = QTableWidgetItem(str(planned_days))
                plan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                plan_item.setData(Qt.ItemDataRole.UserRole, employee_id)
                plan_item.setToolTip(
                    "Скільки додаткових вихідних потрібно врахувати для цього працівника під час генерації графіка вибраного місяця."
                )
                self.plan_table.setItem(row_index, 2, plan_item)

                used_item = QTableWidgetItem(str(used_days))
                used_item.setFlags(used_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                used_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                used_item.setBackground(
                    QColor("#EAF2FD")
                    if used_days <= planned_days
                    else QColor("#FDE2B8")
                )
                used_item.setToolTip(
                    "Скільки додаткових вихідних уже фактично враховано в збереженому графіку цього місяця."
                )
                self.plan_table.setItem(row_index, 3, used_item)

                projected_item = QTableWidgetItem(f"{projected:+d}")
                projected_item.setFlags(
                    projected_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                projected_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                projected_item.setBackground(
                    QColor("#DDF2E0") if projected >= 0 else QColor("#F7D6DA")
                )
                self.plan_table.setItem(row_index, 4, projected_item)

                note_item = QTableWidgetItem(note)
                note_item.setData(Qt.ItemDataRole.UserRole, employee_id)
                note_item.setToolTip(
                    "Коротке пояснення, чому ці додаткові вихідні потрібно врахувати в графіку цього місяця."
                )
                self.plan_table.setItem(row_index, 5, note_item)
        finally:
            del blocker
            self._is_updating_plan = False

    def _reload_compensation_table(
        self,
        employees: list[tuple[int | None, str]],
        balances: dict[int, int],
        planned: dict[int, object],
        workday_adjustments: dict[int, object],
    ) -> None:
        employee_rows = [
            employee
            for employee in self.repository.list_employees(include_archived=True)
            if employee.id is not None
            and any(employee.id == emp_id for emp_id, _ in employees)
        ]
        schedule = self.schedule_snapshot_provider(
            self.current_year, self.current_month
        ) or self.repository.get_schedule(self.current_year, self.current_month)
        calendar = UkrainianCalendar(
            martial_law=self.repository.get_settings().get("martial_law", "1") == "1"
        )
        working_days = (
            calendar.get_production_norm(self.current_year, self.current_month) // 8
        )
        month_days = len(calendar.get_month_info(self.current_year, self.current_month))
        recommendations = build_compensation_recommendations(
            employees=employee_rows,
            assignments=schedule,
            working_days=working_days,
            month_days=month_days,
            extra_off_balances=balances,
            planned_extra_days_off=planned,
            planned_workday_adjustments=workday_adjustments,
        )
        recommendation_by_employee = {
            item.employee_id: item for item in recommendations
        }

        self.compensation_table.setColumnCount(8)
        self.compensation_table.setHorizontalHeaderLabels(
            [
                "Працівник",
                "Факт",
                "Базова норма",
                "Скоригована норма",
                "Відхилення",
                "Статус",
                "Тип",
                "Рекомендація",
            ]
        )
        self.compensation_table.setRowCount(len(employees))

        for row_index, (employee_id, short_name) in enumerate(employees):
            if employee_id is None:
                continue
            employee = next(
                (item for item in employee_rows if item.id == employee_id), None
            )
            days = schedule.get(employee_id, {})
            if employee is None:
                continue
            actual, target, delta = employee_effective_target_work(
                employee,
                days=days,
                working_days=working_days,
                month_days=month_days,
                planned_extra_days_off=(
                    planned.get(employee_id).planned_days
                    if planned.get(employee_id) is not None
                    else 0
                ),
                planned_workday_adjustment=(
                    workday_adjustments.get(employee_id).adjustment_days
                    if workday_adjustments.get(employee_id) is not None
                    else 0
                ),
            )
            recommendation = recommendation_by_employee.get(employee_id)
            base_target = max(
                0,
                min(
                    month_days,
                    target
                    - (
                        workday_adjustments.get(employee_id).adjustment_days
                        if workday_adjustments.get(employee_id) is not None
                        else 0
                    )
                    + (
                        planned.get(employee_id).planned_days
                        if planned.get(employee_id) is not None
                        else 0
                    ),
                ),
            )
            raw_delta = actual - base_target
            if raw_delta == 0 or delta == 0:
                status_text = "Закрито"
            elif delta == raw_delta:
                status_text = "Не застосовано"
            else:
                status_text = "Частково"
            values = [
                short_name,
                str(actual),
                str(base_target),
                str(target),
                f"{delta:+d}",
                status_text,
                self.COMPENSATION_KIND_LABELS.get(
                    recommendation.kind, recommendation.kind
                )
                if recommendation is not None
                else "-",
                recommendation.message
                if recommendation is not None
                else "Компенсація не потрібна.",
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, employee_id)
                if column_index in {1, 2, 3, 4}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column_index == 4:
                    item.setBackground(
                        QColor("#FDE2B8")
                        if delta > 0
                        else QColor("#F7D6DA")
                        if delta < 0
                        else QColor("#DDF2E0")
                    )
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.compensation_table.setItem(row_index, column_index, item)

    def _on_plan_item_changed(self, item: QTableWidgetItem) -> None:
        if self._is_updating_plan or item.column() not in {2, 5}:
            return
        employee_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(employee_id, int):
            return

        plan_item = self.plan_table.item(item.row(), 2)
        note_item = self.plan_table.item(item.row(), 5)
        if plan_item is None or note_item is None:
            return

        raw_plan = plan_item.text().strip()
        try:
            planned_days = int(raw_plan or "0")
        except ValueError:
            QMessageBox.warning(
                self, "Облік вихідних", "У колонці 'План' потрібно вказати ціле число."
            )
            self.reload_data()
            return
        if planned_days < 0:
            QMessageBox.warning(
                self,
                "Облік вихідних",
                "План додаткових вихідних не може бути від'ємним.",
            )
            self.reload_data()
            return

        note = note_item.text().strip()
        self.repository.save_planned_extra_days_off(
            employee_id=employee_id,
            year=self.current_year,
            month=self.current_month,
            planned_days=planned_days,
            note=note,
        )
        self.reload_data()
        self.on_changed()

    def _visible_employee_ids(
        self,
        employees: dict[int | None, str],
        balances: dict[int, int],
        planned: dict[int, object],
        usage_totals: dict[int, int],
    ) -> set[int]:
        text_filter = self.filter_edit.text().strip().casefold()
        status_filter = str(self.plan_status_filter.currentData())
        visible: set[int] = set()
        for employee_id, short_name in employees.items():
            if employee_id is None:
                continue
            if text_filter and text_filter not in short_name.casefold():
                continue
            planned_item = planned.get(employee_id)
            planned_days = planned_item.planned_days if planned_item is not None else 0
            balance = balances.get(employee_id, 0)
            used_days = usage_totals.get(employee_id, 0)
            if status_filter == "planned" and planned_days <= 0:
                continue
            if status_filter == "overplanned" and planned_days <= balance:
                continue
            if status_filter == "underused" and not (
                planned_days > 0 and used_days < planned_days
            ):
                continue
            visible.add(employee_id)
        return visible

    def _selected_plan_employee_ids(self) -> list[int]:
        employee_ids: list[int] = []
        seen: set[int] = set()
        for item in self.plan_table.selectedItems():
            row_item = self.plan_table.item(item.row(), 0)
            if row_item is None:
                continue
            employee_id = row_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(employee_id, int) or employee_id in seen:
                continue
            seen.add(employee_id)
            employee_ids.append(employee_id)
        return employee_ids

    def _adjust_selected_plans(self, delta: int) -> None:
        employee_ids = self._selected_plan_employee_ids()
        if not employee_ids:
            QMessageBox.information(
                self, "Облік вихідних", "Оберіть хоча б один рядок у таблиці плану."
            )
            return
        planned = self.repository.get_planned_extra_days_off_map(
            self.current_year, self.current_month
        )
        for employee_id in employee_ids:
            current = planned.get(employee_id)
            planned_days = max(
                0, (current.planned_days if current is not None else 0) + delta
            )
            note = current.note if current is not None else ""
            self.repository.save_planned_extra_days_off(
                employee_id=employee_id,
                year=self.current_year,
                month=self.current_month,
                planned_days=planned_days,
                note=note,
            )
        self.reload_data()
        self.on_changed()

    def _clear_selected_plans(self) -> None:
        employee_ids = self._selected_plan_employee_ids()
        if not employee_ids:
            QMessageBox.information(
                self, "Облік вихідних", "Оберіть хоча б один рядок у таблиці плану."
            )
            return
        planned = self.repository.get_planned_extra_days_off_map(
            self.current_year, self.current_month
        )
        for employee_id in employee_ids:
            current = planned.get(employee_id)
            note = current.note if current is not None else ""
            self.repository.save_planned_extra_days_off(
                employee_id=employee_id,
                year=self.current_year,
                month=self.current_month,
                planned_days=0,
                note=note,
            )
        self.reload_data()
        self.on_changed()

    def _selected_compensation_employee_ids(self) -> list[int]:
        employee_ids: list[int] = []
        seen: set[int] = set()
        for item in self.compensation_table.selectedItems():
            row_item = self.compensation_table.item(item.row(), 0)
            if row_item is None:
                continue
            employee_id = row_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(employee_id, int) or employee_id in seen:
                continue
            seen.add(employee_id)
            employee_ids.append(employee_id)
        return employee_ids

    def _next_period(self) -> tuple[int, int]:
        if self.current_month == 12:
            return self.current_year + 1, 1
        return self.current_year, self.current_month + 1

    def _apply_underwork_to_current_extra_off(self) -> None:
        self._apply_compensation_action("underwork_current_extra_off")

    def _apply_underwork_to_next_month_workdays(self) -> None:
        self._apply_compensation_action("underwork_next_month_workdays")

    def _apply_overwork_to_next_month_extra_off(self) -> None:
        self._apply_compensation_action("overwork_next_month_extra_off")

    def _apply_overwork_to_balance_credit(self) -> None:
        self._apply_compensation_action("overwork_balance_credit")

    def _apply_compensation_action(self, action: str) -> None:
        employee_ids = self._selected_compensation_employee_ids()
        if not employee_ids:
            QMessageBox.information(
                self,
                "Облік вихідних",
                "Оберіть хоча б один рядок у таблиці компенсації.",
            )
            return

        employees = {
            employee.id: employee
            for employee in self.repository.list_employees(include_archived=True)
            if employee.id is not None
        }
        schedule = self.schedule_snapshot_provider(
            self.current_year, self.current_month
        ) or self.repository.get_schedule(self.current_year, self.current_month)
        current_extra_off_map = self.repository.get_planned_extra_days_off_map(
            self.current_year, self.current_month
        )
        current_workday_adjustment_map = (
            self.repository.get_planned_workday_adjustments_map(
                self.current_year, self.current_month
            )
        )
        calendar = UkrainianCalendar(
            martial_law=self.repository.get_settings().get("martial_law", "1") == "1"
        )
        working_days = (
            calendar.get_production_norm(self.current_year, self.current_month) // 8
        )
        month_days = len(calendar.get_month_info(self.current_year, self.current_month))
        next_year, next_month = self._next_period()

        for employee_id in employee_ids:
            employee = employees.get(employee_id)
            if employee is None:
                continue
            actual, target, delta = employee_effective_target_work(
                employee,
                days=schedule.get(employee_id, {}),
                working_days=working_days,
                month_days=month_days,
                planned_extra_days_off=(
                    current_extra_off_map.get(employee_id).planned_days
                    if current_extra_off_map.get(employee_id) is not None
                    else 0
                ),
                planned_workday_adjustment=(
                    current_workday_adjustment_map.get(employee_id).adjustment_days
                    if current_workday_adjustment_map.get(employee_id) is not None
                    else 0
                ),
            )
            if delta == 0:
                continue

            if action == "underwork_current_extra_off" and delta < 0:
                current = current_extra_off_map.get(employee_id)
                self.repository.save_planned_extra_days_off(
                    employee_id=employee_id,
                    year=self.current_year,
                    month=self.current_month,
                    planned_days=max(
                        0,
                        (current.planned_days if current is not None else 0)
                        + abs(delta),
                    ),
                    note=(current.note if current is not None else "")
                    or "Компенсація недобору поточного місяця",
                )
                self.repository.create_work_norm_compensation_action(
                    employee_id=employee_id,
                    action_type="underwork_current_month_extra_off_plan",
                    days_count=abs(delta),
                    source_year=self.current_year,
                    source_month=self.current_month,
                    target_year=self.current_year,
                    target_month=self.current_month,
                    description="Заплановано вихідні в поточному місяці для компенсації недобору.",
                )
            elif action == "underwork_next_month_workdays" and delta < 0:
                current = self.repository.get_planned_workday_adjustments_map(
                    next_year, next_month
                ).get(employee_id)
                self.repository.save_planned_workday_adjustment(
                    employee_id=employee_id,
                    year=next_year,
                    month=next_month,
                    adjustment_days=max(
                        0,
                        (current.adjustment_days if current is not None else 0)
                        + abs(delta),
                    ),
                    source_year=self.current_year,
                    source_month=self.current_month,
                    note=(current.note if current is not None else "")
                    or "Компенсація недобору попереднього місяця",
                )
                self.repository.create_work_norm_compensation_action(
                    employee_id=employee_id,
                    action_type="underwork_next_month_work_adjustment",
                    days_count=abs(delta),
                    source_year=self.current_year,
                    source_month=self.current_month,
                    target_year=next_year,
                    target_month=next_month,
                    description="Перенесено недобір як додаткові робочі дні наступного місяця.",
                )
            elif action == "overwork_next_month_extra_off" and delta > 0:
                current = self.repository.get_planned_extra_days_off_map(
                    next_year, next_month
                ).get(employee_id)
                self.repository.save_planned_extra_days_off(
                    employee_id=employee_id,
                    year=next_year,
                    month=next_month,
                    planned_days=max(
                        0, (current.planned_days if current is not None else 0) + delta
                    ),
                    note=(current.note if current is not None else "")
                    or "Компенсація переробки попереднього місяця",
                )
                self.repository.create_work_norm_compensation_action(
                    employee_id=employee_id,
                    action_type="overwork_next_month_extra_off_plan",
                    days_count=delta,
                    source_year=self.current_year,
                    source_month=self.current_month,
                    target_year=next_year,
                    target_month=next_month,
                    description="Заплановано додаткові вихідні наступного місяця для компенсації переробки.",
                )
            elif action == "overwork_balance_credit" and delta > 0:
                self.repository.create_extra_day_off_operation(
                    employee_id=employee_id,
                    action="credit",
                    days_count=delta,
                    schedule_year=self.current_year,
                    schedule_month=self.current_month,
                    description="Нараховано за переробку відносно місячної норми.",
                )
                self.repository.create_work_norm_compensation_action(
                    employee_id=employee_id,
                    action_type="overwork_balance_credit",
                    days_count=delta,
                    source_year=self.current_year,
                    source_month=self.current_month,
                    description="Переробку зараховано в баланс додаткових вихідних.",
                )

        self.reload_data()
        self.on_changed()
        if action == "underwork_next_month_workdays":
            QMessageBox.information(
                self,
                "Компенсація норми",
                f"Компенсацію записано як додаткові робочі дні на {next_month:02d}.{next_year}.",
            )
        elif action == "overwork_next_month_extra_off":
            QMessageBox.information(
                self,
                "Компенсація норми",
                f"Компенсацію записано як додаткові вихідні на {next_month:02d}.{next_year}.",
            )

    def add_operation(self) -> None:
        employees = self.repository.list_employees(include_archived=True)
        dialog = ExtraDayOffDialog(
            employees, self.current_year, self.current_month, parent=self
        )
        if dialog.exec():
            payload = dialog.get_payload()
            self.repository.create_extra_day_off_operation(
                employee_id=int(payload["employee_id"]),
                action=str(payload["action"]),
                days_count=int(payload["days_count"]),
                schedule_year=self.current_year,
                schedule_month=self.current_month,
                description=str(payload["description"]),
            )
            self.reload_data()
            self.on_changed()

    def delete_operation(self) -> None:
        row = self.operations_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Облік вихідних", "Оберіть операцію для видалення."
            )
            return
        item = self.operations_table.item(row, 0)
        if item is None:
            return
        operation_id = item.data(Qt.ItemDataRole.UserRole)
        if operation_id is None:
            return
        confirm = QMessageBox.question(self, "Видалення", "Видалити вибрану операцію?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_extra_day_off_operation(int(operation_id))
        self.reload_data()
        self.on_changed()
