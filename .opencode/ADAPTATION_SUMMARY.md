# OpenCode Adaptation Summary for ShiftMaster АСКОЕ

## Дата адаптації: 2026-04-10

## Виконані зміни

### 1. AGENTS.md — Оновлено для OpenCode
**Зміни:**
- ✅ Замінено `app/` на `schedule_askue/` у всіх посиланнях
- ✅ Замінено `config.toml` на `config.yaml`
- ✅ Видалено посилання на OR-Tools CP-SAT (проект використовує heuristic scheduler)
- ✅ Видалено посилання на SQLAlchemy 2.0 (проект використовує dataclasses + SQLite repository)
- ✅ Додано секцію "Current Implementation Status" з описом реального стану проекту
- ✅ Оновлено "OpenCode Tool Usage Rules" замість "MCP Tool Usage Rules"
- ✅ Додано інструкції щодо використання Context7 для документації
- ✅ Оновлено посилання на `calendar_ua.py` замість `calendar_utils.py`

**Ключові інструкції для OpenCode:**
```
- Use context7_resolve-library-id + context7_query-docs for PyQt6, openpyxl, reportlab
- Use sequential-thinking for complex algorithm design
- Use bash to run tests: python -m unittest discover -s tests
- Use todowrite to track multi-step tasks
- Use task (explore agent) to understand codebase structure
```

### 2. Skills — Адаптовано під реальну структуру

#### code-reviewer/SKILL.md
- ✅ Замінено SQLAlchemy 2.0 checklist на SQLite Repository Pattern
- ✅ Оновлено шляхи: `app/` → `schedule_askue/`
- ✅ Оновлено auto-fix commands: `black schedule_askue/` замість `black app/`
- ✅ Оновлено приклади commit messages (видалено OR-Tools, додано priority_scheduler)
- ✅ Виправлено посилання на `config.yaml` замість `config.general.martial_law`

#### debugging-wizard/SKILL.md
- ✅ Оновлено Philosophy: `priority_scheduler.py` замість `algorithm_ortools.py`
- ✅ Оновлено шляхи: `generator.py`, `calendar_ua.py`, `repository.py`
- ✅ Оновлено Stage 2: Generator → Priority Scheduler → Validator
- ✅ Оновлено Stage 3 bug patterns з правильними файлами
- ✅ Виправлено import paths: `from schedule_askue.core.validator import validate_schedule`

#### debug-skill/SKILL.md
- ✅ Видалено OR-Tools INFEASIBLE debugging
- ✅ Видалено SQLAlchemy session debugging
- ✅ Додано Algorithm timeout debugging
- ✅ Додано SQLite repository debugging
- ✅ Оновлено launch command: `python -m debugpy --listen 5678 --wait-for-client schedule_askue/main.py`
- ✅ Оновлено Common Errors table з правильними файлами

#### test-master/SKILL.md
- ✅ Замінено pytest на unittest (stdlib)
- ✅ Видалено conftest.py (не потрібен для unittest)
- ✅ Додано unittest.TestCase template замість pytest fixtures
- ✅ Оновлено test file locations (видалено test_algorithm_ortools.py)
- ✅ Оновлено running tests commands: `python -m unittest discover -s tests`
- ✅ Оновлено coverage targets з правильними модулями

### 3. MCP_RECOMMENDATIONS.md — Новий документ
**Створено повний гайд щодо використання OpenCode замість MCP серверів:**

- ✅ Пояснено, що OpenCode не використовує MCP servers як Claude Desktop
- ✅ Описано вбудовані інструменти OpenCode (Context7, bash, file ops, skills, task agents)
- ✅ Надано рекомендації щодо документації (Context7)
- ✅ Надано рекомендації щодо SQLite (bash + sqlite3)
- ✅ Надано рекомендації щодо Git (bash + git)
- ✅ Пояснено, що не потрібно (Filesystem MCP, Brave Search, PostgreSQL MCP, Puppeteer)
- ✅ Додано Best Practices для проекту

## Структура .opencode/ після адаптації

```
.opencode/
├── skills/
│   ├── code-reviewer/
│   │   └── SKILL.md          ✅ Адаптовано
│   ├── debugging-wizard/
│   │   └── SKILL.md          ✅ Адаптовано
│   ├── debug-skill/
│   │   └── SKILL.md          ✅ Адаптовано
│   └── test-master/
│       └── SKILL.md          ✅ Адаптовано
├── MCP_RECOMMENDATIONS.md    ✅ Створено
├── ADAPTATION_SUMMARY.md     ✅ Створено (цей файл)
├── package.json
├── package-lock.json
└── .gitignore
```

## Ключові відмінності від оригінального AGENTS.md

| Аспект | Було (оригінал) | Стало (адаптовано) |
|--------|-----------------|-------------------|
| Структура проекту | `app/` | `schedule_askue/` |
| Конфіг | `config.toml` | `config.yaml` |
| Алгоритм | OR-Tools CP-SAT | priority_scheduler (heuristic) |
| База даних | SQLAlchemy 2.0 ORM | dataclasses + SQLite repository |
| Тести | pytest | unittest (stdlib) |
| Календар | `calendar_utils.py` | `calendar_ua.py` |
| MCP сервери | Згадувались | Пояснено, що не потрібні |
| Фази впровадження | 4 фази (Foundation→Algorithm→Export→UI) | Проект вже функціональний |

## Як використовувати адаптовані інструкції

### Для розробника:
1. Читайте `AGENTS.md` для загального розуміння проекту
2. Використовуйте skills через OpenCode:
   - "review this code" → code-reviewer
   - "write tests for X" → test-master
   - "schedule is wrong" → debugging-wizard
   - "why does this crash" → debug-skill
3. Читайте `MCP_RECOMMENDATIONS.md` для розуміння, як працювати з OpenCode

### Для OpenCode AI:
1. Завжди читайте `AGENTS.md` на початку сесії
2. Використовуйте Context7 для документації PyQt6/openpyxl/reportlab
3. Використовуйте bash для git/sqlite3/python commands
4. Використовуйте skills для спеціалізованих завдань
5. Використовуйте task tool (explore agent) для дослідження кодової бази

## Перевірка адаптації

### ✅ Всі шляхи оновлено
```bash
# Перевірка, що немає посилань на app/
grep -r "app/" .opencode/skills/  # Має бути порожньо
grep -r "schedule_askue/" .opencode/skills/  # Має знайти багато
```

### ✅ Всі інструменти оновлено
- OR-Tools → видалено
- SQLAlchemy → видалено
- pytest → unittest
- MCP servers → пояснено альтернативи

### ✅ Всі файли оновлено
- AGENTS.md ✅
- code-reviewer/SKILL.md ✅
- debugging-wizard/SKILL.md ✅
- debug-skill/SKILL.md ✅
- test-master/SKILL.md ✅
- MCP_RECOMMENDATIONS.md ✅ (новий)

## Наступні кроки

1. Прочитайте `AGENTS.md` для розуміння проекту
2. Прочитайте `README.md` для розуміння поточного стану
3. Прочитайте `IMPLEMENTATION_PLAN.md` для розуміння наступних завдань
4. Використовуйте skills через OpenCode для розробки
5. Використовуйте Context7 для документації бібліотек

## Контакти та підтримка

Для питань щодо OpenCode:
- Ctrl+P → список доступних дій
- Feedback: https://github.com/anomalyco/opencode

Для питань щодо проекту:
- Читайте `IMPLEMENTATION_PLAN.md`
- Читайте `IMPLEMENTATION_TRACKER.md`
