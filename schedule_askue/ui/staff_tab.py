from __future__ import annotations

from typing import Callable

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from schedule_askue.db.models import (
    SHIFT_TYPE_FULL_R,
    SHIFT_TYPE_MIXED,
    SHIFT_TYPE_SPLIT_CH,
    Employee,
)
from schedule_askue.db.repository import Repository
from schedule_askue.ui.employee_dialog import EmployeeDialog
from schedule_askue.ui.table_widgets import GridTableWidget

logger = logging.getLogger(__name__)


class StaffTab(QWidget):
    SHIFT_LABELS = {
        SHIFT_TYPE_MIXED: "Гнучкий розподіл (Р/Д)",
        SHIFT_TYPE_FULL_R: "Переважно робочий день 'Р'",
        SHIFT_TYPE_SPLIT_CH: "Переважно чергування 'Д'",
    }

    def __init__(
        self, repository: Repository, on_changed: Callable[[], None] | None = None
    ) -> None:
        super().__init__()
        self.repository = repository
        self.on_changed = on_changed or (lambda: None)
        self.table = GridTableWidget(self)
        self.search_input = QLineEdit(self)
        self.status_filter = QComboBox(self)
        self.shift_type_filter = QComboBox(self)

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

        title = QLabel("Персонал", self)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        hint = QLabel(
            "Тут зберігається список працівників, їх скорочення для графіка, ставка та режим роботи. Зміни вносяться через кнопки 'Додати', 'Редагувати' та 'В архів'. Архівні працівники не потрапляють у нові графіки.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )

        # Search and filters
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(4)

        search_label = QLabel("Пошук:", self)
        self.search_input.setPlaceholderText("Введіть ім'я або посаду...")
        self.search_input.textChanged.connect(self.reload_data)
        self.search_input.setMaximumWidth(250)

        status_label = QLabel("Статус:", self)
        self.status_filter.addItem("Усі", "all")
        self.status_filter.addItem("Активні", "active")
        self.status_filter.addItem("Архів", "archived")
        self.status_filter.currentIndexChanged.connect(self.reload_data)
        self.status_filter.setMaximumWidth(150)

        shift_label = QLabel("Режим роботи:", self)
        self.shift_type_filter.addItem("Усі", "all")
        self.shift_type_filter.addItem("Гнучкий (Р/Д)", SHIFT_TYPE_MIXED)
        self.shift_type_filter.addItem("Переважно Р", SHIFT_TYPE_FULL_R)
        self.shift_type_filter.addItem("Переважно Д", SHIFT_TYPE_SPLIT_CH)
        self.shift_type_filter.currentIndexChanged.connect(self.reload_data)
        self.shift_type_filter.setMaximumWidth(180)

        filters.addWidget(search_label)
        filters.addWidget(self.search_input)
        filters.addWidget(status_label)
        filters.addWidget(self.status_filter)
        filters.addWidget(shift_label)
        filters.addWidget(self.shift_type_filter)
        filters.addStretch()

        buttons = QHBoxLayout()
        add_button = QPushButton("Додати", self)
        add_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        edit_button = QPushButton("Редагувати", self)
        edit_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        archive_button = QPushButton("В архів", self)
        archive_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton)
        )

        for button in (add_button, edit_button, archive_button):
            button.setMinimumHeight(26)
            button.setMaximumHeight(26)

        add_button.setToolTip("Створити нового працівника")
        edit_button.setToolTip("Змінити дані вибраного працівника")
        archive_button.setToolTip("Перемістити в архів")

        add_button.clicked.connect(self.add_employee)
        edit_button.clicked.connect(self.edit_employee)
        archive_button.clicked.connect(self.archive_employee)

        buttons.addWidget(add_button)
        buttons.addWidget(edit_button)
        buttons.addWidget(archive_button)
        buttons.addStretch()

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(filters)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.enable_row_reorder(self._on_rows_reordered)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.use_content_height(False)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_table_proportions()

    def _apply_table_proportions(self) -> None:
        self.table.apply_proportional_widths(
            weights={0: 30, 1: 15, 2: 22, 3: 8, 4: 15, 5: 5, 6: 5},
            min_widths={0: 180, 1: 110, 2: 160, 3: 70, 4: 120, 5: 80, 6: 70},
        )

    def _save_auto_layout(self) -> None:
        """Автоматично зберегти ширину колонок."""
        self.repository.auto_save_table_widths("staffTab", "main", self.table.get_column_widths())
        self.table.reset_to_stretch()

    def _restore_auto_layout(self) -> None:
        """Відновити ширину колонок."""
        widths = self.repository.get_auto_table_widths("staffTab", "main")
        if widths:
            self.table.set_column_widths(widths)
            self.table.enable_resize_mode()

    def reload_data(self) -> None:
        employees = self.repository.list_employees(include_archived=True)

        # Apply filters
        search_text = self.search_input.text().strip().lower()
        status_filter = str(self.status_filter.currentData())
        shift_filter = str(self.shift_type_filter.currentData())

        filtered_employees = []
        for employee in employees:
            # Status filter
            if status_filter == "active" and not employee.is_active:
                continue
            if status_filter == "archived" and employee.is_active:
                continue

            # Shift type filter
            if shift_filter != "all" and employee.shift_type != shift_filter:
                continue

            # Search filter
            if search_text:
                if (
                    search_text not in employee.full_name.lower()
                    and search_text not in employee.short_name.lower()
                    and search_text not in (employee.position or "").lower()
                ):
                    continue

            filtered_employees.append(employee)

        headers = [
            "ПІБ",
            "Коротке ім'я",
            "Режим роботи",
            "Ставка",
            "Посада",
            "Статус",
            "Порядок",
        ]

        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(filtered_employees))

        for row_index, employee in enumerate(filtered_employees):
            values = [
                employee.full_name,
                employee.short_name,
                self.SHIFT_LABELS.get(employee.shift_type, employee.shift_type),
                str(employee.rate),
                employee.position,
                "Активний" if employee.is_active else "Архів",
                str(employee.sort_order),
            ]
            tooltips = [
                employee.full_name,
                "Ім'я, яке показується в графіку.",
                self._shift_tooltip(employee.shift_type),
                "Розмір ставки працівника.",
                employee.position or "Посада не вказана.",
                "Архівні працівники не потрапляють у нові графіки.",
                "Службовий порядок сортування у списках.",
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltips[column_index])
                if employee.id is not None and column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, employee.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)

        self.table.sync_row_headers()
        self._apply_table_proportions()

    def _shift_tooltip(self, shift_type: str) -> str:
        return {
            SHIFT_TYPE_MIXED: "Працівник може отримувати як робочі дні 'Р', так і чергування 'Д'.",
            SHIFT_TYPE_FULL_R: "Працівник орієнтований на робочі дні 'Р'.",
            SHIFT_TYPE_SPLIT_CH: "Працівник орієнтований на чергування 'Д'.",
        }.get(shift_type, shift_type)

    def _selected_employee(self) -> Employee | None:
        row = self.table.currentRow()
        if row < 0:
            return None

        row_item = self.table.item(row, 0)
        if row_item is None:
            return None
        employee_id = row_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(employee_id, int):
            return None

        employees = self.repository.list_employees(include_archived=True)
        return next(
            (employee for employee in employees if employee.id == employee_id), None
        )

    def add_employee(self) -> None:
        dialog = EmployeeDialog(parent=self)
        if dialog.exec():
            employee = dialog.get_employee()
            if not employee.full_name:
                QMessageBox.warning(
                    self, "Персонал", "Потрібно вказати ПІБ співробітника."
                )
                return
            self.repository.create_employee(employee)
            self.reload_data()
            self.on_changed()

    def edit_employee(self) -> None:
        employee = self._selected_employee()
        if employee is None:
            QMessageBox.information(
                self, "Персонал", "Оберіть співробітника для редагування."
            )
            return

        dialog = EmployeeDialog(employee=employee, parent=self)
        if dialog.exec():
            updated = dialog.get_employee()
            self.repository.update_employee(updated)
            self.reload_data()
            self.on_changed()

    def archive_employee(self) -> None:
        employee = self._selected_employee()
        if employee is None:
            QMessageBox.information(
                self, "Персонал", "Оберіть співробітника для архівації."
            )
            return
        if not employee.is_active:
            QMessageBox.information(self, "Персонал", "Співробітник уже в архіві.")
            return

        confirm = QMessageBox.question(
            self,
            "Архівація",
            "Цей співробітник не з'явиться у нових графіках. Продовжити?",
        )
        if confirm == QMessageBox.StandardButton.Yes and employee.id is not None:
            self.repository.archive_employee(employee.id)
            self.reload_data()
            self.on_changed()

    def _on_rows_reordered(self, ordered_ids: list[int]) -> None:
        self.repository.reorder_employees(ordered_ids)
        self.reload_data()
        self.on_changed()
