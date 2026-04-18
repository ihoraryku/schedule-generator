from __future__ import annotations

CANONICAL_SHIFT_CODES = {"", "Р", "Д", "В", "О"}
WORK_SHIFT_CODES = {"Р", "Д"}

SHIFT_LABELS: dict[str, str] = {
    "": "Порожньо",
    "Р": "Робочий день (8)",
    "Д": "Чергування (8)",
    "В": "Вихідний",
    "О": "Відпустка",
}

SHIFT_ALIASES: dict[str, str] = {
    "": "",
    "Р": "Р",
    "8": "Р",
    "Д": "Д",
    "Ч": "Д",
    "5-3": "Д",
    "В": "В",
    "О": "О",
    "O": "О",
}


def normalize_shift_code(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return SHIFT_ALIASES.get(text, text)


def is_work_shift(value: str | None) -> bool:
    return normalize_shift_code(value) in WORK_SHIFT_CODES
