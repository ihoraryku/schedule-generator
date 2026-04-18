---
name: debug-skill
description: >
  Use this skill when code throws an unexpected error, produces wrong output,
  crashes at runtime, or when you need to inspect variable state during execution.
  Triggers: "why does this crash", "debug this", "what's the value of X at line N",
  "PyQt6 segfault", "SQLite error", "repository error",
  "breakpoint", "step through", "inspect locals", "call stack".
  Do NOT use for static code review or writing new features.
---

# Debug Skill — debugpy-based Python Debugger

## Overview
Use `debugpy` to run a real debugger instead of inserting print statements.
This gives you breakpoints, step execution, variable inspection, and call stack analysis.

## Prerequisites
```bash
pip install debugpy
```

## Workflow

### Step 1 — Reproduce
Identify the minimal code path that triggers the bug.
State clearly: what input → what actual output → what expected output.

### Step 2 — Launch with debugpy
```bash
# Terminal 1 — launch with debugpy listener
python -m debugpy --listen 5678 --wait-for-client schedule_askue/main.py

# Terminal 2 — attach from Python (or use VS Code debugger)
python -c "
import debugpy
debugpy.connect(('127.0.0.1', 5678))
debugpy.wait_for_client()
"
```

### Step 3 — Inspect State (via VS Code or inline)
```python
# Add temporarily to code at the point of interest:
import debugpy
debugpy.breakpoint()
# Then inspect via VS Code Debug Console:
# > locals()
# > vars(obj)
```

### Step 4 — ShiftMaster-Specific Patterns

**Algorithm timeout or wrong result:**
```python
# After priority_scheduler.generate(), add:
import debugpy; debugpy.breakpoint()
# Inspect:
# schedule
# employee_stats
# validation_errors
```

**SQLite repository error:**
```python
# Inside repository method:
import debugpy; debugpy.breakpoint()
# Inspect:
# conn
# cursor.fetchall()
# params
```

**PyQt6 QThread race condition:**
```python
# Inside slot connected to generation signal:
import debugpy; debugpy.breakpoint()
# Inspect:
# QThread.currentThread().objectName()
```

### Step 5 — Fix and Verify
After identifying the root cause:
1. Fix the code
2. Remove all `debugpy.breakpoint()` calls
3. Run: `pytest tests/ -x -v` to confirm no regressions
4. Use `code-reviewer` skill before committing

## Common Errors → Debug Entry Points

| Error | File | Breakpoint hint |
|---|---|---|
| Algorithm timeout | priority_scheduler.py | Inside `generate()` method |
| Wrong shift pattern | priority_scheduler.py | Inside `_fill_remaining()` |
| DB lock | repository.py | Inside repository method |
| PyQt6 crash | main_window.py | In slot connected to generation signal |
| Wrong norm count | calendar_ua.py | In `work_norm()` function |
| Trailing streak error | generator.py | In `_get_context()` cross-month logic |
```
