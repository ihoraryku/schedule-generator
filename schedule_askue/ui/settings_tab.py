from __future__ import annotations

from typing import Callable

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from schedule_askue.db.repository import Repository

logger = logging.getLogger(__name__)


class SettingsTab(QWidget):
    def __init__(self, repository: Repository, on_saved: Callable[[], None]) -> None:
        super().__init__()
        self.repository = repository
        self.on_saved = on_saved

        self.company_name = QLineEdit(self)
        self.director_title = QLineEdit(self)
        self.director_name = QLineEdit(self)
        self.department_name = QLineEdit(self)
        self.schedule_title = QLineEdit(self)
        self.work_days_tolerance = QSpinBox(self)
        self.daily_shift_count = QSpinBox(self)
        self.max_consecutive_days = QSpinBox(self)
        self.max_consecutive_duty_days = QSpinBox(self)
        self.max_vacation_overlap = QSpinBox(self)
        self.weekday_regular_target = QSpinBox(self)
        self.special_day_regular_target = QSpinBox(self)
        self.month_start_full_staff_days = QSpinBox(self)
        self.month_start_regular_per_day = QSpinBox(self)
        self.weekend_pairing = QCheckBox(
            "Намагатися давати вихідні парами (субота+неділя)", self
        )
        self.weekend_auto_regular_allowed = QCheckBox(
            "Дозволити автоматично ставити Р на вихідні", self
        )
        self.martial_law = QCheckBox(
            "Воєнний стан: державні свята вважаються робочими", self
        )
        self.summary_label = QLabel(self)
        self.show_advanced = QCheckBox("Показати розширені налаштування", self)

        self._build_ui()
        self.load_settings()

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

        title = QLabel("Налаштування", self)
        title.setStyleSheet("font-size: 14px; font-weight: 700;")  # Зменшено
        help_label = QLabel(
            "Параметри генерації графіка та експорту.",
            self,
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #5B6573; font-size: 10px;")  # Зменшено
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "padding: 4px 6px; background: #F4F7FB; border: 1px solid #CFD9E6; border-radius: 4px; color: #465467; font-size: 10px;"  # Зменшено
        )
        layout.addWidget(title)
        layout.addWidget(help_label)
        layout.addWidget(self.summary_label)

        self.work_days_tolerance.setRange(0, 10)
        self.daily_shift_count.setRange(1, 10)
        self.max_consecutive_days.setRange(1, 14)
        self.max_consecutive_duty_days.setRange(1, 10)
        self.max_vacation_overlap.setRange(1, 10)
        self.weekday_regular_target.setRange(0, 4)
        self.special_day_regular_target.setRange(0, 4)
        self.month_start_full_staff_days.setRange(0, 10)
        self.month_start_regular_per_day.setRange(0, 4)

        self.company_name.setPlaceholderText('Наприклад: ТОВ "Іст Енерджі Інжиніринг"')
        self.company_name.setToolTip("Назва компанії для шапки документа та експорту.")
        self.director_title.setPlaceholderText("Наприклад: Заступник директора")
        self.director_title.setToolTip(
            "Посада підписанта, яка виводиться у шапці графіка."
        )
        self.director_name.setPlaceholderText("Наприклад: Ущенко С.Г.")
        self.director_name.setToolTip("ПІБ підписанта для шапки документа.")
        self.department_name.setPlaceholderText(
            "Наприклад: Відділ комерційного обліку електроенергії"
        )
        self.department_name.setToolTip(
            "Назва відділу або підрозділу, для якого формується графік."
        )
        self.schedule_title.setPlaceholderText(
            "Наприклад: Графік роботи інженерів АСКОЕ"
        )
        self.schedule_title.setToolTip(
            "Основний заголовок графіка в інтерфейсі та Excel."
        )
        self.work_days_tolerance.setToolTip(
            "Допустиме відхилення від цільової кількості робочих днів на місяць для одного працівника. 0 означає без запасу."
        )
        self.daily_shift_count.setToolTip(
            "Скільки змін типу 'Д' система намагатиметься ставити за день під час автоматичного розподілу."
        )
        self.max_consecutive_days.setToolTip(
            "Бажаний максимум робочих днів поспіль без вихідного. Генератор намагається дотримуватись цього значення."
        )
        self.max_consecutive_duty_days.setToolTip(
            "Бажаний максимум чергувань 'Д' підряд. Генератор намагається дотримуватись цього значення, але не завжди може виконати його жорстко."
        )
        self.max_vacation_overlap.setToolTip(
            "Скільки людей одночасно може бути у відпустці. Параметр використовується частково."
        )
        self.weekday_regular_target.setToolTip(
            "Бажана кількість робочих днів 'Р' на звичайний будній день (0-4)."
        )
        self.special_day_regular_target.setToolTip(
            "Бажана кількість робочих днів 'Р' на вихідний/святковий день (зазвичай 0)."
        )
        self.month_start_full_staff_days.setToolTip(
            "Перші N днів місяця з повним складом (2Р+2Д). Зазвичай 3-5 днів."
        )
        self.month_start_regular_per_day.setToolTip(
            "Кількість 'Р' на день у перші дні місяця (зазвичай 2)."
        )
        self.weekend_pairing.setToolTip(
            "Якщо увімкнено, генератор намагається давати вихідні парами (субота+неділя)."
        )
        self.weekend_auto_regular_allowed.setToolTip(
            "Якщо увімкнено, генератор може автоматично ставити 'Р' на вихідні дні."
        )
        self.martial_law.setToolTip(
            "Якщо увімкнено, державні свята не зменшують норму робочого часу автоматично."
        )

        document_group = QGroupBox("Документ", self)
        document_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; }"
        )  # Компактніше
        document_form = QFormLayout(document_group)
        document_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        document_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        document_form.setVerticalSpacing(3)  # Зменшено
        document_form.setHorizontalSpacing(6)  # Зменшено
        document_form.addRow("Компанія", self.company_name)
        document_form.addRow("Посада", self.director_title)
        document_form.addRow("ПІБ", self.director_name)
        document_form.addRow("Відділ", self.department_name)
        document_form.addRow("Заголовок", self.schedule_title)

        generation_group = QGroupBox("Генерація", self)
        generation_group.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 600; }"
        )
        generation_form = QFormLayout(generation_group)
        generation_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        generation_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        generation_form.setVerticalSpacing(3)  # Зменшено
        generation_form.setHorizontalSpacing(6)  # Зменшено
        generation_form.addRow("Допуск днів (±)", self.work_days_tolerance)
        generation_form.addRow("'Д' за день", self.daily_shift_count)
        generation_form.addRow("Макс днів підряд", self.max_consecutive_days)
        generation_form.addRow("Макс 'Д' підряд", self.max_consecutive_duty_days)
        generation_form.addRow("Макс у відпустці", self.max_vacation_overlap)

        # Advanced settings (initially hidden)
        self.advanced_rows = []
        row_idx = generation_form.rowCount()
        generation_form.addRow("'Р' будні", self.weekday_regular_target)
        self.advanced_rows.append(row_idx)
        row_idx += 1
        generation_form.addRow("'Р' вихідні", self.special_day_regular_target)
        self.advanced_rows.append(row_idx)
        row_idx += 1
        generation_form.addRow("Днів повний склад", self.month_start_full_staff_days)
        self.advanced_rows.append(row_idx)
        row_idx += 1
        generation_form.addRow("'Р' на старті", self.month_start_regular_per_day)
        self.advanced_rows.append(row_idx)

        self.generation_form = generation_form
        self._toggle_advanced_settings(False)

        calendar_group = QGroupBox("Календар", self)
        calendar_group.setStyleSheet("QGroupBox { font-size: 12px; font-weight: 600; }")
        calendar_form = QFormLayout(calendar_group)
        calendar_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        calendar_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        calendar_form.setVerticalSpacing(3)  # Зменшено
        calendar_form.setHorizontalSpacing(6)  # Зменшено
        calendar_form.addRow("", self.martial_law)
        calendar_form.addRow("", self.weekend_pairing)
        calendar_form.addRow("", self.weekend_auto_regular_allowed)

        self.show_advanced.setChecked(False)
        self.show_advanced.toggled.connect(self._toggle_advanced_settings)

        button_row = QHBoxLayout()
        save_button = QPushButton("Зберегти", self)
        save_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        save_button.setMinimumHeight(26)
        save_button.setMaximumHeight(26)
        save_button.setToolTip("Зберегти налаштування")
        save_button.clicked.connect(self.save_settings)
        button_row.addStretch()
        button_row.addWidget(save_button)

        layout.addWidget(document_group)
        layout.addWidget(generation_group)
        layout.addWidget(self.show_advanced)
        layout.addWidget(calendar_group)
        layout.addLayout(button_row)
        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def load_settings(self) -> None:
        settings = self.repository.get_settings()
        self.company_name.setText(settings.get("company_name", ""))
        self.director_title.setText(settings.get("director_title", ""))
        self.director_name.setText(settings.get("director_name", ""))
        self.department_name.setText(settings.get("department_name", ""))
        self.schedule_title.setText(settings.get("schedule_title", ""))
        self.work_days_tolerance.setValue(int(settings.get("work_days_tolerance", "1")))
        self.daily_shift_count.setValue(
            int(
                settings.get(
                    "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
                )
            )
        )
        self.max_consecutive_days.setValue(
            int(settings.get("max_consecutive_work_days", "6"))
        )
        self.max_consecutive_duty_days.setValue(
            int(settings.get("max_consecutive_duty_days", "5"))
        )
        self.max_vacation_overlap.setValue(
            int(settings.get("max_vacation_overlap", "1"))
        )
        self.weekday_regular_target.setValue(
            int(settings.get("weekday_regular_target", "1"))
        )
        self.special_day_regular_target.setValue(
            int(settings.get("special_day_regular_target", "0"))
        )
        self.month_start_full_staff_days.setValue(
            int(settings.get("month_start_full_staff_days", "4"))
        )
        self.month_start_regular_per_day.setValue(
            int(settings.get("month_start_regular_per_day", "2"))
        )
        self.martial_law.setChecked(settings.get("martial_law", "1") == "1")
        self.weekend_pairing.setChecked(settings.get("weekend_pairing", "1") == "1")
        self.weekend_auto_regular_allowed.setChecked(
            settings.get("weekend_auto_regular_allowed", "0") == "1"
        )
        self._refresh_summary()

    def save_settings(self) -> None:
        self.repository.save_settings(
            {
                "company_name": self.company_name.text().strip(),
                "director_title": self.director_title.text().strip(),
                "director_name": self.director_name.text().strip(),
                "department_name": self.department_name.text().strip(),
                "schedule_title": self.schedule_title.text().strip(),
                "work_days_tolerance": str(self.work_days_tolerance.value()),
                "daily_shift_d_count": str(self.daily_shift_count.value()),
                "daily_shift_ch_count": str(self.daily_shift_count.value()),
                "max_consecutive_work_days": str(self.max_consecutive_days.value()),
                "max_consecutive_duty_days": str(
                    self.max_consecutive_duty_days.value()
                ),
                "max_vacation_overlap": str(self.max_vacation_overlap.value()),
                "weekday_regular_target": str(self.weekday_regular_target.value()),
                "special_day_regular_target": str(
                    self.special_day_regular_target.value()
                ),
                "month_start_full_staff_days": str(
                    self.month_start_full_staff_days.value()
                ),
                "month_start_regular_per_day": str(
                    self.month_start_regular_per_day.value()
                ),
                "martial_law": "1" if self.martial_law.isChecked() else "0",
                "weekend_pairing": "1" if self.weekend_pairing.isChecked() else "0",
                "weekend_auto_regular_allowed": "1"
                if self.weekend_auto_regular_allowed.isChecked()
                else "0",
            }
        )
        self._refresh_summary()
        QMessageBox.information(self, "Налаштування", "Налаштування збережено.")
        self.on_saved()

    def _refresh_summary(self) -> None:
        self.summary_label.setText(
            "Поточний профіль: "
            f"{self.daily_shift_count.value()} змін 'Д' на день, "
            f"допуск ±{self.work_days_tolerance.value()} дн., "
            f"максимум {self.max_consecutive_days.value()} дн. підряд (робочих) / {self.max_consecutive_duty_days.value()} 'Д' підряд, "
            f"бажана кількість 'Р': {self.weekday_regular_target.value()} (будні) / {self.special_day_regular_target.value()} (вихідні), "
            f"старт місяця: {self.month_start_full_staff_days.value()} дн. з {self.month_start_regular_per_day.value()} 'Р', "
            f"воєнний стан: {'увімкнено' if self.martial_law.isChecked() else 'вимкнено'}, "
            f"парні вихідні: {'так' if self.weekend_pairing.isChecked() else 'ні'}."
        )

    def _toggle_advanced_settings(self, show: bool) -> None:
        if not hasattr(self, "generation_form"):
            return
        for row_idx in self.advanced_rows:
            label_item = self.generation_form.itemAt(
                row_idx, QFormLayout.ItemRole.LabelRole
            )
            field_item = self.generation_form.itemAt(
                row_idx, QFormLayout.ItemRole.FieldRole
            )
            if label_item and label_item.widget():
                label_item.widget().setVisible(show)
            if field_item and field_item.widget():
                field_item.widget().setVisible(show)
