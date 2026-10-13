"""Транскрипция PDF в LaTeX и нарезка текста на куски.

Транскрипцию делает модель: при расхождении с оригиналом первичен PDF. Механические
замечания к собранному тексту (`lint_tex`) и проверка сборки `pdflatex` не заменяют чтения
страниц. Нарезка на куски сохраняет печатные номера страниц и утверждений — по ним поиск
показывает «Теорема 6.6, с. 41».
"""
from __future__ import annotations

import bisect
import re
import subprocess
from pathlib import Path

from sources import papers, paths, registry, search, store, web
PREAMBLE = r'''% Транскрипция PDF, сделанная моделью. При расхождении первичен PDF.
% Собрано командой `python scripts/sources/lit.py tex` из частей output/literature/parts/.
\documentclass[11pt]{article}
\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[english,russian]{babel}
\usepackage{amsmath,amssymb,amsthm,mathrsfs}
% \pagemark{N} стоит там, где в оригинале начинается страница с печатным номером N
\newcommand{\pagemark}[1]{\marginpar{\footnotesize\textsf{с.\,#1}}}
% \unsure{...} — место, которое по изображению прочитано неуверенно
\newcommand{\unsure}[1]{\fbox{#1}}
% Утверждение с печатным номером: \begin{statement}{Теорема}{6.6} ... \end{statement}
\newenvironment{statement}[2]{\par\medskip\noindent\textbf{#1 #2.}\ \itshape}{\par\medskip}
'''


def tex_escape(text: str) -> str:
    return re.sub(r'(?<!\\)([&%#])', r'\\\1', text)


def lint_tex(text: str, pages: int | None) -> list[str]:
    """Механические замечания к транскрипции: окружения, скобки, метки страниц."""
    notes, stack = [], []
    for number, line in enumerate(text.split('\n'), 1):
        for kind, name in re.findall(r'\\(begin|end)\{([^{}]+)\}', re.sub(r'(?<!\\)%.*', '', line)):
            if kind == 'begin':
                stack.append((name, number))
            elif stack and stack[-1][0] == name:
                stack.pop()
            else:
                notes.append(f'строка {number}: \\end{{{name}}} без пары')
    notes += [f'строка {number}: \\begin{{{name}}} не закрыт' for name, number in stack]
    plain = re.sub(r'\\[{}]', '', text)
    if plain.count('{') != plain.count('}'):
        notes.append(f"фигурные скобки не сбалансированы: {plain.count('{')} открывающих, {plain.count('}')} закрывающих")
    marks = len(re.findall(r'\\pagemark\{', text)) - 1  # одно вхождение — определение в преамбуле
    if pages is not None and marks != pages:
        notes.append(f'меток \\pagemark: {marks}, страниц в PDF: {pages}')
    unsure = len(re.findall(r'\\unsure\{', text)) - 1
    if unsure > 0:
        notes.append(f'мест, прочитанных неуверенно (\\unsure): {unsure}')
    return notes


def compile_tex(path: Path) -> list[str]:
    if not shutil.which('pdflatex'):
        return ['pdflatex не найден: сборка не проверена']
    build = LIT / 'build'
    build.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
                          f'-output-directory={build}', str(path)], capture_output=True, cwd=LIT, stdin=subprocess.DEVNULL)
    log = run.stdout.decode('utf-8', 'replace')
    errors = [line for line in log.split('\n') if re.match(r'.*:\d+: |^! ', line)][:6]
    return [f'pdflatex: {line.strip()}' for line in errors] if run.returncode else []


