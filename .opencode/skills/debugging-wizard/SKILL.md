---
name: debugging-wizard
description: >
  Use this skill for structured Python debugging when you have a bug but no crash —
  wrong output, incorrect schedule patterns, off-by-one errors, wrong counts.
  Triggers: "schedule is wrong", "norm doesn't match", "wrong pattern generated",
  "employee has too many consecutive days", "duty count is off",
  "2Д+2Р appeared but shouldn't", "trailing streak is wrong".
  Do NOT use for crashes or exceptions — use debug-skill for those.
---

# Debugging Wizard — Structured Python Bug Analysis

## Philosophy
Bugs in schedule generation are almost always one of:
1. Wrong constraint definition (priority_scheduler.py)
2. Wrong input data transformation (generator.py)
3. Off-by-one in date/norm calculation (calendar_ua.py)
4. State corruption between months (repository.py → state table)

## Debugging Protocol

### Stage 1 — Characterize the Bug
Answer these before touching any code:
- Which employee(s) are affected?
- Which day(s) / month?
- What code appeared? What was expected?
- Is it reproducible with the same input?
- Did it happen before a recent change?

### Stage 2 — Isolate the Layer

```
Input data (wishes/rules) → Generator → Priority Scheduler → Validator → DB → UI
         ↑                      ↑            ↑                ↑
    Check first            Check second   Check third     Check fourth
```

**Check input layer:**
```python
# In generator.py, add temporary logging:
logger.debug(f"Wishes for {emp}: {wishes}")
logger.debug(f"Rules for {emp}: {rules}")
logger.debug(f"trailing_streak for {emp}: {trailing_streak}")
```

**Check algorithm output:**
```python
# After priority_scheduler, dump raw schedule:
for emp in employees:
    row = [sched[emp][d] for d in range(1, days_in_month+1)]
    logger.debug(f"{emp}: {' '.join(row)}")
```

**Check validator:**
```python
# Run validator in isolation:
from schedule_askue.core.validator import validate_schedule
errors = validate_schedule(schedule, employees, year, month)
for e in errors: logger.error(e)
```

### Stage 3 — ShiftMaster Pattern Bugs

**Bug: Employee has >7 consecutive working days**
```
Root cause: trailing_streak from previous month not passed to scheduler
Fix location: generator.py → _get_seamless_context()
Check: state table → trailing_streak field
```

**Bug: 2Д+2Р appears (should be 2Д+1Р max)**
```
Root cause: isRQuotaExceededToday() not applied in heuristic
Fix location: priority_scheduler.py → _fill_remaining()
Check: count Д per day, if ≥2 then max 1 Р allowed
```

**Bug: Work norm ±1 off**
```
Root cause: vacation days or extra_days_off not subtracted from norm
Fix location: generator.py → _calculate_budget()
Check: work_norm(y,m) - len(vacation_days) - extra_days_off[emp]
```

**Bug: Seamless break at month boundary**
```
Root cause: comp_balance/under_balance not loaded from state table
Fix location: db/repository.py → load_state()
Check: SELECT * FROM state WHERE employee_id=? AND month=? AND year=?
```

### Stage 4 — Verify Fix
```bash
pytest tests/test_validator.py -v        # all constraints pass
pytest tests/test_scheduler.py -v        # seamless context correct
pytest tests/ --tb=short                 # no regressions
```