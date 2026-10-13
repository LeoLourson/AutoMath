"""Полные тексты источника: скачивание, хранение, страницы и текстовый слой.

Тексты лежат в `output/literature/`, вне Git: они крупные и чужие, а восстановимы командой
`lit.py fetch`. Контрольная сумма из реестра сверяется при каждой записи файла, поэтому
подмена версии заметна сразу.
"""
from __future__ import annotations

import gzip
import re
import urllib.error
from pathlib import Path

from sources import papers, paths, registry, web
def pdf_text(pdf: Path) -> tuple[int, bool]:
    """Число страниц и признак текстового слоя; слой пишется в соседний .txt (страницы через \\f)."""
    import pymupdf as fitz
    with fitz.open(pdf) as doc:
        pages = [page.get_text() for page in doc]
    layer = sum(map(len, pages)) >= 400 * len(pages)
    if layer:
        pdf.with_suffix('.txt').write_text('\f'.join(pages), encoding='utf-8', newline='\n')
    return len(pages), layer


def store_pdf(row: dict, data: bytes, name: str) -> None:
    if data[:5] != b'%PDF-':
        raise ValueError(f"{row['code']}: по ссылке {row.get('pdf_url', '')} пришёл не PDF (доступ закрыт?)")
    if row.get('sha256') and row['sha256'] != registry.sha256(data):
        raise ValueError(f"{row['code']}: PDF отличается от записанного в реестре; сверь версию")
    LIT.mkdir(parents=True, exist_ok=True)
    (LIT / name).write_bytes(data)
    pages, layer = pdf_text(LIT / name)
    row.update(filename=name, pages=pages, sha256=registry.sha256(data), text_layer=layer)


def store_eprint(row: dict) -> str:
    """Скачивает исходник arXiv в output/literature/; возвращает 'tex' или 'pdf'."""
    data = web.http_get('https://arxiv.org/e-print/' + registry.arxiv_id(row))
    if row.get('eprint_sha256') not in (None, registry.sha256(data)):
        raise ValueError(f"{row['code']}: исходник arXiv отличается от записанного в реестре")
    files = papers.unpack(data)
    if files is None:
        if not row.get('filename'):
            store_pdf(row, gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data, registry.stem_of(row) + '.pdf')
        row['eprint'] = 'pdf'
        return 'pdf'
    name = registry.stem_of(row) + '.tex'
    LIT.mkdir(parents=True, exist_ok=True)
    (LIT / name).write_text(papers.flatten(files), encoding='utf-8', newline='\n')
    row.update(tex=name, tex_origin='arxiv', eprint_sha256=registry.sha256(data))
    return 'tex'


def read_source(source: str) -> bytes:
    return web.http_get(source) if re.match(r'https?://', source) else Path(source).read_bytes()
def fetch(codes: list[str] | None = None) -> list[str]:
    """Восстанавливает недостающие файлы: исходники arXiv и PDF, записанные в реестре."""
    rows, report = registry.load(), []
    for row in rows:
        if codes and row['code'] not in codes:
            continue
        done = []
        try:
            if row.get('filename') and not (LIT / row['filename']).exists():
                store.store_pdf(row, web.http_get(row['pdf_url']), row['filename'])
                done.append('PDF')
            if row.get('filename') and row.get('text_layer', True) \
                    and not (LIT / row['filename']).with_suffix('.txt').exists():
                row['pages'], row['text_layer'] = store.pdf_text(LIT / row['filename'])
                done.append('текст PDF')
            if registry.arxiv_id(row) and row.get('eprint') != 'pdf' and not (row.get('tex') and (LIT / row['tex']).exists()):
                done.append('LaTeX' if store.store_eprint(row) == 'tex' else 'на arXiv только PDF')
            if row.get('tex') and not (LIT / row['tex']).exists():
                raise ValueError(f"нет {row['tex']}: транскрипция и локальный LaTeX по ссылке не восстанавливаются")
        except (ValueError, ConnectionError, urllib.error.URLError) as error:
            report.append(f"{row['code']}: ОШИБКА — {error}")
            continue
        if done:
            registry.save(rows)
            report.append(f"{row['code']}: " + ', '.join(done))
    catalog()
    return report or ['Все файлы реестра на месте.']


def pdf(code: str) -> list[str]:
    """Скачивает PDF источника: номера теорем и страницы для карточки сверяются по нему."""
    rows = registry.load()
    row = registry.by_code(rows, code)
    if row.get('filename') and (LIT / row['filename']).exists():
        return [f"{row['code']}: output/literature/{row['filename']} уже есть"]
    if not row.get('pdf_url'):
        raise SystemExit(f"{row['code']}: ссылки на PDF нет; прикрепите файл командой attach")
    store.store_pdf(row, web.http_get(row['pdf_url']), row.get('filename') or registry.stem_of(row) + '.pdf')
    registry.save(rows)
    catalog()
    return [f"{row['code']}: output/literature/{row['filename']}, {row['pages']} стр."]


def pages(code: str, first: int = 1, last: int | None = None, dpi: int = 170) -> list[str]:
    """Страницы PDF в PNG и их текстовый слой: материал для транскрипции и сверки карточек."""
    import pymupdf as fitz
    row = registry.by_code(registry.load(), code)
    if not (row.get('filename') and (LIT / row['filename']).exists()):
        pdf(code)
        row = registry.by_code(registry.load(), code)
    folder = LIT / 'pages' / Path(row['filename']).stem
    folder.mkdir(parents=True, exist_ok=True)
    report = []
    with fitz.open(LIT / row['filename']) as doc:
        for number in range(first, min(last or len(doc), len(doc)) + 1):
            page = doc[number - 1]
            image = folder / f'p{number:04d}.png'
            if not image.exists():
                page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).save(image)
            text = page.get_text()
            note = 'текстового слоя нет'
            if len(text) >= 400:
                image.with_suffix('.txt').write_text(text, encoding='utf-8', newline='\n')
                note = f'слой: {image.with_suffix(".txt").relative_to(ROOT).as_posix()}'
            report.append(f'стр. файла {number}: {image.relative_to(ROOT).as_posix()}; {note}')
    return report
