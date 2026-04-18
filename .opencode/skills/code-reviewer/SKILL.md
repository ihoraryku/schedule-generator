---
name: code-reviewer
description: >
  Use this skill before every git commit to review Python code quality.
  Triggers: "review this code", "check before commit", "code review",
  "is this correct", "check my implementation", "ready to commit?".
  Run after completing any module and before using git tool to commit.
---

# Code Reviewer — Pre-commit Python Review for ShiftMaster

## Review Checklist

Run through ALL items before approving a commit.

### ✅ Python 3.13+ Standards
- [ ] Type hints on ALL public functions: `def foo(x: int) -> str | None:`
- [ ] Use `X | None` not `Optional[X]` (no `from typing import Optional`)
- [ ] Use `list[str]` not `List[str]`, `dict[str, int]` not `Dict[str, int]`
- [ ] Dataclasses use `@dataclass(slots=True)` where appropriate
- [ ] f-strings used instead of `.format()` or `%`

### ✅ SQLite Repository Pattern
- [ ] Use `schedule_askue/db/repository.py` for all DB operations
- [ ] No direct SQL in business logic — use repository methods
- [ ] Dataclasses from `schedule_askue/db/models.py` for data transfer
- [ ] Connection handling via repository context managers
- [ ] No raw `sqlite3.connect()` calls outside repository

### ✅ ShiftMaster Business Rules
- [ ] No hardcoded employee names (must read from DB)
- [ ] No hardcoded month norms (must use `calendar_ua.work_norm()`)
- [ ] Shift codes only from: `{"Д", "Р", "В", "О"}`
- [ ] Priority order respected: Wishes → Rules → Auto
- [ ] `source` field set correctly: "auto" / "wish" / "rule" / "manual"
- [ ] `martial_law` flag read from `config.yaml`, never hardcoded

### ✅ Logging
- [ ] `logger = logging.getLogger(__name__)` at module top
- [ ] Generation start/end logged at INFO level
- [ ] Algorithm fallback logged at WARNING level
- [ ] Constraint violations logged at ERROR level
- [ ] No `print()` statements in production code

### ✅ Error Handling
- [ ] DB operations wrapped in try/except with logger.error()
- [ ] Algorithm timeout handled with graceful fallback
- [ ] File operations (export) handle PermissionError
- [ ] No bare `except:` — always `except SpecificError as e:`

### ✅ Documentation
- [ ] Every public function has docstring with Args and Returns
- [ ] Complex algorithm steps have inline comments
- [ ] Module-level docstring explains purpose

## Auto-fix Commands
```bash
# Format
black schedule_askue/ tests/

# Sort imports
isort schedule_askue/ tests/

# Type check
mypy schedule_askue/ --python-version 3.13 --strict

# Lint
ruff check schedule_askue/ tests/

# Run all checks
black schedule_askue/ && isort schedule_askue/ && ruff check schedule_askue/ && mypy schedule_askue/
```

## Commit Message Format (Ukrainian)
```
feat(module): що реалізовано
fix(module): що виправлено
refactor(module): що змінено
test(module): які тести додано
docs(module): що задокументовано

Приклади:
feat(db): додано repository pattern для SQLite
fix(scheduler): виправлено trailing_streak для безшовності місяців
feat(algo): реалізовано priority_scheduler з детермінованою евристикою
test(validator): unittest покриття 95% для всіх hard constraints
```

## 🚫 Never Commit If:
- mypy reports errors in modified files
- pytest fails (any test)
- Hardcoded employee name found
- `print()` statement in production code
- Missing type hints on public functions
```