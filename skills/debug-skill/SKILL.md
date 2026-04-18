---
name: debug-skill
description: >
  Debug runtime failures, crashes, worker-process errors, invalid subprocess
  output, or solver/runtime exceptions in this repository. Use when the app
  crashes, generation fails, the worker returns an error, or runtime state behaves
  unexpectedly, or imports/runtime state need to be inspected during execution.
  Also use for Ukrainian requests such as "падає генерація", "падає воркер",
  "є помилка під час запуску", "чому крашиться", "знайди runtime помилку",
  "worker повертає помилку", "процес аварійно завершується", or "runtime
  поводиться дивно".
---

# Debug Skill

Use real runtime inspection for this project instead of adding random `print()` calls.

## Primary Targets In This Repo

- `schedule_askue/ui/schedule_tab.py` for worker launch and UI-triggered failures
- `schedule_askue/worker/generate_schedule_worker.py` for subprocess payload/debug output
- `schedule_askue/core/generator.py` for payload transformation and result packaging
- `schedule_askue/core/priority_scheduler.py` for generation logic
- `schedule_askue/core/heuristic_generator.py` for compatibility delegation paths
- `schedule_askue/db/repository.py` for SQLite issues

## Workflow

### 1. Reproduce

- Capture the exact year/month, employees, rules, wishes, and settings.
- Note whether the failure happens in UI, worker subprocess, or direct Python call.

### 2. Reproduce Outside UI First

Prefer a direct Python invocation before debugging the full GUI:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from schedule_askue.db.repository import Repository; from schedule_askue.core.generator import ScheduleGenerator; repo=Repository(Path('schedule.db')); repo.initialize(); print(repo.list_employees())"
```

### 3. Debug the Worker Boundary

If generation fails only from the GUI, inspect:

- the payload created in `ScheduleTab.generate_schedule`
- `sys.executable` used by `GenerateWorker`
- `stdout` / `stderr` parsing in `GenerateWorker.run`

### 4. Runtime Inspection Of Generation Logic

When diagnosing generation behavior:

- log the final settings used for generation
- log counts of mandatory wishes, vacations, and personal rules
- log which stage of `PriorityScheduleBuilder` introduced the bad assignment
- inspect whether the issue comes from inputs, construction order, repair, or validation mismatch

Useful temporary probe:

```python
print("status", status)
print("warnings", [w.message for w in result.warnings])
```

Remove probes after diagnosis.

### 5. Crash/Exception Triage

- GUI exception: inspect `logs/app.log`
- worker failure: inspect JSON returned by `generate_schedule_worker`
- import/runtime issue: reproduce with direct `.venv\Scripts\python.exe`
- generator issue: reproduce with a minimal script and fixed inputs

## Preferred Debugging Style

- Minimize the failing case first.
- Debug one layer at a time: UI -> worker -> generator -> validator -> repository.
- Preserve failing artifacts such as settings, wishes, and personal rules until root cause is confirmed.
