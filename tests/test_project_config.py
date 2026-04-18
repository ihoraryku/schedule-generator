from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from schedule_askue.core.project_config import (
    load_project_config,
    project_settings_overrides,
)
from schedule_askue.db.repository import Repository


class ProjectConfigTests(unittest.TestCase):
    def test_load_project_config_reads_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config.yaml").write_text(
                "document:\n  company_name: YAML\n"
                "generation:\n  target_duty_per_day: 3\n",
                encoding="utf-8",
            )

            config = load_project_config(root)

            self.assertEqual(config["document"]["company_name"], "YAML")
            self.assertEqual(config["generation"]["target_duty_per_day"], 3)

    def test_project_settings_overrides_flattens_generation_and_solver(self) -> None:
        config = load_project_config(Path(r"D:\Projects\schedule-generator_python_2"))

        settings = project_settings_overrides(config)

        self.assertEqual(settings["daily_shift_d_count"], "2")
        self.assertEqual(settings["max_regular_per_day"], "1")
        self.assertEqual(settings["hard_max_consecutive_work_days"], "9")
        self.assertNotIn("solver_max_time_seconds", settings)
        self.assertEqual(settings["martial_law"], "1")

    def test_repository_get_settings_uses_config_defaults(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            (root / "config.yaml").write_text(
                "document:\n  company_name: Repo YAML\n"
                "generation:\n  target_duty_per_day: 4\n  max_consecutive_duty_days: 5\n"
                "export:\n  default_dir: ./custom-exports\n",
                encoding="utf-8",
            )
            repo = Repository(root / "schedule.db")
            repo.initialize()

            settings = repo.get_settings()

            self.assertEqual(settings["company_name"], "Repo YAML")
            self.assertEqual(settings["daily_shift_d_count"], "4")
            self.assertEqual(settings["max_consecutive_duty_days"], "5")
            self.assertEqual(settings["export_dir"], "./custom-exports")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
