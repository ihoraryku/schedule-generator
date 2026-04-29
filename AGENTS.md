# ShiftMaster АСКОЕ — OpenCode Agent Instructions

> Global personal rules apply to this project as well.
> Read them first: @~/.config/opencode/AGENTS.md

---

## Project Overview

Windows desktop app (.exe) for automated monthly work schedule generation.

- **Stack:** Python 3.12 + PyQt6 6.7+ + SQLite 3 + priority_scheduler (heuristic) + openpyxl + reportlab
- **Run:** `python -m schedule_askue.main` (from project root)
- **Tests:** `python -m unittest discover -s tests`
- **Format changed files:** `python -m ruff format <files>`
- **Lint:** `python -m ruff check schedule_askue tests`
- **Config:** `config.yaml` (NOT `config.toml`)
- **Directory:** `schedule_askue/` (NOT `app/`)

---

## Architecture

Read `README.md` for full details. Key modules:

| Module | Path |
|---|---|
| Generator (main algorithm) | `schedule_askue/core/priority_scheduler.py` |
| Models (dataclasses) | `schedule_askue/db/models.py` |
| Repository (SQLite CRUD) | `schedule_askue/db/repository.py` |
| Validator | `schedule_askue/core/validator.py` |
| UI (PyQt6 tabs) | `schedule_askue/ui/` |
| Export (Excel + PDF) | `schedule_askue/export/` |

> `priority_scheduler.py` is stable — do not refactor without an explicit task for it.

---

## Tools

| Situation | Tool |
|---|---|
| PyQt6 / openpyxl / reportlab docs | `context7_resolve-library-id` → `context7_query-docs` |
| Complex algorithm or constraint logic | `sequential-thinking` |
| PyQt6 crash or runtime error | `debug-skill` |
| Wrong schedule output (algorithm logic) | `debugging-wizard` |
| Writing tests for a module | `test-master` |
| Formatting / linting Python | `ruff format` → `ruff check` |
| Before every commit | `code-reviewer` |

---

## Skills (.opencode/skills/)

- `debug-skill` — PyQt6 UI crashes, exceptions, runtime errors
- `debugging-wizard` — algorithm produces incorrect shift patterns
- `test-master` — write unittest tests; run before marking any module complete
- `code-reviewer` — review diff before committing

---

## Domain: Shift Codes

| Code | Meaning | Color |
|---|---|---|
| Д | Чергування (duty) | #FFF2CC |
| Р | Робочий день (workday) | #DDEEFF |
| В | Вихідний (day off) | #E8E8E8 |
| О | Відпустка (vacation) | #C6EFCE |

- Priority: **Побажання → Правила → Auto algorithm**
- Each day defaults to 2Д unless configured otherwise
- Normal day patterns: `1Р-2Д-1В`, `0Р-2Д-2В` (auto-distribution)
- **Read `SCHEDULE_PRINCIPLES.md` for full HARD invariants**

---

## Domain: Martial Law

- `martial_law` flag lives in `config.yaml` — always read it, never assume its value
- Always call `UkrainianCalendar.get_production_norm()` or shared helpers from `work_norms.py` — **never hardcode** monthly hour norms
- Work norms may differ from the standard calendar when `martial_law=true`

---

## CRITICAL: Before Every Substantial Algorithm Change

1. **Read `SCHEDULE_PRINCIPLES.md`** — verify the change does not violate any HARD invariant.
2. Key principles to check:
   - **P1:** Побажання → Правила → Авторозподіл (global priority)
   - **P2:** 2Д/день (HARD) — unless overridden by wishes/rules/config
   - **P3:** ≤1Р/день (HARD) — unless overridden by wishes/rules/config
   - **P4:** Locked shifts are immutable
   - **P7:** `require_work + prohibit_duty` = occupied Р slot
3. If a principle is violated, either reject the change or update the principle with explicit justification.

---

## Coding Standards

- **Python version:** 3.12 (type hints style: `X | None`, not `Optional[X]`)
- No SQLAlchemy ORM — use dataclasses + SQLite repository pattern
- All UI strings in Ukrainian; all identifiers in English
- `logger = logging.getLogger(__name__)` in every module
- Never hardcode employee names — always read from DB
- No `# TODO` or bare `pass` in core logic
- Do not use `QThread` directly — use `WorkerBase` wrapper
- Use Ruff for formatting and linting. Format changed Python files with `python -m ruff format <files>`, then run `python -m ruff check schedule_askue tests`.

---

## What Not to Do

- Do not touch `priority_scheduler.py` without an explicit refactor task
- Do not change DB schema without updating `models.py` and `repository.py` together
- Do not add new dependencies without checking if stdlib or existing deps cover the need
- Do not fix bugs found outside the current task scope — report them instead
- **Do not make algorithm changes without verifying against `SCHEDULE_PRINCIPLES.md`**

---

## Git Commit Format

```
feat(module): короткий опис
fix(module): що виправлено
refactor(module): що змінено
test(module): які тести додано
```

Examples:
```
feat(algo): реалізовано CP-SAT hard constraints
fix(scheduler): виправлено trailing_streak для безшовності місяців
test(validator): pytest покриття 95% для всіх hard constraints
```

---

## Current Status

See `IMPLEMENTATION_PLAN.md` and `IMPLEMENTATION_TRACKER.md` for active tasks and completed work.
Do not rely on this file for implementation status — those files are the source of truth.
