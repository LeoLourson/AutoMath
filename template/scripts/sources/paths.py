"""Пути источников в проекте: реестр, карточки, тексты и индекс.

Считаются от корня проекта, а не от места установки скрипта, поэтому один и тот же
инструмент работает в любом каталоге: `paths.configure(корень)`. Корень передаёт
`sources/lit.py` (ключ `--root`); тесты зовут `configure` с временным каталогом.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from sources import web

# Заполняются configure(); до него указывают на каталог этого файла.
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'sources' / 'papers.json'
CATALOG = ROOT / 'sources' / 'catalog.md'
CARDS = ROOT / 'sources' / 'cards'
RESULTS = ROOT / 'sources' / 'results.md'  # вариант раскладки: все карточки в одном файле
LIT = ROOT / 'output' / 'literature'
DB = LIT / 'index' / 'lit.sqlite'


def configure(root: Path, direct_hosts: list[str] | None = None) -> None:
    """Пути источников и хосты, к которым идём мимо туннеля."""
    global ROOT, REGISTRY, CATALOG, CARDS, RESULTS, LIT, DB
    ROOT = Path(root)
    REGISTRY = ROOT / 'sources' / 'papers.json'
    CATALOG = ROOT / 'sources' / 'catalog.md'
    CARDS = ROOT / 'sources' / 'cards'
    RESULTS = ROOT / 'sources' / 'results.md'
    LIT = ROOT / 'output' / 'literature'
    DB = LIT / 'index' / 'lit.sqlite'
    web.configure(root, direct_hosts)


configure(ROOT)
