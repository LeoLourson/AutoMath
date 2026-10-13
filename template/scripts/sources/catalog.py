"""Каталог подборки: страница `sources/catalog.md`, статус источника, наличие карточки.

Каталог — сводка реестра: что скачано, что сверено, чего не хватает. Ручных правок в нём
не бывает, его пересобирает `lit.py catalog` и `proj.py sync`.
"""
from __future__ import annotations

import re
from datetime import date

import records

from sources import paths, registry
def cards() -> set[str]:
    """Коды источников, у которых есть карточка проверенных теорем."""
    found: set[str] = set()
    if paths.CARDS.exists():
        found = {doc.id for doc in (records.read_doc(path) for path in paths.CARDS.glob('S*.md')) if doc.id}
    if paths.RESULTS.exists():
        headings = ' '.join(re.findall(r'^## (.*)$', paths.RESULTS.read_text(encoding='utf-8'), re.M))
        found |= set(re.findall(r'S\d+', headings))
    return found


def status_of(row: dict, carded: set[str]) -> str:
    have = []
    if row.get('tex'):
        have.append({'arxiv': 'LaTeX-исходник', 'transcription': 'LaTeX-транскрипция'}.get(row.get('tex_origin'), 'LaTeX'))
    if row.get('filename'):
        have.append('PDF' if row.get('text_layer', True) else 'PDF-скан без текстового слоя')
    missing = [row[key] for key in ('tex', 'filename') if row.get(key) and not (LIT / row[key]).exists()]
    return ((', '.join(have) if have else 'Полного текста нет')
            + ('; карточка есть.' if row['code'] in carded else '; теоремы не проверены.')
            + (f" Нет файлов: {', '.join(missing)} — `python scripts/sources/lit.py fetch`." if missing else ''))


def catalog() -> str:
    rows, carded = registry.load(), cards()
    out = [
        '# Подборка полных текстов', '',
        f'Обновлено {date.today():%d.%m.%Y}. Работ в подборке: {len(rows)}. Файл собран командой '
        '`python scripts/sources/lit.py catalog` из [papers.json](papers.json); правки вносятся в реестр. Тексты лежат в '
        '`output/literature/`, вне Git. Наличие полного текста не означает проверку его теорем. '
        'LaTeX-транскрипция сделана моделью по PDF: при расхождении первичен PDF.', '',
    ]
    for row in rows:
        row['status'] = status_of(row, carded)
        links = [f"[Первичный источник]({row['url']})"]
        if row.get('pdf_url'):
            links.append(f"[полный текст]({row['pdf_url']})")
        if row.get('tex'):
            links.append(f"[локальный LaTeX](../output/literature/{row['tex']})")
        if row.get('filename'):
            links.append(f"[локальный PDF](../output/literature/{row['filename']})")
        volume = f"**Объём:** {row['pages']} стр. " if row.get('pages') else ''
        sums = [f"PDF `{row['sha256']}`"] if row.get('sha256') else []
        if row.get('eprint_sha256'):
            sums.append(f"исходник arXiv `{row['eprint_sha256']}`")
        title = row['title'] + (f" / {row['title_en']}" if row.get('title_en') else '')
        out += [f"## {row['code']}. {title}", '',
                f"**Авторы:** {row['authors']}. **Версия:** {row['version']}.",
                '; '.join(links) + '.',
                f"{volume}**Статус:** {row['status']}",
                f"**Связь с проектом:** {row['role']}"]
        if sums:
            out.append('**SHA-256:** ' + '; '.join(sums) + '.')
        out.append('')
    if rows:
        registry.save(rows)
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text('\n'.join(out), encoding='utf-8', newline='\n')
    return f'Каталог пересобран, работ: {len(rows)}.'
