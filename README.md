# Шаблон исследовательского проекта: математика, источники, Lean

Заготовка проекта, который ведут агенты DeepSeek Harness или Claude Code: постановка, источники, идеи с
независимой критикой, доказательства с рецензией, формализация в Lean 4 с проверкой
соответствия, статья. От темы шаблон не зависит: всё тематическое лежит в двух файлах
нового проекта, `question.md` и `PROJECT.md`.

Порядок работы и возможности проекта для нового пользователя описаны в
[GUIDE.md](GUIDE.md).

## Новый проект

```
python create.py ..\Spectra --lib Spectra --title "Название темы"
cd ..\Spectra
lake exe cache get
lake build
python scripts/proj.py doctor
python scripts/proj.py check
python scripts/harness.py run web
```

`--lib` — имя библиотеки Lean и пространства имён. Версии Lean и Mathlib берутся из
шаблона; ключ `--pins-from ПРОЕКТ` берёт их из работающего проекта. Дальнейшие шаги
описаны в `README.md` созданного проекта.

Для DeepSeek Harness нужны Node.js 22.19+ (ветка 22) или 24+ и npm. Команда запуска
подготовит нативные skills, роли и MCP, затем откроет Harness закреплённой версии.
Модель и ключ настраиваются в Harness. Подробности, headless-запуск и проверки —
[DEEPSEEK.md](template/DEEPSEEK.md). Поддержка Claude Code сохраняется.

## Обновление инструментов в проекте

```
python create.py --update ..\Spectra --dry-run
python create.py --update ..\Spectra
```

Обновление переписывает только то, чем владеет шаблон: `AGENTS.md`, `CLAUDE.md`,
`scripts/`, `tests/`, `.claude/agents/`, `.claude/commands/`, `.claude/skills/`,
`DEEPSEEK.md`, `sources/README.md`, `experiments/README.md`, CI. Постановка, записи, идеи, источники,
библиотека Lean, статья, `.mcp.json` и `.claude/settings.json` не трогаются. Файлы,
которых в шаблоне больше нет, команда перечисляет, но не удаляет.

После обновления пересобираются производные `.dsh/skills/` и Cordis patch для Harness
из актуальных инструкций и локальной `.mcp.json`. `--dry-run` ничего не пишет.

## Изменение воркфлоу

Команды, роли и навыки правятся в одном месте — `template/.claude/`; MCP-серверы — в
`template/.mcp.json`. Поддержка DeepSeek Harness строится из этих файлов:
`template/scripts/harness.py` не содержит имён команд и ролей, тесты берут ожидаемый
состав из тех же каталогов, документация ссылается на `python scripts/harness.py list`.
После правки воркфлоу достаточно прогнать тесты:

```
python -m unittest discover -s template/tests
python -m unittest discover -s tests
python template/scripts/harness.py --root template list
```

Таблица соответствия и три случая, когда адаптер всё же правится (поле шапки без правила,
новый встроенный инструмент Claude Code, новая версия Harness), — в разделе «Как
переносится воркфлоу Claude Code» файла [DEEPSEEK.md](template/DEEPSEEK.md). Таблицы
агентов и команд в `template/AGENTS.md`, `template/README.md` и `GUIDE.md` общие для двух
сред и обновляются вместе с воркфлоу.

## Требования

Python 3.11 или новее, `uv`, `elan` с `lake`, `git`; `pdflatex` — для статьи и проверки
транскрипций. Серверы MCP из `.mcp.json` запускаются через `uv` и ставят свои зависимости
сами.

## Что входит

| Часть | Содержание |
| --- | --- |
| `template/AGENTS.md` | общие правила: карта проекта, статусы, роли агентов, проверки |
| `template/scripts/proj.py` | заготовки записей, поля шапок, сводки, проверки, аудит аксиом, отпечатки формулировок, сборка статьи, пакеты Aristotle |
| `template/scripts/lit.py` | источники: zbMATH, arXiv, MathNet, DOI; транскрипции; гибридный поиск по полным текстам |
| `template/scripts/*_mcp.py` | те же действия как инструменты MCP-серверов `proj` и `lit` |
| `template/scripts/harness.py` | DeepSeek Harness: skills, роли и MCP из `.claude/` и `.mcp.json`, Cordis patch, запуск Web/Headless |
| `template/DEEPSEEK.md` | запуск Harness, перенос воркфлоу Claude Code, проверки |
| `template/.claude/agents/` | генератор идей, критик, экспериментатор, рецензент, формализатор, проверяющий соответствие, поиск по Mathlib, поиск литературы, транскрипция PDF, сверка карточек |
| `template/.claude/commands/` | `/day`, `/ideas`, `/referee`, `/formalize`, `/fidelity`, `/sources`, `/transcribe` |
| `template/.claude/skills/` | оформление текста: `paper-canvas`, `shkalikov-style`, `paper-de-ai`, `exposition`; набор и типографика LaTeX: `math-rigor` |
| `template/tests/` | тесты инструментов без сети и без Lean; `harness_runtime.mjs` сверяет patch со схемами Harness |
| `tests/` | тесты создания и обновления проекта |

## Устройство

- Статус утверждения стоит в шапке его записи `results/R*.md`. `blueprint.md` и индекс
  идей собирает `proj.py sync`.
- `proj.py check` находит объявления записей в библиотеке, запускает Lean, разбирает
  аксиомы и ищет в исходниках `sorry`, `axiom`, `native_decide` и отключённые линтеры.
- Соответствие формулировки Lean утверждению записи проверяет отдельный агент. Отпечаток
  формулировки и её определений показывает, что проверка устарела.
- Идею проверяет критик, доказательство — рецензент, карточку источника — сверяющий по
  PDF. Каждому передают только написанный текст.
- На запись и на идею — по файлу.
- Тема лежит в `PROJECT.md`, `question.md` и `project.toml`; инструменты обновляются из
  шаблона.
- Скрипты написаны на Python и печатают в UTF-8. У каждого действия есть инструмент MCP,
  которому строки передаются без оболочки.
- Опыт — папка `experiments/E*/` с кодом и одной командой запуска; она входит в Git.
- В `output/` лежит только восстановимое.
- У транскрипции есть печатные номера страниц и утверждений. Карточку теоремы сверяют с
  PDF вместе с условиями раздела, стоящими вне текста теоремы.
- Обозначения не пересекаются: `R` — запись, `I` — идея, `S` — источник, `E` — опыт,
  `Q` — открытый вопрос.
