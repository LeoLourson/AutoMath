# Changelog

## 0.1.0 — первый публичный релиз (2026-10-31)

Набор для исследовательского проекта по одной математической теме, который ведут агенты
Claude Code или DeepSeek Harness: постановка, источники, идеи с независимой критикой,
доказательства с рецензией, формализация в Lean 4 с проверкой соответствия, статья.
От темы шаблон не зависит: всё тематическое живёт в двух файлах нового проекта,
`question.md` и `PROJECT.md`.

- **`template/`** — проект-заготовка: Lean 4 с Mathlib (`lakefile.toml`, `lean-toolchain`,
  `__LIB__/Basic.lean`), статья в LaTeX (`paper/main.tex`), правила агентов (`AGENTS.md`,
  `CLAUDE.md`, `DEEPSEEK.md`), роли (`.claude/agents/`: генератор идей, критик,
  экспериментатор, рецензент, формализатор, проверяющий соответствие, поиск по Mathlib,
  поиск литературы, транскрипция PDF, сверка карточек), команды (`/day`, `/ideas`,
  `/referee`, `/formalize`, `/fidelity`, `/sources`, `/transcribe`, `/exposition`) и
  навыки слоёв математического текста (`math-rigor`, `paper-canvas`, `shkalikov-style`,
  `paper-de-ai`, `math-typeset`).
- **`template/scripts/`** — инструменты проекта: записи с шапками, сводки, аудит аксиом,
  отпечатки формулировок (`state/proj.py`, `state/summaries.py`, `state/aristotle.py`),
  источники — zbMATH, arXiv, MathNet, DOI, транскрипции, гибридный поиск по полным
  текстам (`sources/`), проверки (`check/`), те же действия как MCP-серверы `proj` и
  `lit` (`state/mcp.py`, `sources/mcp.py`).
- **`template/scripts/host/harness.py`** — адаптер DeepSeek Harness: собирает skills,
  роли и MCP из `.claude/` и `.mcp.json`, готовит Cordis patch и производные
  `.dsh/skills/`, запускает Web и Headless. Имена команд и ролей адаптер не содержит —
  состав берётся из тех же каталогов, что читает Claude Code.
- **`tools/create.py`** — создание нового проекта из заготовки с подстановкой имени
  библиотеки и названия темы (`--lib`, `--title`, `--pins-from`) и обновление инструментов
  существующего (`--update`, `--dry-run`): переписывает только то, чем владеет шаблон,
  постановку, записи, идеи, источники, библиотеку Lean и статью не трогает.
- **`tests/`** — проверки без сети и без Lean: инструменты проекта, согласованность
  документации с составом `.claude/`, создание и обновление проекта (`tests/kit`),
  сверка patch со схемами Harness (`tests/template/harness_runtime.mjs`).
- **CI** — матрица ubuntu/windows на Python 3.11 и 3.14 плюс контрактная проверка
  адаптера с Node.
