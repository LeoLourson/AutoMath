"""Каталог подборки: страница `sources/catalog.md`, статус источника, наличие карточки.

Каталог — сводка реестра: что скачано, что сверено, чего не хватает. Ручных правок в нём
не бывает. Сборка текста (`text`) отделена от записи (`catalog`): свежесть страницы сверяет
`check/summaries.py`, а проверка не должна уметь писать, поэтому она берёт только чистую
сборку. Запись обновляет статусы в `papers.json` и переписывает страницу.

Строки «Обновлено <дата>» в тексте нет: с ней содержимое менялось бы каждые сутки и точная
сверка свежести была бы невозможна. Когда страница правилась, видно в Git.

Факты о подборке — коды реестра, коды с карточкой и коды со сверенной карточкой — считает
`registry.facts()`: одно правило на каталог и на `proj.py check`.
"""
from __future__ import annotations

from sources import paths, registry


def status_of(row: dict, carded: set[str]) -> str:
    have = []
    if row.get('tex'):
        have.append({'arxiv': 'LaTeX-исходник', 'transcription': 'LaTeX-транскрипция'}.get(row.get('tex_origin'), 'LaTeX'))
    if row.get('filename'):
        have.append('PDF' if row.get('text_layer', True) else 'PDF-скан без текстового слоя')
    missing = [row[key] for key in ('tex', 'filename') if row.get(key) and not (paths.LIT / row[key]).exists()]
    return ((', '.join(have) if have else 'Полного текста нет')
            + ('; карточка есть.' if row['code'] in carded else '; теоремы не проверены.')
            + (f" Нет файлов: {', '.join(missing)} — `python scripts/sources/lit.py fetch`." if missing else ''))


def marked(rows: list[dict], carded: set[str]) -> list[dict]:
    """Копии строк реестра с пересчитанным полем status: сам реестр при сборке не меняется."""
    found = [dict(row) for row in rows]
    for row in found:
        row['status'] = status_of(row, carded)
    return found


def page(rows: list[dict]) -> str:
    """Текст страницы по строкам реестра со статусами."""
    out = [
        '# Подборка полных текстов', '',
        f'Работ в подборке: {len(rows)}. Файл собран командой '
        '`python scripts/sources/lit.py catalog` из [papers.json](papers.json); правки вносятся в реестр. Тексты лежат в '
        '`output/literature/`, вне Git. Наличие полного текста не означает проверку его теорем. '
        'LaTeX-транскрипция сделана моделью по PDF: при расхождении первичен PDF.', '',
    ]
    for row in rows:
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
    return '\n'.join(out)


def text() -> str:
    """Чистая сборка текста каталога: ничего не пишет и реестр не меняет."""
    facts = registry.facts()
    return page(marked(registry.load(), facts.carded))


def catalog() -> str:
    """Пересобирает страницу каталога и статусы в papers.json; возвращает сообщение."""
    facts = registry.facts()
    rows = marked(registry.load(), facts.carded)
    if rows:
        registry.save(rows)
    paths.CATALOG.parent.mkdir(parents=True, exist_ok=True)
    paths.CATALOG.write_text(page(rows), encoding='utf-8', newline='\n')
    return f'Каталог пересобран, работ: {len(rows)}.'
