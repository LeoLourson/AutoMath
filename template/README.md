# __TITLE__

Постановка — [question.md](question.md). Результаты, их статусы и зависимости —
[blueprint.md](blueprint.md). Идеи — [ideas/](ideas/README.md). Источники —
[sources/](sources/README.md). Статья — `paper/main.tex`.

## С чего начать

1. `lake exe cache get`, затем `lake build`: загрузка готовой сборки Mathlib и сборка
   библиотеки `__LIB__`.
2. `python scripts/state/proj.py doctor` — проверка окружения. Первый запуск MCP-серверов `lit`
   и `proj` ставит зависимости через `uv`; чтобы не ждать этого в редакторе, один раз
   выполните `uv run scripts/sources/lit.py list`.
3. Заполните `question.md` и `PROJECT.md`.
4. `python scripts/state/proj.py check` — должно пройти с одним замечанием о примере.
5. Удалите пример: запись `results/R01.md` и теорему `sq_add` из `__LIB__/Basic.lean`,
   затем `python scripts/state/proj.py sync`.

Дальше работа идёт командами: `/sources тема` собирает литературу, `/ideas` предлагает
и проверяет подходы, `/day` ведёт ежедневный цикл.

Для DeepSeek Harness: `python scripts/host/harness.py run web`, затем выберите папку проекта,
preset Standard и модель в интерфейсе. Адаптер подключит роли, skills и MCP.
Нужны Node.js 22.19+ (ветка 22) или 24+ и npm; подробности — [DEEPSEEK.md](DEEPSEEK.md).
Команды, роли и навыки Harness собираются из `.claude/`; их список печатает
`python scripts/host/harness.py list`.
Можно также работать в Claude Code с прежними настройками.

## Файлы

| Файл или папка | Содержание |
| --- | --- |
| [question.md](question.md) | объект, условия, вопрос, контрольные случаи, открытые вопросы |
| [PROJECT.md](PROJECT.md) | тема, обозначения, ловушки, особые правила |
| [AGENTS.md](AGENTS.md) | общие правила работы агентов |
| `results/` | записи `R*.md`: утверждение, доказательство, границы; статус — в шапке |
| `ideas/` | идеи `I*.md` с критикой; отвергнутые остаются с причиной |
| `experiments/` | опыты `E*/`: код, команда запуска, результат |
| `sources/` | реестр `papers.json`, каталог, карточки теорем `cards/S*.md` |
| `__LIB__/`, `__LIB__.lean` | библиотека Lean |
| `paper/` | статья |
| [blueprint.md](blueprint.md) | сводка записей и граф зависимостей; собирается из шапок |
| `scripts/` | `proj.py` — записи, проверки, сводки; `lit.py` — источники; `records.py` — общий разбор записей; MCP-серверы |
| `.claude/` | агенты, команды, скиллы оформления текста |
| `.dsh/skills/` | производные skills для Harness; собираются автоматически, в Git не входят |
| [DEEPSEEK.md](DEEPSEEK.md) | запуск, модели, MCP, диагностика и обновление Harness |
| `output/` | сборки, полные тексты, индекс; в Git не входит |

## Работа

Команды и роли — в `AGENTS.md`: там их состав, куда каждая роль пишет и что запускает.
В Harness те же команды приходят нативными skills, их список печатает
`python scripts/host/harness.py list`.

## Проверки

```
python scripts/state/proj.py check          # всё, включая lake build и аксиомы
python scripts/state/proj.py check --fast   # без Lean
```

Версии Lean и Mathlib закреплены в `lean-toolchain`, `lakefile.toml`, `lake-manifest.json`.
