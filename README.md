# Шаблон проекта: математика, источники, Lean

Набор для исследовательского проекта, который ведут агенты Claude Code или DeepSeek
Harness: постановка, источники, идеи с независимой критикой, доказательства с рецензией,
формализация в Lean 4 с проверкой соответствия, статья. От темы шаблон не зависит: всё
тематическое живёт в двух файлах нового проекта, `question.md` и `PROJECT.md`.

Порядок работы и возможности для нового пользователя — в [docs/guide.md](docs/guide.md).
Как устроен сам набор — в [docs/architecture.md](docs/architecture.md).

## Новый проект

```
python tools/create.py ..\Spectra --lib Spectra --title "Название темы"
cd ..\Spectra
lake exe cache get
lake build
python scripts/state/proj.py doctor
python scripts/state/proj.py check
python scripts/host/harness.py run web
```

`--lib` — имя библиотеки Lean и пространства имён. Версии Lean и Mathlib берутся из
шаблона; ключ `--pins-from ПРОЕКТ` берёт их из работающего проекта. Дальнейшие шаги —
в `README.md` созданного проекта.

Для DeepSeek Harness нужны Node.js 22.19+ (ветка 22) или 24+ и npm. Команда запуска
подготовит нативные skills, роли и MCP, затем откроет Harness закреплённой версии. Модель
и ключ настраиваются в Harness. Подробности, headless-запуск и проверки —
[template/DEEPSEEK.md](template/DEEPSEEK.md). Поддержка Claude Code сохраняется.

## Обновление инструментов в проекте

```
python tools/create.py --update ..\Spectra --dry-run
python tools/create.py --update ..\Spectra
```

Обновление переписывает только то, чем владеет шаблон: `AGENTS.md`, `CLAUDE.md`,
`scripts/`, `tests/`, `.claude/agents/`, `.claude/commands/`, `.claude/skills/`,
`DEEPSEEK.md`, `sources/README.md`, `experiments/README.md`, CI. Постановка, записи, идеи,
источники, библиотека Lean, статья, `.mcp.json` и `.claude/settings.json` не трогаются.
Файлы, которых в шаблоне больше нет, команда перечисляет, но не удаляет. Если в проекте
лежит навык с именем команды шаблона, обновление останавливается и называет папку
`.claude/skills/ИМЯ/`, которую нужно удалить: команды и навыки делят одно пространство имён.

После обновления пересобираются производные `.dsh/skills/` и Cordis patch для Harness из
актуальных инструкций и локальной `.mcp.json`. `--dry-run` ничего не пишет.

## Изменение воркфлоу

Команды, роли и навыки правятся в одном месте — `template/.claude/`; MCP-серверы — в
`template/.mcp.json`. Поддержка DeepSeek Harness строится из этих файлов:
`template/scripts/host/harness.py` не содержит имён команд и ролей, тесты берут ожидаемый
состав из тех же каталогов, документация ссылается на `python scripts/host/harness.py list`.
После правки воркфлоу достаточно прогнать проверки:

```
python -m unittest discover -s tests/template
python -m unittest discover -s tests/kit
python template/scripts/host/harness.py --root template list
```

Таблица соответствия и три случая, когда адаптер всё же правится (поле шапки без
правила, новый встроенный инструмент Claude Code, новая версия Harness), — в разделе «Как
переносится воркфлоу Claude Code» файла [template/DEEPSEEK.md](template/DEEPSEEK.md).
Состав воркфлоу описан в `template/AGENTS.md`; он же попадает в созданный проект, поэтому
его не дублируют ни здесь, ни в руководстве.

## Устройство набора

| Слой | Где | Что это |
| --- | --- | --- |
| Продукт | `template/` | проект-заготовка; создание копирует его целиком, подставляя имя библиотеки и название |
| Набор | `tools/` | `create.py` — создание и обновление проекта; `tests/kit/` проверяет его без сети и Lean |
| Проверки продукта | `tests/template/` | инструменты проекта, адаптер Harness, согласованность документации |
| Описание | `docs/`, `README.md` | руководство пользователя, архитектура, эта страница |

Такое деление — по назначению, а не по типу файла: всё, что копируется в проект, лежит
целиком в `template/`, а всё, что описывает и проверяет копирование, — вне него. Поэтому
`PROJECT.md`, `question.md` и остальные файлы заготовки не встречаются в двух местах.
Полный разбор с обоснованием — в [docs/architecture.md](docs/architecture.md).

## Требования

Python 3.11 или новее, `uv`, `elan` с `lake`, `git`; `pdflatex` — для статьи и проверки
транскрипций. Серверы MCP из `.mcp.json` запускаются через `uv` и ставят свои зависимости
сами.

## Что входит

| Часть | Содержание |
| --- | --- |
| `template/AGENTS.md` | общие правила: карта проекта, статусы, роли агентов, проверки |
| `template/scripts/state/proj.py` | заготовки записей, поля шапок, сводки, проверки, аудит аксиом, отпечатки формулировок, сборка статьи, пакеты Aristotle |
| `template/scripts/records.py` | один разбор записей с шапкой для `proj.py` и `lit.py`: чтение, запись, номера, заготовки |
| `template/scripts/sources/lit.py` | источники: zbMATH, arXiv, MathNet, DOI; транскрипции; гибридный поиск по полным текстам |
| `template/scripts/state/mcp.py и scripts/sources/mcp.py` | те же действия как инструменты MCP-серверов `proj` и `lit` |
| `template/scripts/host/harness.py` | DeepSeek Harness: skills, роли и MCP из `.claude/` и `.mcp.json`, Cordis patch, запуск Web/Headless |
| `template/DEEPSEEK.md` | запуск Harness, перенос воркфлоу Claude Code, проверки |
| `template/.claude/agents/` | генератор идей, критик, экспериментатор, рецензент, формализатор, проверяющий соответствие, поиск по Mathlib, поиск литературы, транскрипция PDF, сверка карточек |
| `template/.claude/commands/` | `/day`, `/ideas`, `/referee`, `/formalize`, `/fidelity`, `/sources`, `/transcribe`, `/exposition` |
| `template/.claude/skills/` | слои математического текста: содержание — `math-rigor`, композиция — `paper-canvas`, стиль автора — `shkalikov-style`, язык — `paper-de-ai`, набор — `math-typeset` |
| `tests/template/` | тесты инструментов без сети и без Lean; `harness_runtime.mjs` сверяет patch со схемами Harness |
| `tests/kit/` | тесты создания и обновления проекта |
