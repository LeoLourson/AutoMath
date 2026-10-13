"""Запрещённое в библиотеке Lean: `sorry`, `admit`, `axiom`, `native_decide`, отключённые линтеры."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import records  # noqa: E402
from check import declarations  # noqa: E402


def lean_files(root: Path, library: str) -> list[Path]:
    """Файлы библиотеки: каталог с её именем и корневой файл оглавления."""
    return sorted((root / library).rglob('*.lean')) + [root / f'{library}.lean']


def check_hygiene(root: Path, library: str) -> tuple[list[str], list[str]]:
    """Ошибки — запрещённые конструкции, замечания — отключённые линтеры."""
    errors, warnings = [], []
    for path in lean_files(root, library):
        if not path.exists():
            errors.append(f'нет файла {records.rel(root, path)}')
            continue
        text = declarations.strip_comments(path.read_text(encoding='utf-8'))
        for number, line in enumerate(text.split('\n'), 1):
            if found := re.search(r'\b(sorry|admit|native_decide)\b|^\s*(axiom)\b', line):
                errors.append(f'{records.rel(root, path)}:{number}: в библиотеке запрещено '
                              f'`{found.group(1) or found.group(2)}`')
            if re.search(r'set_option\s+linter\.\S+\s+false', line):
                warnings.append(f'{records.rel(root, path)}:{number}: отключён линтер')
    return errors, warnings
