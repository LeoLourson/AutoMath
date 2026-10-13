"""Объявления Lean по тексту исходников: имена, формулировки, отпечатки.

Разбор текстовый и приблизительный: он не заменяет компилятор. Существование имени и аксиомы
проверяет `proj.py audit` через Lean; здесь — то, что нужно без сборки: найти объявление, вынуть
формулировку, сравнить её с заготовкой, заметить, что формулировка или определения изменились.

Модуль группы `check/`: ею пользуются и проверки (`proj.py check`), и отпечаток формулировки.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

KINDS = 'theorem|lemma|def|abbrev|instance|structure|class|inductive|axiom|opaque'
MODIFIERS = 'private|protected|public|noncomputable|unsafe|partial|nonrec|scoped|local|meta'
DECL = re.compile(rf'(?:@\[[^\]]*\]\s*)*(?:(?:{MODIFIERS})\s+)*({KINDS})\b\s*([^\s:({{\[]*)')
SECTION = re.compile(rf'(?:@\[[^\]]*\]\s*)*(?:(?:{MODIFIERS})\s+)*section\b[ \t]*(\S*)')
CONTINUES = ('|', ')', ']', '}', '⟩', '·', '<;>', 'termination_by', 'decreasing_by', 'deriving', 'where', 'with')
DEFINING = {'def', 'abbrev', 'instance', 'structure', 'class', 'inductive', 'axiom', 'opaque'}
IDENT = re.compile(r"[^\W\d][\w'!?]*(?:\.[^\W\d][\w'!?]*)*")


@dataclass
class Decl:
    kind: str
    name: str            # полное имя с пространствами имён
    file: str
    line: int
    text: str            # объявление целиком, без комментариев
    variables: list[str] = field(default_factory=list)  # команды variable, действующие в файле выше

    @property
    def statement(self) -> str:
        """Формулировка: для теоремы — до `:=`, для определения — весь текст."""
        if self.kind not in ('theorem', 'lemma'):
            return squash(self.text)
        depth = 0
        for position, char in enumerate(self.text):
            if char in '([{⟨':
                depth += 1
            elif char in ')]}⟩':
                depth -= 1
            elif depth == 0 and self.text.startswith(':=', position):
                return squash(self.text[:position])
            elif depth == 0 and char == '\n' and self.text[position + 1:].lstrip(' ').startswith('|'):
                return squash(self.text[:position])
        return squash(self.text)


def squash(text: str) -> str:
    return ' '.join(text.split())


def strip_comments(source: str) -> str:
    """Заменяет комментарии пробелами, сохраняя строки; строковые литералы не трогает."""
    out, position, depth = [], 0, 0
    while position < len(source):
        if depth:
            if source.startswith('/-', position):
                depth, position = depth + 1, position + 2
                out.append('  ')
            elif source.startswith('-/', position):
                depth, position = depth - 1, position + 2
                out.append('  ')
            else:
                out.append('\n' if source[position] == '\n' else ' ')
                position += 1
        elif source.startswith('/-', position):
            depth, position = 1, position + 2
            out.append('  ')
        elif source.startswith('--', position):
            end = source.find('\n', position)
            end = len(source) if end < 0 else end
            out.append(' ' * (end - position))
            position = end
        elif source[position] == '"':
            end = position + 1
            while end < len(source) and source[end] != '"':
                end += 2 if source[end] == '\\' else 1
            out.append(source[position:end + 1])
            position = end + 1
        else:
            out.append(source[position])
            position += 1
    return ''.join(out)


def parse(source: str, file: str = '') -> list[Decl]:
    """Объявления верхнего уровня одного файла."""
    lines = strip_comments(source.replace('\r\n', '\n')).split('\n')
    decls, scopes, variables = [], [], []
    number = 0
    while number < len(lines):
        line = lines[number]
        start = number
        number += 1
        if not line or line[0].isspace():
            continue
        # Команда тянется, пока строки пусты, начинаются с отступа или с продолжения
        while number < len(lines) and (not lines[number].strip() or lines[number][0].isspace()
                                       or lines[number].startswith(CONTINUES)):
            number += 1
        text = '\n'.join(lines[start:number]).rstrip()
        while re.fullmatch(r'\s*(@\[[^\]]*\]\s*|open\b[^\n]*\bin\b\s*)', text) and number < len(lines):
            more = number + 1   # атрибут или `open … in` на отдельной строке относится к следующей команде
            while more < len(lines) and (not lines[more].strip() or lines[more][0].isspace()
                                         or lines[more].startswith(CONTINUES)):
                more += 1
            text = '\n'.join(lines[start:more]).rstrip()
            number = more
        body = re.sub(r'^\s*open\b[^\n]*\bin\b\s*', '', text)
        if match := re.match(r'namespace\s+(\S+)', body):
            scopes.append(('namespace', match.group(1), len(variables)))
        elif body.strip() == 'mutual':
            scopes.append(('section', '', len(variables)))
        elif match := SECTION.fullmatch(body.split('\n')[0].strip()):
            scopes.append(('section', match.group(1), len(variables)))
        elif match := re.match(r'end\b[ \t]*(\S*)', body):
            for position in range(len(scopes) - 1, -1, -1):
                if scopes[position][1] == match.group(1):
                    del variables[scopes[position][2]:]
                    del scopes[position:]
                    break
        elif re.match(r'(?:@\[[^\]]*\]\s*)*variable\b', body):
            variables.append(squash(body))
        elif match := DECL.match(body):
            kind, short = match.group(1), match.group(2).strip('«»')
            if not short:
                continue  # безымянный instance
            prefix = [name for scope, name, _ in scopes if scope == 'namespace']
            name = short[len('_root_.'):] if short.startswith('_root_.') else '.'.join(prefix + [short])
            clean = re.sub(r'^(?:@\[[^\]]*\]\s*)+', '', body)
            decls.append(Decl(kind, name, file, start + 1, clean, list(variables)))
    return decls


def library(root: Path, lib: str) -> dict[str, Decl]:
    """Все объявления библиотеки по полным именам."""
    index: dict[str, Decl] = {}
    files = sorted((root / lib).rglob('*.lean')) + [root / f'{lib}.lean']
    for path in files:
        if path.exists():
            for decl in parse(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()):
                index.setdefault(decl.name, decl)
    return index


def resolve(index: dict[str, Decl], name: str) -> Decl | None:
    """Объявление по полному имени или по единственному совпадению хвоста имени."""
    if name in index:
        return index[name]
    tails = [decl for full, decl in index.items() if full.endswith('.' + name)]
    return tails[0] if len(tails) == 1 else None


def fingerprint(index: dict[str, Decl], name: str) -> tuple[str, list[str]]:
    """Отпечаток смысла теоремы: её формулировка, действующие variable и определения проекта,
    от которых она зависит. Меняется, когда меняется что-либо из этого; доказательства не учитывает."""
    decl = resolve(index, name)
    if decl is None:
        raise KeyError(name)
    by_tail: dict[str, list[Decl]] = {}
    for full, item in index.items():
        if item.kind in DEFINING:
            parts = full.split('.')
            for cut in range(len(parts)):
                by_tail.setdefault('.'.join(parts[cut:]), []).append(item)
    seen: dict[str, Decl] = {}
    queue = [decl.statement] + decl.variables
    while queue:
        for token in IDENT.findall(queue.pop()):
            parts = token.split('.')
            for candidate in {token, parts[-1], '.'.join(parts[-2:])}:
                for item in by_tail.get(candidate, []):
                    if item.name not in seen and item.name != decl.name:
                        seen[item.name] = item
                        queue.append(squash(item.text))
                        queue.extend(item.variables)
    material = [decl.statement] + decl.variables + [squash(seen[key].text) for key in sorted(seen)]
    return hashlib.sha256('\n'.join(material).encode('utf-8')).hexdigest()[:12], sorted(seen)


def record_fingerprint(index: dict[str, Decl], names: list[str]) -> str:
    """Общий отпечаток формулировок записи: его последним словом стоит вердикт в поле fidelity."""
    parts = sorted(f'{name} {fingerprint(index, name)[0]}' for name in names)
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:12]


def compare(skeleton: str, result: str) -> dict[str, list[str]]:
    """Сверка ответа с заготовкой: формулировки заготовки должны остаться дословно теми же."""
    before = {decl.name: decl for decl in parse(skeleton)}
    after = {decl.name: decl for decl in parse(result)}
    report = {'changed': [], 'missing': [], 'added': [], 'sorry': []}
    for name, decl in before.items():
        if name not in after:
            report['missing'].append(name)
        elif decl.statement != after[name].statement and (
                decl.kind in ('theorem', 'lemma') or 'sorry' not in decl.text):
            report['changed'].append(name)
    report['added'] = [name for name in after if name not in before]
    report['sorry'] = [name for name, decl in after.items() if re.search(r'\b(sorry|admit)\b', decl.text)]
    return report
