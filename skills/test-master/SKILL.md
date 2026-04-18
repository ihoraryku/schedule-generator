---
name: test-master
description: >
  Write or update tests for the schedule_askue repository. Use when adding test
  coverage for generator, heuristic fallback, validator, repository, export, or
  archive-matching behavior, and when reproducing bugs with focused automated
  checks. Also use for Ukrainian requests such as "додай тести", "напиши
  pytest", "покрий тестами", "зроби regression test", "додай перевірку для
  validator", "напиши unit test", or "зроби сценарний тест генератора".
---

# Test Master

Write tests for the actual project layout and business rules in this repository.

## Test Priorities

1. `schedule_askue/core/validator.py`
2. `schedule_askue/core/generator.py`
3. `schedule_askue/core/heuristic_generator.py`
4. `schedule_askue/db/repository.py`
5. exporters and UI helpers only after core logic

## Preferred Test Types

- Unit tests for helper methods and mappings
- Scenario tests for month generation with fixed employees/wishes/rules
- Regression tests for previously broken schedules
- Archive-parity tests for known real patterns

## High-Value Cases

- exactly 2 duty shifts expected per day
- max consecutive workdays respected
- mandatory wishes override auto logic
- vacation overlap limit enforced
- fallback path does not return structurally invalid data
- validator catches broken patterns that generator should avoid
- repository round-trip for `save_schedule()` / `get_schedule_bundle()`

## Suggested Structure

```text
tests/
  test_validator.py
  test_generator.py
  test_heuristic_generator.py
  test_repository.py
  test_exporters.py
```

## Fixture Guidance

- Use in-memory or temporary SQLite where possible.
- Build employees with current dataclasses from `schedule_askue.db.models`.
- Keep month scenarios small and explicit.
- Prefer named helpers like `build_employees()`, `build_settings()`, `build_mandatory_wishes()`.

## Example Focused Scenario

```python
def test_two_mandatory_vacations_over_limit_is_detected():
    ...
```

## Verification

Run the smallest relevant subset first, then the wider suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_validator.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_generator.py -q
.\.venv\Scripts\python.exe -m pytest
```
