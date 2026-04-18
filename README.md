# Генератор графіків АСКУЕ

Desktop-застосунок на Python + PyQt6 для створення, редагування, перевірки та експорту місячних графіків роботи інженерів АСКОЕ.

## Поточний стан

Проєкт уже не є стартовим каркасом. На поточний момент у репозиторії реалізовано робочу desktop-систему з такими можливостями:

- ведення персоналу, побажань, правил і балансу додаткових вихідних через SQLite;
- генерація місячного графіка через новий детермінований `priority_scheduler`;
- пріоритет генерації: `побажання -> правила -> автоматичний розподіл`;
- підтримка канонічних кодів змін `Р / Д / В / О` з нормалізацією старих alias-кодів;
- ручне редагування графіка, undo/redo, autosave, reset-to-auto;
- валідація графіка з підсвічуванням помилок і попереджень у UI;
- експорт у Excel і PDF у форматі, наближеному до архівних файлів;
- централізований конфіг через `config.yaml`.

## Ключова архітектура

### Генерація

- `schedule_askue/core/generator.py` — фасад генерації;
- `schedule_askue/core/priority_scheduler.py` — актуальний бойовий алгоритм генерації;
- `schedule_askue/core/heuristic_generator.py` — суміснісний шар, який теж делегує в новий scheduler;
- `schedule_askue/worker/generate_schedule_worker.py` — окремий worker-процес для запуску генерації з UI.

### Правила і валідація

- `schedule_askue/core/validator.py` — постгенераційна перевірка графіка;
- `schedule_askue/core/personal_rule_logic.py` — єдина логіка резолву персональних правил;
- `schedule_askue/core/calendar_rules.py` — спільна семантика special days.

### Дані

- `schedule_askue/db/models.py` — доменні dataclass-моделі;
- `schedule_askue/db/repository.py` — SQLite repository, CRUD і міграції.

### UI

- `schedule_askue/ui/main_window.py` — головне вікно;
- `schedule_askue/ui/schedule_tab.py` — головний екран графіка;
- `schedule_askue/ui/wishes_tab.py` — побажання на місяць;
- `schedule_askue/ui/rules_tab.py` — загальні та персональні правила;
- `schedule_askue/ui/balance_tab.py` — облік додаткових вихідних;
- `schedule_askue/ui/staff_tab.py` — персонал;
- `schedule_askue/ui/settings_tab.py` — базові налаштування.

### Експорт

- `schedule_askue/export/excel_exporter.py` — експорт у Excel;
- `schedule_askue/export/pdf_exporter.py` — експорт у PDF.

## Основні функції

### 1. Графік

- перегляд і редагування помісячної таблиці;
- генерація графіка для вибраного місяця;
- undo/redo, autosave, reset до автоматичного варіанту;
- валідація з помилками й попередженнями;
- статистика по працівниках: `Д`, `Р`, `В`, `О`, норма, відхилення, баланс додаткових вихідних.

### 2. Побажання

- відпустки, вихідні, робочі дні, чергування;
- paste з Excel/TSV;
- пріоритети `mandatory` / `desired`;
- прапорець `use_extra_day_off` у моделі побажання.

### 3. Правила

- загальні правила на місяць або за замовчуванням;
- персональні правила на період;
- пріоритети, активність, порядок відображення;
- швидке увімкнення/вимкнення правил.

### 4. Персонал

- список працівників;
- ставка, посада, тип робочого профілю;
- архівація співробітників;
- зміна порядку працівників у всіх основних вкладках.

### 5. Облік додаткових вихідних

- поточний баланс по працівниках;
- журнал нарахувань і списань;
- ручне додавання і видалення операцій.

Примітка: логіка інтеграції додаткових вихідних безпосередньо в алгоритм генерації ще в доробці. Поточний стан і наступні кроки описані в `IMPLEMENTATION_PLAN.md`.

## Коди змін

Канонічні коди системи:

- `Р` — робочий день;
- `Д` — чергування;
- `В` — вихідний;
- `О` — відпустка.

При читанні старих даних підтримуються alias-и:

- `8 -> Р`
- `5-3 -> Д`
- `Ч -> Д`
- `O -> О`

## Конфігурація

