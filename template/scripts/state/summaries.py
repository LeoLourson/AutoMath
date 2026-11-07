"""Сводки проекта: `blueprint.md`, `ideas/README.md` и фрагмент статьи `paper/generated/status.tex`.

Тексты сводок — производное: их никто не правит руками, а `python scripts/state/proj.py sync`
перезаписывает. Проверка свежести живёт в `check/summaries.py`. Фрагмент `status.tex` —
таблица «запись — статус — объявление Lean» для обзорного текста; статья его сама не
подключает, `\\input{generated/status.tex}` ставится там, где таблица нужна.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import records  # noqa: E402
from check import declarations, hygiene  # noqa: E402


def cell(text: str | None) -> str:
    """Значение для ячейки таблицы: пустое место — прочерк, вертикальная черта экранируется."""
    return (text or '—').replace('|', '\\|')


def module_heading(path: Path) -> str:
    """Содержание модуля Lean — первая строка заголовка `/-! # …`."""
    found = re.search(r'/-!\s*#*\s*([^\n]*)', path.read_text(encoding='utf-8'))
    return found.group(1).strip() if found else ''


def blueprint(root: Path, library: str, results: list, index: dict) -> str:
    """Карта результатов: таблица записей, граф зависимостей и список модулей Lean."""
    rows, edges, marks = [], [], []
    for doc in results:
        names = doc.many('lean')
        ok = names and all(declarations.resolve(index, name) for name in names)
        fidelity = (doc.meta.get('fidelity') or '').split()
        if not names:
            match = '—'
        elif not fidelity:
            match = 'не проверено'
        elif ok and fidelity[-1] == declarations.record_fingerprint(index, names):
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
    final = [doc for doc in results if doc.meta.get('final') == 'true']
    final_lines = ([f"* {doc.id} — {cell(doc.meta.get('title'))}"
                    + (', `' + ', '.join(doc.many('lean')) + '`' if doc.many('lean') else '')
                    for doc in final] if final else
                   ['Записей с `final: true` пока нет.'])
    modules = [f"| `{records.rel(root, path)}` | {cell(module_heading(path))} |"
               for path in hygiene.lean_files(root, library) if path.exists() and path.parent != root]
    return '\n'.join([
        '# Карта результатов', '',
        'Файл собран командой `python scripts/state/proj.py sync` из шапок записей `results/`. Правится шапка '
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
        '## Итоговые теоремы', '',
        'Записи с `final: true` — итог работы; их аксиомы проверяет `python scripts/state/proj.py audit`, '
        'а список для `#print axioms` собирает `proj.py ledger`.', '',
        *final_lines, '',
        '## Модули Lean', '', '| Модуль | Содержание |', '| --- | --- |', *modules, ''])


def listing(ideas: list) -> str:
    """Список идей: отвергнутые остаются вместе с причиной, чтобы их не предлагали снова."""
    return '\n'.join([
        '# Идеи', '',
        'Файл собран командой `python scripts/state/proj.py sync` из шапок записей этой папки. Отвергнутые идеи '
        'остаются вместе с причиной, чтобы их не предлагали повторно.', '',
        '| Идея | Название | Цель | Статус | Критика |', '| --- | --- | --- | --- | --- |',
        *[f"| [{doc.id}]({doc.path.name}) | {cell(doc.meta.get('title'))} | {cell(doc.meta.get('target'))} | "
          f"{cell(doc.meta.get('status'))} | {cell(doc.meta.get('critic'))} |" for doc in ideas], ''])


def latex_escape(value: str) -> str:
    """Экранирует символы, ломающие tabular, не трогая формулы `$...$`.

    Заголовок считается LaTeX-фрагментом: обратная косая черта, фигурные скобки и `$`
    передаются как есть; вне формул экранируются `_ % & # ~ ^`, внутри формул — только `% & #`.
    """
    out: list[str] = []
    in_math = False
    for ch in value:
        if ch == '$':
            in_math = not in_math
            out.append(ch)
            continue
        if in_math:
            out.append('\\' + ch if ch in '%&#' else ch)
            continue
        if ch in '_%&#':
            out.append('\\' + ch)
        elif ch == '~':
            out.append('\\textasciitilde{}')
        elif ch == '^':
            out.append('\\textasciicircum{}')
        elif ch in '\r\n':
            out.append(' ')
        else:
            out.append(ch)
    return ''.join(out).strip()


def latex_breakable(name: str) -> str:
    """Имя объявления с разрешёнными переносами: полные имена дают Overfull в узкой таблице."""
    escaped = latex_escape(name).replace('\\_', '\\_\\allowbreak ')
    return escaped.replace('.', '.\\allowbreak ')


def status_tex(results: list) -> str:
    """Фрагмент `paper/generated/status.tex`: запись, статус, объявление Lean.

    Формат — окружение `center`, `\\arraystretch` и `tabular` из трёх столбцов с
    вертикальными линейками; подписи и метки фрагмент не несёт. Дат в файле нет,
    иначе проверка свежести была бы невозможна.
    """
    rows = [doc for doc in results if doc.meta.get('status')]
    lines = [
        '% generated by scripts/state/proj.py sync; do not edit',
        '% Источник: шапки results/R*.md (id, status, lean).',
        '% Строк: ' + str(len(rows)) + '. Подключается командой \\input{generated/status.tex} рядом с текстом статьи.',
        '\\begin{center}',
        '\\small',
        '\\renewcommand{\\arraystretch}{1.2}',
        '\\begin{tabular}{|l|l|l|}',
        '\\hline',
        '\\textbf{Запись} & \\textbf{Статус} & \\textbf{Объявление Lean}\\\\\\hline',
    ]
    for doc in rows:
        lean = ', '.join(doc.many('lean'))
        lines.append('{id} & {status} & {lean}\\\\\\hline'.format(
            id=latex_escape(doc.id or ''),
            status=latex_escape(doc.meta.get('status', '')),
            lean=('\\texttt{' + latex_breakable(lean) + '}') if lean else '---'))
    if not rows:
        lines.append('% В results/ нет записей со статусом.')
    lines += ['\\end{tabular}', '\\end{center}', '']
    return '\n'.join(lines)


def summaries(root: Path, library: str, results: list, ideas: list, index: dict) -> dict[str, str]:
    """Тексты всех собираемых файлов по их путям."""
    return {'blueprint.md': blueprint(root, library, results, index),
            'ideas/README.md': listing(ideas),
            'paper/generated/status.tex': status_tex(results)}
