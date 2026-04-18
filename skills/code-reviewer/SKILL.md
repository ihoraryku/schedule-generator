---
name: code-reviewer
description: >
  Review code changes in this repository before committing or after implementing
  a feature or bug fix. Use when the user asks for a review, asks whether code
  is ready, or when checking generator, validator, repository, exporter, or UI
  changes in the schedule_askue project. Also use for Ukrainian requests such as
  "зроби рев'ю", "перевір код", "перевір зміни", "подивись перед комітом",
  "чи готовий код", "чи можна комітити", "знайди регресії", or "перевір
  реалізацію".
---

# Code Reviewer

Review changes against the real structure of this repository, not generic Python advice.

## Focus Order

1. Find behavioral bugs and regressions first.
2. Check whether schedule rules still match the archive and validator.
3. Check whether changed code fits the current architecture.
4. Only then comment on style or cleanup.

## Repository-Specific Checks

- Keep module names and imports under `schedule_askue/...`.
- Treat `Р`, `Д`, `В`, `О` as the current canonical shift codes; `Ч` is only a legacy alias for input normalization.
- Check that generator output still passes `ScheduleValidator`.
- Check that any fallback path does not silently bypass required constraints.
- Check that settings are read from repository settings or config, not hardcoded in UI/core/export.
- Check that exports still match the intended archive-like format.
- Check that database changes are reflected in `Repository.initialize()` migrations.
- Check that UI actions in `schedule_tab.py` still preserve manual flags, auto assignments, and autosave behavior.

## Review Checklist

- Verify modified code paths against `generator.py`, `heuristic_generator.py`, and `validator.py`.
- Confirm new logic respects priorities: mandatory wishes -> rules -> auto assignment.
- Confirm month-boundary context is preserved when code touches previous/next month logic.
- Confirm personal rules are interpreted consistently in generator and validator.
- Confirm no new unknown shift codes are introduced without validator/export/UI support.
- Confirm repository writes are safe for existing schedules and notes payloads.
- Confirm logging uses `logging.getLogger(__name__)` and avoids `print()`.
- Confirm public-facing messages and labels are Ukrainian where appropriate.

## Useful Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests -x
.\.venv\Scripts\python.exe -c "from pathlib import Path; from schedule_askue.db.repository import Repository; repo=Repository(Path('schedule.db')); repo.initialize(); print(repo.get_settings())"
```

## Review Output Style

- Lead with findings, ordered by severity.
- Include file and line references.
- Be explicit whether an issue is confirmed, likely, or only a risk.
- If no findings are found, state that clearly and mention remaining test gaps.
