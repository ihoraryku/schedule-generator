from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import logging

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional dependency during migration
    yaml = None

logger = logging.getLogger(__name__)


DEFAULT_PROJECT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "Генератор графіків АСКУЕ",
        "language": "uk",
    },
    "archive": {
        "path": "./Архів графіків роботи",
        "canonical_codes": ["Р", "Д", "В", "О"],
    },
    "archive_analysis": {
        "daily_duty_per_day": 2,
        "daily_regular_per_day_min": 0,
        "daily_regular_per_day_max": 1,
        "work_run_min": 1,
        "work_run_max_observed": 9,
        "off_run_min": 1,
        "off_run_max_observed": 9,
        "notes": [
            "Архів 2025 містить старі коди 8 і 5-3.",
            "Архів 2026 переходить на коди Р, Д, В, О.",
            "Щодня спостерігаються рівно 2 чергування.",
        ],
    },
    "document": {
        "company_name": 'ТОВ "Компанія АСКУЕ"',
        "director_title": "Заступник директора",
        "director_name": "ПІБ керівника",
        "department_name": "інженерів АСКУЕ",
        "schedule_title": "Графік роботи інженерів АСКУЕ",
    },
    "calendar": {
        "martial_law": True,
    },
    "shifts": {
        "aliases": {
            "8": "Р",
            "5-3": "Д",
            "Ч": "Д",
            "Д": "Д",
            "Р": "Р",
            "В": "В",
            "О": "О",
            "O": "О",
        },
        "definitions": {
            "Р": {"label": "Робочий день (8)", "hours": 8, "color": "#AEC6E8"},
            "Д": {"label": "Чергування (5-3)", "hours": 8, "color": "#FFF3B0"},
            "В": {"label": "Вихідний", "hours": 0, "color": "#D9D9D9"},
            "О": {"label": "Відпустка", "hours": 0, "color": "#FFD580"},
        },
    },
    "generation": {
        "target_duty_per_day": 2,
        "daily_regular_per_day_min": 0,
        "daily_regular_per_day_max": 1,
        "weekday_regular_target": 1,
        "special_day_regular_target": 0,
        "month_start_full_staff_days": 4,
        "month_start_regular_per_day": 1,
        "max_consecutive_work_days": 7,
        "hard_max_consecutive_work_days": 9,
        "max_consecutive_duty_days": 5,
        "max_vacation_overlap": 1,
        "work_days_tolerance": 1,
        "use_auto_norm": True,
        "weekend_pairing": True,
        "weekend_auto_regular_allowed": False,
        "scoring": {
            "split_ch_duty": 0,
            "split_ch_regular": 40,
            "split_ch_off": 8,
            "full_r_regular": -22,
            "full_r_duty": 60,
            "full_r_off": 8,
            "mixed_regular": -14,
            "mixed_duty": 4,
            "mixed_off": 6,
            "mixed_weekday_duty": 35,
            "mixed_weekday_regular": -20,
            "busy_start_split_ch_non_duty": 14,
            "busy_start_full_r_non_regular": 18,
            "busy_start_mixed_non_regular": 16,
            "special_day_regular": 25,
            "work_deficit": 8,
            "min_deficit": 12,
            "off_work_deficit": 4,
            "off_min_deficit": 10,
            "duty_deficit": 6,
            "split_ch_duty_deficit": 4,
            "desired_shift_match": -18,
            "desired_shift_mismatch": 7,
            "streak_continue": -6,
            "streak_break_to_off": 3,
            "streak_start_after_off": 1,
            "work_streak_near_max": 25,
            "duty_streak_near_max": 8,
            "locked_by_wish": -40,
            "locked_by_rule": -16,
            "weekend_pairing": -30,
            "split_ch_duty_streak_continue": 8,
            "require_work_streak_break": -30,
        },
    },
    "export": {
        "default_dir": "./exports",
        "template": "archive_2026",
        "excel": {
            "sheet_title_mode": "month-year",
            "font_name": "Arial Cyr",
            "title_font_size": 14,
            "base_font_size": 12,
        },
        "pdf": {
            "page_size": "A4",
            "orientation": "landscape",
        },
    },
    "ui": {
        "editable_shift_values": ["", "Р", "Д", "В", "О"],
    },
    "logging": {
        "level": "DEBUG",
        "file": "logs/app.log",
        "max_bytes": 5242880,
        "backup_count": 3,
        "console_level": "INFO",
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    },
}


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _stringify_setting(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _read_project_config_file(config_path: Path) -> dict[str, Any] | None:
    if not config_path.exists():
        return None
    if config_path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    else:
        return None
    if not isinstance(data, dict):
        return None
    return data


def load_project_config(project_root: Path) -> dict[str, Any]:
    root = Path(project_root)
    for filename in ("config.yaml", "config.yml"):
        data = _read_project_config_file(root / filename)
        if data is not None:
            return _deep_merge(DEFAULT_PROJECT_CONFIG, data)
    return deepcopy(DEFAULT_PROJECT_CONFIG)


def project_settings_overrides(config: dict[str, Any]) -> dict[str, str]:
    document = config.get("document", {})
    generation = config.get("generation", {})
    export = config.get("export", {})
    calendar = config.get("calendar", {})
    scoring = generation.get("scoring", DEFAULT_PROJECT_CONFIG["generation"]["scoring"])
    return {
        "company_name": _stringify_setting(
            document.get(
                "company_name", DEFAULT_PROJECT_CONFIG["document"]["company_name"]
            )
        ),
        "director_title": _stringify_setting(
            document.get(
                "director_title", DEFAULT_PROJECT_CONFIG["document"]["director_title"]
            )
        ),
        "director_name": _stringify_setting(
            document.get(
                "director_name", DEFAULT_PROJECT_CONFIG["document"]["director_name"]
            )
        ),
        "department_name": _stringify_setting(
            document.get(
                "department_name", DEFAULT_PROJECT_CONFIG["document"]["department_name"]
            )
        ),
        "schedule_title": _stringify_setting(
            document.get(
                "schedule_title", DEFAULT_PROJECT_CONFIG["document"]["schedule_title"]
            )
        ),
        "daily_shift_d_count": _stringify_setting(
            generation.get(
                "target_duty_per_day",
                DEFAULT_PROJECT_CONFIG["generation"]["target_duty_per_day"],
            )
        ),
        "daily_shift_ch_count": _stringify_setting(
            generation.get(
                "target_duty_per_day",
                DEFAULT_PROJECT_CONFIG["generation"]["target_duty_per_day"],
            )
        ),
        "daily_regular_per_day_min": _stringify_setting(
            generation.get(
                "daily_regular_per_day_min",
                DEFAULT_PROJECT_CONFIG["generation"]["daily_regular_per_day_min"],
            )
        ),
        "max_regular_per_day": _stringify_setting(
            generation.get(
                "daily_regular_per_day_max",
                DEFAULT_PROJECT_CONFIG["generation"]["daily_regular_per_day_max"],
            )
        ),
        "weekday_regular_target": _stringify_setting(
            generation.get(
                "weekday_regular_target",
                DEFAULT_PROJECT_CONFIG["generation"]["weekday_regular_target"],
            )
        ),
        "special_day_regular_target": _stringify_setting(
            generation.get(
                "special_day_regular_target",
                DEFAULT_PROJECT_CONFIG["generation"]["special_day_regular_target"],
            )
        ),
        "month_start_full_staff_days": _stringify_setting(
            generation.get(
                "month_start_full_staff_days",
                DEFAULT_PROJECT_CONFIG["generation"]["month_start_full_staff_days"],
            )
        ),
        "month_start_regular_per_day": _stringify_setting(
            generation.get(
                "month_start_regular_per_day",
                DEFAULT_PROJECT_CONFIG["generation"]["month_start_regular_per_day"],
            )
        ),
        "max_consecutive_work_days": _stringify_setting(
            generation.get(
                "max_consecutive_work_days",
                DEFAULT_PROJECT_CONFIG["generation"]["max_consecutive_work_days"],
            )
        ),
        "hard_max_consecutive_work_days": _stringify_setting(
            generation.get(
                "hard_max_consecutive_work_days",
                DEFAULT_PROJECT_CONFIG["generation"]["hard_max_consecutive_work_days"],
            )
        ),
        "max_consecutive_duty_days": _stringify_setting(
            generation.get(
                "max_consecutive_duty_days",
                DEFAULT_PROJECT_CONFIG["generation"]["max_consecutive_duty_days"],
            )
        ),
        "max_vacation_overlap": _stringify_setting(
            generation.get(
                "max_vacation_overlap",
                DEFAULT_PROJECT_CONFIG["generation"]["max_vacation_overlap"],
            )
        ),
        "work_days_tolerance": _stringify_setting(
            generation.get(
                "work_days_tolerance",
                DEFAULT_PROJECT_CONFIG["generation"]["work_days_tolerance"],
            )
        ),
        "use_auto_norm": _stringify_setting(
            generation.get(
                "use_auto_norm", DEFAULT_PROJECT_CONFIG["generation"]["use_auto_norm"]
            )
        ),
        "weekend_pairing": _stringify_setting(
            generation.get(
                "weekend_pairing",
                DEFAULT_PROJECT_CONFIG["generation"]["weekend_pairing"],
            )
        ),
        "weekend_auto_regular_allowed": _stringify_setting(
            generation.get(
                "weekend_auto_regular_allowed",
                DEFAULT_PROJECT_CONFIG["generation"]["weekend_auto_regular_allowed"],
            )
        ),
        "martial_law": _stringify_setting(
            calendar.get(
                "martial_law", DEFAULT_PROJECT_CONFIG["calendar"]["martial_law"]
            )
        ),
        "export_dir": _stringify_setting(
            export.get("default_dir", DEFAULT_PROJECT_CONFIG["export"]["default_dir"])
        ),
        "year": _stringify_setting(0),
        "month": _stringify_setting(0),
    } | {f"scoring_{key}": _stringify_setting(value) for key, value in scoring.items()}


def get_logging_config(config: dict[str, Any]) -> dict[str, Any]:
    defaults = DEFAULT_PROJECT_CONFIG["logging"]
    return _deep_merge(defaults, config.get("logging", {}))
