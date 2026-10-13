"""Записи проекта с шапкой: разбор, запись, заготовки.

Один вид документа на весь проект: запись результата `results/R*.md`, идея `ideas/I*.md`,
карточка теоремы `sources/cards/S*.md`, опыт `experiments/E*/README.md`. Шапка — плоское
YAML-подмножество `ключ: значение`, списки в квадратных скобках. Здесь же словари статусов
и заготовки новых файлов, поэтому `proj.py` и `lit.py` видят записи одинаково.

Пути записей выводятся из корня проекта: `proj.py` и `lit.py` передают свой, тесты —
временный каталог.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RESULT_STATUS = ['цель', 'набросок', 'доказано', 'опровергнуто']
IDEA_STATUS = ['новая', 'выдержала критику', 'в работе', 'отвергнута', 'перенесена']
# Аксиомы, на которые разрешено опираться, если project.toml не задаёт свой список.
DEFAULT_AXIOMS = ['propext', 'Classical.choice', 'Quot.sound']
# Вид записи: папка и префикс номера.
FOLDERS = {'result': ('results', 'R'), 'idea': ('ideas', 'I'), 'card': ('sources/cards', 'S')}
# Поля шапки, которые всегда списки, даже когда в записи стоит одно значение.
MANY = ('depends', 'sources', 'lean')


@dataclass
class Doc:
    path: Path
    meta: dict
    body: str

    @property
    def id(self) -> str | None:
        """Номер записи из имени файла; None, если имя не подходит под схему."""
        found = re.match(r'[A-Z]+\d+', self.path.stem)
        return found.group(0) if found else None

    def many(self, key: str) -> list[str]:
        value = self.meta.get(key) or []
        return value if isinstance(value, list) else [value]


def read_doc(path: Path) -> Doc:
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    if not text.startswith('---\n'):
        return Doc(path, {}, text)
    head, _, body = text[4:].partition('\n---\n')
    meta: dict = {}
    for line in head.split('\n'):
        key, colon, value = line.partition(':')
        if not colon or not key.strip() or key.lstrip().startswith('#'):
            continue
        value = value.strip()
        meta[key.strip()] = [item.strip() for item in value[1:-1].split(',') if item.strip()] \
            if value.startswith('[') and value.endswith(']') else value
    return Doc(path, meta, body)


def write_doc(doc: Doc) -> None:
    lines = [f"{key}: [{', '.join(value)}]" if isinstance(value, list) else f'{key}: {value}'.rstrip()
             for key, value in doc.meta.items()]
    doc.path.write_text('---\n' + '\n'.join(lines) + '\n---\n' + doc.body, encoding='utf-8', newline='\n')


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def docs(root: Path, folder: str, prefix: str) -> list[Doc]:
    paths = [path for path in (root / folder).glob(f'{prefix}*.md') if re.fullmatch(rf'{prefix}\d+', path.stem)]
    return [read_doc(path) for path in sorted(paths, key=lambda path: int(path.stem[len(prefix):]))]


def find_doc(root: Path, ident: str) -> Doc:
    """Запись по номеру: R07 — результат, I12 — идея, S31 — карточка источника."""
    folder = {prefix: name for name, prefix in FOLDERS.values()}.get(ident[:1].upper())
    path = root / (folder or '') / f'{ident.upper()}.md'
    if not folder or not path.is_file():
        raise SystemExit(f'Нет записи {ident}.')
    return read_doc(path)


def save_doc(root: Path, ident: str, key: str, value: str) -> str:
    """Меняет поле шапки; списком становится поле, которое уже список или перечислено в MANY."""
    doc = find_doc(root, ident)
    many = isinstance(doc.meta.get(key), list) or key in MANY
    doc.meta[key] = [item.strip() for item in value.split(',') if item.strip()] if many else value
    write_doc(doc)
    return f'{doc.id}: {key} = {value}'


# ---------- заготовки ----------

RESULT = '''---
id: {id}
title: {title}
status: цель
depends: [{depends}]
sources: []
lean: []
review:
fidelity:
---

## Утверждение

Точная формулировка: объекты, гипотезы, вывод, область определения.

## Доказательство

Пока нет.

## Границы

Что утверждение не покрывает; какие гипотезы существенны и почему.
'''

IDEA = '''---
id: {id}
title: {title}
target: {target}
status: новая
created: {today}
critic:
---

## Формулировка

Гипотезы, вывод, область определения.

## Набросок

Шаги по одному. У каждого шага опора: запись R…, карточка источника S…, стандартный факт
с названием или «пробел».

## Чем убить

Самая дешёвая проверка, которая опровергла бы идею: частный случай, расчёт, известный пример.

## Следующий шаг
'''

CARD = '''---
source: {source}
verified:
---

# {title}

## Теорема N, с. P

**Гипотезы.** Все, включая соглашения раздела и статьи («всюду далее …»).

**Вывод.**

**Определения, от которых зависит формулировка.** Как они даны в этой работе.

**Применимость.** Где используется (R…) и как там проверена каждая гипотеза.
'''

EXPERIMENT = '''---
id: {id}
title: {title}
idea: {idea}
status: начат
---

## Вопрос

Что проверяем и какой исход опроверг бы гипотезу.

## Запуск

`uv run experiments/{id}/run.py`

## Проверка метода

Случай с известным ответом и расхождение с ним.

## Результат

Таблица чисел с оценкой погрешности. Вывод — «согласуется» или «не согласуется», не «доказано».
'''

RUN_PY = '''# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "mpmath", "sympy"]
# ///
"""{title}"""
'''


def create(root: Path, kind: str, title: str, **fields) -> Path:
    """Создаёт запись со следующим свободным номером; номер занимается созданием файла."""
    if kind == 'experiment':
        folder, prefix = root / 'experiments', 'E'
        taken = [int(path.name[1:]) for path in folder.glob('E*') if re.fullmatch(r'E\d+', path.name)]
    else:
        subfolder, prefix = FOLDERS[kind]
        folder = root / subfolder
        taken = [int(path.stem[len(prefix):]) for path in folder.glob(f'{prefix}*.md')
                 if re.fullmatch(rf'{prefix}\d+', path.stem)]
    folder.mkdir(parents=True, exist_ok=True)
    if kind == 'card':
        path = folder / f"{fields['source']}.md"
        with path.open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(CARD.format(source=fields['source'], title=title))
        return path
    number = max(taken, default=0) + 1
    while True:
        ident = f'{prefix}{number:02d}'
        try:
            if kind == 'experiment':
                (folder / ident).mkdir()
                (folder / ident / 'README.md').write_text(
                    EXPERIMENT.format(id=ident, title=title, idea=fields.get('idea', '')),
                    encoding='utf-8', newline='\n')
                (folder / ident / 'run.py').write_text(RUN_PY.format(title=title), encoding='utf-8', newline='\n')
                return folder / ident / 'README.md'
            stub = RESULT if kind == 'result' else IDEA
            path = folder / f'{ident}.md'
            with path.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(stub.format(id=ident, title=title, today=f'{date.today():%Y-%m-%d}',
                                         depends=fields.get('depends', ''), target=fields.get('target', '')))
            return path
        except FileExistsError:
            number += 1


def card_for(root: Path, code: str, title: str) -> Path:
    """Карточка теоремы источника; `title` — строка шапки, собранная из реестра."""
    return create(root, 'card', title, source=code.upper())
