"""Проект: заготовки записей, сводки, проверки, аудит аксиом, сборка статьи, пакеты для Aristotle.

Статус утверждения хранится в шапке его записи в results/; blueprint.md и ideas/README.md
собираются из шапок. Команды: python scripts/proj.py -h.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leandecl  # noqa: E402
import records  # noqa: E402

RESULT_STATUS = records.RESULT_STATUS
IDEA_STATUS = records.IDEA_STATUS
DEFAULT_AXIOMS = ['propext', 'Classical.choice', 'Quot.sound']

# Корень проекта подставляется из project.toml; подчёркивание отличает это имя от
# модульной переменной `ROOT`, по которой records строит пути записей.
_ROOT = Path(__file__).resolve().parent.parent
LIB = ''
AXIOMS: set[str] = set()
PAPER = 'paper/main.tex'


def configure(root: Path) -> None:
    """Читает project.toml; тесты вызывают с временным каталогом."""
    global _ROOT, LIB, AXIOMS, PAPER
    _ROOT = Path(root)
    config = tomllib.loads((_ROOT / 'project.toml').read_text(encoding='utf-8'))
    LIB = config['project']['lib']
    AXIOMS = set(config.get('lean', {}).get('allowed_axioms', DEFAULT_AXIOMS))
    PAPER = config.get('paper', {}).get('main', PAPER)


# Общий разбор записей живёт в records.py; здесь только привязка к корню проекта.
Doc = records.Doc


def rel(path: Path) -> str:
    return records.rel(_ROOT, path)


def find_doc(ident: str) -> Doc:
    return records.find_doc(_ROOT, ident)


def docs(folder: str, prefix: str) -> list[Doc]:
    return records.docs(_ROOT, folder, prefix)


def new(kind: str, title: str, **fields) -> Path:
    return records.create(_ROOT, kind, title, **fields)


def set_field(ident: str, key: str, value: str) -> str:
    vocabulary = {'R': RESULT_STATUS, 'I': IDEA_STATUS}.get(ident[:1].upper())
    if key == 'status' and vocabulary and value not in vocabulary:
        raise SystemExit(f'Статус «{value}» не из списка: {", ".join(vocabulary)}.')
    return records.save_doc(_ROOT, ident, key, value)


# ---------- Lean ----------

def lake() -> str:
    found = shutil.which('lake')
    if found:
        return found
    fallback = Path.home() / '.elan' / 'bin' / ('lake.exe' if os.name == 'nt' else 'lake')
    if fallback.exists():
        return str(fallback)
    raise SystemExit('lake не найден: установите elan, https://lean-lang.org/install')


def run(command: list[str], timeout: int = 3600) -> tuple[int, str]:
    # stdin закрыт: под MCP-сервером дочерний процесс иначе наследует его канал и на Windows зависает
    done = subprocess.run(command, cwd=_ROOT, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')


def lean_files() -> list[Path]:
    return sorted((_ROOT / LIB).rglob('*.lean')) + [_ROOT / f'{LIB}.lean']


def hygiene() -> tuple[list[str], list[str]]:
    """Запрещённое в библиотеке: sorry, admit, axiom, native_decide; отключённые линтеры."""
    errors, warnings = [], []
    for path in lean_files():
        if not path.exists():
            errors.append(f'нет файла {rel(path)}')
            continue
        text = leandecl.strip_comments(path.read_text(encoding='utf-8'))
        for number, line in enumerate(text.split('\n'), 1):
            if found := re.search(r'\b(sorry|admit|native_decide)\b|^\s*(axiom)\b', line):
                errors.append(f'{rel(path)}:{number}: в библиотеке запрещено `{found.group(1) or found.group(2)}`')
            if re.search(r'set_option\s+linter\.\S+\s+false', line):
                warnings.append(f'{rel(path)}:{number}: отключён линтер')
    return errors, warnings


def record_fingerprint(index: dict, names: list[str]) -> str:
    """Общий отпечаток формулировок записи."""
    parts = sorted(f'{name} {leandecl.fingerprint(index, name)[0]}' for name in names)
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:12]


def audit(names: list[str]) -> list[str]:
    """Проверяет в Lean, что объявления существуют и зависят только от разрешённых аксиом."""
    if not names:
        return []
    target = _ROOT / 'output' / 'Audit.lean'
    target.parent.mkdir(exist_ok=True)
    target.write_text(f'import {LIB}\n' + ''.join(f'#print axioms {name}\n' for name in names),
                      encoding='utf-8', newline='\n')
    code, output = run([lake(), 'env', 'lean', rel(target)])
    found = {name: {axiom.strip() for axiom in listed.split(',') if axiom.strip()}
             for name, listed in re.findall(r"'([^']+)' depends on axioms: \[(.*?)\]", output, re.S)}
    found.update({name: set() for name in re.findall(r"'([^']+)' does not depend on any axioms", output)})
    errors = []
    for name in names:
        if name not in found:
            errors.append(f'{name}: Lean не нашёл объявление или не смог его проверить')
        elif found[name] - AXIOMS:
            errors.append(f"{name}: лишние аксиомы {', '.join(sorted(found[name] - AXIOMS))}")
    if errors and code:
        errors.append('вывод Lean: ' + ' '.join(output.split())[:600])
    return errors


# ---------- проверки ----------

def check_records(records: list[Doc], sources: set[str], carded: set[str], index: dict,
                  verified: set[str] | None = None) -> tuple[list, list]:
    errors, warnings = [], []
    by_id = {doc.id: doc for doc in records}
    for doc in records:
        where, meta = rel(doc.path), doc.meta
        if meta.get('id') != doc.id:
            errors.append(f'{where}: поле id не совпадает с именем файла')
        if not meta.get('title'):
            errors.append(f'{where}: нет title')
        status = meta.get('status')
        if status not in RESULT_STATUS:
            errors.append(f'{where}: статус «{status}» не из списка: {", ".join(RESULT_STATUS)}')
        for dep in doc.many('depends'):
            if dep not in by_id:
                errors.append(f'{where}: зависит от несуществующей записи {dep}')
            elif by_id[dep].meta.get('status') == 'опровергнуто' and status != 'опровергнуто':
                errors.append(f'{where}: зависит от опровергнутой записи {dep}')
            elif status == 'доказано' and by_id[dep].meta.get('status') in ('цель', 'набросок') \
                    and not by_id[dep].many('lean'):
                warnings.append(f'{where}: доказательство опирается на недоказанную запись {dep}')
        for code in doc.many('sources'):
            if code not in sources:
                errors.append(f'{where}: источника {code} нет в sources/papers.json')
            elif code not in carded:
                warnings.append(f'{where}: у источника {code} нет карточки, его теорема не проверена')
            elif verified is not None and code not in verified:
                warnings.append(f'{where}: карточка источника {code} не сверена с PDF')
        names = doc.many('lean')
        missing = [name for name in names if leandecl.resolve(index, name) is None]
        errors += [f'{where}: объявления {name} нет в библиотеке' for name in missing]
        if names and not missing:
            stored = (meta.get('fidelity') or '').split()
            if not stored:
                warnings.append(f'{where}: соответствие формализации не проверено')
            elif stored[-1] != record_fingerprint(index, names):
                warnings.append(f'{where}: формулировка или определения изменились после проверки соответствия')
        if status == 'доказано' and not meta.get('review') and not names:
            warnings.append(f'{where}: доказательство без рецензии')

    state: dict[str, int] = {}

    def visit(ident: str, trail: list[str]) -> None:
        if state.get(ident) == 1:
            errors.append('цикл зависимостей: ' + ' → '.join(trail + [ident]))
        if ident in state or ident not in by_id:
            return
        state[ident] = 1
        for dep in by_id[ident].many('depends'):
            visit(dep, trail + [ident])
        state[ident] = 2

    for ident in by_id:
        visit(ident, [])
    return errors, warnings


def check_ideas(ideas: list[Doc], records: set[str]) -> tuple[list, list]:
    errors, warnings = [], []
    for doc in ideas:
        where, meta = rel(doc.path), doc.meta
        if meta.get('id') != doc.id:
            errors.append(f'{where}: поле id не совпадает с именем файла')
        if meta.get('status') not in IDEA_STATUS:
            errors.append(f"{where}: статус «{meta.get('status')}» не из списка: {', '.join(IDEA_STATUS)}")
        if not meta.get('target'):
            errors.append(f'{where}: нет target — вопроса или записи, к которой относится идея')
        if meta.get('status') == 'перенесена' and meta.get('result') not in records:
            errors.append(f'{where}: статус «перенесена» требует поля result с номером записи')
        if meta.get('status') == 'новая' and not meta.get('critic'):
            warnings.append(f'{where}: идея не прошла критика')
    return errors, warnings


def registry() -> tuple[set[str], set[str], set[str]]:
    """Коды источников реестра; коды с карточкой; коды с карточкой, сверенной по PDF."""
    import json
    path = _ROOT / 'sources' / 'papers.json'
    codes = {row['code'] for row in json.loads(path.read_text(encoding='utf-8'))} if path.exists() else set()
    cards = [records.read_doc(card) for card in (_ROOT / 'sources' / 'cards').glob('S*.md')]
    return (codes, {card.path.stem for card in cards},
            {card.path.stem for card in cards if card.meta.get('verified')})


def check(fast: bool) -> tuple[int, list[str]]:
    errors, warnings, passed = [], [], []
    for required in ('AGENTS.md', 'PROJECT.md', 'question.md', 'project.toml', 'lakefile.toml', 'lean-toolchain',
                     f'{LIB}.lean', 'sources/papers.json', '.gitignore'):
        if not (_ROOT / required).exists():
            errors.append(f'нет файла {required}')
    lakefile = (_ROOT / 'lakefile.toml').read_text(encoding='utf-8') if (_ROOT / 'lakefile.toml').exists() else ''
    if f'name = "{LIB}"' not in lakefile:
        errors.append(f'lakefile.toml не объявляет библиотеку {LIB} из project.toml')

    index = leandecl.library(_ROOT, LIB)
    records, ideas = docs('results', 'R'), docs('ideas', 'I')
    sources, carded, verified = registry()
    for found_errors, found_warnings in (check_records(records, sources, carded, index, verified),
                                         check_ideas(ideas, {doc.id for doc in records}), hygiene()):
        errors += found_errors
        warnings += found_warnings
    errors += [f'карточка sources/cards/{code}.md: источника нет в реестре' for code in sorted(carded - sources)]
    passed.append(f'записи: {len(records)}, идеи: {len(ideas)}, источники: {len(sources)}, '
                  f'объявлений Lean: {len(index)}')

    for name, text in views(records, ideas, index).items():
        current = (_ROOT / name).read_text(encoding='utf-8').replace('\r\n', '\n') if (_ROOT / name).exists() else ''
        if current != text:
            errors.append(f'{name} устарел: python scripts/proj.py sync')

    if not (_ROOT / '.git').exists():
        warnings.append('каталог не под Git: git init')
    else:
        code, output = run(['git', 'check-ignore', 'output/probe'])
        if code:
            errors.append('output/ не исключён из Git')
        code, output = run(['git', 'diff', '--check'])
        if code and output.strip():
            warnings.append('git diff --check: ' + ' '.join(output.split())[:300])

    if fast:
        passed.append('Lean не запускался (--fast)')
    else:
        code, output = run([lake(), 'build'])
        if code:
            errors.append('lake build не прошёл: ' + ' '.join(output.split())[-700:])
        else:
            noisy = [line for line in output.split('\n') if 'warning:' in line]
            warnings += [f'lake build: {line.strip()[:200]}' for line in noisy[:10]]
            passed.append('lake build')
            names = sorted({leandecl.resolve(index, name).name for doc in records for name in doc.many('lean')
                            if leandecl.resolve(index, name)})
            found = audit(names)
            errors += found
            if not found:
                passed.append(f'аксиомы: {len(names)} объявлений, только {", ".join(sorted(AXIOMS))}')

    report = [f'пройдено: {line}' for line in passed] + [f'замечание: {line}' for line in warnings] \
        + [f'ОШИБКА: {line}' for line in errors] + [f'Итог: ошибок {len(errors)}, замечаний {len(warnings)}.']
    return (1 if errors else 0), report


# ---------- сводки ----------

def views(records: list[Doc], ideas: list[Doc], index: dict) -> dict[str, str]:
    """Тексты собираемых файлов по их путям."""
    cell = lambda text: (text or '—').replace('|', '\\|')
    rows, edges, marks = [], [], []
    for doc in records:
        names = doc.many('lean')
        ok = names and all(leandecl.resolve(index, name) for name in names)
        fidelity = (doc.meta.get('fidelity') or '').split()
        if not names:
            match = '—'
        elif not fidelity:
            match = 'не проверено'
        elif ok and fidelity[-1] == record_fingerprint(index, names):
            match = ' '.join(fidelity[:-1])
        else:
            match = 'устарело'
        short = ', '.join('`' + name.split('.')[-1] + '`' for name in names)
        rows.append(f"| [{doc.id}](results/{doc.path.name}) | {cell(doc.meta.get('title'))} | "
                    f"{cell(doc.meta.get('status'))} | {cell(doc.meta.get('review'))} | "
                    f"{cell(short)} | {match} | {cell(', '.join(doc.many('depends')))} |")
        label = (doc.meta.get('title') or '')[:38].replace('"', "'").replace('$', '')
        marks.append(f'  {doc.id}["{doc.id}. {label}"]:::'
                     + ('lean' if names else {'доказано': 'proved', 'опровергнуто': 'refuted'}.get(
                         doc.meta.get('status'), 'open')))
        edges += [f'  {dep} --> {doc.id}' for dep in doc.many('depends')]
    modules = []
    for path in lean_files():
        if path.exists() and path.parent != _ROOT:
            found = re.search(r'/-!\s*#*\s*([^\n]*)', path.read_text(encoding='utf-8'))
            modules.append(f"| `{rel(path)}` | {cell(found.group(1).strip() if found else '')} |")
    blueprint = '\n'.join([
        '# Карта результатов', '',
        'Файл собран командой `python scripts/proj.py sync` из шапок записей `results/`. Правится шапка '
        'записи, а не этот файл.', '',
        'Столбец «Бумага» — состояние бумажного доказательства; «Lean» — объявления библиотеки, аксиомы '
        'которых проверяет `proj.py check`; «Соответствие» — вердикт проверки того, что формулировка в Lean '
        'означает утверждение записи. «Устарело» — формулировка или её определения менялись после проверки.', '',
        '| Запись | Утверждение | Бумага | Рецензия | Lean | Соответствие | Зависит от |',
        '| --- | --- | --- | --- | --- | --- | --- |', *rows, '',
        '```mermaid', 'graph LR', *marks, *edges,
        '  classDef lean fill:#cfe8cf,stroke:#3c763d;', '  classDef proved fill:#dbe9f6,stroke:#31708f;',
        '  classDef open fill:#fff,stroke:#999,stroke-dasharray: 4 3;',
        '  classDef refuted fill:#f2dede,stroke:#a94442;', '```', '',
        '## Модули Lean', '', '| Модуль | Содержание |', '| --- | --- |', *modules, ''])
    listing = '\n'.join([
        '# Идеи', '',
        'Файл собран командой `python scripts/proj.py sync` из шапок записей этой папки. Отвергнутые идеи '
        'остаются вместе с причиной, чтобы их не предлагали повторно.', '',
        '| Идея | Название | Цель | Статус | Критика |', '| --- | --- | --- | --- | --- |',
        *[f"| [{doc.id}]({doc.path.name}) | {cell(doc.meta.get('title'))} | {cell(doc.meta.get('target'))} | "
          f"{cell(doc.meta.get('status'))} | {cell(doc.meta.get('critic'))} |" for doc in ideas], ''])
    return {'blueprint.md': blueprint, 'ideas/README.md': listing}


def sync() -> list[str]:
    """Собирает сводки записей и каталог источников; каталог строит lit, а не этот файл."""
    index = leandecl.library(_ROOT, LIB)
    written = []
    for name, text in views(docs('results', 'R'), docs('ideas', 'I'), index).items():
        (_ROOT / name).parent.mkdir(parents=True, exist_ok=True)
        (_ROOT / name).write_text(text, encoding='utf-8', newline='\n')
        written.append(name)
    if (_ROOT / 'sources' / 'papers.json').exists():
        # sys.executable и путь рядом с этим файлом: то же окружение, что у proj.py.
        catalog = Path(__file__).resolve().parent / 'lit.py'
        code, output = run([sys.executable, str(catalog), 'catalog', '--root', str(_ROOT)])
        written.append('sources/catalog.md' if not code else 'sources/catalog.md не собран: ' + output[-200:])
    return written


# ---------- статья ----------

def tex(source: str) -> int:
    """Два прохода pdflatex в output/ и предупреждения из журнала."""
    path = _ROOT / source
    if not shutil.which('pdflatex'):
        print('pdflatex не найден.')
        return 1
    (_ROOT / 'output').mkdir(exist_ok=True)
    for attempt in (1, 2):
        code, output = run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
                            '-output-directory=output', source])
        if code:
            print(f'pdflatex не прошёл (проход {attempt}):')
            print('\n'.join(line for line in output.split('\n') if re.search(r':\d+: |^! ', line))[:1500])
            return 1
    log = (_ROOT / 'output' / (path.stem + '.log')).read_text(encoding='utf-8', errors='replace')
    found = [line for line in log.split('\n') if re.search(r'undefined|Overfull|LaTeX Warning|Package .* Warning', line)]
    for line in found:
        print('замечание:', line.strip())
    print(f'PDF: output/{path.stem}.pdf; замечаний {len(found)}')
    return 0


# ---------- окружение ----------

def doctor() -> int:
    lines, bad = [], 0
    for label, command in (('lake', None), ('git', ['git', '--version']), ('uv', ['uv', '--version']),
                           ('pdflatex', ['pdflatex', '--version'])):
        try:
            code, output = run(command or [lake(), '--version'], timeout=60)
            lines.append(f"{label}: {output.strip().split(chr(10))[0][:90]}")
        except (FileNotFoundError, SystemExit):
            lines.append(f'{label}: НЕ НАЙДЕН')
            bad += label in ('lake', 'git')
    lines.append(f'python: {sys.version.split()[0]}')
    for module in ('numpy', 'onnxruntime', 'tokenizers', 'huggingface_hub', 'pymupdf', 'certifi', 'mcp'):
        try:
            __import__(module)
        except ImportError:
            lines.append(f'модуль {module}: нет — нужен scripts/lit.py; `uv run scripts/lit.py …` поставит сам')
    toolchain = (_ROOT / 'lean-toolchain').read_text(encoding='utf-8').strip()
    lines.append(f'lean-toolchain: {toolchain}; библиотека: {LIB}')
    if not (_ROOT / '.lake' / 'packages' / 'mathlib').exists():
        lines.append('Mathlib не загружен: lake exe cache get')
    print('\n'.join(lines))
    return 1 if bad else 0


# ---------- Aristotle ----------

def aristotle_pack(name: str, skeleton: str) -> list[str]:
    """Пакет для Aristotle: библиотека, закреплённые версии и заготовка с sorry как новый модуль."""
    source = Path(skeleton)
    source = source if source.is_absolute() else _ROOT / source
    package = _ROOT / 'output' / 'aristotle' / name
    if package.exists():
        raise SystemExit(f'{rel(package)} уже есть: выберите другое имя.')
    (package / LIB).mkdir(parents=True)
    for item in ('lakefile.toml', 'lean-toolchain', 'lake-manifest.json', f'{LIB}.lean'):
        shutil.copy2(_ROOT / item, package / item)
    shutil.copytree(_ROOT / LIB, package / LIB, dirs_exist_ok=True)
    shutil.copy2(source, package / LIB / source.name)
    shutil.copy2(source, package / 'skeleton.lean')
    with (package / f'{LIB}.lean').open('a', encoding='utf-8', newline='\n') as root_file:
        root_file.write(f'import {LIB}.{source.stem}\n')
    prompt = package / 'prompt.md'
    prompt.write_text(
        f'# Task\n\nWork in the attached Lean project with its pinned Lean and Mathlib (see `lean-toolchain`, '
        f'`lake-manifest.json`). The only `sorry`s are in `{LIB}/{source.name}`.\n\n'
        'Do not change the statements or definitions given there or anywhere else in the project; no new '
        'axioms. You may add auxiliary lemmas. If a statement is false, say so and give the obstruction.\n\n'
        '## Setting\n\n## Proof sketch\n', encoding='utf-8', newline='\n')
    return [f'пакет: {rel(package)}', f'заготовка: {rel(package / LIB / source.name)}',
            f'допишите {rel(prompt)}: формулировка, опоры в проекте, набросок доказательства']


def aristotle_accept(name: str, result: str) -> int:
    """Сверяет ответ с заготовкой: формулировки, sorry, axiom, изменённые файлы. Ничего не переносит."""
    package = _ROOT / 'output' / 'aristotle' / name
    answer = Path(result) if Path(result).is_absolute() else _ROOT / result
    if answer.is_file():
        folder = package.parent / (name + '-result')
        with tarfile.open(answer) as archive:
            archive.extractall(folder, filter='data')
        answer = folder
    skeleton = (package / 'skeleton.lean').read_text(encoding='utf-8')
    module = next((path.name for path in (package / LIB).glob('*.lean')
                   if path.read_text(encoding='utf-8') == skeleton), None)
    returned = {path.relative_to(base).as_posix(): path
                for base in [next((p.parent for p in answer.rglob(f'{LIB}.lean')), answer)]
                for path in base.rglob('*.lean')}
    bad = 0
    target = returned.get(f'{LIB}/{module}')
    if target is None:
        print(f'ОШИБКА: в ответе нет {LIB}/{module}')
        return 1
    report = leandecl.compare(skeleton, target.read_text(encoding='utf-8'))
    for key, label in (('changed', 'формулировка изменена'), ('missing', 'объявление пропало'),
                       ('sorry', 'остался sorry')):
        for decl in report[key]:
            print(f'ОШИБКА: {label}: {decl}')
            bad += 1
    print(f"добавлено объявлений: {len(report['added'])}")
    for relative, path in sorted(returned.items()):
        original = package / relative
        text = path.read_text(encoding='utf-8')
        if re.search(r'^\s*axiom\b', leandecl.strip_comments(text), re.M):
            print(f'ОШИБКА: axiom в {relative}')
            bad += 1
        if relative != f'{LIB}/{module}' and (not original.exists() or original.read_text(encoding='utf-8') != text):
            print(f'изменён или добавлен файл: {relative}')
    print('Сверка пройдена: переносите модуль в библиотеку, затем lake build и proj.py check.' if not bad
          else f'Сверка не пройдена, ошибок: {bad}.')
    return 1 if bad else 0


# ---------- действия, общие для командной строки и MCP-сервера ----------

def create(kind: str, title: str, depends: str = '', target: str = '', idea: str = '') -> str:
    """Создаёт запись и возвращает путь к ней; для card title — код источника."""
    if kind != 'card':
        return rel(new(kind, title, depends=depends, target=target, idea=idea))
    import json
    rows = json.loads((_ROOT / 'sources' / 'papers.json').read_text(encoding='utf-8'))
    row = next((row for row in rows if row['code'] == title.upper()), None)
    if row is None:
        raise SystemExit(f'Источника {title} нет в реестре.')
    heading = f"{row['title']}\n\n{row['authors']}. {row['version']}. [Источник]({row['url']})."
    return rel(new('card', heading, source=row['code']))


def declarations(items: list[str]) -> tuple[dict, list]:
    """Объявления по полным именам или номерам записей; пустой список — все записи."""
    index = leandecl.library(_ROOT, LIB)
    names = []
    for item in items or [doc.id for doc in docs('results', 'R')]:
        names += find_doc(item).many('lean') if re.fullmatch(r'[Rr]\d+', item) else [item]
    decls = [leandecl.resolve(index, name) for name in names]
    if None in decls:
        raise SystemExit('Нет в библиотеке: ' + ', '.join(n for n, d in zip(names, decls) if d is None))
    return index, decls


def audit_report(items: list[str]) -> tuple[int, str]:
    names = sorted({decl.name for decl in declarations(items)[1]})
    errors = audit(names)
    return (1 if errors else 0), '\n'.join(f'ОШИБКА: {line}' for line in errors) or \
        f'Аксиомы в порядке: {len(names)} объявлений, только {", ".join(sorted(AXIOMS))}.'


def fingerprint_report(item: str) -> str:
    index, decls = declarations([item])
    lines = []
    for decl in decls:
        value, used = leandecl.fingerprint(index, decl.name)
        lines.append(f'{decl.name} {value} (определений проекта в формулировке: {len(used)})')
    return '\n'.join(lines + [f'отпечаток записи: {record_fingerprint(index, [decl.name for decl in decls])}'])


def statement_report(item: str) -> str:
    return '\n'.join(f'{decl.file}:{decl.line}\n{decl.statement}\n' for decl in declarations([item])[1])


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
    parser.add_argument('--root', type=Path, default=_ROOT,
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
        return doctor()
    elif args.action == 'pack':
        print('\n'.join(aristotle_pack(args.name, args.file)))
    else:
        return aristotle_accept(args.name, args.file)
    return 0


if __name__ == '__main__':
    sys.exit(main())
