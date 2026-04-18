from __future__ import annotations

import calendar
from pathlib import Path

import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.project_config import load_project_config
from schedule_askue.core.shift_codes import normalize_shift_code
from schedule_askue.db.models import Employee

logger = logging.getLogger(__name__)


class PdfExporter:
    MONTH_NAMES_UA = {
        1: "СІЧЕНЬ",
        2: "ЛЮТИЙ",
        3: "БЕРЕЗЕНЬ",
        4: "КВІТЕНЬ",
        5: "ТРАВЕНЬ",
        6: "ЧЕРВЕНЬ",
        7: "ЛИПЕНЬ",
        8: "СЕРПЕНЬ",
        9: "ВЕРЕСЕНЬ",
        10: "ЖОВТЕНЬ",
        11: "ЛИСТОПАД",
        12: "ГРУДЕНЬ",
    }
    WEEKDAYS = {0: "пн", 1: "вт", 2: "ср", 3: "чт", 4: "пт", 5: "сб", 6: "нд"}

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.config = load_project_config(self.project_root)
        self.shift_colors = {
            code: meta.get("color", "")
            for code, meta in self.config.get("shifts", {})
            .get("definitions", {})
            .items()
        }
        self.font_name = self._register_font()
        styles = getSampleStyleSheet()
        self.title_style = ParagraphStyle(
            "TitleUA",
            parent=styles["Title"],
            fontName=self.font_name,
            fontSize=14,
            leading=16,
            alignment=1,
        )
        self.normal_style = ParagraphStyle(
            "NormalUA",
            parent=styles["Normal"],
            fontName=self.font_name,
            fontSize=9,
            leading=11,
        )
        self.small_style = ParagraphStyle(
            "SmallUA",
            parent=styles["Normal"],
            fontName=self.font_name,
            fontSize=7,
            leading=8,
            alignment=1,
        )
        self.bold_style = ParagraphStyle(
            "BoldUA",
            parent=self.small_style,
            fontName=self.font_name + "-Bold" if self.font_name != "Helvetica" else "Helvetica-Bold",
            fontSize=9,
            leading=11,
            alignment=1,
        )

    def export_month(
        self,
        output_path: Path,
        year: int,
        month: int,
        employees: list[Employee],
        assignments: dict[int, dict[int, str]],
        settings: dict[str, str],
        calendar_ua: UkrainianCalendar,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=landscape(A4),
            leftMargin=8 * mm,
            rightMargin=8 * mm,
            topMargin=8 * mm,
            bottomMargin=8 * mm,
        )
        story = []
        month_info = calendar_ua.get_month_info(year, month)
        month_days = calendar.monthrange(year, month)[1]

        story.append(self._build_approval_block(settings))
        story.append(Spacer(1, 6 * mm))
        story.append(
            Paragraph(
                settings.get("schedule_title", "Графік роботи інженерів АСКУЕ"),
                self.title_style,
            )
        )
        story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(f"{self.MONTH_NAMES_UA[month]} {year} р.", self.normal_style)
        )
        story.append(Spacer(1, 4 * mm))
        story.append(
            self._build_schedule_table(month_days, employees, assignments, month_info)
        )
        story.append(Spacer(1, 4 * mm))

        # Примітка про чергування
        duty_note = self.config.get("export", {}).get(
            "duty_note",
            "Примітка: Д — Чергування, робота з перервою, вранці 5 год (08:00–13:00), вночі 3 год (22:00–01:00)",
        )
        story.append(Paragraph(duty_note, self.normal_style))
        story.append(Spacer(1, 3 * mm))

        # Умовні позначення
        story.append(self._build_legend_table())
        story.append(Spacer(1, 4 * mm))

        # Ознайомлені
        story.append(self._build_signatures_table(employees))

        doc.build(story)
        return output_path

    def _build_approval_block(self, settings: dict[str, str]) -> Table:
        rows = [
            ["", Paragraph('" ЗАТВЕРДЖУЮ"', self.normal_style)],
            [
                "",
                Paragraph(
                    settings.get("director_title", "Заступник директора"),
                    self.normal_style,
                ),
            ],
            ["", Paragraph(settings.get("company_name", ""), self.normal_style)],
            [
                "",
                Paragraph(
                    f"____________ {settings.get('director_name', '')}",
                    self.normal_style,
                ),
            ],
        ]
        table = Table(rows, colWidths=[190 * mm, 75 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), self.font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return table

    def _build_schedule_table(
        self,
        month_days: int,
        employees: list[Employee],
        assignments: dict[int, dict[int, str]],
        month_info: dict[int, object],
    ) -> Table:
        header_row = [Paragraph("ПІБ співробітника", self.small_style)]
        for day in range(1, month_days + 1):
            # Об'єднати число та день тижня в один рядок
            day_text = f"{day:02d} {self.WEEKDAYS[month_info[day].weekday]}"
            header_row.append(Paragraph(day_text, self.small_style))

        data = [header_row]
        for employee in employees:
            emp_days = assignments.get(employee.id or 0, {})
            row = [Paragraph(employee.short_name, self.normal_style)]
            for day in range(1, month_days + 1):
                shift_code = normalize_shift_code(emp_days.get(day, ""))
                is_weekend = month_info[day].is_weekend
                
                # Вибрати стиль залежно від коду та вихідного дня
                if shift_code == "Д":
                    # Жирний шрифт для "Д"
                    cell_style = self.bold_style
                elif is_weekend and shift_code:
                    # Червоний колір для вихідних
                    weekend_style = ParagraphStyle(
                        'weekend_cell',
                        parent=self.small_style,
                        textColor=colors.HexColor("#C91C23")
                    )
                    cell_style = weekend_style
                else:
                    cell_style = self.small_style
                
                row.append(Paragraph(shift_code, cell_style))
            
            data.append(row)

        col_widths = [34 * mm] + [7.2 * mm] * month_days
        table = Table(data, colWidths=col_widths, repeatRows=1)
        style = TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), self.font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F7F5EF")),
            ]
        )

        # Фарбування клітинок
        for row_idx, employee in enumerate(employees):
            emp_days = assignments.get(employee.id or 0, {})
            for day in range(1, month_days + 1):
                shift_code = normalize_shift_code(emp_days.get(day, ""))

                # Фон залежить від коду зміни
                color_hex = self.shift_colors.get(shift_code)
                if color_hex:
                    style.add(
                        "BACKGROUND",
                        (day, row_idx + 1),
                        (day, row_idx + 1),
                        colors.HexColor(color_hex),
                    )

        # Фарбування заголовків вихідних днів
        for day in range(1, month_days + 1):
            if month_info[day].is_weekend:
                # Фон червоний
                style.add("BACKGROUND", (day, 0), (day, 0), colors.HexColor("#FFCCCC"))
                # Текст червоний
                style.add("TEXTCOLOR", (day, 0), (day, 0), colors.HexColor("#C91C23"))
            else:
                # Звичайні дні - білий фон
                style.add("BACKGROUND", (day, 0), (day, 0), colors.HexColor("#FFFFFF"))

        table.setStyle(style)
        return table

    def _build_legend_table(self) -> Table:
        """Створити таблицю з умовними позначеннями."""
        # Отримати умовні позначення з конфігу
        legend = self.config.get("export", {}).get(
            "legend",
            [
                {"code": "Д", "description": "— Чергування"},
                {"code": "Р", "description": "— Робочий день"},
                {"code": "В", "description": "— Вихідний"},
                {"code": "О", "description": "— Відпустка"},
            ],
        )

        # Заголовок в одному рядку + порожній стовпець-заповнювач
        data = [[Paragraph("Умовні позначення:", self.normal_style), "", ""]]

        # Додати кожне позначення + порожній стовпець
        for item in legend:
            code = item.get("code", "")
            description = item.get("description", "")
            # Використовуємо Paragraph зі стилем центрування для правильного розміщення в кольоровій області
            data.append(
                [
                    Paragraph(code, self.bold_style),  # Жирний шрифт + центрування
                    Paragraph(description, self.normal_style),
                    ""  # Порожній стовпець-заповнювач
                ]
            )

        # Третій стовпець займає решту місця, штовхаючи таблицю вліво
        table = Table(data, colWidths=[10 * mm, 50 * mm, 200 * mm])

        # Стилі таблиці
        style = TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), self.font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),  # Коди по центру
                ("ALIGN", (1, 1), (1, -1), "LEFT"),    # Описи по лівому краю
                ("ALIGN", (0, 0), (0, 0), "LEFT"),     # Заголовок по лівому краю
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),    # Заголовок без відступу
                ("LEFTPADDING", (0, 1), (0, -1), 0),   # Коди без відступу для правильного центрування
                ("RIGHTPADDING", (0, 1), (0, -1), 0),  # Коди без відступу справа
                ("LEFTPADDING", (1, 0), (-1, -1), 0),  # Описи без відступу
                ("RIGHTPADDING", (1, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("SPAN", (0, 0), (2, 0)),  # Об'єднати заголовок на 3 стовпці
            ]
        )

        # Додати кольорові фони для кодів (починаючи з рядка 1, бо 0 - заголовок)
        for idx, item in enumerate(legend):
            code = item.get("code", "")
            color_hex = self.shift_colors.get(code)
            if color_hex:
                # idx + 1 бо перший рядок - заголовок
                style.add("BACKGROUND", (0, idx + 1), (0, idx + 1), colors.HexColor(color_hex))

        table.setStyle(style)
        return table

    def _build_signatures_table(self, employees: list[Employee]) -> Table:
        # Заголовок + порожній стовпець-заповнювач
        data = [[Paragraph("Ознайомлені:", self.normal_style), "", ""]]
        for employee in employees:
            data.append(
                [
                    Paragraph(employee.short_name, self.normal_style),
                    "_______________________",
                    ""  # Порожній стовпець-заповнювач
                ]
            )

        # Третій стовпець займає решту місця, штовхаючи таблицю вліво
        table = Table(data, colWidths=[50 * mm, 40 * mm, 170 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), self.font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (0, 0), (0, 0), "LEFT"),  # Заголовок по лівому краю
                    ("ALIGN", (0, 1), (0, -1), "LEFT"),  # Імена по лівому краю
                    ("ALIGN", (1, 1), (1, -1), "LEFT"),  # Підкреслення по лівому краю
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("SPAN", (0, 0), (2, 0)),  # Об'єднати заголовок на 3 стовпці
                ]
            )
        )
        return table

    def _display_shift(self, shift_code: str) -> str:
        return normalize_shift_code(shift_code)

    def _register_font(self) -> str:
        regular = Path(r"C:\Windows\Fonts\arial.ttf")
        bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
        
        if regular.exists():
            try:
                pdfmetrics.registerFont(TTFont("ArialUA", str(regular)))
                # Реєструємо жирний шрифт
                if bold.exists():
                    pdfmetrics.registerFont(TTFont("ArialUA-Bold", str(bold)))
                return "ArialUA"
            except Exception:
                pass
        return "Helvetica"
