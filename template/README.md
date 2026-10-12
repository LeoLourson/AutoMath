# __TITLE__

Постановка — [question.md](question.md). Результаты, их статусы и зависимости —
[blueprint.md](blueprint.md). Идеи — [ideas/](ideas/README.md). Источники —
[sources/](sources/README.md). Статья — `paper/main.tex`.

## С чего начать

1. `lake exe cache get`, затем `lake build`: загрузка готовой сборки Mathlib и сборка
   библиотеки `__LIB__`.
2. `python scripts/proj.py doctor` — проверка окружения. Первый запуск MCP-серверов `lit`
   и `proj` ставит зависимости через `uv`; чтобы не ждать этого в редакторе, один раз
   выполните `uv run scripts/lit.py list`.
3. Заполните `question.md` и `PROJECT.md`.
4. `python scripts/proj.py check` — должно пройти с одним замечанием о примере.
5. Удалите пример: запись `results/R01.md` и теорему `sq_add` из `__LIB__/Basic.lean`,
   затем `python scripts/proj.py sync`.

Дальше работа идёт командами: `/sources тема` собирает литературу, `/ideas` предлагает
и проверяет подходы, `/day` ведёт ежедневный цикл.

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
| `scripts/` | `proj.py` — записи, проверки, сводки; `lit.py` — источники; MCP-серверы |
| `.claude/` | агенты, команды, скиллы оформления текста |
| `output/` | сборки, полные тексты, индекс; в Git не входит |

## Команды

| Команда | Что делает |
| --- | --- |
| `/day` | ежедневный цикл |
| `/ideas [цель]` | идеи и их критика |
| `/referee R07` | рецензия доказательства |
| `/formalize R07` | формализация и проверка соответствия |
| `/fidelity` | проверка соответствия формулировок Lean |
| `/sources [тема]` | поиск и загрузка источников |
| `/transcribe S12` | PDF источника в LaTeX |
| `/exposition` | обновление статьи |

## Проверки

```
python scripts/proj.py check          # всё, включая lake build и аксиомы
python scripts/proj.py check --fast   # без Lean
python -m unittest discover tests     # сами инструменты
```

Версии Lean и Mathlib закреплены в `lean-toolchain`, `lakefile.toml`, `lake-manifest.json`.
