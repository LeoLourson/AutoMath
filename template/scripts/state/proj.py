"""Состояние проекта: заготовки записей, шапки, сводки, проверки, аксиомы, статья.

Записи результатов лежат в `results/`, идеи — в `ideas/`, карточки источников — в
`sources/cards/`. Статус утверждения хранится в шапке его записи; `blueprint.md`,
`ideas/README.md` и `sources/catalog.md` собираются из шапок и реестра. Разбор шапки — общий
с `sources/lit.py` (records.py), проверки — в `check/`, тексты сводок записей — в
`state/summaries.py`, каталог источников — в `sources/catalog.py`, `lake` — в `host/lean.py`.
Слой состояния верхний: он может импортировать `records`, `host`, `check` и `sources`.
Команды: python scripts/state/proj.py -h.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import records  # noqa: E402
from check import declarations, doctor as environment, hygiene, results as checks, structure  # noqa: E402
from check import summaries as audit  # noqa: E402
from host import lean  # noqa: E402
from sources import catalog, paths  # noqa: E402
from sources import registry as source_registry  # noqa: E402
from state import aristotle, summaries  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]  # scripts/state/proj.py -> корень проекта
LIB = ''
AXIOMS: set[str] = set()
PAPER = 'paper/main.tex'


def configure(root: Path) -> None:
    """Читает project.toml; тесты вызывают с временным каталогом.

    Заодно настраивает корень слоя источников: `sources.catalog` вызывается отсюда в том же
    процессе, поэтому порядок импортов не должен решать, на какой проект он смотрит.
    """
    global ROOT, LIB, AXIOMS, PAPER
    ROOT = Path(root)
    config = tomllib.loads((ROOT / 'project.toml').read_text(encoding='utf-8'))
    LIB = config['project']['lib']
    AXIOMS = set(config.get('lean', {}).get('allowed_axioms', records.DEFAULT_AXIOMS))
    PAPER = config.get('paper', {}).get('main', PAPER)
    paths.configure(ROOT)


configure(ROOT)

# Общий разбор записей живёт в records.py; здесь только привязка к корню проекта.
Doc = records.Doc


def rel(path: Path) -> str:
    return records.rel(ROOT, path)


def docs(folder: str, prefix: str) -> list[Doc]:
    return records.docs(ROOT, folder, prefix)


def find_doc(ident: str) -> Doc:
    return records.find_doc(ROOT, ident)


def new(kind: str, title: str, **fields) -> Path:
    return records.create(ROOT, kind, title, **fields)


def set_field(ident: str, key: str, value: str) -> str:
    vocabulary = {'R': records.RESULT_STATUS, 'I': records.IDEA_STATUS}.get(ident[:1].upper())
    if key == 'status' and vocabulary and value not in vocabulary:
        raise SystemExit(f'Статус «{value}» не из списка: {", ".join(vocabulary)}.')
    return records.save_doc(ROOT, ident, key, value)


# ---------- проверки ----------

def registry() -> tuple[set[str], set[str], set[str]]:
    """Коды источников реестра; коды с карточкой; коды с карточкой, сверенной по PDF.

    Факты считает слой источников (`sources/registry.py::facts`), чтобы у каталога и у
    проверки было одно правило, а не два расходящихся.
    """
    facts = source_registry.facts()
    return facts.codes, facts.carded, facts.verified


def check(fast: bool) -> tuple[int, list[str]]:
    """Все проверки проекта: структура, шапки, сводки, гигиена, а без `--fast` ещё Lean."""
    errors, warnings, passed = [], [], []
    errors += structure.missing(ROOT, LIB)

    index = declarations.library(ROOT, LIB)
    results, ideas = docs('results', 'R'), docs('ideas', 'I')
    sources, carded, verified = registry()
    for found_errors, found_warnings in (checks.check_records(ROOT, results, sources, carded, index, verified),
                                         checks.check_ideas(ROOT, ideas, {doc.id for doc in results}),
                                         hygiene.check_hygiene(ROOT, LIB)):
        errors += found_errors
        warnings += found_warnings
    errors += [f'карточка sources/cards/{code}.md: источника нет в реестре' for code in sorted(carded - sources)]
    passed.append(f'записи: {len(results)}, идеи: {len(ideas)}, источники: {len(sources)}, '
                  f'объявлений Lean: {len(index)}')

    errors += audit.stale(ROOT, summaries.summaries(ROOT, LIB, results, ideas, index))
    # Каталог источников сверяется той же проверкой свежести; его текст собирает чистая
    # функция, поэтому проверка по-прежнему ничего не пишет.
    errors += audit.stale(ROOT, {rel(paths.CATALOG): catalog.text()})

    if not (ROOT / '.git').exists():
        warnings.append('каталог не под Git: git init')
    else:
        code, _ = lean.run(ROOT, ['git', 'check-ignore', 'output/probe'])
        if code:
            errors.append('output/ не исключён из Git')
        code, output = lean.run(ROOT, ['git', 'diff', '--check'])
        if code and output.strip():
            warnings.append('git diff --check: ' + ' '.join(output.split())[:300])

    if fast:
        passed.append('Lean не запускался (--fast)')
    else:
        code, output = lean.run(ROOT, [lean.lake(), 'build'])
        if code:
            errors.append('lake build не прошёл: ' + ' '.join(output.split())[-700:])
        else:
            noisy = [line for line in output.split('\n') if 'warning:' in line]
            warnings += [f'lake build: {line.strip()[:200]}' for line in noisy[:10]]
            passed.append('lake build')
            names = sorted({declarations.resolve(index, name).name for doc in results for name in doc.many('lean')
                            if declarations.resolve(index, name)})
            found = lean.audit(ROOT, LIB, names, AXIOMS)
            errors += found
            if not found:
                passed.append(f'аксиомы: {len(names)} объявлений, только {", ".join(sorted(AXIOMS))}')

    report = [f'пройдено: {line}' for line in passed] + [f'замечание: {line}' for line in warnings] \
        + [f'ОШИБКА: {line}' for line in errors] + [f'Итог: ошибок {len(errors)}, замечаний {len(warnings)}.']
    return (1 if errors else 0), report


# ---------- сводки ----------

def views(results: list[Doc], ideas: list[Doc], index: dict) -> dict[str, str]:
    """Тексты собираемых файлов по их путям."""
    return summaries.summaries(ROOT, LIB, results, ideas, index)


def sync() -> list[str]:
    """Собирает сводки записей и каталог источников в этом же процессе."""
    index = declarations.library(ROOT, LIB)
    written = []
    for name, text in views(docs('results', 'R'), docs('ideas', 'I'), index).items():
        (ROOT / name).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / name).write_text(text, encoding='utf-8', newline='\n')
        written.append(name)
    # Каталог собирает слой источников: без подпроцесса и разбора его вывода. Корень слоя
    # выставлен в configure, поэтому он смотрит на тот же проект.
    try:
        catalog.catalog()
    except (OSError, ValueError) as error:
        written.append(f'sources/catalog.md не собран: {error}')
    else:
        written.append('sources/catalog.md')
    return written


# ---------- статья ----------

def tex(source: str) -> int:
    """Два прохода pdflatex в output/ и предупреждения из журнала."""
    path = ROOT / source
    if not shutil.which('pdflatex'):
        print('pdflatex не найден.')
        return 1
    (ROOT / 'output').mkdir(exist_ok=True)
    for attempt in (1, 2):
        code, output = lean.run(ROOT, ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
                                       '-output-directory=output', source])
        if code:
            print(f'pdflatex не прошёл (проход {attempt}):')
            print('\n'.join(line for line in output.split('\n') if re.search(r':\d+: |^! ', line))[:1500])
            return 1
    log = (ROOT / 'output' / (path.stem + '.log')).read_text(encoding='utf-8', errors='replace')
    found = [line for line in log.split('\n') if re.search(r'undefined|Overfull|LaTeX Warning|Package .* Warning', line)]
    for line in found:
        print('замечание:', line.strip())
    print(f'PDF: output/{path.stem}.pdf; замечаний {len(found)}')
    return 0


# ---------- действия, общие для командной строки и MCP-сервера ----------

def create(kind: str, title: str, depends: str = '', target: str = '', idea: str = '') -> str:
    """Создаёт запись и возвращает путь к ней; для card title — код источника."""
    if kind != 'card':
        return rel(new(kind, title, depends=depends, target=target, idea=idea))
    rows = source_registry.load()
    row = next((row for row in rows if row['code'] == title.upper()), None)
    if row is None:
        raise SystemExit(f'Источника {title} нет в реестре.')
    heading = f"{row['title']}\n\n{row['authors']}. {row['version']}. [Источник]({row['url']})."
    return rel(new('card', heading, source=row['code']))


def declarations_of(items: list[str]) -> tuple[dict, list]:
    """Объявления по полным именам или номерам записей; пустой список — все записи."""
    index = declarations.library(ROOT, LIB)
    names = []
    for item in items or [doc.id for doc in docs('results', 'R')]:
        names += find_doc(item).many('lean') if re.fullmatch(r'[Rr]\d+', item) else [item]
    decls = [declarations.resolve(index, name) for name in names]
    if None in decls:
        raise SystemExit('Нет в библиотеке: ' + ', '.join(n for n, d in zip(names, decls) if d is None))
    return index, decls


def audit_report(items: list[str]) -> tuple[int, str]:
    names = sorted({decl.name for decl in declarations_of(items)[1]})
    errors = lean.audit(ROOT, LIB, names, AXIOMS)
    return (1 if errors else 0), '\n'.join(f'ОШИБКА: {line}' for line in errors) or \
        f'Аксиомы в порядке: {len(names)} объявлений, только {", ".join(sorted(AXIOMS))}.'


def fingerprint_report(item: str) -> str:
    index, decls = declarations_of([item])
    lines = []
    for decl in decls:
        value, used = declarations.fingerprint(index, decl.name)
        lines.append(f'{decl.name} {value} (определений проекта в формулировке: {len(used)})')
    return '\n'.join(lines + [f'отпечаток записи: '
                              f'{declarations.record_fingerprint(index, [decl.name for decl in decls])}'])


def statement_report(item: str) -> str:
    return '\n'.join(f'{decl.file}:{decl.line}\n{decl.statement}\n' for decl in declarations_of([item])[1])


def overview() -> str:
    """Записи и идеи одной строкой каждая: для выбора, что читать целиком."""
    lines = [f"{doc.id} · {doc.meta.get('status')} · {doc.meta.get('title')}"
             + (f" · Lean: {', '.join(doc.many('lean'))}" if doc.many('lean') else '')
             + (f" · зависит от {', '.join(doc.many('depends'))}" if doc.many('depends') else '')
             for doc in docs('results', 'R')]
    lines += [f"{doc.id} · {doc.meta.get('status')} · к {doc.meta.get('target')} · {doc.meta.get('title')}"
              + (f" · критика: {doc.meta.get('critic')}" if doc.meta.get('critic') else '')
              for doc in docs('ideas', 'I')]
    return '\n'.join(lines) or 'Записей и идей пока нет.'


# ---------- командная строка ----------

def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', type=Path, default=ROOT,
                        help='корень проекта, по умолчанию каталог над scripts/')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('new', help='создать запись со следующим номером')
    p.add_argument('kind', choices=['result', 'idea', 'card', 'experiment'])
    p.add_argument('title', help='название; для card — код источника, например S4')
    p.add_argument('--depends', default='', help='для result: записи через запятую')
    p.add_argument('--target', default='', help='для idea: запись или вопрос, к которому она относится')
    p.add_argument('--idea', default='', help='для experiment: идея, которую он проверяет')
    p = commands.add_parser('set', help='изменить поле шапки: set R05 status доказано')
    p.add_argument('id')
    p.add_argument('key')
    p.add_argument('value')
    commands.add_parser('sync', help='пересобрать blueprint.md, ideas/README.md, каталог источников')
    p = commands.add_parser('check', help='все проверки проекта')
    p.add_argument('--fast', action='store_true', help='без lake build и аудита аксиом')
    p = commands.add_parser('audit', help='аксиомы объявлений: записи или имена')
    p.add_argument('names', nargs='*')
    p = commands.add_parser('fingerprint', help='отпечаток формулировок записи или объявления')
    p.add_argument('name')
    p = commands.add_parser('statement', help='формулировка объявления Lean, как её видит разбор')
    p.add_argument('name')
    p = commands.add_parser('tex', help='собрать LaTeX-файл в output/')
    p.add_argument('file', nargs='?')
    commands.add_parser('doctor', help='проверить окружение')
    p = commands.add_parser('aristotle', help='пакет для Aristotle и сверка ответа')
    p.add_argument('action', choices=['pack', 'accept'])
    p.add_argument('name')
    p.add_argument('file', help='pack: заготовка .lean с sorry; accept: архив или папка ответа')
    args = parser.parse_args()
    configure(args.root)

    if args.command == 'new':
        print(create(args.kind, args.title, args.depends, args.target, args.idea))
    elif args.command == 'set':
        print(set_field(args.id, args.key, args.value))
    elif args.command == 'sync':
        print('\n'.join(sync()))
    elif args.command == 'check':
        code, report = check(args.fast)
        print('\n'.join(report))
        return code
    elif args.command == 'audit':
        code, report = audit_report(args.names)
        print(report)
        return code
    elif args.command == 'fingerprint':
        print(fingerprint_report(args.name))
    elif args.command == 'statement':
        print(statement_report(args.name))
    elif args.command == 'tex':
        return tex(args.file or PAPER)
    elif args.command == 'doctor':
        return environment.doctor(ROOT, LIB)
    elif args.action == 'pack':
        print('\n'.join(aristotle.pack(ROOT, LIB, args.name, args.file)))
    else:
        return aristotle.accept(ROOT, LIB, args.name, args.file)
    return 0


if __name__ == '__main__':
    sys.exit(main())
