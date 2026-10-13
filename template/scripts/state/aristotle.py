"""Пакет для сервиса Aristotle и сверка его ответа с заготовкой.

Сервис необязателен. Пакет — копия библиотеки с закреплёнными версиями и заготовкой, в
которой остались `sorry`. Ответ сверяется с заготовкой, но не переносится: формулировки,
`sorry`, `axiom` и изменённые файлы должны быть проверены человеком и общими проверками
проекта. Ничего в библиотеке проекта этот модуль не меняет.
"""
from __future__ import annotations

import re
import shutil
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import records  # noqa: E402
from check import declarations  # noqa: E402


def pack(root: Path, library: str, name: str, skeleton: str) -> list[str]:
    """Собирает `output/aristotle/<имя>`: библиотеку, версии и заготовку как новый модуль."""
    source = Path(skeleton)
    source = source if source.is_absolute() else root / source
    package = root / 'output' / 'aristotle' / name
    if package.exists():
        raise SystemExit(f'{records.rel(root, package)} уже есть: выберите другое имя.')
    (package / library).mkdir(parents=True)
    for item in ('lakefile.toml', 'lean-toolchain', 'lake-manifest.json', f'{library}.lean'):
        shutil.copy2(root / item, package / item)
    shutil.copytree(root / library, package / library, dirs_exist_ok=True)
    shutil.copy2(source, package / library / source.name)
    shutil.copy2(source, package / 'skeleton.lean')
    with (package / f'{library}.lean').open('a', encoding='utf-8', newline='\n') as root_file:
        root_file.write(f'import {library}.{source.stem}\n')
    prompt = package / 'prompt.md'
    prompt.write_text(
        f'# Task\n\nWork in the attached Lean project with its pinned Lean and Mathlib (see `lean-toolchain`, '
        f'`lake-manifest.json`). The only `sorry`s are in `{library}/{source.name}`.\n\n'
        'Do not change the statements or definitions given there or anywhere else in the project; no new '
        'axioms. You may add auxiliary lemmas. If a statement is false, say so and give the obstruction.\n\n'
        '## Setting\n\n## Proof sketch\n', encoding='utf-8', newline='\n')
    return [f'пакет: {records.rel(root, package)}',
            f'заготовка: {records.rel(root, package / library / source.name)}',
            f'допишите {records.rel(root, prompt)}: формулировка, опоры в проекте, набросок доказательства']


def accept(root: Path, library: str, name: str, result: str) -> int:
    """Сверяет ответ с заготовкой: формулировки, `sorry`, `axiom`, изменённые файлы."""
    package = root / 'output' / 'aristotle' / name
    answer = Path(result) if Path(result).is_absolute() else root / result
    if answer.is_file():
        folder = package.parent / (name + '-result')
        with tarfile.open(answer) as archive:
            archive.extractall(folder, filter='data')
        answer = folder
    skeleton = (package / 'skeleton.lean').read_text(encoding='utf-8')
    module = next((path.name for path in (package / library).glob('*.lean')
                   if path.read_text(encoding='utf-8') == skeleton), None)
    returned = {path.relative_to(base).as_posix(): path
                for base in [next((p.parent for p in answer.rglob(f'{library}.lean')), answer)]
                for path in base.rglob('*.lean')}
    bad = 0
    target = returned.get(f'{library}/{module}')
    if target is None:
        print(f'ОШИБКА: в ответе нет {library}/{module}')
        return 1
    report = declarations.compare(skeleton, target.read_text(encoding='utf-8'))
    for key, label in (('changed', 'формулировка изменена'), ('missing', 'объявление пропало'),
                       ('sorry', 'остался sorry')):
        for decl in report[key]:
            print(f'ОШИБКА: {label}: {decl}')
            bad += 1
    print(f"добавлено объявлений: {len(report['added'])}")
    for relative, path in sorted(returned.items()):
        original = package / relative
        text = path.read_text(encoding='utf-8')
        if re.search(r'^\s*axiom\b', declarations.strip_comments(text), re.M):
            print(f'ОШИБКА: axiom в {relative}')
            bad += 1
        if relative != f'{library}/{module}' and (not original.exists()
                                                  or original.read_text(encoding='utf-8') != text):
            print(f'изменён или добавлен файл: {relative}')
    print('Сверка пройдена: переносите модуль в библиотеку, затем lake build и proj.py check.' if not bad
          else f'Сверка не пройдена, ошибок: {bad}.')
    return 1 if bad else 0