def tex(code: str, origin: str = 'transcription', build: bool = False) -> list[str]:
    """Собирает транскрипцию из частей, проверяет её и записывает в реестр как LaTeX источника."""
    rows = registry.load()
    row = registry.by_code(rows, code)
    stem = registry.stem_of(row)
    target, parts = LIT / (stem + '.tex'), sorted((LIT / 'parts' / stem).glob('*.tex'))
    if parts:
        head = PREAMBLE + f"\\title{{{tex_escape(row['title'])}}}\n\\author{{{tex_escape(row['authors'])}}}\n" \
            f"\\date{{{tex_escape(row['version'])}}}\n" '\\begin{document}\n\\maketitle\n\n'
        body = '\n\n'.join(part.read_text(encoding='utf-8').strip() for part in parts)
        target.write_text(head + body + '\n\n\\end{document}\n', encoding='utf-8', newline='\n')
    elif not target.exists():
        raise SystemExit(f'Нет ни частей в output/literature/parts/{stem}/, ни файла output/literature/{stem}.tex.')
    text = target.read_text(encoding='utf-8')
    notes = lint_tex(text, row.get('pages')) if origin == 'transcription' else []
    if build:
        notes += compile_tex(target)
    row.update(tex=target.name, tex_origin=origin, tex_date=f'{date.today():%Y-%m-%d}')
    registry.save(rows)
    catalog()
    return ([f"{row['code']}: output/literature/{target.name}, частей: {len(parts)}"]
            + [f'ЗАМЕЧАНИЕ: {note}' for note in notes] + search.index([row['code']]))
ENVIRONMENTS = {
    'abstract': 'Abstract', 'theorem': 'Theorem', 'thm': 'Theorem', 'lemma': 'Lemma', 'lem': 'Lemma',
    'proposition': 'Proposition', 'prop': 'Proposition', 'corollary': 'Corollary', 'cor': 'Corollary',
    'definition': 'Definition', 'defn': 'Definition', 'remark': 'Remark', 'rem': 'Remark',
    'example': 'Example', 'conjecture': 'Conjecture', 'claim': 'Claim', 'proof': 'Proof',
    'statement': 'Statement',
}
NEWTHEOREM = re.compile(r'\\newtheorem\*?\s*\{([^{}]+)\}\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}')
# Заголовок утверждения, набранный текстом: распознанный LaTeX и текст PDF
HEADING = re.compile(
    r'\s*(Теорема|Лемма|Предложение|Следствие|Определение|Замечание|'
    r'Theorem|Lemma|Proposition|Corollary|Definition|Remark)\s+(\d+(?:\.\d+)*)\s*[.:(]')
ENGLISH = {'Теорема': 'Theorem', 'Лемма': 'Lemma', 'Предложение': 'Proposition', 'Следствие': 'Corollary',
           'Определение': 'Definition', 'Замечание': 'Remark', 'Пример': 'Example', 'Утверждение': 'Proposition'}


def balanced(text: str, start: int) -> tuple[str, int]:
    """Содержимое группы {...}, открытой в позиции start, и позиция после неё."""
    depth = 0
    for position in range(start, min(len(text), start + 2000)):
        if text[position] == '{' and text[position - 1] != '\\':
            depth += 1
        elif text[position] == '}' and text[position - 1] != '\\':
            depth -= 1
            if depth == 0:
                return text[start + 1:position], position + 1
    return '', start + 1


def pack(text: str, offset: int) -> list[tuple[int, str]]:
    """Режет текст на куски до search.CHUNK знаков по границам абзацев, строк и предложений.

    Строка с заголовком утверждения («Теорема 6.6.», «Theorem 4.1.») начинает новый кусок.
    """
    units, position = [], offset
    for line in text.split('\n'):
        if len(line) > search.CHUNK:
            units += [(position, part) for part in re.split(r'(?<=[.;])\s+(?=[A-ZА-Я\\$])', line)]
        else:
            units.append((position, line))
        position += len(line) + 1
    chunks, current, start = [], [], offset
    for position, unit in units:
        size = sum(len(part) + 1 for part in current)
        if current and (size + len(unit) > search.CHUNK or (not unit.strip() and size > 0.6 * search.CHUNK)
                        or HEADING.match(unit)):
            chunks.append((start, '\n'.join(current).strip()))
            current = []
        if not current:
            start = position
        current.append(unit)
    chunks.append((start, '\n'.join(current).strip()))
    return [(start, chunk) for start, chunk in chunks if len(chunk) >= 40]


