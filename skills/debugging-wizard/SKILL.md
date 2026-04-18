---
name: debugging-wizard
description: >
  Diagnose wrong schedule output without a hard crash. Use when generated
  schedules have bad patterns, wrong hour balance, broken weekend pairing,
  incorrect consecutive-day behavior, archive mismatches, or validator
  violations in the schedule_askue project. Also use for Ukrainian requests such
  as "графік неправильний", "дивний розподіл змін", "не той патерн", "чому
  validator лається", "баланс годин кривий", "забагато днів підряд", "зміни
  розставились неправильно", or "не збігається з архівом".
---

# Debugging Wizard

Use this skill for structured analysis of logic bugs.

## Typical Bug Layers

1. Input transformation: wishes, rules, personal rules, previous/next month tail
2. Priority scheduler: day construction order, hard rules, scoring, repair steps
3. Validation mismatch: generator output looks plausible, but validator disagrees
4. Archive mismatch: current logic differs from real 2025/2026 schedules
5. Repository/input mismatch: stored wishes, rules, previous-month tail, or settings are wrong

## Protocol

### Stage 1: Describe the bad output

- Which employee?
- Which day or date range?
- Which code appeared?
- What code or pattern was expected?
- Does the validator flag it already?

### Stage 2: Isolate the layer

Use this order:

`Repository inputs -> ScheduleGenerator -> PriorityScheduleBuilder -> Validator -> Export`

### Stage 3: Compare with archive rules

Use the archive when checking:

- daily count of duty shifts
- day-off pairing on weekends
- typical number of `Р` on weekdays
- balance of hours and duty load
- real employee roles and rotation patterns

### Stage 4: Confirm with a minimal reproduction

Prefer a direct script using:

- `Repository`
- `ScheduleGenerator`
- `ScheduleValidator`

If possible, reduce the case to one month and a small set of wishes/rules.

## Frequent Bug Patterns In This Repo

- Priority scheduler returns a graph that still violates one of the archive invariants.
- Generator and validator disagree on a personal rule or special-day interpretation.
- Personal rules are interpreted differently in generator and validator.
- Hour balance is measured in workdays, while archive expectations are closer to hours.
- Weekend handling differs between archive, generator, validator, and export labels.

## Expected Output

When using this skill, produce:

- root cause
- exact file/function involved
- minimal reproduction if possible
- whether the problem is in data, generator, heuristic, validator, or export
- the smallest safe fix
