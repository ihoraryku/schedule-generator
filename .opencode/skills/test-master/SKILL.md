---
name: test-master
description: >
  Use this skill to write unittest tests for ShiftMaster modules.
  Triggers: "write tests for", "add unittest", "test coverage", "unit test",
  "test this function", "test the validator", "test the algorithm".
  Use after implementing any module.
  Always write tests before marking a module as complete.
---

# Test Master — unittest for ShiftMaster АСКОЕ

## Testing Stack
- Framework: unittest (stdlib)
- Coverage: coverage.py
- Mocking: unittest.mock (stdlib)

## Test File Locations
```
tests/
├── test_calendar_ua.py
├── test_validator.py              # most critical — all hard constraints
├── test_priority_scheduler.py
├── test_generator.py
├── test_excel_exporter.py
└── test_repository.py
```

## Test Template
```python
import unittest
from datetime import date
from schedule_askue.db.models import Employee, ShiftEntry, State
from schedule_askue.db.repository import Repository

class TestValidator(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.employees = [
            Employee(id=1, full_name="Петрова О.В.", duty_block=2, max_consec=7),
            Employee(id=2, full_name="Арику І.В.", duty_block=2, max_consec=7),
            Employee(id=3, full_name="Юхименко А.А.", duty_block=4, max_consec=7),
            Employee(id=4, full_name="Гайдуков Ю.В.", duty_block=4, max_consec=7),
        ]
        self.year = 2026
        self.month = 4
    
    def test_exactly_one_code_per_day(self):
        """HC-1: кожен співробітник має рівно один код кожного дня"""
        sched = self._build_valid_schedule()
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertEqual(len(errors), 0)
```

## Critical Tests — validator.py (all hard constraints)

```python
# tests/test_validator.py
import unittest
from schedule_askue.core.validator import validate_schedule

class TestHardConstraints(unittest.TestCase):

    def setUp(self):
        self.employees = self._create_sample_employees()
        self.year = 2026
        self.month = 4

    def test_exactly_one_code_per_day(self):
        """HC-1: кожен співробітник має рівно один код кожного дня"""
        sched = self._build_valid_schedule()
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertEqual(len(errors), 0)

    def test_duty_coverage_minimum_2(self):
        """HC-3: щодня мінімум 2 особи з кодом Д"""
        sched = self._build_schedule_with(duty_per_day=1)
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertTrue(any("покриття" in e.lower() for e in errors))

    def test_no_auto_r_on_weekends(self):
        """HC-10: Р у Сб/Нд тільки через побажання або правило"""
        sched = self._build_schedule_with_r_on_saturday(source="auto")
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertTrue(any("вихідний" in e.lower() for e in errors))

    def test_max_consecutive_work(self):
        """HC-7: не більше max_consec підряд робочих днів"""
        sched = self._build_schedule_with_streak(days=8, emp_id=1)
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertTrue(any("підряд" in e.lower() for e in errors))

    def test_work_norm_exact(self):
        """HC-8: (Д + Р) = норма місяця"""
        sched = self._build_valid_schedule()
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertFalse(any("норма" in e.lower() for e in errors))

    def test_saturday_sunday_same_pair(self):
        """HC-4: Сб+Нд чергують ті самі двоє"""
        sched = self._build_schedule_with_different_weekend_pair()
        errors = validate_schedule(sched, self.employees, self.year, self.month)
        self.assertTrue(any("пара" in e.lower() for e in errors))
```

## Running Tests
```bash
# Run all tests
python -m unittest discover -s tests -v

# Run with coverage
coverage run -m unittest discover -s tests
coverage report -m

# Run only validator tests (fastest feedback loop)
python -m unittest tests.test_validator -v

# Run and stop on first failure
python -m unittest discover -s tests --failfast

# Run specific test
python -m unittest tests.test_validator.TestHardConstraints.test_duty_coverage_minimum_2 -v
```

## Coverage Targets
| Module | Target |
|---|---|
| validator.py | ≥ 95% |
| calendar_ua.py | ≥ 90% |
| priority_scheduler.py | ≥ 80% |
| generator.py | ≥ 80% |
| repository.py | ≥ 85% |
```