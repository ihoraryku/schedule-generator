from __future__ import annotations

import calendar
import json
import logging

logger = logging.getLogger(__name__)

import subprocess
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QSignalBlocker, Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QStyledItemDelegate,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.calendar_rules import is_special_day_info
from schedule_askue.core.compensation_recommendations import (
    build_compensation_recommendations,
)
from schedule_askue.core.personal_rule_periods import covered_days_for_personal_rule
from schedule_askue.core.personal_rule_logic import resolve_personal_rule_for_day
from schedule_askue.core.project_config import load_project_config
from schedule_askue.core.shift_codes import (
    CANONICAL_SHIFT_CODES,
    SHIFT_LABELS as CANONICAL_SHIFT_LABELS,
    normalize_shift_code,
)
from schedule_askue.core.work_norms import employee_work_delta
from schedule_askue.core.validator import ScheduleValidator, ValidationError
from schedule_askue.db.repository import Repository
from schedule_askue.export.excel_exporter import ExcelExporter
from schedule_askue.export.pdf_exporter import PdfExporter
from schedule_askue.ui.table_widgets import GridTableWidget
from schedule_askue.ui.custom_header import ColoredHeaderView


class ShiftComboDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.shift_values = ["", "Р", "Д", "В", "О"]

    def createEditor(self, parent, option, index):
        if index.column() == 0:
            return None
        editor = QComboBox(parent)
        editor.addItems(self.shift_values)
        return editor

    def setEditorData(self, editor, index) -> None:
        if not isinstance(editor, QComboBox):
            return
        value = index.data(Qt.ItemDataRole.EditRole) or ""
        position = editor.findText(str(value))
        editor.setCurrentIndex(position if position >= 0 else 0)

    def setModelData(self, editor, model, index) -> None:
        if not isinstance(editor, QComboBox):
            return
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class GenerateWorker(QThread):
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    def __init__(self, payload: dict, project_dir: str):
        super().__init__()
        self.payload = payload
        self.project_dir = project_dir

    def run(self):
        try:
            command = [
                sys.executable,
                "-m",
                "schedule_askue.worker.generate_schedule_worker",
            ]
            completed = subprocess.run(
                command,
                input=json.dumps(self.payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                cwd=self.project_dir,
                timeout=60,
                check=False,
            )
            if completed.returncode != 0 and not completed.stdout.strip():
                self.finished_err.emit(
                    "Окремий процес генерації завершився аварійно. Це схоже на native crash OR-Tools."
                )
                return

            try:
                response = json.loads(completed.stdout or "{}")
            except json.JSONDecodeError as exc:
                self.finished_err.emit(
                    f"Процес генерації повернув некоректну відповідь. STDERR: {completed.stderr.strip()}"
                )
                return

            if response.get("status") != "ok":
                detail = (
                    response.get("traceback")
                    or response.get("error")
                    or completed.stderr.strip()
                )
                self.finished_err.emit(
                    f"Worker генерації повідомив про помилку. {detail}"
                )
                return

            assignments = {
                int(employee_id): {int(day): str(value) for day, value in days.items()}
                for employee_id, days in response.get("assignments", {}).items()
            }
            warnings = [
                str(warning.get("message", ""))
                for warning in response.get("warnings", [])
            ]
            self.finished_ok.emit({"assignments": assignments, "warnings": warnings})
        except Exception as e:
            self.finished_err.emit(f"Помилка під час запуску: {str(e)}")


class ScheduleTab(QWidget):
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
    SHIFT_LABELS = CANONICAL_SHIFT_LABELS
    EMPLOYEE_COLUMN_MIN_WIDTH = 100
    EMPLOYEE_COLUMN_MAX_WIDTH = 140
    DAY_COLUMN_MIN_WIDTH = 26

    def __init__(
        self,
        repository: Repository,
        calendar_ua: UkrainianCalendar,
        on_period_changed: Callable[[int, int], None] | None = None,
        on_employee_order_changed: Callable[[], None] | None = None,
        on_snapshot_changed: Callable[
            [int, int, dict[int, dict[int, str]] | None], None
        ]
        | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.calendar_ua = calendar_ua
        self.on_period_changed = on_period_changed or (lambda year, month: None)
        self.on_employee_order_changed = on_employee_order_changed or (lambda: None)
        self.on_snapshot_changed = on_snapshot_changed or (
            lambda year, month, assignments: None
        )
        self.validator = ScheduleValidator()
        self.project_config = load_project_config(Path(self.repository.db_path).parent)
        self.exporter = ExcelExporter(Path(self.repository.db_path).parent)
        self.pdf_exporter = PdfExporter(Path(self.repository.db_path).parent)
        self.current_year = date.today().year
        self.current_month = date.today().month
        self._is_updating_table = False
        self._table_update_depth = 0
        self._table_signal_blocker: QSignalBlocker | None = None
        self._suspend_history = False
        self._history: list[list[dict[str, object]]] = []
        self._future: list[list[dict[str, object]]] = []
        self._dirty = False
        self._last_saved_signature = ""
        self._show_problem_rows_only = False
        self._visible_employees = []
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1200)
        self._autosave_timer.timeout.connect(self._autosave_draft)

        self.month_label = QLabel(self)
        self.save_state_label = QLabel(self)
        self.last_saved_time_label = QLabel(self)
        self.draft_status_label = QLabel(self)
        self.validation_label = QLabel(self)
        self.edit_hint_label = QLabel(self)
        self.stats_hint_label = QLabel(self)
        self.norm_status_label = QLabel(self)
        self.table = GridTableWidget(self)
        self.stats_table = GridTableWidget(self)
        self.problem_panel = QListWidget(self)
        self.problem_title_label = QLabel(self)
        self.problem_summary_label = QLabel(self)
        self.problem_filter_combo = QComboBox(self)
        self.next_problem_button = QPushButton(self)
        self.problem_rows_button = QPushButton(self)
        self.table_delegate = ShiftComboDelegate(self.table)

        self._build_ui()
        self.reload_table()
        self._restore_auto_layout()
        
        # Підключити auto-save
        self.table.set_auto_save_callback(self._save_auto_layout)

    def _push_snapshot(
        self, assignments: dict[int, dict[int, str]] | None = None
    ) -> None:
        self.on_snapshot_changed(
            self.current_year,
            self.current_month,
            assignments or self._collect_assignments_from_table(),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adjust_schedule_table_widths()
        self._sync_schedule_table_height()
        self._sync_stats_table_height()
        self._apply_stats_table_proportions()

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(self.scroll_area.frameShape().NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        content = QWidget(self.scroll_area)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)  # Зменшено з 12 до 6
        layout.setSpacing(4)  # Зменшено з 10 до 4

        prev_button = QPushButton("←", self)
        prev_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        )
        next_button = QPushButton("→", self)
        next_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        )
        move_up_button = QPushButton("↑", self)
        move_up_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        )
        move_down_button = QPushButton("↓", self)
        move_down_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.undo_button = QPushButton("Скасувати", self)
        self.undo_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
        )
        self.redo_button = QPushButton("Повернути", self)
        self.redo_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)
        )
        self.reset_button = QPushButton("Скинути", self)
        self.reset_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.generate_btn = QPushButton("Генерувати", self)
        self.generate_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton)
        )
        generate_button = self.generate_btn
        save_button = QPushButton("Зберегти", self)
        save_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        export_button = QPushButton("Excel", self)
        export_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        pdf_button = QPushButton("PDF", self)
        pdf_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        )

        for button in (
            prev_button,
            next_button,
            move_up_button,
            move_down_button,
            self.undo_button,
            self.redo_button,
            self.reset_button,
            generate_button,
            save_button,
            export_button,
            pdf_button,
        ):
            button.setMinimumHeight(26)
            button.setMaximumHeight(26)

        for button in (prev_button, next_button, move_up_button, move_down_button):
            button.setMaximumWidth(40)

        prev_button.setToolTip("Попередній місяць")
        next_button.setToolTip("Наступний місяць")
        move_up_button.setToolTip("Перемістити працівника в таблиці вгору")
        move_down_button.setToolTip("Перемістити працівника в таблиці вниз")
        self.undo_button.setToolTip("Скасувати (Ctrl+Z)")
        self.redo_button.setToolTip("Повернути (Ctrl+Y)")
        self.reset_button.setToolTip(
            "Повернути вибрані зміни до автоматично згенерованого стану"
        )
        generate_button.setToolTip("Згенерувати графік (Ctrl+G)")
        save_button.setToolTip("Зберегти поточну чернетку графіка (Ctrl+S)")
        export_button.setToolTip("Експорт у Excel")
        pdf_button.setToolTip("Експорт у PDF")

        prev_button.clicked.connect(self._go_prev_month)
        next_button.clicked.connect(self._go_next_month)
        move_up_button.clicked.connect(lambda: self._move_selected_employee_row(-1))
        move_down_button.clicked.connect(lambda: self._move_selected_employee_row(1))
        self.undo_button.clicked.connect(self.undo_last_change)
        self.redo_button.clicked.connect(self.redo_last_change)
        self.reset_button.clicked.connect(self.reset_to_auto)
        generate_button.clicked.connect(self.generate_schedule)
        save_button.clicked.connect(self.save_schedule)
        export_button.clicked.connect(self.export_excel)
        pdf_button.clicked.connect(self.export_pdf)

        QShortcut(
            QKeySequence("Ctrl+Z"),
            self,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
            activated=self.undo_last_change,
        )
        QShortcut(
            QKeySequence("Ctrl+Y"),
            self,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
            activated=self.redo_last_change,
        )
        QShortcut(
            QKeySequence("Ctrl+S"),
            self,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
            activated=self.save_schedule,
        )
        QShortcut(
            QKeySequence("Ctrl+G"),
            self,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
            activated=self.generate_schedule,
        )
        QShortcut(
            QKeySequence("Ctrl+P"),
            self,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
            activated=self._toggle_problem_panel_shortcut,
        )

        # Компактніші стилі
        self.month_label.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #1F2933;"
        )  # Зменшено з 18px
        self.save_state_label.setStyleSheet(
            "font-size: 10px; color: #697586; padding-left: 4px;"
        )  # Зменшено
        self.last_saved_time_label.setStyleSheet(
            "font-size: 10px; color: #697586;"
        )  # Зменшено
        self.draft_status_label.setStyleSheet(
            "font-size: 10px; padding: 2px 6px; border-radius: 3px;"
        )  # Зменшено
        self.validation_label.setWordWrap(True)
        self.validation_label.setMaximumHeight(120)  # Обмежити висоту
        self.validation_label.setStyleSheet(
            "padding: 4px 6px; background: #FFF7E6; border: 1px solid #E6B450; border-radius: 4px; font-size: 11px;"  # Компактніше
        )
        # Hint labels - приховуємо за замовчуванням, показуємо через tooltip
        self.edit_hint_label.setVisible(False)

        self.stats_hint_label.setWordWrap(True)
        self.stats_hint_label.setStyleSheet(
            "padding: 4px 6px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )
        self.stats_hint_label.setVisible(False)

        self.norm_status_label.setStyleSheet(
            "padding: 3px 8px; background: #F8F5EE; border-top: 1px solid #DED8CC; color: #3B4450; font-size: 11px;"
        )
        self.problem_title_label.setText("Проблеми")
        self.problem_title_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #1F2933;"
        )  # Зменшено
        self.problem_summary_label.setWordWrap(True)
        self.problem_summary_label.setStyleSheet(
            "padding: 3px 5px; background: #F8F5EE; border: 1px solid #DED8CC; border-radius: 4px; color: #5B6573; font-size: 10px;"
        )
        self.problem_filter_combo.addItem("Усі", "all")
        self.problem_filter_combo.addItem("Помилки", "error")
        self.problem_filter_combo.addItem("Попередження", "warning")
        self.problem_filter_combo.currentIndexChanged.connect(
            lambda: self._run_validation()
        )
        self.next_problem_button = QPushButton("→", self)
        self.next_problem_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        )
        self.next_problem_button.setMinimumHeight(24)
        self.next_problem_button.setMaximumHeight(24)
        self.next_problem_button.setMaximumWidth(40)
        self.next_problem_button.setToolTip("Перейти до наступної проблеми")
        self.next_problem_button.clicked.connect(self._select_next_problem)
        self.problem_rows_button.setText("Проблемні")
        self.problem_rows_button.setToolTip(
            "Показати лише працівників з активними проблемами"
        )
        self.problem_rows_button.setMinimumHeight(24)
        self.problem_rows_button.setMaximumHeight(24)
        self.problem_rows_button.setCheckable(True)
        self.problem_rows_button.toggled.connect(self._toggle_problem_rows_only)

        self._toggle_problem_panel_button = QPushButton("▼", self)
        self._toggle_problem_panel_button.setCheckable(True)
        self._toggle_problem_panel_button.setChecked(True)
        self._toggle_problem_panel_button.setMinimumHeight(20)
        self._toggle_problem_panel_button.setMaximumHeight(20)
        self._toggle_problem_panel_button.setFixedWidth(28)
        self._toggle_problem_panel_button.setToolTip("Згорнути панель проблем (Ctrl+P)")
        self._toggle_problem_panel_button.toggled.connect(self._toggle_problem_panel)
        self._toggle_problem_panel_button.setStyleSheet(
            "QPushButton { border: 1px solid #C9C1B4; border-radius: 3px; padding: 1px; }"
            "QPushButton:checked { background: #EFE8DC; }"
            "QPushButton:!checked { background: #FFF8EE; border: 2px solid #C9A96E; font-weight: bold; }"
        )

        toolbar_row1 = QHBoxLayout()
        toolbar_row1.setContentsMargins(0, 0, 0, 0)
        toolbar_row1.setSpacing(3)
        toolbar_row1.addWidget(prev_button)
        toolbar_row1.addWidget(self.month_label)
        toolbar_row1.addWidget(next_button)
        toolbar_row1.addWidget(self.draft_status_label)
        toolbar_row1.addStretch()

        toolbar_row2 = QHBoxLayout()
        toolbar_row2.setContentsMargins(0, 0, 0, 0)
        toolbar_row2.setSpacing(3)
        toolbar_row2.addWidget(generate_button)
        toolbar_row2.addWidget(save_button)
        toolbar_row2.addWidget(export_button)
        toolbar_row2.addWidget(pdf_button)
        toolbar_row2.addSpacing(4)
        toolbar_row2.addWidget(self.undo_button)
        toolbar_row2.addWidget(self.redo_button)
        toolbar_row2.addWidget(self.reset_button)
        toolbar_row2.addWidget(move_up_button)
        toolbar_row2.addWidget(move_down_button)
        toolbar_row2.addStretch()

        self.table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self.table.setAlternatingRowColors(False)
        self.table.setItemDelegate(self.table_delegate)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setShowGrid(True)
        self.table.setWordWrap(True)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setMinimumSectionSize(self.DAY_COLUMN_MIN_WIDTH)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(0, self.EMPLOYEE_COLUMN_MIN_WIDTH)
        # Replace horizontal header with custom colored header
        custom_header = ColoredHeaderView(Qt.Orientation.Horizontal, self.table)
        custom_header.setMinimumSectionSize(self.DAY_COLUMN_MIN_WIDTH)
        custom_header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        custom_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        custom_header.setFixedHeight(44)
        self.table.setHorizontalHeader(custom_header)

        self.table.setStyleSheet(
            "QTableWidget { background: #FFFFFF; gridline-color: #D6D9DE; border: 1px solid #D6D9DE; selection-background-color: #D9E8F5; font-size: 11px; }"
            "QHeaderView::section { color: #24303F; border: 1px solid #D6D9DE; padding: 2px; font-size: 10px; }"
        )
        self.table.set_paste_handler(self._paste_from_clipboard)
        self.table.enable_row_reorder(self._on_employee_rows_reordered)

        self.stats_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.stats_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.stats_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.verticalHeader().setDefaultSectionSize(22)
        # Видалено ResizeToContents — використовуємо пропорційні ширини замість цього
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table.setStyleSheet(
            "QTableWidget { background: #FFFFFF; gridline-color: #D6D9DE; border: 1px solid #D6D9DE; selection-background-color: #D9E8F5; font-size: 10px; }"
            "QHeaderView::section { background: #F1EEE7; color: #24303F; border: 1px solid #D6D9DE; padding: 3px 2px; font-weight: 600; font-size: 10px; }"
        )
        self.problem_panel.setAlternatingRowColors(True)
        self.problem_panel.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.problem_panel.setMinimumWidth(200)
        self.problem_panel.setMaximumWidth(260)
        self.problem_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.problem_panel.setStyleSheet(
            "QListWidget { background: #FFFFFF; border: 1px solid #D6D9DE; border-radius: 4px; padding: 2px; font-size: 10px; }"
            "QListWidget::item { padding: 4px 6px; border-bottom: 1px solid #EEF1F4; }"
            "QListWidget::item:selected { background: #E7F0F9; color: #24303F; }"
        )
        self.problem_panel.itemDoubleClicked.connect(self._jump_to_problem)

        stats_title = QLabel("Статистика", self)
        stats_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #1F2933;")

        layout.addLayout(toolbar_row1)
        layout.addLayout(toolbar_row2)
        layout.addWidget(self.validation_label)
        schedule_area = QHBoxLayout()
        schedule_area.setContentsMargins(0, 0, 0, 0)
        schedule_area.setSpacing(4)
        schedule_area.addWidget(self.table, stretch=1)
        schedule_area.addWidget(self._toggle_problem_panel_button)
        self._problem_panel_widget = QWidget(self)
        problem_area = QVBoxLayout(self._problem_panel_widget)
        problem_area.setContentsMargins(0, 0, 0, 0)
        problem_area.setSpacing(2)
        problem_header = QHBoxLayout()
        problem_header.setContentsMargins(0, 0, 0, 0)
        problem_header.setSpacing(3)
        problem_header.addWidget(self.problem_title_label)
        problem_header.addStretch()
        problem_area.addLayout(problem_header)
        problem_area.addWidget(self.problem_summary_label)
        problem_controls = QHBoxLayout()
        problem_controls.setContentsMargins(0, 0, 0, 0)
        problem_controls.setSpacing(3)
        problem_controls.addWidget(self.problem_filter_combo, stretch=1)
        problem_controls.addWidget(self.problem_rows_button)
        problem_controls.addWidget(self.next_problem_button)
        problem_area.addLayout(problem_controls)
        problem_area.addWidget(self.problem_panel)
        schedule_area.addWidget(self._problem_panel_widget)
        layout.addLayout(schedule_area)
        layout.addWidget(stats_title)
        layout.addWidget(self.stats_table)
        layout.addWidget(self.norm_status_label)
        layout.addStretch()

        self.scroll_area.setWidget(content)
        outer_layout.addWidget(self.scroll_area)

    def _adjust_schedule_table_widths(self) -> None:
        month_days = max(0, self.table.columnCount() - 1)
        if month_days <= 0:
            return

        viewport_width = self.table.viewport().width()
        if viewport_width <= 0:
            return

        employee_width = min(
            self.EMPLOYEE_COLUMN_MAX_WIDTH,
            max(self.EMPLOYEE_COLUMN_MIN_WIDTH, viewport_width // 10),
        )
        available_for_days = max(
            self.DAY_COLUMN_MIN_WIDTH * month_days, viewport_width - employee_width
        )
        fit_day_width = (
            available_for_days // month_days
            if month_days
            else self.DAY_COLUMN_MIN_WIDTH
        )
        day_width = max(self.DAY_COLUMN_MIN_WIDTH, fit_day_width)

        self.table.setColumnWidth(0, employee_width)
        for day in range(1, month_days + 1):
            self.table.setColumnWidth(day, day_width)

    def _save_auto_layout(self) -> None:
        """Автоматично зберегти ширину колонок."""
        self.repository.auto_save_table_widths("scheduleTab", "main", self.table.get_column_widths())
        self.table.reset_to_stretch()

    def _restore_auto_layout(self) -> None:
        """Відновити ширину колонок."""
        widths = self.repository.get_auto_table_widths("scheduleTab", "main")
        if widths:
            self.table.set_column_widths(widths)
            self.table.enable_resize_mode()

    def _sync_schedule_table_height(self) -> None:
        header_height = self.table.horizontalHeader().height()
        frame = self.table.frameWidth() * 2
        rows_height = sum(
            self.table.rowHeight(row) for row in range(self.table.rowCount())
        )
        horizontal_scroll = 0
        total_height = header_height + rows_height + horizontal_scroll + frame + 4
        self.table.setMaximumHeight(total_height)
        self.table.setMinimumHeight(0)

    def _sync_stats_table_height(self) -> None:
        header_height = self.stats_table.horizontalHeader().height()
        frame = self.stats_table.frameWidth() * 2
        rows_height = sum(
            self.stats_table.rowHeight(row)
            for row in range(self.stats_table.rowCount())
        )
        horizontal_scroll = 0
        total_height = header_height + rows_height + horizontal_scroll + frame + 4
        self.stats_table.setMaximumHeight(total_height)
        self.stats_table.setMinimumHeight(0)
        self.stats_table.setMaximumHeight(total_height)

    def _apply_stats_table_proportions(self) -> None:
        """Застосувати пропорційні ширини для таблиці статистики."""
        self.stats_table.apply_proportional_widths(
            weights={0: 20, 1: 12, 2: 8, 3: 8, 4: 8, 5: 8, 6: 12, 7: 10, 8: 8, 9: 10},
            min_widths={0: 140, 1: 90, 2: 50, 3: 50, 4: 50, 5: 50, 6: 90, 7: 80, 8: 60, 9: 80}
        )

    def _go_prev_month(self) -> None:
        if not self._confirm_leave_current_period():
            return
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self.reload_table()

    def _go_next_month(self) -> None:
        if not self._confirm_leave_current_period():
            return
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self.reload_table()

    def update_calendar(self, calendar_ua: UkrainianCalendar) -> None:
        self.calendar_ua = calendar_ua
        self.reload_table()

    def reload_table(self) -> None:
        employees = self.repository.list_employees()
        if self._show_problem_rows_only:
            problem_ids = self._current_problem_employee_ids()
            visible_employees = [
                employee for employee in employees if (employee.id or 0) in problem_ids
            ]
            if not visible_employees:
                visible_employees = employees
        else:
            visible_employees = employees
        self._visible_employees = visible_employees
        saved_schedule, manual_flags, auto_assignments = (
            self.repository.get_schedule_bundle(self.current_year, self.current_month)
        )
        self._manual_flags = manual_flags
        self._auto_assignments = auto_assignments
        month_days = calendar.monthrange(self.current_year, self.current_month)[1]
        self.month_label.setText(
            f"{self.MONTH_NAMES_UA[self.current_month]} {self.current_year}"
        )
        self._history.clear()
        self._future.clear()

        self._begin_table_update()
        try:
            self.table.setRowCount(len(visible_employees))
            self.table.setColumnCount(month_days + 1)
            self.table.setHorizontalHeaderItem(0, QTableWidgetItem("Співробітник"))

            month_info = self.calendar_ua.get_month_info(
                self.current_year, self.current_month
            )
            for day in range(1, month_days + 1):
                header_text = f"{day}\n{self.WEEKDAY_LABELS[month_info[day].weekday]}"
                header_item = QTableWidgetItem(header_text)
                header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setHorizontalHeaderItem(day, header_item)

            self.table.horizontalHeader().setFixedHeight(44)

            # Apply header styles using stylesheet on QHeaderView
            self._apply_header_styles_via_stylesheet(month_info, month_days)

            special_days_set = self._get_special_days_set()

            for row_index, employee in enumerate(visible_employees):
                name_item = QTableWidgetItem(employee.short_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setBackground(QColor("#F7F5EF"))
                name_item.setToolTip(employee.full_name)
                if employee.id is not None:
                    name_item.setData(Qt.ItemDataRole.UserRole, employee.id)
                self.table.setItem(row_index, 0, name_item)
                for day in range(1, month_days + 1):
                    value = saved_schedule.get(employee.id or 0, {}).get(day, "")
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, value)
                    self.table.setItem(row_index, day, item)
                    is_special = day in special_days_set
                    self._apply_shift_style(
                        item,
                        value,
                        manual_flags.get(employee.id or 0, {}).get(day, False),
                        is_special,
                    )
        finally:
            self._end_table_update()
        self._last_saved_signature = self._build_schedule_signature()
        self._dirty = False
        self._update_save_state_label()
        self._update_history_buttons()
        self.table.sync_row_headers()
        self._adjust_schedule_table_widths()
        self._sync_schedule_table_height()
        self._run_validation()
        self._refresh_stats()
        self._apply_stats_table_proportions()
        self._push_snapshot(saved_schedule)
        self.on_period_changed(self.current_year, self.current_month)

    def generate_schedule(self) -> None:
        if not self._confirm_regenerate():
            return
        try:
            employees = self.repository.list_employees()
            wishes = self.repository.list_wishes(self.current_year, self.current_month)
            rules = self.repository.list_rules(self.current_year, self.current_month)
            personal_rules = self.repository.list_personal_rules(
                self.current_year, self.current_month
            )
            planned_extra_days_off = self.repository.list_planned_extra_days_off(
                self.current_year, self.current_month
            )
            planned_workday_adjustments = (
                self.repository.list_planned_workday_adjustments(
                    self.current_year, self.current_month
                )
            )
            previous_month_tail = self.repository.get_previous_month_tail(
                self.current_year, self.current_month
            )
            next_month_head = self._build_next_month_head(days_forward=7)
            settings = self._validation_settings()

            payload = {
                "year": self.current_year,
                "month": self.current_month,
                "employees": [asdict(employee) for employee in employees],
                "wishes": [asdict(wish) for wish in wishes],
                "rules": [asdict(rule) for rule in rules],
                "personal_rules": [asdict(rule) for rule in personal_rules],
                "planned_extra_days_off": [
                    asdict(item) for item in planned_extra_days_off
                ],
                "planned_workday_adjustments": [
                    asdict(item) for item in planned_workday_adjustments
                ],
                "prev_month_schedule": {
                    str(employee_id): {str(day): value for day, value in days.items()}
                    for employee_id, days in previous_month_tail.items()
                },
                "next_month_schedule": {
                    str(employee_id): {str(day): value for day, value in days.items()}
                    for employee_id, days in next_month_head.items()
                },
                "settings": settings,
            }

            self.generate_btn.setEnabled(False)
            self.generate_btn.setText("Генерування...")

            self._generate_worker = GenerateWorker(
                payload, str(Path(__file__).resolve().parents[2])
            )
            self._generate_worker.finished_ok.connect(self._on_generate_finished)
            self._generate_worker.finished_err.connect(self._on_generate_error)
            self._generate_worker.start()

        except Exception as exc:
            logger.exception("Помилка під час генерації графіка")
            QMessageBox.critical(
                self,
                "Помилка генерації",
                "Під час підготовки генерації сталася помилка. Деталі записано у logs/app.log\n\n"
                f"Коротко: {exc}",
            )
            if hasattr(self, "generate_btn"):
                self.generate_btn.setEnabled(True)
                self.generate_btn.setText("Згенерувати")

    def _on_generate_finished(self, result: dict) -> None:
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Згенерувати")

        self._auto_assignments = result["assignments"]
        self._history.clear()
        self._future.clear()
        self._manual_flags = {
            employee_id: {day: False for day in days}
            for employee_id, days in self._auto_assignments.items()
        }
        self._apply_assignments(result["assignments"])
        self._push_snapshot(result["assignments"])
        self._mark_dirty()
        self._autosave_timer.start()
        self._adjust_schedule_table_widths()
        self._sync_schedule_table_height()
        validation_errors = self._run_validation()
        self._refresh_stats()

        messages = result["warnings"]
        messages.extend(self._planned_extra_day_off_summary(self._auto_assignments))
        messages.extend(
            self._compensation_recommendations_summary(self._auto_assignments)
        )
        if validation_errors:
            messages.append(f"Валідація виявила {len(validation_errors)} проблем(и).")
        if messages:
            QMessageBox.information(self, "Генерація", "\n".join(messages))

    def _on_generate_error(self, err_msg: str) -> None:
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Згенерувати")
        logger.error("GenerateWorker error: %s", err_msg)
        QMessageBox.critical(
            self,
            "Помилка генерації",
            f"Під час генерації сталася помилка. Деталі записано у logs/app.log\n\n"
            f"Коротко: {err_msg}",
        )

    def _build_next_month_head(
        self, days_forward: int = 7
    ) -> dict[int, dict[int, str]]:
        if self.current_month == 12:
            next_year, next_month = self.current_year + 1, 1
        else:
            next_year, next_month = self.current_year, self.current_month + 1

        schedule = self.repository.get_schedule(next_year, next_month)
        result: dict[int, dict[int, str]] = {}
        if schedule:
            for employee_id, days in schedule.items():
                head_days = {
                    day: val for day, val in days.items() if day <= days_forward
                }
                if head_days:
                    result[employee_id] = head_days
            return result

        wishes = self.repository.list_wishes(next_year, next_month)
        personal_rules = self.repository.list_personal_rules(next_year, next_month)
        month_info = self.calendar_ua.get_month_info(next_year, next_month)
        special_days = {
            day for day, info in month_info.items() if is_special_day_info(info)
        }
        month_days = len(month_info)
        employees = self.repository.list_employees()

        for employee in employees:
            employee_id = employee.id or 0
            emp_wishes = [
                w
                for w in wishes
                if w.employee_id == employee_id and w.priority == "mandatory"
            ]
            emp_rules = [
                r
                for r in personal_rules
                if r.employee_id == employee_id and r.is_active
            ]

            head: dict[int, str] = {}
            for day in range(1, days_forward + 1):
                shift: str | None = None
                assigned = False
                for w in emp_wishes:
                    if (w.date_from or 1) <= day <= (w.date_to or 31):
                        if w.wish_type == "work_day":
                            shift = (
                                normalize_shift_code(w.comment)
                                if normalize_shift_code(w.comment) in {"Р", "Д"}
                                else "Д"
                            )
                        elif w.wish_type == "vacation":
                            shift = "О"
                        else:
                            shift = "В"
                        assigned = True
                        break
                if assigned and shift is not None:
                    head[day] = shift
                    continue

                info = month_info[day]
                day_rules = [
                    r
                    for r in emp_rules
                    if day
                    in covered_days_for_personal_rule(
                        r,
                        month_days=month_days,
                        special_days=special_days,
                    )
                ]
                resolved = resolve_personal_rule_for_day(
                    day_rules,
                    is_special_day=is_special_day_info(info),
                )
                if resolved.forced_shift is not None:
                    shift = resolved.forced_shift
                if shift is not None:
                    head[day] = shift
            if head:
                result[employee_id] = head

        return result

    def save_schedule(self) -> None:
        try:
            assignments = self._collect_assignments_from_table()
            self._save_schedule_core(assignments)
            validation_errors = self._run_validation()
            self._refresh_stats()
            message = "Чернетку графіка збережено."
            summary_messages = self._planned_extra_day_off_summary(assignments)
            compensation_messages = self._compensation_recommendations_summary(
                assignments
            )
            if validation_errors:
                message += f" Виявлено {len(validation_errors)} проблем(и) у правилах."
            if summary_messages:
                message += "\n\n" + "\n".join(summary_messages)
            if compensation_messages:
                message += "\n\n" + "\n".join(compensation_messages)
            QMessageBox.information(self, "Збереження", message)
        except Exception as exc:
            logger.exception("Помилка під час збереження графіка")
            QMessageBox.critical(
                self,
                "Помилка збереження",
                "Під час збереження сталася помилка. Деталі записано у logs/app.log\n\n"
                f"Коротко: {exc}",
            )

    def _save_schedule_core(self, assignments: dict[int, dict[int, str]]) -> None:
        self.repository.save_schedule(
            self.current_year,
            self.current_month,
            assignments,
            manual_flags=self._manual_flags,
            auto_assignments=self._auto_assignments,
        )
        self._push_snapshot(assignments)
        self._last_saved_signature = self._build_schedule_signature(assignments)
        self._dirty = False
        self._update_save_state_label()

    def _planned_extra_day_off_summary(
        self, assignments: dict[int, dict[int, str]]
    ) -> list[str]:
        planned = self.repository.get_planned_extra_days_off_map(
            self.current_year, self.current_month
        )
        if not planned:
            return []
        used = self.repository.get_extra_day_off_usage_totals(
            self.current_year, self.current_month
        )
        employees = {
            employee.id: employee.short_name
            for employee in self.repository.list_employees(include_archived=True)
        }
        messages: list[str] = []
        for employee_id, plan in planned.items():
            if plan.planned_days <= 0:
                continue
            used_days = used.get(employee_id, 0)
            employee_name = employees.get(employee_id, f"Співробітник {employee_id}")
            messages.append(
                f"Додаткові вихідні {employee_name}: враховано {used_days} з {plan.planned_days}."
            )
        return messages

    def _compensation_recommendations_summary(
        self, assignments: dict[int, dict[int, str]]
    ) -> list[str]:
        employees = self.repository.list_employees(include_archived=True)
        working_days = (
            self.calendar_ua.get_production_norm(self.current_year, self.current_month)
            // 8
        )
        month_days = calendar.monthrange(self.current_year, self.current_month)[1]
        recommendations = build_compensation_recommendations(
            employees=employees,
            assignments=assignments,
            working_days=working_days,
            month_days=month_days,
            extra_off_balances=self.repository.get_extra_day_off_balances(),
            planned_extra_days_off=self.repository.get_planned_extra_days_off_map(
                self.current_year, self.current_month
            ),
            planned_workday_adjustments=self.repository.get_planned_workday_adjustments_map(
                self.current_year, self.current_month
            ),
        )
        return [f"Компенсація норми: {item.message}" for item in recommendations]

    def _has_manual_edits(self) -> bool:
        return any(
            is_manual
            for employee_days in self._manual_flags.values()
            for is_manual in employee_days.values()
        )

    def _confirm_leave_current_period(self) -> bool:
        if not self._dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Незбережені зміни")
        box.setText("У поточному місяці є незбережені зміни.")
        box.setInformativeText("Зберегти чернетку перед переходом на інший місяць?")
        save_button = box.addButton(
            "Зберегти і перейти", QMessageBox.ButtonRole.AcceptRole
        )
        discard_button = box.addButton(
            "Перейти без збереження", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = box.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_button:
            self._save_schedule_core(self._collect_assignments_from_table())
            return True
        if clicked is discard_button:
            self._dirty = False
            self._update_save_state_label()
            return True
        return False

    def _confirm_regenerate(self) -> bool:
        if not self._dirty and not self._has_manual_edits():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Повторна генерація")
        if self._has_manual_edits():
            box.setText("У графіку є ручні правки, і нова генерація перезапише їх.")
        else:
            box.setText("У графіку є незбережені зміни.")
        box.setInformativeText("Зберегти поточну чернетку перед новою генерацією?")
        save_button = box.addButton(
            "Зберегти і згенерувати", QMessageBox.ButtonRole.AcceptRole
        )
        continue_button = box.addButton(
            "Генерувати без збереження", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = box.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_button:
            self._save_schedule_core(self._collect_assignments_from_table())
            return True
        if clicked is continue_button:
            return True
        return False

    def _autosave_draft(self) -> None:
        if not self._dirty:
            return
        try:
            self._save_schedule_core(self._collect_assignments_from_table())
        except Exception:
            logger.exception("Помилка автозбереження графіка")
            self.save_state_label.setText("Автозбереження не вдалося")
            self.save_state_label.setStyleSheet(
                "font-size: 12px; color: #B54708; padding-left: 8px;"
            )

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_save_state_label()

    def _update_save_state_label(self) -> None:
        current_signature = self._build_schedule_signature()
        is_dirty = current_signature != self._last_saved_signature
        self._dirty = is_dirty

        # Update draft status badge
        if is_dirty:
            self.draft_status_label.setText("● Незбережені зміни")
            self.draft_status_label.setStyleSheet(
                "font-size: 11px; padding: 4px 8px; border-radius: 4px; "
                "background: #FFF7E6; color: #B8860B; border: 1px solid #E6B450;"
            )
            self.save_state_label.setText("Є незбережені зміни")
        else:
            self.draft_status_label.setText("✓ Збережено")
            self.draft_status_label.setStyleSheet(
                "font-size: 11px; padding: 4px 8px; border-radius: 4px; "
                "background: #E8F5E9; color: #2E7D32; border: 1px solid #81C784;"
            )
            self.save_state_label.setText("Чернетка збережена")

        # Update last saved time
        saved_schedule = self.repository.get_schedule(
            self.current_year, self.current_month
        )
        if saved_schedule:
            self.last_saved_time_label.setText("Останнє збереження: сьогодні")
        else:
            self.last_saved_time_label.setText("")

        # Update last saved time
        saved_schedule = self.repository.get_schedule(
            self.current_year, self.current_month
        )
        if saved_schedule:
            self.last_saved_time_label.setText("Останнє збереження: сьогодні")
        else:
            self.last_saved_time_label.setText("")

    def _update_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self._history))
        self.redo_button.setEnabled(bool(self._future))
        self.reset_button.setEnabled(bool(self._auto_assignments))

    def _build_schedule_signature(
        self, assignments: dict[int, dict[int, str]] | None = None
    ) -> str:
        payload = assignments or self._collect_assignments_from_table()
        serializable = {
            str(employee_id): {str(day): value for day, value in days.items()}
            for employee_id, days in payload.items()
        }
        return json.dumps(serializable, ensure_ascii=False, sort_keys=True)

    def _record_change_set(self, changes: list[dict[str, object]]) -> None:
        if not changes or self._suspend_history:
            return
        self._history.append(changes)
        self._future.clear()
        self._update_history_buttons()

    def _set_cell_value(self, row: int, day: int, value: str, is_manual: bool) -> None:
        item = self.table.item(row, day)
        if item is None:
            item = QTableWidgetItem(value)
            self.table.setItem(row, day, item)
        value = normalize_shift_code(value)
        item.setText(value)
        item.setData(Qt.ItemDataRole.UserRole, value)
        employees = self._visible_employees or self.repository.list_employees()
        if 0 <= row < len(employees):
            employee_id = employees[row].id or 0
            self._manual_flags.setdefault(employee_id, {})[day] = is_manual
        self._apply_shift_style(
            item, value, is_manual, day in self._get_special_days_set()
        )

    def _apply_history_change(
        self, changes: list[dict[str, object]], *, reverse: bool
    ) -> None:
        employees = self._visible_employees or self.repository.list_employees()
        self._begin_table_update()
        self._suspend_history = True
        try:
            for change in reversed(changes) if reverse else changes:
                employee_id = int(change["employee_id"])
                row = next(
                    (
                        index
                        for index, employee in enumerate(employees)
                        if (employee.id or 0) == employee_id
                    ),
                    -1,
                )
                if row < 0:
                    continue
                day = int(change["day"])
                value_key = "old_value" if reverse else "new_value"
                manual_key = "old_manual" if reverse else "new_manual"
                self._set_cell_value(
                    row, day, str(change[value_key]), bool(change[manual_key])
                )
        finally:
            self._suspend_history = False
            self._end_table_update()
        self._run_validation()
        self._refresh_stats()
        self._push_snapshot()
        self._mark_dirty()
        self._autosave_timer.start()
        self._update_history_buttons()

    def undo_last_change(self) -> None:
        if not self._history:
            return
        changes = self._history.pop()
        self._future.append(changes)
        self._apply_history_change(changes, reverse=True)

    def redo_last_change(self) -> None:
        if not self._future:
            return
        changes = self._future.pop()
        self._history.append(changes)
        self._apply_history_change(changes, reverse=False)

    def reset_to_auto(self) -> None:
        if not self._auto_assignments:
            QMessageBox.information(
                self,
                "Скидання",
                "Немає автоматично згенерованого варіанту для скидання.",
            )
            return

        selected = self.table.currentItem()
        changes: list[dict[str, object]] = []
        employees = self._visible_employees or self.repository.list_employees()
        if selected is not None and selected.column() > 0:
            row = selected.row()
            if 0 <= row < len(employees):
                employee = employees[row]
                employee_id = employee.id or 0
                day = selected.column()
                old_value = selected.text().strip()
                old_manual = bool(
                    self._manual_flags.get(employee_id, {}).get(day, False)
                )
                auto_value = self._auto_assignments.get(employee_id, {}).get(day, "")
                new_manual = False
                if old_value != auto_value or old_manual != new_manual:
                    changes.append(
                        {
                            "employee_id": employee_id,
                            "day": day,
                            "old_value": old_value,
                            "new_value": auto_value,
                            "old_manual": old_manual,
                            "new_manual": new_manual,
                        }
                    )

        if not changes:
            for row_index, employee in enumerate(employees):
                employee_id = employee.id or 0
                for day in range(1, self.table.columnCount()):
                    item = self.table.item(row_index, day)
                    if item is None:
                        continue
                    old_value = item.text().strip()
                    old_manual = bool(
                        self._manual_flags.get(employee_id, {}).get(day, False)
                    )
                    auto_value = self._auto_assignments.get(employee_id, {}).get(
                        day, ""
                    )
                    new_manual = False
                    if old_value == auto_value and old_manual == new_manual:
                        continue
                    changes.append(
                        {
                            "employee_id": employee_id,
                            "day": day,
                            "old_value": old_value,
                            "new_value": auto_value,
                            "old_manual": old_manual,
                            "new_manual": new_manual,
                        }
                    )

        if not changes:
            QMessageBox.information(
                self, "Скидання", "Ручних змін для скидання не знайдено."
            )
            return

        self._record_change_set(changes)
        self._apply_history_change(changes, reverse=False)
        self._push_snapshot()
        QMessageBox.information(
            self,
            "Скидання",
            "Ручні зміни повернуто до останнього автоматичного варіанту.",
        )

    def export_excel(self) -> None:
        employees = self.repository.list_employees()
        if not employees:
            QMessageBox.information(
                self, "Експорт", "Немає співробітників для експорту."
            )
            return
        output_dir = (
            Path(self.repository.db_path).parent
            / self.project_config.get("export", {}).get("default_dir", "./exports")
        ).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Отримати шаблон назви файлу з конфігу
        filename_template = self.project_config.get("export", {}).get("filename_template", {}).get("excel", "Графік_{year}_{month:02d}.xlsx")
        
        # Словник для форматування
        month_names_ua = {
            1: "СІЧЕНЬ", 2: "ЛЮТИЙ", 3: "БЕРЕЗЕНЬ", 4: "КВІТЕНЬ",
            5: "ТРАВЕНЬ", 6: "ЧЕРВЕНЬ", 7: "ЛИПЕНЬ", 8: "СЕРПЕНЬ",
            9: "ВЕРЕСЕНЬ", 10: "ЖОВТЕНЬ", 11: "ЛИСТОПАД", 12: "ГРУДЕНЬ"
        }
        
        default_name = filename_template.format(
            year=self.current_year,
            month=self.current_month,
            month_name_ua=month_names_ua.get(self.current_month, "")
        )
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Зберегти Excel",
            str(output_dir / default_name),
            "Excel Workbook (*.xlsx)",
        )
        if not file_path:
            return
        assignments = self._collect_assignments_from_table()
        saved_path = self.exporter.export_month(
            Path(file_path),
            self.current_year,
            self.current_month,
            employees,
            assignments,
            self.repository.get_settings(),
            self.calendar_ua,
        )
        QMessageBox.information(self, "Експорт", f"Excel-файл збережено:\n{saved_path}")

    def export_pdf(self) -> None:
        employees = self.repository.list_employees()
        if not employees:
            QMessageBox.information(
                self, "Експорт", "Немає співробітників для експорту."
            )
            return
        output_dir = (
            Path(self.repository.db_path).parent
            / self.project_config.get("export", {}).get("default_dir", "./exports")
        ).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Отримати шаблон назви файлу з конфігу
        filename_template = self.project_config.get("export", {}).get("filename_template", {}).get("pdf", "Графік_{year}_{month:02d}.pdf")
        
        # Словник для форматування
        month_names_ua = {
            1: "СІЧЕНЬ", 2: "ЛЮТИЙ", 3: "БЕРЕЗЕНЬ", 4: "КВІТЕНЬ",
            5: "ТРАВЕНЬ", 6: "ЧЕРВЕНЬ", 7: "ЛИПЕНЬ", 8: "СЕРПЕНЬ",
            9: "ВЕРЕСЕНЬ", 10: "ЖОВТЕНЬ", 11: "ЛИСТОПАД", 12: "ГРУДЕНЬ"
        }
        
        default_name = filename_template.format(
            year=self.current_year,
            month=self.current_month,
            month_name_ua=month_names_ua.get(self.current_month, "")
        )
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Зберегти PDF", str(output_dir / default_name), "PDF Document (*.pdf)"
        )
        if not file_path:
            return
        assignments = self._collect_assignments_from_table()
        saved_path = self.pdf_exporter.export_month(
            Path(file_path),
            self.current_year,
            self.current_month,
            employees,
            assignments,
            self.repository.get_settings(),
            self.calendar_ua,
        )
        QMessageBox.information(self, "Експорт", f"PDF-файл збережено:\n{saved_path}")

    def _apply_assignments(self, assignments: dict[int, dict[int, str]]) -> None:
        employees = self._visible_employees or self.repository.list_employees()
        employee_row_map = {
            employee.id: index for index, employee in enumerate(employees)
        }
        special_days_set = self._get_special_days_set()
        self._begin_table_update()
        try:
            for employee_id, days in assignments.items():
                row_index = employee_row_map.get(employee_id)
                if row_index is None:
                    continue
                for day, value in days.items():
                    item = self.table.item(row_index, day)
                    if item is None:
                        item = QTableWidgetItem(value)
                        self.table.setItem(row_index, day, item)
                    else:
                        item.setText(normalize_shift_code(value))
                    normalized_value = normalize_shift_code(value)
                    item.setData(Qt.ItemDataRole.UserRole, normalized_value)
                    self._apply_shift_style(
                        item,
                        normalized_value,
                        self._manual_flags.get(employee_id, {}).get(day, False),
                        day in special_days_set,
                    )
        finally:
            self._end_table_update()

    def _collect_assignments_from_table(self) -> dict[int, dict[int, str]]:
        employees = self._visible_employees or self.repository.list_employees()
        assignments: dict[int, dict[int, str]] = {}
        for row_index, employee in enumerate(employees):
            if employee.id is None:
                continue
            employee_days: dict[int, str] = {}
            for column in range(1, self.table.columnCount()):
                item = self.table.item(row_index, column)
                employee_days[column] = (
                    normalize_shift_code(item.text().strip())
                    if item is not None
                    else ""
                )
            assignments[employee.id] = employee_days
        return assignments

    def _validation_settings(self) -> dict[str, str]:
        settings = dict(self.repository.get_settings())
        settings["schedule_year"] = str(self.current_year)
        settings["schedule_month"] = str(self.current_month)
        return settings

    def _run_validation(self) -> list[ValidationError]:
        employees = self._visible_employees or self.repository.list_employees()
        rules = self.repository.list_rules(self.current_year, self.current_month)
        wishes = self.repository.list_wishes(self.current_year, self.current_month)
        personal_rules = self.repository.list_personal_rules(
            self.current_year, self.current_month
        )
        previous_month_tail = self.repository.get_previous_month_tail(
            self.current_year, self.current_month
        )
        assignments = self._collect_assignments_from_table()
        errors = self.validator.validate(
            assignments,
            employees,
            rules,
            self._validation_settings(),
            personal_rules=personal_rules,
            prev_month_tail=previous_month_tail,
            month_info=self.calendar_ua.get_month_info(
                self.current_year, self.current_month
            ),
            wishes=wishes,
        )
        self._render_validation(errors)
        return errors

    def _render_validation(self, errors: list[ValidationError]) -> None:
        self._begin_table_update()
        try:
            self._reset_cell_styles()
            self.problem_panel.clear()
            employees = self.repository.list_employees()
            employee_row_map = {
                employee.id: index for index, employee in enumerate(employees)
            }
            cell_messages: dict[tuple[int, int], list[str]] = {}
            day_only_messages: dict[int, list[str]] = {}
            general_messages: list[str] = []
            error_count = 0
            warning_count = 0
            for error in errors:
                if error.severity == "error":
                    error_count += 1
                else:
                    warning_count += 1
                if error.employee_id is not None and error.day is not None:
                    cell_messages.setdefault((error.employee_id, error.day), []).append(
                        (error.severity, error.message)
                    )
                elif error.day is not None:
                    day_only_messages.setdefault(error.day, []).append(
                        (error.severity, error.message)
                    )
                else:
                    general_messages.append((error.severity, error.message))
                if self._problem_matches_filter(error):
                    self._append_problem_item(error, employees)
            for (employee_id, day), entries in cell_messages.items():
                row_index = employee_row_map.get(employee_id)
                if row_index is None:
                    continue
                item = self.table.item(row_index, day)
                if item is None:
                    continue
                has_error = any(severity == "error" for severity, _ in entries)
                icon_kind = (
                    QStyle.StandardPixmap.SP_MessageBoxCritical
                    if has_error
                    else QStyle.StandardPixmap.SP_MessageBoxWarning
                )
                item.setIcon(QApplication.style().standardIcon(icon_kind))
                font = item.font()
                font.setUnderline(True)
                item.setFont(font)
                item.setToolTip(
                    "Проблема валідації:\n"
                    + "\n".join(message for _, message in entries)
                )
            for day, entries in day_only_messages.items():
                header_item = self.table.horizontalHeaderItem(day)
                if header_item is not None:
                    has_error = any(severity == "error" for severity, _ in entries)
                    icon_kind = (
                        QStyle.StandardPixmap.SP_MessageBoxCritical
                        if has_error
                        else QStyle.StandardPixmap.SP_MessageBoxWarning
                    )
                    header_item.setIcon(QApplication.style().standardIcon(icon_kind))
                    header_item.setToolTip(
                        "Проблема дня:\n" + "\n".join(message for _, message in entries)
                    )
            if errors:
                extra = f" {general_messages[0][1]}" if general_messages else ""
                if error_count > 0:
                    self.validation_label.setStyleSheet(
                        "padding: 10px 12px; background: #FFF1F2; border: 1px solid #D97988; border-radius: 8px; color: #7A1C27;"
                    )
                else:
                    self.validation_label.setStyleSheet(
                        "padding: 10px 12px; background: #FFF8E1; border: 1px solid #E1B955; border-radius: 8px; color: #7A5D00;"
                    )
                self.validation_label.setText(
                    f"Валідація: помилок {error_count}, попереджень {warning_count}. Проблеми показано в правій панелі.{extra}"
                )
                self.problem_title_label.setText(f"Проблеми ({len(errors)})")
                self.problem_summary_label.setText(
                    f"Помилки: {error_count} | Попередження: {warning_count} | Показано у списку: {self.problem_panel.count()}"
                )
            else:
                self.validation_label.setStyleSheet(
                    "padding: 10px 12px; background: #EEF8F0; border: 1px solid #88BF95; border-radius: 8px; color: #245B31;"
                )
                self.validation_label.setText(
                    "Валідація: активних порушень не знайдено."
                )
                self.problem_title_label.setText("Проблеми (0)")
                self.problem_summary_label.setText(
                    "Активних порушень немає. Список праворуч порожній."
                )
                ok_item = QListWidgetItem("Активних порушень не знайдено.")
                ok_item.setData(
                    Qt.ItemDataRole.UserRole, {"employee_id": None, "day": None}
                )
                self.problem_panel.addItem(ok_item)
            self.next_problem_button.setEnabled(
                self.problem_panel.count() > 0 and errors != []
            )
        finally:
            self._end_table_update()

    def _problem_matches_filter(self, error: ValidationError) -> bool:
        mode = str(self.problem_filter_combo.currentData())
        if mode == "error":
            return error.severity == "error"
        if mode == "warning":
            return error.severity != "error"
        return True

    def _append_problem_item(
        self, error: ValidationError, employees: list[object]
    ) -> None:
        prefix = "Помилка" if error.severity == "error" else "Попередження"
        scope_parts: list[str] = []
        if error.employee_id is not None:
            employee = next(
                (item for item in employees if (item.id or 0) == error.employee_id),
                None,
            )
            scope_parts.append(
                employee.short_name
                if employee is not None
                else f"ID {error.employee_id}"
            )
        if error.day is not None:
            scope_parts.append(f"день {error.day}")
        scope = " | ".join(scope_parts) if scope_parts else "Загальна перевірка"
        item = QListWidgetItem(f"{prefix}: {scope}\n{error.message}")
        item.setToolTip(error.message)
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "employee_id": error.employee_id,
                "day": error.day,
                "severity": error.severity,
            },
        )
        icon_kind = (
            QStyle.StandardPixmap.SP_MessageBoxCritical
            if error.severity == "error"
            else QStyle.StandardPixmap.SP_MessageBoxWarning
        )
        item.setIcon(QApplication.style().standardIcon(icon_kind))
        self.problem_panel.addItem(item)

    def _jump_to_problem(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        employee_id = payload.get("employee_id") if isinstance(payload, dict) else None
        day = payload.get("day") if isinstance(payload, dict) else None
        employees = self._visible_employees or self.repository.list_employees()
        if employee_id is not None:
            row_index = next(
                (
                    index
                    for index, employee in enumerate(employees)
                    if (employee.id or 0) == employee_id
                ),
                None,
            )
            if row_index is not None:
                target_column = int(day) if isinstance(day, int) else 0
                table_item = self.table.item(row_index, target_column)
                if table_item is not None:
                    self.table.setCurrentItem(table_item)
                    self.table.scrollToItem(
                        table_item, QAbstractItemView.ScrollHint.PositionAtCenter
                    )
                    return
        if (
            isinstance(day, int)
            and 0 < day < self.table.columnCount()
            and self.table.rowCount() > 0
        ):
            table_item = self.table.item(0, day)
            if table_item is not None:
                self.table.setCurrentItem(table_item)
                self.table.scrollToItem(
                    table_item, QAbstractItemView.ScrollHint.PositionAtCenter
                )

    def _select_next_problem(self) -> None:
        count = self.problem_panel.count()
        if count <= 0:
            return
        current_row = self.problem_panel.currentRow()
        next_row = 0 if current_row < 0 or current_row >= count - 1 else current_row + 1
        self.problem_panel.setCurrentRow(next_row)
        item = self.problem_panel.item(next_row)
        if item is not None:
            self._jump_to_problem(item)

    def _reset_cell_styles(self) -> None:
        month_days = self.table.columnCount() - 1
        month_info = self.calendar_ua.get_month_info(
            self.current_year, self.current_month
        )
        special_days_set = {
            d
            for d, info in month_info.items()
            if info.is_weekend or (info.is_holiday and not self.calendar_ua.martial_law)
        }
        employees = self._visible_employees or self.repository.list_employees()
        for day in range(1, month_days + 1):
            header_item = self.table.horizontalHeaderItem(day)
            if header_item is not None:
                self._apply_header_style(header_item, day, month_info)
                header_item.setIcon(QIcon())
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item is not None:
                name_item.setBackground(QColor("#F7F5EF"))
                name_item.setForeground(QColor("#24303F"))
                name_item.setToolTip(name_item.toolTip() or name_item.text())
            employee_id = employees[row].id if row < len(employees) else None
            for column in range(1, self.table.columnCount()):
                item = self.table.item(row, column)
                if item is None:
                    continue
                is_manual = bool(
                    employee_id
                    and self._manual_flags.get(employee_id, {}).get(column, False)
                )
                is_special = column in special_days_set
                self._apply_shift_style(
                    item, item.text().strip(), is_manual, is_special
                )

    def _get_special_days_set(self) -> set[int]:
        """Return set of day numbers that are weekends or holidays."""
        month_info = self.calendar_ua.get_month_info(
            self.current_year, self.current_month
        )
        return {
            d
            for d, info in month_info.items()
            if info.is_weekend or (info.is_holiday and not self.calendar_ua.martial_law)
        }

    def _apply_header_styles_via_stylesheet(
        self, month_info: dict[int, object], month_days: int
    ) -> None:
        """Apply header styles using custom ColoredHeaderView."""
        header = self.table.horizontalHeader()
        if not isinstance(header, ColoredHeaderView):
            return

        # Clear previous colors
        header.clear_section_colors()

        # Apply colors to weekend/holiday columns
        for day in range(1, month_days + 1):
            info = month_info[day]
            if info.is_weekend or (
                info.is_holiday and not self.calendar_ua.martial_law
            ):
                # Weekend/holiday - red background
                header.set_section_color(day, QColor("#FFCCCC"), QColor("#C91C23"))
            else:
                # Regular day - gray background
                header.set_section_color(day, QColor("#F7F5EF"), QColor("#24303F"))

        # Set employee column color
        header.set_section_color(0, QColor("#F7F5EF"), QColor("#24303F"))

        # Force repaint
        header.viewport().update()

    def _apply_header_style(
        self, item: QTableWidgetItem, day: int, month_info: dict[int, object]
    ) -> None:
        info = month_info[day]
        font = item.font()
        font.setBold(False)
        is_special = info.is_weekend or (
            info.is_holiday and not self.calendar_ua.martial_law
        )

        if is_special:
            # Weekend or holiday - red background
            item.setBackground(QColor("#FFCCCC"))
            item.setForeground(QColor("#C91C23"))
            font.setBold(True)
            item.setToolTip(
                "Державне свято"
                if info.is_holiday and not self.calendar_ua.martial_law
                else "Вихідний день календаря"
            )
        else:
            # Regular working day - gray background
            item.setBackground(QColor("#F7F5EF"))
            item.setForeground(QColor("#24303F"))
            item.setToolTip("Робочий день календаря")
        item.setFont(font)

    def _apply_shift_style(
        self,
        item: QTableWidgetItem,
        value: str,
        is_manual: bool = False,
        is_special_day: bool = False,
    ) -> None:
        colors = {
            "Р": "#AEC6E8",
            "Д": "#FFF3B0",
            "В": "#D9D9D9",
            "О": "#FFD580",
            "": "#FFFFFF",
        }
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = item.font()
        font.setBold(value == "Д")
        font.setUnderline(False)
        item.setFont(font)
        item.setIcon(QIcon())
        if is_special_day:
            item.setForeground(QColor("#C91C23"))
        else:
            item.setForeground(QColor("#24303F"))
        background = QColor(colors.get(value, "#FFFFFF"))
        if is_manual:
            background = background.darker(108)
        item.setBackground(background)
        item.setToolTip(
            self._shift_tooltip(value)
            + ("\nСтан: ручна зміна" if is_manual else "\nСтан: авто")
        )

    def _shift_tooltip(self, value: str) -> str:
        return f"Код: {value or '-'}\nЗначення: {self.SHIFT_LABELS.get(value, value)}"

    def _refresh_stats(self) -> None:
        employees = self.repository.list_employees()
        assignments = self._collect_assignments_from_table()
        balances = self.repository.get_extra_day_off_balances()
        working_days_norm = (
            self.calendar_ua.get_production_norm(self.current_year, self.current_month)
            // 8
        )
        month_days = calendar.monthrange(self.current_year, self.current_month)[1]
        tolerance = int(self.repository.get_settings().get("work_days_tolerance", "0"))
        problem_ids = self._current_problem_employee_ids()

        headers = [
            "Співробітник",
            "Баланс дод. вихідних",
            "Д",
            "Р",
            "В",
            "О",
            "Всього відпрацьовано",
            "Норма роб. днів",
            "Відхилення",
            "Стан",
        ]
        self.stats_table.setColumnCount(len(headers))
        self.stats_table.setHorizontalHeaderLabels(headers)
        self.stats_table.setRowCount(len(employees))

        for row_index, employee in enumerate(employees):
            employee_id = employee.id or 0
            days = assignments.get(employee_id, {})
            short_count = sum(1 for value in days.values() if value == "Д")
            full_count = sum(1 for value in days.values() if value == "Р")
            off_count = sum(1 for value in days.values() if value == "В")
            vacation_count = sum(1 for value in days.values() if value == "О")
            worked_total, employee_norm, deviation = employee_work_delta(
                employee,
                days=days,
                working_days=working_days_norm,
                month_days=month_days,
            )
            state_text, state_color = self._stats_state(deviation, tolerance)

            values = [
                employee.short_name,
                str(balances.get(employee_id, 0)),
                str(short_count),
                str(full_count),
                str(off_count),
                str(vacation_count),
                str(worked_total),
                str(employee_norm),
                f"{deviation:+d}",
                state_text,
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if column_index != 0
                    else Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                )
                if column_index == 9:
                    item.setBackground(state_color)
                elif column_index in {2, 3, 6, 7}:
                    item.setBackground(QColor("#E8F1FB"))
                elif column_index in {4, 5}:
                    item.setBackground(QColor("#F6F1DD"))
                elif column_index == 1:
                    item.setBackground(QColor("#E9F4E8"))
                elif column_index == 8:
                    item.setBackground(QColor("#F8EEE1"))
                if column_index == 0:
                    item.setToolTip(employee.full_name)
                    if employee_id in problem_ids:
                        item.setBackground(QColor("#FFF1F2"))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                if employee_id in problem_ids and column_index == 9:
                    item.setToolTip(
                        "У працівника є активні проблеми валідації. Скористайтесь правою панеллю 'Проблеми'."
                    )
                self.stats_table.setItem(row_index, column_index, item)

        self._apply_stats_table_proportions()
        self._sync_stats_table_height()
        self.stats_hint_label.setText(
            f"Норма робочих днів у {self.MONTH_NAMES_UA[self.current_month].lower()} {self.current_year}: {working_days_norm}. Стан показує, чи вкладається працівник у норму з урахуванням допуску ±{tolerance} дн. "
            f"Проблемні працівники додатково підсвічені в першій колонці статистики."
        )
        hour_norm = self.calendar_ua.get_production_norm(
            self.current_year, self.current_month
        )
        employee_count = len(employees)
        self.norm_status_label.setText(
            f"Співробітників: {employee_count} | Норма: {working_days_norm} дн. ({hour_norm} год)"
        )

    def _stats_state(self, deviation: int, tolerance: int) -> tuple[str, QColor]:
        if abs(deviation) <= tolerance:
            return "Норма", QColor("#DDF2E0")
        if deviation > tolerance:
            return "Переробка", QColor("#FDE2B8")
        return "Недобір", QColor("#F7D6DA")

    def _begin_table_update(self) -> None:
        self._table_update_depth += 1
        if self._table_update_depth == 1:
            self._is_updating_table = True
            self._table_signal_blocker = QSignalBlocker(self.table)

    def _end_table_update(self) -> None:
        if self._table_update_depth <= 0:
            self._table_update_depth = 0
            self._is_updating_table = False
            self._table_signal_blocker = None
            return
        self._table_update_depth -= 1
        if self._table_update_depth == 0:
            blocker = self._table_signal_blocker
            self._table_signal_blocker = None
            if blocker is not None:
                blocker.unblock()
            self._is_updating_table = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._is_updating_table or item.column() == 0:
            return
        self._begin_table_update()
        try:
            value = item.text().strip()
            if value not in {"", "Р", "Д", "В", "О"}:
                item.setText("")
                value = ""
            row = item.row()
            employees = self._visible_employees or self.repository.list_employees()
            old_value = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if 0 <= row < len(employees):
                employee = employees[row]
                employee_id = employee.id or 0
                day = item.column()
                old_manual = bool(
                    self._manual_flags.get(employee_id, {}).get(day, False)
                )
                auto_value = self._auto_assignments.get(employee_id, {}).get(day, "")
                is_manual = bool(self._auto_assignments) and value != auto_value
                self._manual_flags.setdefault(employee_id, {})[day] = is_manual
                item.setData(Qt.ItemDataRole.UserRole, value)
                self._apply_shift_style(
                    item, value, is_manual, day in self._get_special_days_set()
                )
                if not self._suspend_history and (
                    old_value != value or old_manual != is_manual
                ):
                    self._record_change_set(
                        [
                            {
                                "employee_id": employee_id,
                                "day": day,
                                "old_value": old_value,
                                "new_value": value,
                                "old_manual": old_manual,
                                "new_manual": is_manual,
                            }
                        ]
                    )
                    self._mark_dirty()
                    self._autosave_timer.start()
            else:
                item.setData(Qt.ItemDataRole.UserRole, value)
                self._apply_shift_style(
                    item, value, False, item.column() in self._get_special_days_set()
                )
            self._run_validation()
            self._refresh_stats()
            self._push_snapshot()
            self._update_history_buttons()
        finally:
            self._end_table_update()

    def _paste_from_clipboard(
        self, text: str, start_row: int, start_column: int
    ) -> None:
        if start_column <= 0:
            QMessageBox.information(
                self, "Графік", "Вставка можлива тільки в денні колонки."
            )
            return
        rows = [
            line.split("\t")
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line != ""
        ]
        if not rows:
            return

        employees = self._visible_employees or self.repository.list_employees()
        changes: list[dict[str, object]] = []
        for row_offset, values in enumerate(rows):
            row = start_row + row_offset
            if row >= len(employees):
                break
            employee_id = employees[row].id or 0
            for col_offset, raw_value in enumerate(values):
                day = start_column + col_offset
                if day >= self.table.columnCount():
                    break
                value = normalize_shift_code(raw_value)
                if value not in CANONICAL_SHIFT_CODES:
                    QMessageBox.warning(
                        self, "Графік", f"Невідомий код '{raw_value}' у буфері вставки."
                    )
                    return
                item = self.table.item(row, day)
                old_value = (
                    ""
                    if item is None
                    else str(item.data(Qt.ItemDataRole.UserRole) or item.text().strip())
                )
                old_manual = bool(
                    self._manual_flags.get(employee_id, {}).get(day, False)
                )
                auto_value = self._auto_assignments.get(employee_id, {}).get(day, "")
                new_manual = bool(self._auto_assignments) and value != auto_value
                if old_value == value and old_manual == new_manual:
                    continue
                changes.append(
                    {
                        "employee_id": employee_id,
                        "day": day,
                        "old_value": old_value,
                        "new_value": value,
                        "old_manual": old_manual,
                        "new_manual": new_manual,
                    }
                )

        if not changes:
            return
        self._record_change_set(changes)
        self._apply_history_change(changes, reverse=False)

    def _on_employee_rows_reordered(self, ordered_ids: list[int]) -> None:
        self.repository.reorder_employees(ordered_ids)
        self.reload_table()
        self.on_employee_order_changed()

    def _move_selected_employee_row(self, direction: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Графік", "Оберіть працівника для переміщення."
            )
            return
        if self._show_problem_rows_only:
            QMessageBox.information(
                self,
                "Графік",
                "Перестановка працівників недоступна в режимі 'лише проблемні працівники'.",
            )
            return
        target_row = row + direction
        if target_row < 0 or target_row >= self.table.rowCount():
            return
        ordered_ids = []
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
        self.reload_table()
        self.table.setCurrentCell(target_row, max(0, self.table.currentColumn()))
        self.on_employee_order_changed()

    def _current_problem_employee_ids(self) -> set[int]:
        problem_ids: set[int] = set()
        for row in range(self.problem_panel.count()):
            item = self.problem_panel.item(row)
            if item is None:
                continue
            payload = item.data(Qt.ItemDataRole.UserRole) or {}
            employee_id = (
                payload.get("employee_id") if isinstance(payload, dict) else None
            )
            if isinstance(employee_id, int):
                problem_ids.add(employee_id)
        return problem_ids

    def _toggle_problem_rows_only(self, checked: bool) -> None:
        self._show_problem_rows_only = checked
        self.reload_table()

    def _toggle_problem_panel(self, expanded: bool) -> None:
        self._problem_panel_widget.setVisible(expanded)
        if expanded:
            self._toggle_problem_panel_button.setText("▼")
            self._toggle_problem_panel_button.setToolTip(
                "Згорнути панель проблем (Ctrl+P)"
            )
            self._toggle_problem_panel_button.setMinimumHeight(20)
            self._toggle_problem_panel_button.setMaximumHeight(20)
            self._toggle_problem_panel_button.setFixedWidth(28)
        else:
            self._toggle_problem_panel_button.setText("▶")
            self._toggle_problem_panel_button.setToolTip(
                "Показати панель проблем (Ctrl+P)"
            )
            self._toggle_problem_panel_button.setMinimumHeight(60)
            self._toggle_problem_panel_button.setMaximumHeight(16777215)
            self._toggle_problem_panel_button.setFixedWidth(28)
        self._adjust_schedule_table_widths()
        self._sync_schedule_table_height()

    def _toggle_problem_panel_shortcut(self) -> None:
        self._toggle_problem_panel_button.toggle()
