"""Окружение проекта: внешние программы, библиотеки Python, версии Lean и Mathlib."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host import lean  # noqa: E402

# Без этих библиотек работают сами инструменты, но не поиск по текстам источников.
OPTIONAL = ('numpy', 'onnxruntime', 'tokenizers', 'huggingface_hub', 'pymupdf', 'certifi', 'mcp')


def doctor(root: Path, library: str) -> int:
    """Печатает отчёт и возвращает 1, если нет lake или git."""
    lines, bad = [], 0
    for label, command in (('lake', None), ('git', ['git', '--version']), ('uv', ['uv', '--version']),
                           ('pdflatex', ['pdflatex', '--version'])):
        try:
            _, output = lean.run(root, command or [lean.lake(), '--version'], timeout=60)
            lines.append(f"{label}: {output.strip().split(chr(10))[0][:90]}")
        except (FileNotFoundError, SystemExit):
            lines.append(f'{label}: НЕ НАЙДЕН')
            bad += label in ('lake', 'git')
    lines.append(f'python: {sys.version.split()[0]}')
    for module in OPTIONAL:
        try:
            __import__(module)
        except ImportError:
            lines.append(f'модуль {module}: нет — нужен scripts/sources/lit.py; '
                         '`uv run scripts/sources/lit.py …` поставит сам')
    toolchain = (root / 'lean-toolchain').read_text(encoding='utf-8').strip()
    lines.append(f'lean-toolchain: {toolchain}; библиотека: {library}')
    if not (root / '.lake' / 'packages' / 'mathlib').exists():
        lines.append('Mathlib не загружен: lake exe cache get')
    print('\n'.join(lines))
    return 1 if bad else 0
