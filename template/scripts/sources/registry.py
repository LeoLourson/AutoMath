"""Реестр источников: papers.json, добавление работ, прикрепление файлов.

Реестр — единственное место, где источник получает код `S…`; номера не переиспользуются.
Теорема источника становится посылкой доказательства только после карточки
`sources/cards/S*.md` и её сверки с PDF, а не после добавления в реестр.
"""
from __future__ import annotations

import hashlib
import json
import re

from sources import papers, paths, store

# Тег arXiv поверх Atom; нужен запросам списка работ.
ATOM = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
def load() -> list[dict]:
    return json.loads(REGISTRY.read_text(encoding='utf-8')) if REGISTRY.exists() else []


def save(rows: list[dict]) -> None:
    rows.sort(key=lambda row: int(row['code'][1:]))
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def next_code(rows: list[dict]) -> str:
    return 'S%d' % (max((int(row['code'][1:]) for row in rows), default=0) + 1)


def arxiv_id(row: dict) -> str | None:
    version = row.get('version', '')
    return version[6:] if version.startswith('arXiv:') else None


def bare(ident: str) -> str:
    return re.sub(r'v\d+$', '', re.sub(r'(?i)^arxiv:', '', ident.strip()))


def dois_of(row: dict) -> list[str]:
    found = [row.get('doi'), row.get('doi_en')]
    match = re.search(r'doi\.org/(.+)$', row.get('url', ''))
    return [doi.lower() for doi in found + [match.group(1) if match else None] if doi]


def known(rows: list[dict]) -> dict[str, str]:
    """Код источника по ключам arxiv:…, mathnet:…, doi:…"""
    table = {}
    for row in rows:
        if arxiv_id(row):
            table['arxiv:' + bare(arxiv_id(row))] = row['code']
        if row.get('mathnet'):
            table['mathnet:' + row['mathnet']] = row['code']
        for doi in dois_of(row):
            table['doi:' + doi] = row['code']
    return table


def by_code(rows: list[dict], code: str) -> dict:
    for row in rows:
        if row['code'] == code.upper():
            return row
    raise SystemExit(f'В реестре нет источника {code}.')


def stem_of(row: dict) -> str:
    for key in ('filename', 'tex'):
        if row.get(key):
            return Path(row[key]).stem
    if arxiv_id(row):
        return arxiv_id(row).replace('/', '-')
    return row.get('mathnet') or row['code']


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify(ident: str) -> tuple[str, str]:
    """Вид идентификатора и его нормальная форма: arxiv, mathnet или doi."""
    text = ident.strip()
    match = (re.search(r'mathnet\.ru/(?:rus/|eng/)?([a-z]+\d+)\b', text)
             or re.fullmatch(r'(?i)(?:mathnet:|mi\s+)([a-z]+\d+)', text))
    if match:
        return 'mathnet', match.group(1).lower()
    match = re.search(r'jrnid=([a-z]+)&(?:amp;)?paperid=(\d+)', text)
    if match:
        return 'mathnet', match.group(1) + match.group(2)
    doi = re.sub(r'(?i)^(doi:|https?://(dx\.)?doi\.org/)', '', text)
    if doi.startswith('10.'):
        if doi.lower().startswith('10.4213/'):  # DOI журналов MathNet: суффикс — идентификатор статьи
            return 'mathnet', doi.split('/', 1)[1].lower()
        if doi.lower().startswith('10.48550/arxiv.'):
            return 'arxiv', doi[len('10.48550/arxiv.'):]
        return 'doi', doi
    match = re.search(r'arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?$', text)
    if match:
        return 'arxiv', match.group(1)
    if re.fullmatch(r'(?i)(arxiv:)?(\d{4}\.\d{4,5}|[a-z-]+(\.[a-z]{2})?/\d{7})(v\d+)?', text):
        return 'arxiv', re.sub(r'(?i)^arxiv:', '', text)
    if re.fullmatch(r'[a-z]+\d+', text):
        return 'mathnet', text
    raise ValueError(f'не распознан идентификатор «{ident}»: нужен arXiv, mathnet:… или DOI')