Головне джерело параметрів проєкту — `config.yaml`.

У ньому зберігаються:

- коди й визначення змін;
- правила генерації;
- календарні налаштування;
- параметри експорту;
- UI-значення за замовчуванням;
- архівні спостереження, використані для побудови алгоритму.

SQLite-налаштування використовуються як runtime-override поверх YAML для частини параметрів, які редагуються з UI.

## Запуск

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m schedule_askue.main
```

## Залежності

Основні залежності:

- `PyQt6` — GUI framework
- `holidays` — календар свят України
- `openpyxl` — експорт у Excel
- `reportlab` — експорт у PDF
- `PyYAML` — читання config.yaml

## Тести і технічна перевірка

Базові перевірки, які варто запускати після змін:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -m compileall schedule_askue tests
```

## Troubleshooting

### Застосунок не запускається

Перевірте `logs/app.log` для деталей помилки. Логи зберігаються у файлі та виводяться в консоль.

### Генерація занадто довга / Worker timeout

Worker timeout після 40 секунд. Можливі причини:
- Занадто складна комбінація правил і побажань
- Багато працівників (>10)
- Конфлікти між обов'язковими побажаннями та правилами

Рішення: спростіть правила або зменшіть кількість обов'язкових побажань.

### Перегляд логів у реальному часі

```powershell
Get-Content logs\app.log -Wait -Tail 50
```

### Логи показують AttributeError або ImportError

Переконайтеся, що всі залежності встановлені:
```powershell
pip install -r requirements.txt
```

## Розробка

### Структура логування

Логування налаштовано на рівні INFO. Логи виводяться:
- У файл `logs/app.log`
- У консоль (stdout)

Ключові модулі з логуванням:
- `core/generator.py` — старт/завершення генерації
- `core/priority_scheduler.py` — процес генерації
- `core/validator.py` — результати валідації
- `ui/schedule_tab.py` — помилки UI та worker

### Запуск тестів з деталями

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### Перевірка синтаксису

```powershell
.venv\Scripts\python.exe -m compileall schedule_askue tests
```

## Актуальні робочі документи

- `IMPLEMENTATION_PLAN.md` — єдиний актуальний план впровадження;
- `IMPLEMENTATION_TRACKER.md` — журнал фактично виконаних змін.

Старі roadmap/plan документи, що описували OR-Tools-first архітектуру або стартовий каркас, навмисно прибрані з кореня репозиторію, щоб документація не суперечила коду.

## Структура проєкту

```text
schedule_askue/
  core/
    calendar_rules.py
    calendar_ua.py
    generator.py
    heuristic_generator.py
    personal_rule_logic.py
    priority_scheduler.py
    project_config.py
    shift_codes.py
    validator.py
  db/
    models.py
    repository.py
  export/
    excel_exporter.py
    pdf_exporter.py
  ui/
    balance_tab.py
    employee_dialog.py
    extra_day_off_dialog.py
    main_window.py
    personal_rule_dialog.py
    rule_dialog.py
    rules_tab.py
    schedule_tab.py
    settings_tab.py
    staff_tab.py
    table_widgets.py
    wish_dialog.py
    wishes_tab.py
  worker/
    generate_schedule_worker.py
  main.py

config.yaml
requirements.txt
README.md
schedule.db.example
schedule_generator.spec
IMPLEMENTATION_PLAN.md
IMPLEMENTATION_TRACKER.md
```

## Збірка Windows .exe

Для створення Windows .exe використовується PyInstaller.

### Встановлення PyInstaller

```powershell
pip install pyinstaller
```

### Збірка .exe

**Варіант 1 — через spec-файл:**
```powershell
pyinstaller schedule_generator.spec
```

**Варіант 2 — напряму:**
```powershell
pyinstaller --name=ScheduleGenerator --onefile --windowed schedule_askue/main.py
```

### Вихідний файл

Після збірки, .exe буде в директорії `dist/`:
```text
dist/
  ScheduleGenerator.exe
```

### notes

- Файл `config.yaml` автоматично включається в .exe
- База даних `schedule.db` створюється автоматично при першому запуску
- Для демо-даних використовуй `schedule.db.example` (скопіюй і перейменуй)
