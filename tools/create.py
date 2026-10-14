"""Новый исследовательский проект из template/ или обновление инструментов в существующем.

    python tools/create.py ПАПКА --lib Spectra --title "Название темы" [--pins-from ПРОЕКТ] [--no-git]
    python tools/create.py --update ПРОЕКТ [--dry-run]

Создание копирует весь шаблон и подставляет имя библиотеки и название. Обновление
переписывает только инструменты (правила, скрипты, агентов, команды); постановка,
записи, идеи, источники, библиотека Lean и статья не трогаются.

Команды ниже в подсказках выполняются уже в папке созданного проекта, где этот файл
лежит как scripts/state/proj.py.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / 'template'
# Файлы, которыми владеет шаблон: обновление переписывает их в проекте
TOOLING = ['AGENTS.md', 'CLAUDE.md', 'DEEPSEEK.md', 'scripts/*', '.claude/agents/*', '.claude/commands/*',
           '.claude/skills/*', 'sources/README.md', 'experiments/README.md', '.github/workflows/ci.yml']
SKIP = {'__pycache__', '.git', '.dsh', 'output', '.lake'}


def files() -> list[Path]:
    return sorted(path for path in TEMPLATE.rglob('*')
                  if path.is_file() and not SKIP & set(path.relative_to(TEMPLATE).parts))


def render(data: bytes, lib: str, title: str) -> bytes:
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return data
    return text.replace('__LIB__', lib).replace('__TITLE__', title).encode('utf-8')


def output_tail(result: subprocess.CompletedProcess, lines: int = 20) -> str:
    """Хвост stdout и stderr команды — чтобы падение было видно в сообщении."""
    parts = []
    for name, stream in (('stdout', result.stdout), ('stderr', result.stderr)):
        text = stream.decode('utf-8', errors='replace') if isinstance(stream, bytes) else (stream or '')
        text = text.strip()
        if text:
            parts.append(f'--- {name} ---\n' + '\n'.join(text.splitlines()[-lines:]))
    return '\n'.join(parts)


def prepare_harness(target: Path) -> None:
    subprocess.run([sys.executable, str(target / 'scripts/host/harness.py'), 'prepare'],
                   cwd=target, check=True)


def create(target: Path, lib: str, title: str, pins: Path | None, git: bool) -> None:
    if not re.fullmatch(r'[A-Z][A-Za-z0-9]*', lib):
        raise SystemExit('Имя библиотеки — идентификатор Lean с заглавной буквы, без пробелов: Spectra, NonlocalOps.')
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f'Папка {target} не пуста.')
    for source in files():
        relative = Path(str(source.relative_to(TEMPLATE)).replace('__LIB__', lib))
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        (target / relative).write_bytes(render(source.read_bytes(), lib, title))
    if pins:
        # Версии Lean и Mathlib берутся из работающего проекта, а не из шаблона
        for name in ('lean-toolchain', 'lake-manifest.json'):
            shutil.copy2(pins / name, target / name)
        revision = re.search(r'^rev\s*=\s*"([^"]+)"', (pins / 'lakefile.toml').read_text(encoding='utf-8'), re.M)
        lakefile = target / 'lakefile.toml'
        lakefile.write_text(re.sub(r'^rev\s*=\s*"[^"]+"', f'rev = "{revision.group(1)}"',
                                   lakefile.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8', newline='\n')
    manifest = target / 'lake-manifest.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['name'] = lib
    manifest.write_text(json.dumps(data, indent=1) + '\n', encoding='utf-8', newline='\n')
    if git and shutil.which('git'):
        subprocess.run(['git', 'init', '--quiet'], cwd=target, check=False)
    # Сводки собираются сразу, чтобы первая проверка проекта прошла
    summary = subprocess.run([sys.executable, 'scripts/state/proj.py', 'sync'],
                             cwd=target, check=False, capture_output=True)
    if summary.returncode:
        raise SystemExit(
            f'Проект создан: {target}\n'
            'Но сводки не собраны: python scripts/state/proj.py sync завершилась с кодом '
            f'{summary.returncode}.\n'
            'Скопированные файлы оставлены на месте. Исправьте причину и повторите из папки проекта:\n'
            '  python scripts/state/proj.py sync\n'
            'Вывод команды:\n' + output_tail(summary))
    prepare_harness(target)
    print(f'Проект создан: {target}\n\nДальше, из папки проекта:\n'
          '  lake exe cache get                  # готовая сборка Mathlib\n'
          '  lake build\n'
          '  python scripts/state/proj.py doctor       # окружение\n'
          '  python scripts/state/proj.py check        # одно замечание о примере R01\n'
          '  python scripts/host/harness.py run web   # DeepSeek Harness\n'
          'Затем заполните question.md и PROJECT.md; остальное — в README.md проекта.')


def update(target: Path, dry: bool) -> None:
    config = tomllib.loads((target / 'project.toml').read_text(encoding='utf-8'))['project']
    changed = []
    for source in files():
        relative = source.relative_to(TEMPLATE).as_posix()
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in TOOLING):
            continue
        data = render(source.read_bytes(), config['lib'], config.get('title', ''))
        destination = target / relative
        if not destination.exists() or destination.read_bytes().replace(b'\r\n', b'\n') != data.replace(b'\r\n', b'\n'):
            changed.append(relative)
            if not dry:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
    print(('Изменились бы:' if dry else 'Обновлены:') if changed else 'Инструменты проекта совпадают с шаблоном.')
    print('\n'.join('  ' + name for name in changed))
    known = {source.relative_to(TEMPLATE).as_posix() for source in files()}
    extra = sorted(
        relative for folder in ('scripts', 'tests', '.claude/agents', '.claude/commands', '.claude/skills')
        for path in (target / folder).rglob('*')
        if path.is_file() and not SKIP & set(path.relative_to(target).parts)
        for relative in [path.relative_to(target).as_posix()] if relative not in known)
    if extra:
        print('Есть в проекте, но не в шаблоне (свои или устаревшие; не удаляются):')
        print('\n'.join('  ' + name for name in extra))
    # Команда и навык делят одно пространство имён: навык проекта с именем команды шаблона
    # не даст собрать интеграцию.
    commands = {Path(name).stem for name in known if name.startswith('.claude/commands/')}
    clash = sorted(commands & {path.parent.name for path in (target / '.claude/skills').glob('*/SKILL.md')})
    if clash:
        message = ('Навык проекта носит имя команды шаблона: ' + ', '.join(clash) +
                   '. Удалите папку .claude/skills/ИМЯ/ и повторите обновление.')
        if not dry:
            raise SystemExit(message)
        print(message)
    if changed and not dry:
        print('Проверьте: python scripts/state/proj.py check --fast')
    if not dry:
        prepare_harness(target)
    else:
        print('После обновления будут пересобраны .dsh/skills/ и output/harness/ из локальной .mcp.json.')


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('target', type=Path, help='папка нового проекта или, с --update, существующего')
    parser.add_argument('--lib', help='имя библиотеки Lean и пространства имён')
    parser.add_argument('--title', help='название темы')
    parser.add_argument('--pins-from', type=Path, help='проект, из которого взять версии Lean и Mathlib')
    parser.add_argument('--no-git', action='store_true', help='не выполнять git init')
    parser.add_argument('--update', action='store_true', help='обновить инструменты существующего проекта')
    parser.add_argument('--dry-run', action='store_true', help='с --update: только показать, что изменится')
    args = parser.parse_args()
    if args.update:
        update(args.target.resolve(), args.dry_run)
    elif not (args.lib and args.title):
        parser.error('для нового проекта нужны --lib и --title')
    else:
        create(args.target.resolve(), args.lib, args.title, args.pins_from, not args.no_git)


if __name__ == '__main__':
    main()