def add(idents: list[str], role: str) -> list[str]:
    """Добавляет источники по идентификаторам arXiv, MathNet и DOI: метаданные, текст, каталог, индекс."""
    rows, report, added = registry.load(), [], []
    for ident in idents:
        try:
            kind, value = registry.classify(ident)
            key = f'{kind}:{registry.bare(value) if kind == "arxiv" else value.lower()}'
            if key in registry.known(rows):
                report.append(f'{registry.known(rows)[key]}: {key} уже в реестре')
                continue
            row = dict(code=registry.next_code(rows))
            if kind == 'arxiv':
                found = papers.arxiv_query(id_list=value)
                if not found:
                    raise ValueError(f'arXiv:{value}: не найдено')
                meta = found[0]
                row.update(authors='; '.join(meta['authors']), title=meta['title'], year=meta['year'],
                           version='arXiv:' + meta['arxiv'], url='https://arxiv.org/abs/' + meta['arxiv'],
                           pdf_url='https://arxiv.org/pdf/' + meta['arxiv'], role=role)
                if meta.get('doi'):
                    row['doi'] = meta['doi']
                got = 'LaTeX-исходник' if store.store_eprint(row) == 'tex' else 'на arXiv только PDF'
            elif kind == 'mathnet':
                meta = papers.mathnet_meta(value)
                row.update(authors='; '.join(meta['authors']), title=meta['title'], year=meta['year'],
                           version=meta['version'], url=f'https://www.mathnet.ru/rus/{value}',
                           pdf_url=meta['pdf_url'], mathnet=value, role=role)
                for field in ('title_en', 'doi', 'doi_en'):
                    if meta.get(field):
                        row[field] = meta[field]
                if meta['full_text']:
                    store.store_pdf(row, web.http_get(meta['pdf_url']), value + '.pdf')
                    got = f"PDF, {row['pages']} стр." + ('' if row['text_layer'] else ', скан без текстового слоя')
                    got += f"; LaTeX нет — /transcribe {row['code']}"
                else:
                    got = 'полный текст на MathNet закрыт; файл добавляется командой attach'
            else:
                meta = papers.crossref_meta(value)
                row.update(authors='; '.join(meta['authors']), title=meta['title'], year=meta['year'],
                           version=meta['version'], url='https://doi.org/' + value, doi=value, role=role)
                got = 'только описание; файл добавляется командой attach'
        except (ValueError, ConnectionError, urllib.error.URLError) as error:
            report.append(f'{ident}: ОШИБКА — {error}')
            continue
        rows.append(row)
        registry.save(rows)
        added.append(row['code'])
        report.append(f"{row['code']}: {row['title']} ({row['version']}) — {got}")
    catalog()
    return report + (search.index(added) if added else [])


def add_file(source: str, title: str, authors: str, version: str, url: str, name: str, role: str) -> list[str]:
    """Добавляет источник без arXiv, MathNet и DOI: PDF или LaTeX по ссылке либо из локального файла."""
    rows = registry.load()
    row = dict(code=registry.next_code(rows), authors=authors, title=title, version=version, url=url, role=role)
    rows.append(row)
    _attach(row, source, name, 'local')
    registry.save(rows)
    catalog()
    return [f"{row['code']}: {title} — {'PDF' if row.get('filename') else 'LaTeX'}"] + search.index([row['code']])


def _attach(row: dict, source: str, name: str, origin: str) -> str:
    data = store.read_source(source)
    if data[:5] == b'%PDF-':
        if re.match(r'https?://', source):
            row['pdf_url'] = source
        row.pop('sha256', None)
        store.store_pdf(row, data, name + '.pdf')
        return 'PDF'
    LIT.mkdir(parents=True, exist_ok=True)
    (LIT / (name + '.tex')).write_text(papers.decode(data), encoding='utf-8', newline='\n')
    row.update(tex=name + '.tex', tex_origin=origin)
    return 'LaTeX'


def attach(code: str, source: str, origin: str = 'local') -> list[str]:
    """Прикрепляет к записи реестра PDF или LaTeX, полученный вручную."""
    rows = registry.load()
    row = registry.by_code(rows, code)
    got = _attach(row, source, registry.stem_of(row), origin)
    registry.save(rows)
    catalog()
    return [f"{row['code']}: прикреплён {got}"] + search.index([row['code']])
