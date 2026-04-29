from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QKeySequence
from PyQt6.QtWidgets import QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem


class GridTableWidget(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paste_handler: Callable[[str, int, int], None] | None = None
        self._row_reorder_callback: Callable[[list[int]], None] | None = None
        self._is_syncing_row_order = False
        self._auto_save_callback: Callable[[], None] | None = None
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.timeout.connect(self._on_auto_save_timer)
        
        self.horizontalHeader().sectionResized.connect(self._on_section_resized)
        self.verticalHeader().sectionMoved.connect(self._on_section_moved)

    def set_paste_handler(
        self, handler: Callable[[str, int, int], None] | None
    ) -> None:
        self._paste_handler = handler

    def enable_row_reorder(self, callback: Callable[[list[int]], None] | None) -> None:
        self._row_reorder_callback = callback
        header = self.verticalHeader()
        header.setVisible(callback is not None)
        if callback is None:
            header.setSectionsMovable(False)
            return
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        header.setDefaultSectionSize(max(28, header.defaultSectionSize()))
        header.setMinimumWidth(28)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return
        if (
            event.matches(QKeySequence.StandardKey.Paste)
            and self._paste_handler is not None
        ):
            text = QGuiApplication.clipboard().text()
            if text:
                current = self.currentItem()
                row = current.row() if current is not None else 0
                column = current.column() if current is not None else 0
                self._paste_handler(text, row, column)
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection(self) -> None:
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = [index.row() for index in indexes]
        columns = [index.column() for index in indexes]
        min_row, max_row = min(rows), max(rows)
        min_col, max_col = min(columns), max(columns)

        lines: list[str] = []
        for row in range(min_row, max_row + 1):
            values: list[str] = []
            for column in range(min_col, max_col + 1):
                item = self.item(row, column)
                values.append("" if item is None else item.text())
            lines.append("\t".join(values))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _on_section_moved(
        self, logical_index: int, old_visual_index: int, new_visual_index: int
    ) -> None:
        if self._is_syncing_row_order or self._row_reorder_callback is None:
            return
        ordered_ids: list[int] = []
        header = self.verticalHeader()
        for visual_row in range(header.count()):
            logical_row = header.logicalIndex(visual_row)
            item = self.item(logical_row, 0)
            if item is None:
                continue
            row_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(row_id, int):
                ordered_ids.append(row_id)
        if ordered_ids:
            self._row_reorder_callback(ordered_ids)

    def sync_row_headers(self) -> None:
        self._is_syncing_row_order = True
        try:
            for row in range(self.rowCount()):
                header_item = self.verticalHeaderItem(row)
                if header_item is None:
                    header_item = QTableWidgetItem(str(row + 1))
                    self.setVerticalHeaderItem(row, header_item)
                else:
                    header_item.setText(str(row + 1))
        finally:
            self._is_syncing_row_order = False

    def configure_fill_width_table(
        self,
        *,
        stretch_columns: list[int] | None = None,
        resize_to_contents_columns: list[int] | None = None,
        fixed_columns: dict[int, int] | None = None,
    ) -> None:
        stretch_columns = stretch_columns or []
        resize_to_contents_columns = resize_to_contents_columns or []
        fixed_columns = fixed_columns or {}

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)

        for column, width in fixed_columns.items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, width)

        for column in resize_to_contents_columns:
            if column in fixed_columns:
                continue
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        for column in stretch_columns:
            if column in fixed_columns or column in resize_to_contents_columns:
                continue
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def use_content_height(self, enabled: bool) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if enabled:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(0)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(120)

    def apply_proportional_widths(
        self,
        *,
        weights: dict[int, int],
        fixed_columns: dict[int, int] | None = None,
        min_widths: dict[int, int] | None = None,
        stretch_last: bool = True,
    ) -> None:
        if self.columnCount() == 0:
            return

        fixed_columns = fixed_columns or {}
        min_widths = min_widths or {}
        header = self.horizontalHeader()
        available_width = max(0, self.viewport().width())
        if available_width <= 0:
            available_width = max(600, self.width())

        fixed_total = sum(max(0, width) for width in fixed_columns.values())
        weighted_columns = [
            column for column in range(self.columnCount()) if column in weights
        ]
        if not weighted_columns:
            return

        total_weight = sum(max(0, weights[column]) for column in weighted_columns)
        if total_weight <= 0:
            return

        remaining_width = max(0, available_width - fixed_total)
        assigned_widths: dict[int, int] = {}
        consumed = 0
        for index, column in enumerate(weighted_columns):
            if index == len(weighted_columns) - 1:
                width = max(
                    min_widths.get(column, 40),
                    remaining_width - consumed,
                )
            else:
                width = max(
                    min_widths.get(column, 40),
                    int(remaining_width * weights[column] / total_weight),
                )
                consumed += width
            assigned_widths[column] = width

        for column in range(self.columnCount()):
            if column in fixed_columns:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
                self.setColumnWidth(column, fixed_columns[column])
            elif column in assigned_widths:
                self.setColumnWidth(column, assigned_widths[column])
                if stretch_last and column == self.columnCount() - 1:
                    header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
                else:
                    header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

    def get_column_widths(self) -> dict[int, int]:
        """Отримати поточну ширину всіх колонок."""
        return {col: self.columnWidth(col) for col in range(self.columnCount())}

    def set_column_widths(self, widths: dict[object, object]) -> None:
        """Встановити ширину колонок."""
        header = self.horizontalHeader()
        for col, width in widths.items():
            try:
                col_index = int(col)
                width_value = int(width)
            except (TypeError, ValueError):
                continue
            if 0 <= col_index < self.columnCount():
                self.setColumnWidth(col_index, max(20, width_value))
                header.setSectionResizeMode(col_index, QHeaderView.ResizeMode.Fixed)

    def enable_resize_mode(self) -> None:
        """Дозволити ручне розтягування колонок."""
        header = self.horizontalHeader()
        for col in range(self.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

    def reset_to_stretch(self) -> None:
        """Скинути режим на Stretch для останньої колонки."""
        header = self.horizontalHeader()
        for col in range(self.columnCount()):
            if col == self.columnCount() - 1:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

    def set_auto_save_callback(self, callback: Callable[[], None] | None) -> None:
        """Встановити callback для автозбереження ширини колонок."""
        self._auto_save_callback = callback

    def _on_section_resized(self, logical_index: int, old_size: int, new_size: int) -> None:
        """Викликається при ручному розтягуванні колонки."""
        if self._auto_save_callback:
            self._auto_save_timer.start(2000)

    def _on_auto_save_timer(self) -> None:
        """Таймер для автозбереження."""
        if self._auto_save_callback:
            self._auto_save_callback()