def headed(kind: str, label: str, body: str) -> tuple[str, str]:
    """Тип и метка куска; у утверждения, набранного текстом, метка — его печатный номер."""
    heading = HEADING.match(body)
    if heading:
        return ENGLISH.get(heading.group(1), heading.group(1)), f'{heading.group(1)} {heading.group(2)}'
    return kind, label


def tex_chunks(text: str) -> list[dict]:
    """Куски LaTeX: окружения теорем и доказательств отдельно, остальной текст по разделам.

    В транскрипции у куска есть печатная страница: её задаёт последняя метка \\pagemark.
    """
    envs = {**ENVIRONMENTS, **{name: web.squash(title) for name, title in NEWTHEOREM.findall(text)}}
    marker = re.compile(
        r'\\(section|subsection|subsubsection)\*?\s*(?:\[[^\]]*\])?\s*\{|\\(begin|end)\{(%s)\*?\}'
        % '|'.join(map(re.escape, sorted(envs, key=len, reverse=True))))
    begin = text.find('\\begin{document}')
    position = begin + len('\\begin{document}') if begin >= 0 else 0
    stops = [m.start() for m in re.finditer(r'\\begin\{thebibliography\}|\\end\{document\}', text)]
    stop = min((s for s in stops if s > position), default=len(text))
    newlines = [i for i, char in enumerate(text) if char == '\n']
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'\\pagemark\{([^{}#]*)\}', text)]
    mark_starts = [at for at, _ in marks]
    chunks, section, stack = [], '', []

    def emit(kind: str, label: str, start: int, end: int) -> None:
        piece = text[start:end]
        parts = [(start, piece.strip())] if kind != 'text' and len(piece) <= 2 * search.CHUNK else pack(piece, start)
        for offset, body in parts:
            if kind == 'text':
                item, name = headed(kind, '', body)
            else:
                found = re.search(r'\\label\{([^{}]*)\}', body)
                item, name = kind, label or (found.group(1) if found else '')
            mark = bisect.bisect_right(mark_starts, offset + 12) - 1
            chunks.append(dict(kind=item, label=name, section=section, text=body,
                               loc=bisect.bisect_left(newlines, offset) + 1,
                               page=marks[mark][1] if mark >= 0 else ''))

    for match in marker.finditer(text, position, stop):
        if match.group(1):
            if stack:
                continue
            emit('text', '', position, match.start())
            title, position = balanced(text, match.end() - 1)
            section = web.squash(re.sub(r'\\label\{[^{}]*\}', '', title))[:120]
        elif match.group(2) == 'begin':
            if not stack:
                emit('text', '', position, match.start())
                position = match.start()
            stack.append(match.group(3))
        elif stack and stack[-1] == match.group(3):
            stack.pop()
            if not stack:
                kind, label = envs[match.group(3)], ''
                printed = re.match(r'\\begin\{statement\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}', text[position:match.end()])
                if printed:
                    kind = ENGLISH.get(printed.group(1), printed.group(1))
                    label = f'{printed.group(1)} {printed.group(2)}'
                emit(kind, label, position, match.end())
                position = match.end()
    emit('text', '', position, stop)
    return [chunk for chunk in chunks if len(chunk['text']) >= 40]


def txt_chunks(text: str) -> list[dict]:
    """Куски текста, извлечённого из PDF; loc — номер страницы файла."""
    chunks = []
    for number, page in enumerate(text.split('\f'), 1):
        for _, body in pack(page, 0):
            kind, label = headed('page', '', body)
            chunks.append(dict(kind=kind, label=label, section='', loc=number, page='', text=body))
    return chunks
