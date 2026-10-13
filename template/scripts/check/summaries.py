"""Свежесть собираемых сводок.

Тексты сводок строит `state/summaries.py`; здесь только сверка с тем, что лежит в проекте.
Разделение не косметическое: сборка сводки — работа, проверка — суждение, и проверка не
должна уметь писать.
"""
from __future__ import annotations

from pathlib import Path


def stale(root: Path, expected: dict[str, str]) -> list[str]:
    """Имена сводок, которые разошлись с шапками записей."""
    notes = []
    for name, text in expected.items():
        current = (root / name).read_text(encoding='utf-8').replace('\r\n', '\n') \
            if (root / name).exists() else ''
        if current != text:
            notes.append(f'{name} устарел: python scripts/state/proj.py sync')
    return notes
