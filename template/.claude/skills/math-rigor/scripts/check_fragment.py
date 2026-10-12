"""Проверка компиляции LaTeX-фрагмента без преамбулы.

    python check_fragment.py fragment.tex [--keep ПАПКА]

Фрагмент оборачивается в преамбулу с пакетами amsmath, amssymb, amsthm, mathtools, hyperref
и окружениями theorem, lemma, proposition, corollary, definition, remark, example, затем
дважды собирается pdflatex во временной папке. Номера строк в сообщениях — строки
фрагмента. Код возврата 0, если нет ошибок и неразрешённых ссылок.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAMES = {
    'ru': ['Теорема', 'Лемма', 'Предложение', 'Следствие', 'Определение', 'Замечание', 'Пример'],
    'en': ['Theorem', 'Lemma', 'Proposition', 'Corollary', 'Definition', 'Remark', 'Example'],
}
PLAIN = ['theorem', 'lemma', 'proposition', 'corollary']
UPRIGHT = ['definition', 'remark', 'example']


def wrapper(russian: bool) -> str:
    names = dict(zip(PLAIN + UPRIGHT, NAMES['ru' if russian else 'en']))
    language = ['\\usepackage[T2A]{fontenc}', '\\usepackage[english,russian]{babel}'] if russian \
        else ['\\usepackage[T1]{fontenc}']
    return '\n'.join([
        '\\documentclass[12pt,a4paper]{article}',
        '\\usepackage[utf8]{inputenc}',
        *language,
        '\\usepackage{amsmath,amssymb,amsthm,mathtools}',
        '\\usepackage[margin=2.5cm]{geometry}',
        '\\usepackage[unicode,hidelinks]{hyperref}',
        '\\theoremstyle{plain}',
        *(f'\\newtheorem{{{name}}}{{{names[name]}}}' for name in PLAIN),
        '\\theoremstyle{definition}',
        *(f'\\newtheorem{{{name}}}{{{names[name]}}}' for name in UPRIGHT),
        '\\begin{document}',
        '\\input{fragment.tex}',
        '\\end{document}',
        ''])


def compile_once(folder: Path) -> str:
    # Длинные строки журнала не переносятся, иначе сообщение рвётся посреди имени метки
    environment = dict(os.environ, max_print_line='1000', error_line='254', half_error_line='238')
    subprocess.run(['pdflatex', '-interaction=nonstopmode', '-file-line-error', 'wrapper.tex'],
                   cwd=folder, env=environment, capture_output=True, check=False)
    log = folder / 'wrapper.log'
    if not log.exists():
        return ''
    # MiKTeX переменные не читает и режет строки на 79-м знаке: такие строки склеиваются
    return re.sub(r'(?m)^(.{79})\n', r'\1', log.read_text(encoding='utf-8', errors='replace'))


def errors(log: str) -> list[str]:
    lines = log.splitlines()
    found = []
    for number, line in enumerate(lines):
        located = re.match(r'(?:\./)?(fragment|wrapper)\.tex:(\d+): (.*)', line)
        if located:
            where = f'строка {located[2]}' if located[1] == 'fragment' else 'преамбула'
            # Строка журнала вида «l.12 текст» показывает место, где остановился разбор
            context = next((text for text in lines[number + 1:number + 12] if re.match(r'l\.\d+ ', text)), '')
            found.append(f'{where}: {located[3]}' + (f'\n    {context}' if context else ''))
        elif line.startswith('! '):
            found.append(line[2:])
    return found


def unresolved(log: str) -> list[str]:
    found = []
    for kind, label, line in re.findall(
            r"LaTeX Warning: (Reference|Citation) `([^']+)'.*? undefined on input line (\d+)", log):
        what = 'ссылка на метку' if kind == 'Reference' else 'ссылка на источник'
        found.append(f'строка {line}: {what} «{label}» не разрешена')
    found += [f'метка «{label}» определена несколько раз'
              for label in re.findall(r"LaTeX Warning: Label `([^']+)' multiply defined", log)]
    return sorted(set(found))


def overfull(log: str) -> list[str]:
    return [f'строки {lines}: {box} выходит за поле на {size}pt'
            for box, size, lines in re.findall(r'Overfull \\(hbox|vbox) \(([\d.]+)pt too \w+\).*? at lines (\d+--\d+)', log)]


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('fragment', type=Path, help='файл с LaTeX-фрагментом без преамбулы')
    parser.add_argument('--keep', type=Path, help='папка, куда положить обёртку, журнал и PDF')
    args = parser.parse_args()
    if not shutil.which('pdflatex'):
        print('pdflatex не найден: компиляция не проверена.')
        return 2
    text = args.fragment.read_text(encoding='utf-8-sig')
    if re.search(r'\\documentclass|\\begin\{document\}', text):
        print('Во фрагменте есть \\documentclass или \\begin{document}: нужен текст без преамбулы.')
        return 1
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        (folder / 'fragment.tex').write_text(text, encoding='utf-8', newline='\n')
        (folder / 'wrapper.tex').write_text(wrapper(bool(re.search('[А-Яа-яЁё]', text))),
                                            encoding='utf-8', newline='\n')
        log = compile_once(folder)
        failed = errors(log)
        if not failed and log:
            # Второй проход разрешает \ref, \eqref и \cite
            log = compile_once(folder)
            failed = errors(log)
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
            for name in ('wrapper.tex', 'fragment.tex', 'wrapper.log', 'wrapper.pdf'):
                if (folder / name).exists():
                    shutil.copy2(folder / name, args.keep / name)
    if not log:
        print('pdflatex не создал журнал: компиляция не проверена.')
        return 2
    failed = failed or unresolved(log)
    if failed:
        print(f'Ошибки ({len(failed)}):')
        print('\n'.join('  ' + line for line in failed))
        return 1
    print('Фрагмент компилируется без ошибок.')
    remarks = overfull(log)
    if remarks:
        print('Замечания:')
        print('\n'.join('  ' + line for line in remarks))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
