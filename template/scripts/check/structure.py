"""Наличие обязательных файлов проекта и согласие project.toml с lakefile.toml."""
from __future__ import annotations

from pathlib import Path

# Ядро проекта: без этого инструменты работать не могут.
REQUIRED = ('AGENTS.md', 'PROJECT.md', 'question.md', 'project.toml', 'lakefile.toml',
            'lean-toolchain', 'sources/papers.json', '.gitignore')
# Имя библиотеки в самой заготовке ещё не подставлено.
PLACEHOLDER = '__LIB__'


def missing(root: Path, library: str) -> list[str]:
    """Каких обязательных файлов нет и совпадает ли имя библиотеки с lakefile.toml."""
    errors = [f'нет файла {name}' for name in REQUIRED if not (root / name).exists()]
    if not (root / f'{library}.lean').exists():
        errors.append(f'нет файла {library}.lean')
    lakefile = (root / 'lakefile.toml').read_text(encoding='utf-8') if (root / 'lakefile.toml').exists() else ''
    declared = lakefile.replace(PLACEHOLDER, library)
    if f'name = "{library}"' not in declared:
        errors.append(f'lakefile.toml не объявляет библиотеку {library} из project.toml')
    return errors

