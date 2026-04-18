from __future__ import annotations

import calendar
from datetime import date
from typing import Callable

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QStyle,
    QAbstractScrollArea,
    QSizePolicy,
)

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.shift_codes import CANONICAL_SHIFT_CODES, normalize_shift_code
from schedule_askue.db.models import Wish
from schedule_askue.db.repository import Repository
from schedule_askue.ui.table_widgets import GridTableWidget
from schedule_askue.ui.wish_dialog import WishDialog

logger = logging.getLogger(__name__)
from schedule_askue.ui.custom_header import ColoredHeaderView


class WishCellDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.values = ["", "Р", "Д", "В", "О"]

    def createEditor(self, parent, option, index):
        if index.column() == 0:
            return None
        editor = QComboBox(parent)
        editor.addItems(self.values)
        return editor

    def setEditorData(self, editor, index) -> None:
        if not isinstance(editor, QComboBox):
            return
        value = str(index.data(Qt.ItemDataRole.EditRole) or "")
        pos = editor.findText(value)
        editor.setCurrentIndex(pos if pos >= 0 else 0)

    def setModelData(self, editor, model, index) -> None:
        if not isinstance(editor, QComboBox):
            return
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class WishesTab(QWidget):
    WEEKDAY_LABELS = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Нд"}
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
    SYMBOL_HINTS = {
        "Р": "Робочий день (8)",
        "Д": "Чергування (8)",
        "В": "Вихідний",
        "О": "Відпустка",
        "": "Побажання не задане",
    }
    TYPE_LABELS = {
        "vacation": "Відпустка",
        "day_off": "Вихідний",
        "work_day": "Робочий день",
    }
    PRIORITY_LABELS = {
        "mandatory": "Обов'язково виконати",
        "desired": "Бажано врахувати",
    }

    def __init__(
        self,
        repository: Repository,
        calendar_ua: UkrainianCalendar,
        on_changed: Callable[[], None] | None = None,
        on_employee_order_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.calendar_ua = calendar_ua
        self.on_changed = on_changed or (lambda: None)
        self.on_employee_order_changed = on_employee_order_changed or (lambda: None)
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self._cell_wish_ids: dict[tuple[int, int], list[int]] = {}
        self._is_updating_table = False
        self._cell_wishes_by_position: dict[tuple[int, int], list[Wish]] = {}

        self.month_label = QLabel(self)
        self.selection_info_label = QLabel(self)
        self.detail_label = QLabel(self)
        self.table = GridTableWidget(self)
        self.delegate = WishCellDelegate(self.table)

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

        title = QLabel("Побажання", self)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")  # Зменшено
        layout.addWidget(title)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(3)  # Зменшено
        self.month_label.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #1F2933;"
        )  # Зменшено
        hint = QLabel(
            "Коди: Р — робочий (8), Д — чергування (8), В — вихідний, О — відпустка. Зміни в таблиці та масові дії застосовуються одразу. Підтримується вставка з Excel.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )
        hint.setVisible(False)
        move_up_button = QPushButton("↑", self)
        move_up_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        )
        move_down_button = QPushButton("↓", self)
        move_down_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        add_button = QPushButton("Додати", self)
        add_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        delete_button = QPushButton("Видалити", self)
        delete_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        apply_off_button = QPushButton("В", self)
        apply_vacation_button = QPushButton("О", self)
        apply_work_button = QPushButton("Р", self)
        apply_duty_button = QPushButton("Д", self)
        mandatory_button = QPushButton("Обов'язкове", self)
        mandatory_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        desired_button = QPushButton("Бажане", self)
        desired_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
        )
        extra_balance_button = QPushButton("Баланс", self)
        extra_balance_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_RestoreDefaultsButton)
        )
        clear_button = QPushButton("Очистити", self)
        clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_LineEditClearButton)
        )
        for button in (
            move_up_button,
            move_down_button,
            add_button,
            delete_button,
            apply_off_button,
            apply_vacation_button,
            apply_work_button,
            apply_duty_button,
            mandatory_button,
            desired_button,
            extra_balance_button,
            clear_button,
        ):
            button.setMinimumHeight(26)
            button.setMaximumHeight(26)

        for button in (move_up_button, move_down_button):
            button.setMaximumWidth(40)

        move_up_button.setToolTip("Працівник вгору")
        move_down_button.setToolTip("Працівник вниз")
        add_button.setToolTip("Додати побажання")
        delete_button.setToolTip("Видалити побажання")
        apply_off_button.setToolTip("В → вибраним")
        apply_vacation_button.setToolTip("О → вибраним")
        apply_work_button.setToolTip("Р → вибраним")
        apply_duty_button.setToolTip("Д → вибраним")
        mandatory_button.setToolTip("Позначити вибране як обов'язкове побажання")
        desired_button.setToolTip("Бажане")
        extra_balance_button.setToolTip("Позначити вибране як вихідний з балансу")
        clear_button.setToolTip("Очистити вибране")

        move_up_button.clicked.connect(lambda: self._move_selected_employee_row(-1))
        move_down_button.clicked.connect(lambda: self._move_selected_employee_row(1))
        add_button.clicked.connect(self.add_wish)
        delete_button.clicked.connect(self.delete_wish)
        apply_off_button.clicked.connect(lambda: self._apply_symbol_to_selection("В"))
        apply_vacation_button.clicked.connect(
            lambda: self._apply_symbol_to_selection("О")
        )
        apply_work_button.clicked.connect(lambda: self._apply_symbol_to_selection("Р"))
        apply_duty_button.clicked.connect(lambda: self._apply_symbol_to_selection("Д"))
        mandatory_button.clicked.connect(
            lambda: self._apply_attribute_to_selection(priority="mandatory")
        )
        desired_button.clicked.connect(
            lambda: self._apply_attribute_to_selection(priority="desired")
        )
        extra_balance_button.clicked.connect(
            lambda: self._apply_attribute_to_selection(use_extra_day_off=True)
        )
        clear_button.clicked.connect(self._clear_selected_cells)

        self.selection_info_label.setWordWrap(True)
        self.selection_info_label.setStyleSheet(
            "padding: 4px 6px; background: #F4F7FB; border: 1px solid #CFD9E6; border-radius: 4px; color: #465467; font-size: 10px;"
        )
        self.selection_info_label.setVisible(False)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #465467; font-size: 10px;"
        )
        self.detail_label.setVisible(False)

        # Toolbar розбитий на 2 ряди для кращої адаптивності
        # Ряд 1: Навігація та основні дії
        toolbar_row1 = QHBoxLayout()
        toolbar_row1.setContentsMargins(0, 0, 0, 0)
        toolbar_row1.setSpacing(3)
        toolbar_row1.addWidget(self.month_label)
        toolbar_row1.addSpacing(8)
        toolbar_row1.addWidget(move_up_button)
        toolbar_row1.addWidget(move_down_button)
        toolbar_row1.addWidget(add_button)
        toolbar_row1.addWidget(delete_button)
        toolbar_row1.addStretch()

        # Ряд 2: Швидкі дії з кодами та атрибутами
        toolbar_row2 = QHBoxLayout()
        toolbar_row2.setContentsMargins(0, 0, 0, 0)
        toolbar_row2.setSpacing(3)
        toolbar_row2.addWidget(apply_off_button)
        toolbar_row2.addWidget(apply_vacation_button)
        toolbar_row2.addWidget(apply_work_button)
        toolbar_row2.addWidget(apply_duty_button)
        toolbar_row2.addWidget(mandatory_button)
        toolbar_row2.addWidget(desired_button)
        toolbar_row2.addWidget(extra_balance_button)
        toolbar_row2.addWidget(clear_button)
        toolbar_row2.addStretch()

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.table.setWordWrap(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.use_content_height(False)
        self.table.horizontalHeader().setMinimumSectionSize(30)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(0, 120)
        self.table.setItemDelegate(self.delegate)
        self.table.itemChanged.connect(self._on_item_changed)

        # Replace horizontal header with custom colored header
        custom_header = ColoredHeaderView(Qt.Orientation.Horizontal, self.table)
        custom_header.setMinimumSectionSize(30)
        custom_header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        custom_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        custom_header.setFixedHeight(44)
        self.table.setHorizontalHeader(custom_header)

        self.table.setStyleSheet(
            "QTableWidget { background: #FFFFFF; gridline-color: #D6D9DE; border: 1px solid #D6D9DE; selection-background-color: #D9E8F5; font-size: 11px; }"
            "QHeaderView::section { color: #24303F; border: 1px solid #D6D9DE; padding: 2px; font-size: 10px; }"
        )
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.set_paste_handler(self._paste_from_clipboard)
        self.table.enable_row_reorder(self._on_rows_reordered)
        self.table.itemSelectionChanged.connect(self._update_selection_details)

        layout.addLayout(toolbar_row1)
        layout.addLayout(toolbar_row2)
        layout.addWidget(hint)
        layout.addWidget(self.selection_info_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.table)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adjust_table_widths()

    def _adjust_table_widths(self) -> None:
        if self.table.columnCount() <= 1:
            return
        available = max(0, self.table.viewport().width())
        employee_width = max(160, min(220, int(available * 0.18)))
        day_columns = self.table.columnCount() - 1
        day_width = max(
            30, min(52, (available - employee_width) // max(1, day_columns))
        )
        self.table.setColumnWidth(0, employee_width)
        for column in range(1, self.table.columnCount()):
            self.table.setColumnWidth(column, day_width)

    def _save_auto_layout(self) -> None:
        """Автоматично зберегти ширину колонок."""
        self.repository.auto_save_table_widths("wishesTab", "main", self.table.get_column_widths())
        self.table.reset_to_stretch()

    def _restore_auto_layout(self) -> None:
        """Відновити ширину колонок."""
        widths = self.repository.get_auto_table_widths("wishesTab", "main")
        if widths:
            self.table.set_column_widths(widths)
            self.table.enable_resize_mode()

    def set_period(self, year: int, month: int) -> None:
        if self.current_year == year and self.current_month == month:
            return
        self.current_year = year
        self.current_month = month
        self.reload_data()

    def update_calendar(self, calendar_ua: UkrainianCalendar) -> None:
        self.calendar_ua = calendar_ua
        self.reload_data()

    def reload_data(self) -> None:
        self.month_label.setText(
            f"{self.MONTH_NAMES_UA[self.current_month]} {self.current_year}"
        )
        employees = self.repository.list_employees()
        wishes = self.repository.list_wishes(self.current_year, self.current_month)
        month_days = calendar.monthrange(self.current_year, self.current_month)[1]
        month_info = self.calendar_ua.get_month_info(
            self.current_year, self.current_month
        )
        self._cell_wish_ids = {}
        self._cell_wishes_by_position = {}
        employee_rows: dict[int | None, int] = {}

        self._is_updating_table = True
        try:
            self.table.setRowCount(len(employees))
            self.table.setColumnCount(month_days + 1)
            self.table.setHorizontalHeaderItem(0, QTableWidgetItem("Співробітник"))

            # Calculate weekends_set BEFORE using it
            weekends_set = {
                d
                for d, info in month_info.items()
                if info.is_weekend
                or (info.is_holiday and not self.calendar_ua.martial_law)
            }

            for day in range(1, month_days + 1):
                header_text = f"{day}\n{self.WEEKDAY_LABELS[month_info[day].weekday]}"
                header_item = QTableWidgetItem(header_text)
                header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setHorizontalHeaderItem(day, header_item)
                self.table.setColumnWidth(day, 30)
            self.table.horizontalHeader().setFixedHeight(44)

            # Apply header colors using custom header
            header = self.table.horizontalHeader()
            if isinstance(header, ColoredHeaderView):
                header.clear_section_colors()
                for day in range(1, month_days + 1):
                    is_weekend = day in weekends_set
                    if is_weekend:
                        header.set_section_color(
                            day, QColor("#FFCCCC"), QColor("#C91C23")
                        )
                    else:
                        header.set_section_color(
                            day, QColor("#F7F5EF"), QColor("#24303F")
                        )
                # Set employee column color
                header.set_section_color(0, QColor("#F7F5EF"), QColor("#24303F"))
                header.viewport().update()

            for row_index, employee in enumerate(employees):
                employee_rows[employee.id] = row_index
                name_item = QTableWidgetItem(employee.short_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setBackground(QColor("#F7F5EF"))
                name_item.setToolTip(employee.full_name)
                if employee.id is not None:
                    name_item.setData(Qt.ItemDataRole.UserRole, employee.id)
                self.table.setItem(row_index, 0, name_item)
                for day in range(1, month_days + 1):
                    cell = QTableWidgetItem("")
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setToolTip(self.SYMBOL_HINTS[""])
                    if day in weekends_set:
                        cell.setForeground(QColor("#C91C23"))
                    self.table.setItem(row_index, day, cell)

            for wish in wishes:
                row_index = employee_rows.get(wish.employee_id)
                if row_index is None:
                    continue
                start_day = wish.date_from or 1
                end_day = wish.date_to or start_day
                for day in range(start_day, end_day + 1):
                    if day < 1 or day > month_days:
                        continue
                    item = self.table.item(row_index, day)
                    if item is None:
                        continue
                    symbol = self._wish_symbol(wish)
                    item.setText(symbol)
                    item.setBackground(self._wish_color(wish))

                    # Add visual indicator for mandatory wishes
                    if wish.priority == "mandatory":
                        item.setFont(item.font())
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)

                    if day in weekends_set:
                        item.setForeground(QColor("#C91C23"))
                    item.setToolTip(self._wish_tooltip(wish, symbol))
                    if wish.id is not None:
                        self._cell_wish_ids.setdefault((row_index, day), []).append(
                            wish.id
                        )
                    self._cell_wishes_by_position.setdefault(
                        (row_index, day), []
                    ).append(wish)
        finally:
            self._is_updating_table = False

        self.table.sync_row_headers()
        self._update_selection_details()
        self._adjust_table_widths()
        self._adjust_table_widths()

    def add_wish(self) -> None:
        employees = self.repository.list_employees()
        if not employees:
            QMessageBox.information(
                self, "Побажання", "Спочатку додайте хоча б одного співробітника."
            )
            return
        dialog = WishDialog(
            employees, self.current_year, self.current_month, parent=self
        )
        if dialog.exec():
            wish = dialog.get_wish()
            self.repository.create_wish(wish)
            self.reload_data()
            self.on_changed()

    def delete_wish(self) -> None:
        row = self.table.currentRow()
        column = self.table.currentColumn()
        if row < 0 or column <= 0:
            QMessageBox.information(
                self, "Побажання", "Оберіть клітинку з побажанням для видалення."
            )
            return
        self._clear_cell_wishes(row, column)

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column == 0:
            return
        item = self.table.item(row, column)
        if item is not None:
            self.table.editItem(item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._is_updating_table or item.column() == 0:
            return
        row = item.row()
        day = item.column()
        value = normalize_shift_code(item.text().strip())
        if value not in CANONICAL_SHIFT_CODES:
            self._is_updating_table = True
            item.setText("")
            self._is_updating_table = False
            value = ""

        self._clear_cell_wishes(row, day, reload_after=False)
        if value:
            employees = self.repository.list_employees()
            if row < len(employees):
                employee = employees[row]
                if employee.id is not None:
                    self.repository.create_wish(
                        self._wish_from_symbol(employee.id, day, value)
                    )
        self.reload_data()
        self.on_changed()

    def _clear_cell_wishes(
        self, row: int, column: int, reload_after: bool = True
    ) -> None:
        wish_ids = self._cell_wish_ids.get((row, column), [])
        if not wish_ids:
            if reload_after:
                self.reload_data()
            return
        if reload_after:
            confirm = QMessageBox.question(
                self, "Видалення", "Видалити побажання з обраної клітинки?"
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        for wish_id in wish_ids:
            self.repository.delete_wish(int(wish_id))
        if reload_after:
            self.reload_data()
            self.on_changed()

    def _selected_wish_cells(self) -> list[tuple[int, int]]:
        cells = sorted(
            {
                (item.row(), item.column())
                for item in self.table.selectedItems()
                if item.column() > 0
            }
        )
        return cells

    def _apply_symbol_to_selection(self, symbol: str) -> None:
        cells = self._selected_wish_cells()
        if not cells:
            QMessageBox.information(
                self, "Побажання", "Оберіть хоча б одну денну клітинку."
            )
            return
        employees = self.repository.list_employees()
        for row, column in cells:
            self._clear_cell_wishes(row, column, reload_after=False)
            if row >= len(employees):
                continue
            employee = employees[row]
            if employee.id is None:
                continue
            self.repository.create_wish(
                self._wish_from_symbol(employee.id, column, symbol)
            )
        self.reload_data()
        self.on_changed()

    def _apply_attribute_to_selection(
        self,
        *,
        priority: str | None = None,
        use_extra_day_off: bool | None = None,
    ) -> None:
        cells = self._selected_wish_cells()
        if not cells:
            QMessageBox.information(
                self, "Побажання", "Оберіть хоча б одну денну клітинку."
            )
            return
        employees = self.repository.list_employees()
        for row, column in cells:
            wishes = self._cell_wishes_by_position.get((row, column), [])
            if row >= len(employees):
                continue
            employee = employees[row]
            if employee.id is None:
                continue
            if wishes:
                updated_wishes: list[Wish] = []
                for wish in wishes:
                    updated_wishes.append(
                        Wish(
                            id=None,
                            employee_id=wish.employee_id,
                            year=wish.year,
                            month=wish.month,
                            wish_type=wish.wish_type,
                            date_from=wish.date_from,
                            date_to=wish.date_to,
                            priority=priority or wish.priority,
                            use_extra_day_off=use_extra_day_off
                            if use_extra_day_off is not None
                            else wish.use_extra_day_off,
                            comment=wish.comment,
                        )
                    )
                self._clear_cell_wishes(row, column, reload_after=False)
                for wish in updated_wishes:
                    self.repository.create_wish(wish)
            else:
                symbol = "В" if use_extra_day_off else "Р"
                wish = self._wish_from_symbol(employee.id, column, symbol)
                if priority is not None:
                    wish.priority = priority
                if use_extra_day_off is not None:
                    wish.use_extra_day_off = use_extra_day_off
                self.repository.create_wish(wish)
        self.reload_data()
        self.on_changed()

    def _clear_selected_cells(self) -> None:
        cells = self._selected_wish_cells()
        if not cells:
            QMessageBox.information(
                self, "Побажання", "Оберіть хоча б одну денну клітинку."
            )
            return
        confirm = QMessageBox.question(
            self, "Очищення", "Очистити всі вибрані побажання?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        for row, column in cells:
            self._clear_cell_wishes(row, column, reload_after=False)
        self.reload_data()
        self.on_changed()

    def _update_selection_details(self) -> None:
        cells = self._selected_wish_cells()
        if not cells:
            self.selection_info_label.setVisible(False)
            self.detail_label.setVisible(False)
            return
        self.selection_info_label.setVisible(True)
        self.detail_label.setVisible(True)
        self.selection_info_label.setText(
            f"Вибрано клітинок: {len(cells)}. Швидкі дії вище застосовуються до всього вибраного діапазону."
        )
        row, column = cells[0]
        employees = self.repository.list_employees()
        employee_name = (
            employees[row].short_name if row < len(employees) else f"Рядок {row + 1}"
        )
        wishes = self._cell_wishes_by_position.get((row, column), [])
        if not wishes:
            self.detail_label.setText(
                f"Інспектор: {employee_name}, день {column}. У клітинці побажання не задано."
            )
            return
        details = [f"Інспектор: {employee_name}, день {column}."]
        priorities = {wish.priority for wish in wishes}
        extra_flags = {wish.use_extra_day_off for wish in wishes}
        details.append(
            f"Зведення клітинки: записів {len(wishes)} | пріоритет: {'змішано' if len(priorities) > 1 else self.PRIORITY_LABELS.get(next(iter(priorities)), '-')} | "
            f"баланс: {'змішано' if len(extra_flags) > 1 else ('так' if next(iter(extra_flags)) else 'ні')}"
        )
        for wish in wishes:
            symbol = self._wish_symbol(wish)
            details.append(
                f"{symbol or '-'} | {self.TYPE_LABELS.get(wish.wish_type, wish.wish_type)} | "
                f"{self.PRIORITY_LABELS.get(wish.priority, wish.priority)} | "
                f"Баланс: {'так' if wish.use_extra_day_off else 'ні'} | "
                f"Коментар: {wish.comment or '-'}"
            )
        self.detail_label.setText("\n".join(details))

    def _paste_from_clipboard(
        self, text: str, start_row: int, start_column: int
    ) -> None:
        if start_column <= 0:
            QMessageBox.information(
                self, "Побажання", "Вставка можлива тільки в денні колонки."
            )
            return
        rows = [
            line.split("\t")
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line != ""
        ]
        if not rows:
            return
        employees = self.repository.list_employees()
        operations: list[tuple[int, int, str]] = []
        for row_offset, values in enumerate(rows):
            row = start_row + row_offset
            if row >= len(employees):
                break
            for col_offset, raw_value in enumerate(values):
                column = start_column + col_offset
                if column >= self.table.columnCount():
                    break
                code = normalize_shift_code(raw_value)
                if code not in CANONICAL_SHIFT_CODES:
                    QMessageBox.warning(
                        self,
                        "Побажання",
                        f"Невідомий код '{raw_value}' у буфері вставки.",
                    )
                    return
                operations.append((row, column, code))

        for row, column, code in operations:
            self._clear_cell_wishes(row, column, reload_after=False)
            employee = employees[row]
            if employee.id is None:
                continue
            if code:
                self.repository.create_wish(
                    self._wish_from_symbol(employee.id, column, code)
                )
        self.reload_data()
        self.on_changed()

    def _on_rows_reordered(self, ordered_ids: list[int]) -> None:
        self.repository.reorder_employees(ordered_ids)
        self.reload_data()
        self.on_employee_order_changed()

    def _move_selected_employee_row(self, direction: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Побажання", "Оберіть працівника для переміщення."
            )
            return
        target_row = row + direction
        if target_row < 0 or target_row >= self.table.rowCount():
            return
        ordered_ids: list[int] = []
        for visual_row in range(self.table.rowCount()):
            item = self.table.item(visual_row, 0)
            if item is None:
                continue
            employee_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(employee_id, int):
                ordered_ids.append(employee_id)
        if len(ordered_ids) != self.table.rowCount():
            return
        ordered_ids[row], ordered_ids[target_row] = (
            ordered_ids[target_row],
            ordered_ids[row],
        )
        self.repository.reorder_employees(ordered_ids)
        self.reload_data()
        self.table.setCurrentCell(target_row, max(0, self.table.currentColumn()))
        self.on_employee_order_changed()

    def _wish_from_symbol(self, employee_id: int, day: int, symbol: str) -> Wish:
        mapping = {"О": "vacation", "В": "day_off", "Р": "work_day", "Д": "work_day"}
        return Wish(
            id=None,
            employee_id=employee_id,
            year=self.current_year,
            month=self.current_month,
            wish_type=mapping[symbol],
            date_from=day,
            date_to=day,
            priority="mandatory",
            use_extra_day_off=False,
            comment=symbol if symbol in {"Р", "Д"} else "",
        )

    def _wish_symbol(self, wish: Wish) -> str:
        if wish.wish_type == "work_day" and normalize_shift_code(wish.comment) in {
            "Р",
            "Д",
        }:
            return normalize_shift_code(wish.comment)
        return {"vacation": "О", "day_off": "В", "work_day": "Р"}.get(
            wish.wish_type, ""
        )

    def _wish_color(self, wish: Wish) -> QColor:
        # Base colors for wish types
        if wish.wish_type == "work_day":
            color = (
                QColor("#AEC6E8")
                if normalize_shift_code(wish.comment) == "Р"
                else QColor("#FFF3B0")
            )
        elif wish.wish_type == "day_off":
            color = QColor("#D9D9D9")
        elif wish.wish_type == "vacation":
            color = QColor("#FFD580")
        else:
            color = QColor("#FFFFFF")

        # Visual distinction: mandatory = solid color, desired = lighter/pattern
        if wish.priority == "mandatory":
            # Mandatory: solid, slightly darker for emphasis
            return color.darker(105)
        else:
            # Desired: lighter, more subtle
            return color.lighter(110)

    def _wish_tooltip(self, wish: Wish, symbol: str) -> str:
        balance_text = "Так" if wish.use_extra_day_off else "Ні"
        symbol_text = self.SYMBOL_HINTS.get(symbol, symbol)
        return (
            f"Код у клітинці: {symbol or '-'} ({symbol_text})\n"
            f"Тип побажання: {self.TYPE_LABELS.get(wish.wish_type, wish.wish_type)}\n"
            f"Пріоритет: {self.PRIORITY_LABELS.get(wish.priority, wish.priority)}\n"
            f"Діапазон: {wish.date_from}-{wish.date_to}\n"
            f"З балансу додаткових вихідних: {balance_text}\n"
            f"Коментар: {wish.comment or '-'}"
        )
