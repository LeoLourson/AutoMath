"""Запуск Lean в проекте: сборка, произвольная команда, аудит аксиом.

Единственное место, откуда инструменты проекта зовут `lake` и `lean`. Дочернему
процессу закрывается stdin: под MCP-сервером он иначе наследует канал протокола и на
Windows зависает.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def lake() -> str:
    """Путь к lake из PATH или из установки elan по умолчанию."""
    found = shutil.which('lake')
    if found:
        return found
    fallback = Path.home() / '.elan' / 'bin' / ('lake.exe' if os.name == 'nt' else 'lake')
    if fallback.exists():
        return str(fallback)
    raise SystemExit('lake не найден: установите elan, https://lean-lang.org/install')


def run(root: Path, command: list[str], timeout: int = 3600) -> tuple[int, str]:
    """Команда в корне проекта; возвращает код возврата и объединённый вывод."""
    done = subprocess.run(command, cwd=root, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')


def audit(root: Path, library: str, names: list[str], allowed: set[str]) -> list[str]:
    """Проверяет в Lean, что объявления существуют и зависят только от разрешённых аксиом.

    Пишет `output/Audit.lean` с `#print axioms` по каждому имени и разбирает вывод.
    """
    if not names:
        return []
    target = root / 'output' / 'Audit.lean'
    target.parent.mkdir(exist_ok=True)
    target.write_text(f'import {library}\n' + ''.join(f'#print axioms {name}\n' for name in names),
                      encoding='utf-8', newline='\n')
    code, output = run(root, [lake(), 'env', 'lean', target.relative_to(root).as_posix()])
    found = {name: {axiom.strip() for axiom in listed.split(',') if axiom.strip()}
             for name, listed in re.findall(r"'([^']+)' depends on axioms: \[(.*?)\]", output, re.S)}
    found.update({name: set() for name in re.findall(r"'([^']+)' does not depend on any axioms", output)})
    errors = []
    for name in names:
        if name not in found:
            errors.append(f'{name}: Lean не нашёл объявление или не смог его проверить')
        elif found[name] - allowed:
            errors.append(f"{name}: лишние аксиомы {', '.join(sorted(found[name] - allowed))}")
    if errors and code:
        errors.append('вывод Lean: ' + ' '.join(output.split())[:600])
    return errors
