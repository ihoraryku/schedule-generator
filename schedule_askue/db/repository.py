from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.project_config import (
    load_project_config,
    project_settings_overrides,
)
from schedule_askue.core.shift_codes import normalize_shift_code
from schedule_askue.db.models import (
    DEFAULT_SETTINGS,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
    WorkNormCompensationAction,
    SAMPLE_EMPLOYEES,
    Employee,
    PersonalRule,
    Rule,
    Wish,
)

logger = logging.getLogger(__name__)


def _normalize_auto_width_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload

    is_nested_payload = any(isinstance(value, dict) for value in payload.values())
    normalized: dict[object, object] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized_key: object = key
            if isinstance(key, str):
                try:
                    normalized_key = int(key)
                except ValueError:
                    normalized_key = key
            normalized_value = _normalize_auto_width_payload(value)
            normalized[normalized_key] = normalized_value
            continue

        if is_nested_payload:
            normalized[key] = value
            continue

        try:
            normalized_key = int(key)
            normalized_value = int(value)
        except (TypeError, ValueError):
            continue
        normalized[normalized_key] = normalized_value

    return normalized


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    short_name TEXT NOT NULL,
                    shift_type TEXT NOT NULL DEFAULT 'mixed',
                    rate REAL NOT NULL DEFAULT 1.0,
                    position TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS wishes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    wish_type TEXT NOT NULL,
                    date_from INTEGER,
                    date_to INTEGER,
                    priority TEXT NOT NULL DEFAULT 'desired',
                    use_extra_day_off INTEGER NOT NULL DEFAULT 0,
                    comment TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );

                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_type TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'all',
                    year INTEGER,
                    month INTEGER,
                    day INTEGER,
                    params TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    description TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS personal_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    year INTEGER,
                    month INTEGER,
                    start_day INTEGER NOT NULL,
                    end_day INTEGER NOT NULL,
                    shift_code TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    description TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );

                CREATE TABLE IF NOT EXISTS extra_days_off_balance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    days_count INTEGER NOT NULL,
                    schedule_year INTEGER,
                    schedule_month INTEGER,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );

                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(year, month)
                );

                CREATE TABLE IF NOT EXISTS schedule_days (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id INTEGER NOT NULL,
                    employee_id INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    value TEXT NOT NULL,
                    is_manual INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(schedule_id) REFERENCES schedules(id),
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );

                CREATE TABLE IF NOT EXISTS planned_extra_days_off (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    planned_days INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(employee_id, year, month),
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );

                CREATE TABLE IF NOT EXISTS planned_workday_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    adjustment_days INTEGER NOT NULL DEFAULT 0,
                    source_year INTEGER,
                    source_month INTEGER,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(employee_id, year, month),
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );

                CREATE TABLE IF NOT EXISTS work_norm_compensation_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    days_count INTEGER NOT NULL,
                    source_year INTEGER NOT NULL,
                    source_month INTEGER NOT NULL,
                    target_year INTEGER,
                    target_month INTEGER,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(employee_id) REFERENCES employees(id)
                );
                """
            )
            self._migrate_schema(conn)
            self._seed_settings(conn)
            self._seed_employees(conn)
            self._migrate_settings_max_regular_per_day(conn)
            self._migrate_reset_shift_types(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        personal_rule_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(personal_rules)").fetchall()
        }
        if "year" not in personal_rule_columns:
            conn.execute("ALTER TABLE personal_rules ADD COLUMN year INTEGER")
        if "month" not in personal_rule_columns:
            conn.execute("ALTER TABLE personal_rules ADD COLUMN month INTEGER")
        if "description" not in personal_rule_columns:
            conn.execute(
                "ALTER TABLE personal_rules ADD COLUMN description TEXT NOT NULL DEFAULT ''"
            )
        if "priority" not in personal_rule_columns:
            conn.execute(
                "ALTER TABLE personal_rules ADD COLUMN priority INTEGER NOT NULL DEFAULT 100"
            )
        if "sort_order" not in personal_rule_columns:
            conn.execute(
                "ALTER TABLE personal_rules ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )

        rule_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(rules)").fetchall()
        }
        if "priority" not in rule_columns:
            conn.execute(
                "ALTER TABLE rules ADD COLUMN priority INTEGER NOT NULL DEFAULT 100"
            )
        if "sort_order" not in rule_columns:
            conn.execute(
                "ALTER TABLE rules ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )

        self._seed_missing_sort_order(conn, "rules")
        self._seed_missing_sort_order(conn, "personal_rules")
        self._seed_missing_sort_order(conn, "employees")

        planned_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(planned_extra_days_off)"
            ).fetchall()
        }
        if planned_columns and "note" not in planned_columns:
            conn.execute(
                "ALTER TABLE planned_extra_days_off ADD COLUMN note TEXT NOT NULL DEFAULT ''"
            )

        adjustment_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(planned_workday_adjustments)"
            ).fetchall()
        }
        if adjustment_columns and "source_year" not in adjustment_columns:
            conn.execute(
                "ALTER TABLE planned_workday_adjustments ADD COLUMN source_year INTEGER"
            )
        if adjustment_columns and "source_month" not in adjustment_columns:
            conn.execute(
                "ALTER TABLE planned_workday_adjustments ADD COLUMN source_month INTEGER"
            )
        if adjustment_columns and "note" not in adjustment_columns:
            conn.execute(
                "ALTER TABLE planned_workday_adjustments ADD COLUMN note TEXT NOT NULL DEFAULT ''"
            )

        self._migrate_settings_max_regular_per_day(conn)

    def _migrate_settings_max_regular_per_day(self, conn: sqlite3.Connection) -> None:
        settings_migrations = {
            "max_regular_per_day": ("2", "1"),
            "month_start_regular_per_day": ("2", "1"),
        }
        for key, (old_val, new_val) in settings_migrations.items():
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if row and row["value"] == old_val:
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    (new_val, key),
                )

    def _migrate_reset_shift_types(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'shift_types_reset_v2'"
        ).fetchone()
        if row:
            return
        conn.execute(
            "UPDATE employees SET shift_type = 'mixed' WHERE shift_type = 'split_CH'"
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('shift_types_reset_v2', '1')"
        )

    def _seed_missing_sort_order(
        self, conn: sqlite3.Connection, table_name: str
    ) -> None:
        rows = conn.execute(
            f"SELECT id, sort_order FROM {table_name} ORDER BY COALESCE(sort_order, 0), id"
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            if int(row["sort_order"] or 0) > 0:
                continue
            conn.execute(
                f"UPDATE {table_name} SET sort_order = ? WHERE id = ?",
                (index, row["id"]),
            )

    def _seed_settings(self, conn: sqlite3.Connection) -> None:
        seeded_settings = dict(DEFAULT_SETTINGS)
        seeded_settings.update(
            project_settings_overrides(load_project_config(self.db_path.parent))
        )
        for key, value in seeded_settings.items():
            conn.execute(
                """
                INSERT INTO settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (key, value),
            )

    def _seed_employees(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT COUNT(*) AS count FROM employees").fetchone()
        if row["count"] > 0:
            return

        conn.executemany(
            """
            INSERT INTO employees(
                full_name, short_name, shift_type, rate, position, is_active, sort_order
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    employee.full_name,
                    employee.short_name,
                    employee.shift_type,
                    employee.rate,
                    employee.position,
                    int(employee.is_active),
                    employee.sort_order,
                )
                for employee in SAMPLE_EMPLOYEES
            ],
        )

    def list_employees(self, include_archived: bool = False) -> list[Employee]:
        query = """
            SELECT id, full_name, short_name, shift_type, rate, position, is_active, sort_order
            FROM employees
        """
        if not include_archived:
            query += " WHERE is_active = 1"
        query += " ORDER BY sort_order, id"

        with self.connect() as conn:
            rows = conn.execute(query).fetchall()

        return [
            Employee(
                id=row["id"],
                full_name=row["full_name"],
                short_name=row["short_name"],
                shift_type=row["shift_type"],
                rate=row["rate"],
                position=row["position"],
                is_active=bool(row["is_active"]),
                sort_order=row["sort_order"],
            )
            for row in rows
        ]

    def create_employee(self, employee: Employee) -> int:
        with self.connect() as conn:
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM employees"
            ).fetchone()["next_order"]
            cursor = conn.execute(
                """
                INSERT INTO employees(
                    full_name, short_name, shift_type, rate, position, is_active, sort_order
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee.full_name,
                    employee.short_name,
                    employee.shift_type,
                    employee.rate,
                    employee.position,
                    int(employee.is_active),
                    next_order,
                ),
            )
            return int(cursor.lastrowid)

    def update_employee(self, employee: Employee) -> None:
        if employee.id is None:
            raise ValueError("Employee id is required for update")

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE employees
                SET full_name = ?, short_name = ?, shift_type = ?, rate = ?, position = ?, is_active = ?, sort_order = ?
                WHERE id = ?
                """,
                (
                    employee.full_name,
                    employee.short_name,
                    employee.shift_type,
                    employee.rate,
                    employee.position,
                    int(employee.is_active),
                    employee.sort_order,
                    employee.id,
                ),
            )

    def reorder_employees(self, employee_ids: list[int]) -> None:
        with self.connect() as conn:
            for sort_order, employee_id in enumerate(employee_ids, start=1):
                conn.execute(
                    "UPDATE employees SET sort_order = ? WHERE id = ?",
                    (sort_order, employee_id),
                )

    def archive_employee(self, employee_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE employees SET is_active = 0 WHERE id = ?", (employee_id,)
            )

    def list_wishes(self, year: int, month: int) -> list[Wish]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, employee_id, year, month, wish_type, date_from, date_to,
                       priority, use_extra_day_off, comment
                FROM wishes
                WHERE year = ? AND month = ?
                ORDER BY employee_id, date_from, id
                """,
                (year, month),
            ).fetchall()

        return [
            Wish(
                id=row["id"],
                employee_id=row["employee_id"],
                year=row["year"],
                month=row["month"],
                wish_type=row["wish_type"],
                date_from=row["date_from"],
                date_to=row["date_to"],
                priority=row["priority"],
                use_extra_day_off=bool(row["use_extra_day_off"]),
                comment=normalize_shift_code(row["comment"])
                if row["wish_type"] == "work_day"
                else row["comment"],
            )
            for row in rows
        ]

    def create_wish(self, wish: Wish) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO wishes(
                    employee_id, year, month, wish_type, date_from, date_to,
                    priority, use_extra_day_off, comment
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wish.employee_id,
                    wish.year,
                    wish.month,
                    wish.wish_type,
                    wish.date_from,
                    wish.date_to,
                    wish.priority,
                    int(wish.use_extra_day_off),
                    normalize_shift_code(wish.comment)
                    if wish.wish_type == "work_day"
                    else wish.comment,
                ),
            )
            return int(cursor.lastrowid)

    def delete_wish(self, wish_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM wishes WHERE id = ?", (wish_id,))

    def list_rules(
        self, year: int | None = None, month: int | None = None
    ) -> list[Rule]:
        query = """
            SELECT id, rule_type, scope, year, month, day, params, is_active, priority, sort_order, description
            FROM rules
        """
        params: list[object] = []
        if year is not None and month is not None:
            query += (
                " WHERE (year IS NULL AND month IS NULL) OR (year = ? AND month = ?)"
            )
            params.extend([year, month])
        query += " ORDER BY sort_order, id"

        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [
            Rule(
                id=row["id"],
                rule_type=row["rule_type"],
                scope=row["scope"],
                year=row["year"],
                month=row["month"],
                day=row["day"],
                params=row["params"],
                is_active=bool(row["is_active"]),
                priority=row["priority"],
                sort_order=row["sort_order"],
                description=row["description"],
            )
            for row in rows
        ]

    def create_rule(self, rule: Rule) -> int:
        with self.connect() as conn:
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM rules"
            ).fetchone()["next_order"]
            cursor = conn.execute(
                """
                INSERT INTO rules(rule_type, scope, year, month, day, params, is_active, priority, sort_order, description)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.rule_type,
                    rule.scope,
                    rule.year,
                    rule.month,
                    rule.day,
                    rule.params,
                    int(rule.is_active),
                    rule.priority,
                    next_order,
                    rule.description,
                ),
            )
            return int(cursor.lastrowid)

    def update_rule(self, rule: Rule) -> None:
        if rule.id is None:
            raise ValueError("Rule id is required for update")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE rules
                SET rule_type = ?, scope = ?, year = ?, month = ?, day = ?, params = ?, is_active = ?, priority = ?, sort_order = ?, description = ?
                WHERE id = ?
                """,
                (
                    rule.rule_type,
                    rule.scope,
                    rule.year,
                    rule.month,
                    rule.day,
                    rule.params,
                    int(rule.is_active),
                    rule.priority,
                    rule.sort_order,
                    rule.description,
                    rule.id,
                ),
            )

    def delete_rule(self, rule_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))

    def reorder_rules(self, rule_ids: list[int]) -> None:
        with self.connect() as conn:
            for sort_order, rule_id in enumerate(rule_ids, start=1):
                conn.execute(
                    "UPDATE rules SET sort_order = ? WHERE id = ?",
                    (sort_order, rule_id),
                )

    def set_rule_sort_order(self, rule_id: int, sort_order: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE rules SET sort_order = ? WHERE id = ?",
                (sort_order, rule_id),
            )

    def list_personal_rules(
        self,
        year: int | None = None,
        month: int | None = None,
        employee_id: int | None = None,
    ) -> list[PersonalRule]:
        query = """
            SELECT id, employee_id, year, month, start_day, end_day, shift_code, rule_type, is_active, priority, sort_order, description
            FROM personal_rules
        """
        conditions: list[str] = []
        params: list[object] = []
        if year is not None and month is not None:
            conditions.append(
                "((year IS NULL AND month IS NULL) OR (year = ? AND month = ?))"
            )
            params.extend([year, month])
        if employee_id is not None:
            conditions.append("employee_id = ?")
            params.append(employee_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY sort_order, id"

        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [
            PersonalRule(
                id=row["id"],
                employee_id=row["employee_id"],
                year=row["year"],
                month=row["month"],
                start_day=row["start_day"],
                end_day=row["end_day"],
                shift_code=normalize_shift_code(row["shift_code"]),
                rule_type=row["rule_type"],
                is_active=bool(row["is_active"]),
                priority=row["priority"],
                sort_order=row["sort_order"],
                description=row["description"],
            )
            for row in rows
        ]

    def create_personal_rule(self, rule: PersonalRule) -> int:
        with self.connect() as conn:
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM personal_rules"
            ).fetchone()["next_order"]
            cursor = conn.execute(
                """
                INSERT INTO personal_rules(employee_id, year, month, start_day, end_day, shift_code, rule_type, is_active, priority, sort_order, description)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.employee_id,
                    rule.year,
                    rule.month,
                    rule.start_day,
                    rule.end_day,
                    normalize_shift_code(rule.shift_code),
                    rule.rule_type,
                    int(rule.is_active),
                    rule.priority,
                    next_order,
                    rule.description,
                ),
            )
            return int(cursor.lastrowid)

    def update_personal_rule(self, rule: PersonalRule) -> None:
        if rule.id is None:
            raise ValueError("PersonalRule id is required for update")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE personal_rules
                SET employee_id = ?, year = ?, month = ?, start_day = ?, end_day = ?, shift_code = ?, rule_type = ?, is_active = ?, priority = ?, sort_order = ?, description = ?
                WHERE id = ?
                """,
                (
                    rule.employee_id,
                    rule.year,
                    rule.month,
                    rule.start_day,
                    rule.end_day,
                    normalize_shift_code(rule.shift_code),
                    rule.rule_type,
                    int(rule.is_active),
                    rule.priority,
                    rule.sort_order,
                    rule.description,
                    rule.id,
                ),
            )

    def delete_personal_rule(self, rule_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM personal_rules WHERE id = ?", (rule_id,))

    def reorder_personal_rules(self, rule_ids: list[int]) -> None:
        with self.connect() as conn:
            for sort_order, rule_id in enumerate(rule_ids, start=1):
                conn.execute(
                    "UPDATE personal_rules SET sort_order = ? WHERE id = ?",
                    (sort_order, rule_id),
                )

    def set_personal_rule_sort_order(self, rule_id: int, sort_order: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE personal_rules SET sort_order = ? WHERE id = ?",
                (sort_order, rule_id),
            )

    def get_settings(self) -> dict[str, str]:
        settings = dict(DEFAULT_SETTINGS)
        config_defaults = project_settings_overrides(
            load_project_config(self.db_path.parent)
        )
        settings.update(config_defaults)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings ORDER BY key"
            ).fetchall()
        for row in rows:
            key = row["key"]
            value = row["value"]
            # Allow config.yaml to override untouched legacy seed values from SQLite.
            if (
                key in config_defaults
                and value == DEFAULT_SETTINGS.get(key)
                and config_defaults[key] != value
            ):
                continue
            settings[key] = value
        if "daily_shift_d_count" not in settings and "daily_shift_ch_count" in settings:
            settings["daily_shift_d_count"] = settings["daily_shift_ch_count"]
        if "daily_shift_ch_count" not in settings and "daily_shift_d_count" in settings:
            settings["daily_shift_ch_count"] = settings["daily_shift_d_count"]
        return settings

    def save_settings(self, settings: dict[str, str]) -> None:
        payload = dict(settings)
        if "daily_shift_d_count" in payload and "daily_shift_ch_count" not in payload:
            payload["daily_shift_ch_count"] = payload["daily_shift_d_count"]
        if "daily_shift_ch_count" in payload and "daily_shift_d_count" not in payload:
            payload["daily_shift_d_count"] = payload["daily_shift_ch_count"]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                list(payload.items()),
            )

    def save_table_column_widths(self, table_name: str, widths: dict[int, int]) -> None:
        """Зберегти ширину колонок таблиці в налаштування."""
        import json

        key = f"table_width_{table_name}"
        value = json.dumps(widths)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_table_column_widths(self, table_name: str) -> dict[int, int] | None:
        """Отримати збережену ширину колонок таблиці."""
        import json

        key = f"table_width_{table_name}"
        settings = self.get_settings()
        value = settings.get(key)
        if value:
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def auto_save_table_widths(
        self,
        tab_name: str,
        table_name: str,
        widths: dict[int, int] | dict[str, dict[int, int]],
    ) -> None:
        """Автоматично зберегти ширину колонок без повідомлення."""
        import json

        key = f"auto_width_{tab_name}_{table_name}"
        value = json.dumps(widths)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_auto_table_widths(
        self, tab_name: str, table_name: str
    ) -> dict[int, int] | dict[str, dict[int, int]] | None:
        """Отримати автоматично зберегену ширину колонок."""
        import json

        key = f"auto_width_{tab_name}_{table_name}"
        settings = self.get_settings()
        value = settings.get(key)
        if value:
            try:
                payload = json.loads(value)
                normalized = _normalize_auto_width_payload(payload)
                if isinstance(normalized, dict):
                    return normalized
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def get_extra_day_off_balances(self) -> dict[int, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT employee_id, COALESCE(SUM(days_count), 0) AS balance
                FROM extra_days_off_balance
                GROUP BY employee_id
                """
            ).fetchall()
        return {row["employee_id"]: int(row["balance"]) for row in rows}

    def list_extra_day_off_operations(
        self,
        schedule_year: int | None = None,
        schedule_month: int | None = None,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT id, employee_id, action, days_count, schedule_year, schedule_month, description, created_at
            FROM extra_days_off_balance
        """
        params: list[object] = []
        if schedule_year is not None and schedule_month is not None:
            query += " WHERE schedule_year = ? AND schedule_month = ?"
            params.extend([schedule_year, schedule_month])
        query += " ORDER BY created_at DESC, id DESC"

        with self.connect() as conn:
            return conn.execute(query, tuple(params)).fetchall()

    def get_extra_day_off_usage_totals(
        self, schedule_year: int, schedule_month: int
    ) -> dict[int, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT employee_id, COALESCE(SUM(-days_count), 0) AS used_days
                FROM extra_days_off_balance
                WHERE schedule_year = ?
                  AND schedule_month = ?
                  AND days_count < 0
                GROUP BY employee_id
                """,
                (schedule_year, schedule_month),
            ).fetchall()
        return {int(row["employee_id"]): int(row["used_days"]) for row in rows}

    def calculate_planned_extra_day_off_usage(
        self,
        year: int,
        month: int,
        assignments: dict[int, dict[int, str]],
    ) -> dict[int, int]:
        planned_map = self.get_planned_extra_days_off_map(year, month)
        if not planned_map:
            return {}

        settings = self.get_settings()
        calendar = UkrainianCalendar(
            martial_law=settings.get("martial_law", "1") == "1"
        )
        month_info = calendar.get_month_info(year, month)
        return self._calculate_planned_extra_day_off_usage(
            assignments, planned_map, month_info
        )

    def create_extra_day_off_operation(
        self,
        *,
        employee_id: int,
        action: str,
        days_count: int,
        schedule_year: int | None,
        schedule_month: int | None,
        description: str = "",
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO extra_days_off_balance(
                    employee_id, action, days_count, schedule_year, schedule_month, description
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    action,
                    days_count,
                    schedule_year,
                    schedule_month,
                    description,
                ),
            )
            return int(cursor.lastrowid)

    def delete_extra_day_off_operation(self, operation_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM extra_days_off_balance WHERE id = ?", (operation_id,)
            )

    def list_planned_extra_days_off(
        self, year: int, month: int
    ) -> list[PlannedExtraDayOff]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, employee_id, year, month, planned_days, note
                FROM planned_extra_days_off
                WHERE year = ? AND month = ?
                ORDER BY employee_id, id
                """,
                (year, month),
            ).fetchall()

        return [
            PlannedExtraDayOff(
                id=row["id"],
                employee_id=row["employee_id"],
                year=row["year"],
                month=row["month"],
                planned_days=int(row["planned_days"]),
                note=row["note"],
            )
            for row in rows
        ]

    def get_planned_extra_days_off_map(
        self, year: int, month: int
    ) -> dict[int, PlannedExtraDayOff]:
        return {
            item.employee_id: item
            for item in self.list_planned_extra_days_off(year, month)
        }

    def save_planned_extra_days_off(
        self,
        *,
        employee_id: int,
        year: int,
        month: int,
        planned_days: int,
        note: str = "",
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO planned_extra_days_off(employee_id, year, month, planned_days, note)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, year, month)
                DO UPDATE SET planned_days = excluded.planned_days,
                              note = excluded.note,
                              updated_at = CURRENT_TIMESTAMP
                """,
                (employee_id, year, month, planned_days, note),
            )
            row = conn.execute(
                """
                SELECT id
                FROM planned_extra_days_off
                WHERE employee_id = ? AND year = ? AND month = ?
                """,
                (employee_id, year, month),
            ).fetchone()
            if row is None:
                raise RuntimeError("Не вдалося зберегти план додаткових вихідних")
            return int(row["id"])

    def delete_planned_extra_days_off(
        self, employee_id: int, year: int, month: int
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM planned_extra_days_off WHERE employee_id = ? AND year = ? AND month = ?",
                (employee_id, year, month),
            )

    def list_planned_workday_adjustments(
        self, year: int, month: int
    ) -> list[PlannedWorkdayAdjustment]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, employee_id, year, month, adjustment_days, source_year, source_month, note
                FROM planned_workday_adjustments
                WHERE year = ? AND month = ?
                ORDER BY employee_id, id
                """,
                (year, month),
            ).fetchall()

        return [
            PlannedWorkdayAdjustment(
                id=row["id"],
                employee_id=row["employee_id"],
                year=row["year"],
                month=row["month"],
                adjustment_days=int(row["adjustment_days"]),
                source_year=row["source_year"],
                source_month=row["source_month"],
                note=row["note"],
            )
            for row in rows
        ]

    def get_planned_workday_adjustments_map(
        self, year: int, month: int
    ) -> dict[int, PlannedWorkdayAdjustment]:
        return {
            item.employee_id: item
            for item in self.list_planned_workday_adjustments(year, month)
        }

    def save_planned_workday_adjustment(
        self,
        *,
        employee_id: int,
        year: int,
        month: int,
        adjustment_days: int,
        source_year: int | None = None,
        source_month: int | None = None,
        note: str = "",
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO planned_workday_adjustments(
                    employee_id, year, month, adjustment_days, source_year, source_month, note
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, year, month)
                DO UPDATE SET adjustment_days = excluded.adjustment_days,
                              source_year = excluded.source_year,
                              source_month = excluded.source_month,
                              note = excluded.note,
                              updated_at = CURRENT_TIMESTAMP
                """,
                (
                    employee_id,
                    year,
                    month,
                    adjustment_days,
                    source_year,
                    source_month,
                    note,
                ),
            )
            row = conn.execute(
                """
                SELECT id
                FROM planned_workday_adjustments
                WHERE employee_id = ? AND year = ? AND month = ?
                """,
                (employee_id, year, month),
            ).fetchone()
            if row is None:
                raise RuntimeError("Не вдалося зберегти план робочих днів")
            return int(row["id"])

    def delete_planned_workday_adjustment(
        self, employee_id: int, year: int, month: int
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM planned_workday_adjustments WHERE employee_id = ? AND year = ? AND month = ?",
                (employee_id, year, month),
            )

    def list_work_norm_compensation_actions(
        self,
        source_year: int | None = None,
        source_month: int | None = None,
    ) -> list[WorkNormCompensationAction]:
        query = """
            SELECT id, employee_id, action_type, days_count, source_year, source_month,
                   target_year, target_month, description, created_at
            FROM work_norm_compensation_actions
        """
        params: list[object] = []
        if source_year is not None and source_month is not None:
            query += " WHERE source_year = ? AND source_month = ?"
            params.extend([source_year, source_month])
        query += " ORDER BY created_at DESC, id DESC"

        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [
            WorkNormCompensationAction(
                id=row["id"],
                employee_id=row["employee_id"],
                action_type=row["action_type"],
                days_count=int(row["days_count"]),
                source_year=int(row["source_year"]),
                source_month=int(row["source_month"]),
                target_year=row["target_year"],
                target_month=row["target_month"],
                description=row["description"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_work_norm_compensation_action(
        self,
        *,
        employee_id: int,
        action_type: str,
        days_count: int,
        source_year: int,
        source_month: int,
        target_year: int | None = None,
        target_month: int | None = None,
        description: str = "",
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO work_norm_compensation_actions(
                    employee_id, action_type, days_count, source_year, source_month,
                    target_year, target_month, description
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    action_type,
                    days_count,
                    source_year,
                    source_month,
                    target_year,
                    target_month,
                    description,
                ),
            )
            return int(cursor.lastrowid)

    def delete_work_norm_compensation_action(self, action_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM work_norm_compensation_actions WHERE id = ?",
                (action_id,),
            )

    def get_schedule(self, year: int, month: int) -> dict[int, dict[int, str]]:
        with self.connect() as conn:
            schedule = conn.execute(
                "SELECT id FROM schedules WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()
            if schedule is None:
                return {}

            rows = conn.execute(
                """
                SELECT employee_id, day, value
                FROM schedule_days
                WHERE schedule_id = ?
                ORDER BY employee_id, day
                """,
                (schedule["id"],),
            ).fetchall()

        result: dict[int, dict[int, str]] = {}
        for row in rows:
            result.setdefault(row["employee_id"], {})[row["day"]] = (
                normalize_shift_code(row["value"])
            )
        return result

    def get_schedule_bundle(
        self, year: int, month: int
    ) -> tuple[
        dict[int, dict[int, str]], dict[int, dict[int, bool]], dict[int, dict[int, str]]
    ]:
        with self.connect() as conn:
            schedule = conn.execute(
                "SELECT id, notes FROM schedules WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()
            if schedule is None:
                return {}, {}, {}

            rows = conn.execute(
                """
                SELECT employee_id, day, value, is_manual
                FROM schedule_days
                WHERE schedule_id = ?
                ORDER BY employee_id, day
                """,
                (schedule["id"],),
            ).fetchall()

        assignments: dict[int, dict[int, str]] = {}
        manual_flags: dict[int, dict[int, bool]] = {}
        for row in rows:
            assignments.setdefault(row["employee_id"], {})[row["day"]] = (
                normalize_shift_code(row["value"])
            )
            manual_flags.setdefault(row["employee_id"], {})[row["day"]] = bool(
                row["is_manual"]
            )

        auto_assignments: dict[int, dict[int, str]] = {}
        notes = schedule["notes"] or ""
        if notes:
            import json

            try:
                payload = json.loads(notes)
            except json.JSONDecodeError:
                payload = {}
            raw_auto = (
                payload.get("auto_assignments", {}) if isinstance(payload, dict) else {}
            )
            auto_assignments = {
                int(employee_id): {
                    int(day): normalize_shift_code(value) for day, value in days.items()
                }
                for employee_id, days in raw_auto.items()
            }
        return assignments, manual_flags, auto_assignments

    def get_previous_month_tail(
        self,
        year: int,
        month: int,
        *,
        days_back: int = 7,
    ) -> dict[int, dict[int, str]]:
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        schedule = self.get_schedule(prev_year, prev_month)
        if not schedule:
            return {}

        result: dict[int, dict[int, str]] = {}
        for employee_id, days in schedule.items():
            ordered_days = sorted(days)
            tail_days = ordered_days[-days_back:]
            if tail_days:
                result[employee_id] = {day: days[day] for day in tail_days}
        return result

    def save_schedule(
        self,
        year: int,
        month: int,
        assignments: dict[int, dict[int, str]],
        *,
        status: str = "draft",
        manual_flags: dict[int, dict[int, bool]] | None = None,
        auto_assignments: dict[int, dict[int, str]] | None = None,
    ) -> None:
        manual_flags = manual_flags or {}
        auto_assignments = auto_assignments or {}
        import json

        notes_payload = {
            "auto_assignments": {
                str(employee_id): {str(day): value for day, value in days.items()}
                for employee_id, days in auto_assignments.items()
            }
        }
        notes_json = json.dumps(notes_payload, ensure_ascii=False)

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM schedules WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()

            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO schedules(year, month, status, notes)
                    VALUES(?, ?, ?, ?)
                    """,
                    (year, month, status, notes_json),
                )
                schedule_id = cursor.lastrowid
            else:
                schedule_id = existing["id"]
                conn.execute(
                    """
                    UPDATE schedules
                    SET status = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (status, notes_json, schedule_id),
                )
                conn.execute(
                    "DELETE FROM schedule_days WHERE schedule_id = ?", (schedule_id,)
                )

            rows: list[tuple[int, int, int, str, int]] = []
            for employee_id, days in assignments.items():
                for day, value in days.items():
                    normalized_value = normalize_shift_code(value)
                    is_manual = int(manual_flags.get(employee_id, {}).get(day, False))
                    rows.append(
                        (schedule_id, employee_id, day, normalized_value, is_manual)
                    )

            if rows:
                conn.executemany(
                    """
                    INSERT INTO schedule_days(schedule_id, employee_id, day, value, is_manual)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        self.sync_planned_extra_day_off_usage(year, month, assignments)

    def sync_planned_extra_day_off_usage(
        self,
        year: int,
        month: int,
        assignments: dict[int, dict[int, str]],
    ) -> dict[int, int]:
        planned_map = self.get_planned_extra_days_off_map(year, month)
        if not planned_map:
            return {}

        settings = self.get_settings()
        calendar = UkrainianCalendar(
            martial_law=settings.get("martial_law", "1") == "1"
        )
        month_info = calendar.get_month_info(year, month)
        usage_by_employee = self._calculate_planned_extra_day_off_usage(
            assignments, planned_map, month_info
        )

        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM extra_days_off_balance
                WHERE schedule_year = ?
                  AND schedule_month = ?
                  AND action = 'auto_planned_usage'
                """,
                (year, month),
            )
            for employee_id, used_days in usage_by_employee.items():
                if used_days <= 0:
                    continue
                planned_days = planned_map[employee_id].planned_days
                conn.execute(
                    """
                    INSERT INTO extra_days_off_balance(
                        employee_id, action, days_count, schedule_year, schedule_month, description
                    )
                    VALUES(?, 'auto_planned_usage', ?, ?, ?, ?)
                    """,
                    (
                        employee_id,
                        -used_days,
                        year,
                        month,
                        f"Автосписання за збереженим графіком: враховано {used_days} з {planned_days} запланованих додаткових вихідних.",
                    ),
                )
        return usage_by_employee

    def _calculate_planned_extra_day_off_usage(
        self,
        assignments: dict[int, dict[int, str]],
        planned_map: dict[int, PlannedExtraDayOff],
        month_info: dict[int, object],
    ) -> dict[int, int]:
        usage_by_employee: dict[int, int] = {}
        for employee_id, plan in planned_map.items():
            if plan.planned_days <= 0:
                usage_by_employee[employee_id] = 0
                continue
            employee_days = assignments.get(employee_id, {})
            extra_off_days = 0
            for day, value in employee_days.items():
                normalized = normalize_shift_code(value)
                if normalized != "В":
                    continue
                info = month_info.get(day)
                is_regular_working_day = (
                    bool(getattr(info, "is_working_day", False))
                    if info is not None
                    else False
                )
                if is_regular_working_day:
                    extra_off_days += 1
            usage_by_employee[employee_id] = min(plan.planned_days, extra_off_days)
        return usage_by_employee
