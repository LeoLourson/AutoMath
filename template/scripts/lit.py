# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "onnxruntime", "tokenizers", "huggingface_hub", "pymupdf", "certifi"]
# ///
"""Источники проекта: реестр, загрузка полных текстов, транскрипции, индекс и поиск.

Реестр — sources/papers.json; каталог sources/catalog.md строится из него.
Тексты и индекс лежат в output/literature/, вне Git. Команды: python scripts/lit.py -h.
"""
from __future__ import annotations

import argparse
import bisect
import functools
import gzip
import hashlib
import html
import http.client
import http.cookiejar
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / 'sources' / 'papers.json'
CATALOG = ROOT / 'sources' / 'catalog.md'
CARDS = ROOT / 'sources' / 'cards'
RESULTS = ROOT / 'sources' / 'results.md'  # вариант раскладки: все карточки в одном файле
LIT = ROOT / 'output' / 'literature'
DB = LIT / 'index' / 'lit.sqlite'

MODEL = 'intfloat/multilingual-e5-small'
CHUNKER = 3  # увеличить после изменения нарезки: индекс пересоберётся
CHUNK = 1000  # знаков; в LaTeX это около 450 токенов при пределе модели 512
USER_AGENT = 'lit/2.0 (research script)'
ATOM = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
DELAYS = {'arxiv.org': 3.0, 'mathnet.ru': 2.0, 'semanticscholar.org': 1.0}  # секунд между запросами


def settings() -> dict:
    path = ROOT / 'project.toml'
    return tomllib.loads(path.read_text(encoding='utf-8')).get('sources', {}) if path.exists() else {}


# Хосты, до которых трафик через VPN-туннель не доходит: к ним идём с адреса другого интерфейса
DIRECT_HOSTS = [host.strip() for host in os.environ.get('LIT_DIRECT_HOSTS', '').split(',') if host.strip()] \
    or settings().get('direct_hosts', ['mathnet.ru'])


# ---------- сеть ----------

_jar = http.cookiejar.CookieJar()
_openers: dict = {}
_routes: dict = {}
_last: dict = {}
_tls = None


def tls_context() -> ssl.SSLContext:
    """Системные корневые сертификаты и набор certifi: Windows подгружает корни лениво."""
    global _tls
    if _tls is None:
        _tls = ssl.create_default_context()
        try:
            import certifi
            _tls.load_verify_locations(certifi.where())
        except ImportError:
            pass
    return _tls


def local_sources() -> list[str]:
    """Локальные адреса вне маршрута по умолчанию, то есть вне VPN-туннеля."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))
            default = probe.getsockname()[0]
        found = {item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return []
    return sorted(address for address in found
                  if address != default and not address.startswith(('127.', '169.254.')))


def opener(source: str | None) -> urllib.request.OpenerDirector:
    if source not in _openers:
        bind = {'source_address': (source, 0)} if source else {}

        class Https(urllib.request.HTTPSHandler):
            def https_open(self, request):
                return self.do_open(functools.partial(http.client.HTTPSConnection, **bind), request,
                                    context=tls_context())

        class Http(urllib.request.HTTPHandler):
            def http_open(self, request):
                return self.do_open(functools.partial(http.client.HTTPConnection, **bind), request)

        # Ссылка на PDF в MathNet отдаёт файл только сессии с cookie, выданной при перенаправлении
        _openers[source] = urllib.request.build_opener(Https(), Http(), urllib.request.HTTPCookieProcessor(_jar))
    return _openers[source]


def site_of(url: str) -> str:
    return '.'.join((urllib.parse.urlsplit(url).hostname or '').split('.')[-2:])


def http_get(url: str, tries: int = 4) -> bytes:
    site = site_of(url)
    direct = any(site == host or site.endswith('.' + host) for host in DIRECT_HOSTS)
    routes = [_routes[site]] if site in _routes else (local_sources() + [None] if direct else [None])
    failure = None
    for source in routes:
        for attempt in range(tries):
            time.sleep(max(0.0, _last.get(site, 0.0) + DELAYS.get(site, 0.3) - time.monotonic()))
            try:
                request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
                with opener(source).open(request, timeout=25 if len(routes) > 1 else 90) as response:
                    data = response.read()
                _routes[site] = source
                return data
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == tries:
                    raise
                time.sleep(5 * (attempt + 1))
            except (urllib.error.URLError, OSError) as error:
                failure = error
                break
            finally:
                _last[site] = time.monotonic()
    hint = (' Хост из списка direct_hosts недоступен ни через туннель, ни напрямую: добавьте для него прямое '
            'правило в VPN-клиенте или отключите VPN на время загрузки.') if direct else ''
    raise ConnectionError(f'{site}: нет соединения ({failure}).{hint}')


def squash(text: str | None) -> str:
    return ' '.join((text or '').split())


def html_text(fragment: str) -> str:
    return squash(html.unescape(re.sub(r'<[^>]+>', ' ', fragment)).replace('\xa0', ' '))


# ---------- реестр ----------

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


# ---------- arXiv ----------

def arxiv_query(**params) -> list[dict]:
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params)
    papers = []
    for entry in ET.fromstring(http_get(url)).findall('a:entry', ATOM):
        ident = entry.findtext('a:id', '', ATOM)
        if '/abs/' not in ident:
            continue
        papers.append(dict(
            arxiv=ident.rsplit('/abs/', 1)[1],
            title=squash(entry.findtext('a:title', '', ATOM)),
            authors=[squash(a.findtext('a:name', '', ATOM)) for a in entry.findall('a:author', ATOM)],
            year=entry.findtext('a:published', '', ATOM)[:4],
            abstract=squash(entry.findtext('a:summary', '', ATOM)),
            doi=entry.findtext('x:doi', None, ATOM),
        ))
    return papers


def unpack(data: bytes) -> dict[str, bytes] | None:
    """Текстовые файлы исходника по именам; None, если на arXiv лежит только PDF."""
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    if data[:5] == b'%PDF-':
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            return {
                member.name.removeprefix('./'): tar.extractfile(member).read()
                for member in tar
                if member.isfile() and member.size < 20_000_000
                and member.name.lower().endswith(('.tex', '.ltx', '.bbl'))
            }
    except tarfile.ReadError:
        return {'main.tex': data}


def decode(raw: bytes) -> str:
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')


def strip_comments(text: str) -> str:
    text = re.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', text, flags=re.S)
    lines = []
    for line in text.replace('\r\n', '\n').split('\n'):
        if line.lstrip().startswith('%'):
            continue  # строка-комментарий абзац не разрывает
        lines.append(re.sub(r'(?<!\\)%.*', '', line).rstrip())
    return '\n'.join(lines)


INPUT = re.compile(r'\\(?:input|include|subfile)\s*\{([^{}]+)\}|\\input\s+([^\s{}\\]+)')


def flatten(files: dict[str, bytes]) -> str:
    """Главный файл со вставленными \\input и списком литературы из .bbl."""
    texts = {name: strip_comments(decode(raw)) for name, raw in files.items()}

    def resolve(name: str, folder: str) -> str | None:
        for prefix in (folder, ''):
            for ext in ('', '.tex', '.ltx'):
                candidate = (prefix + name.strip() + ext).removeprefix('./')
                if candidate in texts and not candidate.endswith('.bbl'):
                    return candidate
        return None

    def expand(name: str, stack: tuple[str, ...] = ()) -> str:
        folder = name.rsplit('/', 1)[0] + '/' if '/' in name else ''

        def substitute(match: re.Match) -> str:
            target = resolve(match.group(1) or match.group(2), folder)
            if target is None or target in stack or len(stack) > 8:
                return match.group(0)
            return expand(target, stack + (name,))

        return INPUT.sub(substitute, texts[name])

    sources = [name for name in texts if not name.endswith('.bbl')]
    mains = [name for name in sources if re.search(r'\\documentclass|\\documentstyle', texts[name])]
    if not (mains or sources):
        raise ValueError('в архиве нет файлов TeX')
    main = max(mains or sources, key=lambda name: ('\\begin{document}' in texts[name], len(expand(name))))
    text = expand(main)
    bbls = [name for name in texts if name.endswith('.bbl')]
    if bbls and '\\begin{thebibliography}' not in text:
        own = main.rsplit('.', 1)[0] + '.bbl'
        bbl = texts[own if own in bbls else max(bbls, key=lambda name: len(texts[name]))]
        text, count = re.subn(r'\\bibliography\s*\{[^{}]*\}', lambda _: bbl, text, count=1)
        if not count:
            text += '\n' + bbl
    return text.strip() + '\n'


# ---------- MathNet ----------

def amsbib(page: str) -> dict:
    """Поля блока AMSBIB со страницы статьи; перевод (после \\transl) — с суффиксом _en."""
    block = re.search(r'<div class=showamsbib>(.*?)</div>', page, re.S)
    if not block:
        return {}
    fields, suffix = {}, ''
    for line in re.split(r'<br\s*/?>', block.group(1)):
        line = html_text(line).replace('~', ' ').replace('--', '–')
        if line == '\\transl':
            suffix = '_en'
        match = re.match(r'\\(\w+)\s*\{?(.*?)\}?$', line)
        if match and match.group(2):
            fields.setdefault(match.group(1) + suffix, match.group(2).strip())
    return fields


def mathnet_meta(pid: str) -> dict:
    journal, number = re.fullmatch(r'([a-z]+)(\d+)', pid).groups()
    page = http_get(f'https://www.mathnet.ru/rus/{pid}').decode('cp1251', 'replace')
    fields = amsbib(page)
    if not fields.get('paper'):
        raise ValueError(f'mathnet:{pid}: статья не найдена')
    english = amsbib(http_get(f'https://www.mathnet.ru/eng/{pid}').decode('cp1251', 'replace'))
    abstract = re.search(r'<b>Аннотация:</b>(.*?)</div>', page, re.S)
    doi = lambda link: re.sub(r'^https?://doi\.org/', '', link) if link else None
    issue = f":{fields['issue']}" if fields.get('issue') else ''
    return dict(
        mathnet=pid,
        title=fields['paper'],
        title_en=english.get('paper'),
        authors=[name.strip() for name in fields.get('by', '').split(',') if name.strip()],
        year=fields.get('yr', ''),
        version=f"{fields.get('jour', '')}, {fields.get('vol', '')}{issue} ({fields.get('yr', '')}), "
                f"{fields.get('pages', '')}",
        doi=doi(fields.get('crossref')),
        doi_en=doi(fields.get('crossref_en')),
        abstract=html_text(abstract.group(1)).replace('\\lt', '<').replace('\\gt', '>') if abstract else '',
        full_text=f'getFT.phtml?jrnid={journal}&paperid={number}&what=fullt&' in page.replace('&amp;', '&'),
        pdf_url=f'https://www.mathnet.ru/php/getFT.phtml?jrnid={journal}&paperid={number}&what=fullt&option_lang=rus',
    )


def mathnet_citing(pid: str) -> list[dict]:
    """Работы из списка цитирования на странице статьи."""
    page = http_get(f'https://www.mathnet.ru/paperfwl/rus/{pid}').decode('cp1251', 'replace')
    papers = []
    for item in re.split(r'<li\b', page)[1:]:
        text = html_text(item.split('>', 1)[1])
        quoted = re.search(r'“(.+?)”', text)
        link = re.search(r'mi\.mathnet\.ru/(?:rus/|eng/)?([a-z]+\d+)', item)
        doi = re.search(r'https?://doi\.org/([^"\'\s<>]+)', item)
        year = re.search(r'\b(?:19|20)\d\d\b', text[quoted.end():] if quoted else text)
        papers.append(dict(
            mathnet=link.group(1) if link else None,
            doi=doi.group(1) if doi else None,
            title=quoted.group(1) if quoted else text[:200],
            authors=[text[:quoted.start()].strip(' ,')] if quoted else [],
            year=year.group(0) if year else '',
            abstract=text[quoted.end():].strip(' ,') if quoted else '',
        ))
    return papers


# ---------- Crossref, zbMATH, Semantic Scholar ----------

def crossref_meta(doi: str) -> dict:
    item = json.loads(http_get('https://api.crossref.org/works/' + urllib.parse.quote(doi)))['message']
    year = ((item.get('issued') or {}).get('date-parts') or [[None]])[0][0]
    place = ', '.join(part for part in (
        (item.get('container-title') or [''])[0],
        ' '.join(filter(None, [item.get('volume'), f"({item['issue']})" if item.get('issue') else ''])),
        item.get('page')) if part)
    return dict(
        doi=doi,
        title=squash((item.get('title') or ['?'])[0]),
        authors=[squash(f"{a.get('given', '')} {a.get('family', '')}") for a in item.get('author', [])],
        year=str(year or ''),
        version=f'{place} ({year})' if place else f'DOI:{doi}',
    )


def crossref_search(query: str, limit: int, prefix: str) -> list[dict]:
    params = urllib.parse.urlencode({'query.bibliographic': query, 'filter': 'prefix:' + prefix, 'rows': limit,
                                     'select': 'DOI,title,author,issued,container-title'})
    papers = []
    for item in json.loads(http_get('https://api.crossref.org/works?' + params))['message']['items']:
        doi = item['DOI']
        papers.append(dict(
            mathnet=doi.split('/', 1)[1].lower() if doi.startswith('10.4213/') else None,
            doi=doi,
            title=squash((item.get('title') or ['?'])[0]),
            authors=[squash(f"{a.get('given', '')} {a.get('family', '')}") for a in item.get('author', [])],
            year=((item.get('issued') or {}).get('date-parts') or [['']])[0][0],
            abstract=(item.get('container-title') or [''])[0],
        ))
    return papers


def zbmath_search(query: str, limit: int) -> list[dict]:
    """Поиск в zbMATH Open; запрос — в его синтаксисе (au:, ti:, py:, &, |)."""
    params = urllib.parse.urlencode({'search_string': query, 'results_per_page': limit})
    papers = []
    for item in json.loads(http_get('https://api.zbmath.org/v1/document/_search?' + params)).get('result') or []:
        links = {link.get('type'): link.get('identifier') for link in item.get('links') or []}
        notes = item.get('editorial_contributions') or [{}]
        papers.append(dict(
            zbmath=item.get('id'),
            arxiv=links.get('arxiv'),
            doi=links.get('doi'),
            title=squash((item.get('title') or {}).get('title')),
            authors=[a.get('name', '') for a in (item.get('contributors') or {}).get('authors', [])],
            year=item.get('year') or '',
            abstract=squash(f"{(item.get('source') or {}).get('source', '')} {notes[0].get('text') or ''}"),
        ))
    return papers


def scholar(ref: str, references: bool, limit: int) -> list[dict]:
    url = (f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(ref, safe=':/')}/"
           f"{'references' if references else 'citations'}?fields=title,year,authors,externalIds,abstract&limit={limit}")
    papers = []
    for item in json.loads(http_get(url)).get('data') or []:
        paper = item['citedPaper' if references else 'citingPaper']
        if paper.get('title'):
            external = paper.get('externalIds') or {}
            papers.append(dict(arxiv=external.get('ArXiv'), doi=external.get('DOI'), title=paper['title'],
                               year=paper.get('year'), authors=[a['name'] for a in paper.get('authors') or []],
                               abstract=squash(paper.get('abstract'))))
    return papers


# ---------- файлы источников ----------

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
    if row.get('sha256') and row['sha256'] != sha256(data):
        raise ValueError(f"{row['code']}: PDF отличается от записанного в реестре; сверь версию")
    LIT.mkdir(parents=True, exist_ok=True)
    (LIT / name).write_bytes(data)
    pages, layer = pdf_text(LIT / name)
    row.update(filename=name, pages=pages, sha256=sha256(data), text_layer=layer)


def store_eprint(row: dict) -> str:
    """Скачивает исходник arXiv в output/literature/; возвращает 'tex' или 'pdf'."""
    data = http_get('https://arxiv.org/e-print/' + arxiv_id(row))
    if row.get('eprint_sha256') not in (None, sha256(data)):
        raise ValueError(f"{row['code']}: исходник arXiv отличается от записанного в реестре")
    files = unpack(data)
    if files is None:
        if not row.get('filename'):
            store_pdf(row, gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data, stem_of(row) + '.pdf')
        row['eprint'] = 'pdf'
        return 'pdf'
    name = stem_of(row) + '.tex'
    LIT.mkdir(parents=True, exist_ok=True)
    (LIT / name).write_text(flatten(files), encoding='utf-8', newline='\n')
    row.update(tex=name, tex_origin='arxiv', eprint_sha256=sha256(data))
    return 'tex'


def read_source(source: str) -> bytes:
    return http_get(source) if re.match(r'https?://', source) else Path(source).read_bytes()


# ---------- команды реестра ----------

def add(idents: list[str], role: str) -> list[str]:
    """Добавляет источники по идентификаторам arXiv, MathNet и DOI: метаданные, текст, каталог, индекс."""
    rows, report, added = load(), [], []
    for ident in idents:
        try:
            kind, value = classify(ident)
            key = f'{kind}:{bare(value) if kind == "arxiv" else value.lower()}'
            if key in known(rows):
                report.append(f'{known(rows)[key]}: {key} уже в реестре')
                continue
            row = dict(code=next_code(rows))
            if kind == 'arxiv':
                found = arxiv_query(id_list=value)
                if not found:
                    raise ValueError(f'arXiv:{value}: не найдено')
                meta = found[0]
                row.update(authors='; '.join(meta['authors']), title=meta['title'], year=meta['year'],
                           version='arXiv:' + meta['arxiv'], url='https://arxiv.org/abs/' + meta['arxiv'],
                           pdf_url='https://arxiv.org/pdf/' + meta['arxiv'], role=role)
                if meta.get('doi'):
                    row['doi'] = meta['doi']
                got = 'LaTeX-исходник' if store_eprint(row) == 'tex' else 'на arXiv только PDF'
            elif kind == 'mathnet':
                meta = mathnet_meta(value)
                row.update(authors='; '.join(meta['authors']), title=meta['title'], year=meta['year'],
                           version=meta['version'], url=f'https://www.mathnet.ru/rus/{value}',
                           pdf_url=meta['pdf_url'], mathnet=value, role=role)
                for field in ('title_en', 'doi', 'doi_en'):
                    if meta.get(field):
                        row[field] = meta[field]
                if meta['full_text']:
                    store_pdf(row, http_get(meta['pdf_url']), value + '.pdf')
                    got = f"PDF, {row['pages']} стр." + ('' if row['text_layer'] else ', скан без текстового слоя')
                    got += f"; LaTeX нет — /transcribe {row['code']}"
                else:
                    got = 'полный текст на MathNet закрыт; файл добавляется командой attach'
            else:
                meta = crossref_meta(value)
                row.update(authors='; '.join(meta['authors']), title=meta['title'], year=meta['year'],
                           version=meta['version'], url='https://doi.org/' + value, doi=value, role=role)
                got = 'только описание; файл добавляется командой attach'
        except (ValueError, ConnectionError, urllib.error.URLError) as error:
            report.append(f'{ident}: ОШИБКА — {error}')
            continue
        rows.append(row)
        save(rows)
        added.append(row['code'])
        report.append(f"{row['code']}: {row['title']} ({row['version']}) — {got}")
    catalog()
    return report + (index(added) if added else [])


def add_file(source: str, title: str, authors: str, version: str, url: str, name: str, role: str) -> list[str]:
    """Добавляет источник без arXiv, MathNet и DOI: PDF или LaTeX по ссылке либо из локального файла."""
    rows = load()
    row = dict(code=next_code(rows), authors=authors, title=title, version=version, url=url, role=role)
    rows.append(row)
    _attach(row, source, name, 'local')
    save(rows)
    catalog()
    return [f"{row['code']}: {title} — {'PDF' if row.get('filename') else 'LaTeX'}"] + index([row['code']])


def _attach(row: dict, source: str, name: str, origin: str) -> str:
    data = read_source(source)
    if data[:5] == b'%PDF-':
        if re.match(r'https?://', source):
            row['pdf_url'] = source
        row.pop('sha256', None)
        store_pdf(row, data, name + '.pdf')
        return 'PDF'
    LIT.mkdir(parents=True, exist_ok=True)
    (LIT / (name + '.tex')).write_text(decode(data), encoding='utf-8', newline='\n')
    row.update(tex=name + '.tex', tex_origin=origin)
    return 'LaTeX'


def attach(code: str, source: str, origin: str = 'local') -> list[str]:
    """Прикрепляет к записи реестра PDF или LaTeX, полученный вручную."""
    rows = load()
    row = by_code(rows, code)
    got = _attach(row, source, stem_of(row), origin)
    save(rows)
    catalog()
    return [f"{row['code']}: прикреплён {got}"] + index([row['code']])


def fetch(codes: list[str] | None = None) -> list[str]:
    """Восстанавливает недостающие файлы: исходники arXiv и PDF, записанные в реестре."""
    rows, report = load(), []
    for row in rows:
        if codes and row['code'] not in codes:
            continue
        done = []
        try:
            if row.get('filename') and not (LIT / row['filename']).exists():
                store_pdf(row, http_get(row['pdf_url']), row['filename'])
                done.append('PDF')
            if row.get('filename') and row.get('text_layer', True) \
                    and not (LIT / row['filename']).with_suffix('.txt').exists():
                row['pages'], row['text_layer'] = pdf_text(LIT / row['filename'])
                done.append('текст PDF')
            if arxiv_id(row) and row.get('eprint') != 'pdf' and not (row.get('tex') and (LIT / row['tex']).exists()):
                done.append('LaTeX' if store_eprint(row) == 'tex' else 'на arXiv только PDF')
            if row.get('tex') and not (LIT / row['tex']).exists():
                raise ValueError(f"нет {row['tex']}: транскрипция и локальный LaTeX по ссылке не восстанавливаются")
        except (ValueError, ConnectionError, urllib.error.URLError) as error:
            report.append(f"{row['code']}: ОШИБКА — {error}")
            continue
        if done:
            save(rows)
            report.append(f"{row['code']}: " + ', '.join(done))
    catalog()
    return report or ['Все файлы реестра на месте.']


def pdf(code: str) -> list[str]:
    """Скачивает PDF источника: номера теорем и страницы для карточки сверяются по нему."""
    rows = load()
    row = by_code(rows, code)
    if row.get('filename') and (LIT / row['filename']).exists():
        return [f"{row['code']}: output/literature/{row['filename']} уже есть"]
    if not row.get('pdf_url'):
        raise SystemExit(f"{row['code']}: ссылки на PDF нет; прикрепите файл командой attach")
    store_pdf(row, http_get(row['pdf_url']), row.get('filename') or stem_of(row) + '.pdf')
    save(rows)
    catalog()
    return [f"{row['code']}: output/literature/{row['filename']}, {row['pages']} стр."]


def pages(code: str, first: int = 1, last: int | None = None, dpi: int = 170) -> list[str]:
    """Страницы PDF в PNG и их текстовый слой: материал для транскрипции и сверки карточек."""
    import pymupdf as fitz
    row = by_code(load(), code)
    if not (row.get('filename') and (LIT / row['filename']).exists()):
        pdf(code)
        row = by_code(load(), code)
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


def cards() -> set[str]:
    """Коды источников, у которых есть карточка проверенных теорем."""
    found = {path.stem.upper() for path in CARDS.glob('S*.md')} if CARDS.exists() else set()
    if RESULTS.exists():
        headings = ' '.join(re.findall(r'^## (.*)$', RESULTS.read_text(encoding='utf-8'), re.M))
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
            + (f" Нет файлов: {', '.join(missing)} — `python scripts/lit.py fetch`." if missing else ''))


def catalog() -> str:
    rows, carded = load(), cards()
    out = [
        '# Подборка полных текстов', '',
        f'Обновлено {date.today():%d.%m.%Y}. Работ в подборке: {len(rows)}. Файл собран командой '
        '`python scripts/lit.py catalog` из [papers.json](papers.json); правки вносятся в реестр. Тексты лежат в '
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
        save(rows)
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text('\n'.join(out), encoding='utf-8', newline='\n')
    return f'Каталог пересобран, работ: {len(rows)}.'


# ---------- транскрипции ----------

PREAMBLE = r'''% Транскрипция PDF, сделанная моделью. При расхождении первичен PDF.
% Собрано командой `python scripts/lit.py tex` из частей output/literature/parts/.
\documentclass[11pt]{article}
\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[english,russian]{babel}
\usepackage{amsmath,amssymb,amsthm,mathrsfs}
% \pagemark{N} стоит там, где в оригинале начинается страница с печатным номером N
\newcommand{\pagemark}[1]{\marginpar{\footnotesize\textsf{с.\,#1}}}
% \unsure{...} — место, которое по изображению прочитано неуверенно
\newcommand{\unsure}[1]{\fbox{#1}}
% Утверждение с печатным номером: \begin{statement}{Теорема}{6.6} ... \end{statement}
\newenvironment{statement}[2]{\par\medskip\noindent\textbf{#1 #2.}\ \itshape}{\par\medskip}
'''


def tex_escape(text: str) -> str:
    return re.sub(r'(?<!\\)([&%#])', r'\\\1', text)


def lint_tex(text: str, pages: int | None) -> list[str]:
    """Механические замечания к транскрипции: окружения, скобки, метки страниц."""
    notes, stack = [], []
    for number, line in enumerate(text.split('\n'), 1):
        for kind, name in re.findall(r'\\(begin|end)\{([^{}]+)\}', re.sub(r'(?<!\\)%.*', '', line)):
            if kind == 'begin':
                stack.append((name, number))
            elif stack and stack[-1][0] == name:
                stack.pop()
            else:
                notes.append(f'строка {number}: \\end{{{name}}} без пары')
    notes += [f'строка {number}: \\begin{{{name}}} не закрыт' for name, number in stack]
    plain = re.sub(r'\\[{}]', '', text)
    if plain.count('{') != plain.count('}'):
        notes.append(f"фигурные скобки не сбалансированы: {plain.count('{')} открывающих, {plain.count('}')} закрывающих")
    marks = len(re.findall(r'\\pagemark\{', text)) - 1  # одно вхождение — определение в преамбуле
    if pages is not None and marks != pages:
        notes.append(f'меток \\pagemark: {marks}, страниц в PDF: {pages}')
    unsure = len(re.findall(r'\\unsure\{', text)) - 1
    if unsure > 0:
        notes.append(f'мест, прочитанных неуверенно (\\unsure): {unsure}')
    return notes


def compile_tex(path: Path) -> list[str]:
    if not shutil.which('pdflatex'):
        return ['pdflatex не найден: сборка не проверена']
    build = LIT / 'build'
    build.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
                          f'-output-directory={build}', str(path)], capture_output=True, cwd=LIT, stdin=subprocess.DEVNULL)
    log = run.stdout.decode('utf-8', 'replace')
    errors = [line for line in log.split('\n') if re.match(r'.*:\d+: |^! ', line)][:6]
    return [f'pdflatex: {line.strip()}' for line in errors] if run.returncode else []


def tex(code: str, origin: str = 'transcription', build: bool = False) -> list[str]:
    """Собирает транскрипцию из частей, проверяет её и записывает в реестр как LaTeX источника."""
    rows = load()
    row = by_code(rows, code)
    stem = stem_of(row)
    target, parts = LIT / (stem + '.tex'), sorted((LIT / 'parts' / stem).glob('*.tex'))
    if parts:
        head = PREAMBLE + f"\\title{{{tex_escape(row['title'])}}}\n\\author{{{tex_escape(row['authors'])}}}\n" \
            f"\\date{{{tex_escape(row['version'])}}}\n" '\\begin{document}\n\\maketitle\n\n'
        body = '\n\n'.join(part.read_text(encoding='utf-8').strip() for part in parts)
        target.write_text(head + body + '\n\n\\end{document}\n', encoding='utf-8', newline='\n')
    elif not target.exists():
        raise SystemExit(f'Нет ни частей в output/literature/parts/{stem}/, ни файла output/literature/{stem}.tex.')
    text = target.read_text(encoding='utf-8')
    notes = lint_tex(text, row.get('pages')) if origin == 'transcription' else []
    if build:
        notes += compile_tex(target)
    row.update(tex=target.name, tex_origin=origin, tex_date=f'{date.today():%Y-%m-%d}')
    save(rows)
    catalog()
    return ([f"{row['code']}: output/literature/{target.name}, частей: {len(parts)}"]
            + [f'ЗАМЕЧАНИЕ: {note}' for note in notes] + index([row['code']]))


# ---------- нарезка ----------

ENVIRONMENTS = {
    'abstract': 'Abstract', 'theorem': 'Theorem', 'thm': 'Theorem', 'lemma': 'Lemma', 'lem': 'Lemma',
    'proposition': 'Proposition', 'prop': 'Proposition', 'corollary': 'Corollary', 'cor': 'Corollary',
    'definition': 'Definition', 'defn': 'Definition', 'remark': 'Remark', 'rem': 'Remark',
    'example': 'Example', 'conjecture': 'Conjecture', 'claim': 'Claim', 'proof': 'Proof',
    'statement': 'Statement',
}
NEWTHEOREM = re.compile(r'\\newtheorem\*?\s*\{([^{}]+)\}\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}')
# Заголовок утверждения, набранный текстом: распознанный LaTeX и текст PDF
HEADING = re.compile(
    r'\s*(Теорема|Лемма|Предложение|Следствие|Определение|Замечание|'
    r'Theorem|Lemma|Proposition|Corollary|Definition|Remark)\s+(\d+(?:\.\d+)*)\s*[.:(]')
ENGLISH = {'Теорема': 'Theorem', 'Лемма': 'Lemma', 'Предложение': 'Proposition', 'Следствие': 'Corollary',
           'Определение': 'Definition', 'Замечание': 'Remark', 'Пример': 'Example', 'Утверждение': 'Proposition'}


def balanced(text: str, start: int) -> tuple[str, int]:
    """Содержимое группы {...}, открытой в позиции start, и позиция после неё."""
    depth = 0
    for position in range(start, min(len(text), start + 2000)):
        if text[position] == '{' and text[position - 1] != '\\':
            depth += 1
        elif text[position] == '}' and text[position - 1] != '\\':
            depth -= 1
            if depth == 0:
                return text[start + 1:position], position + 1
    return '', start + 1


def pack(text: str, offset: int) -> list[tuple[int, str]]:
    """Режет текст на куски до CHUNK знаков по границам абзацев, строк и предложений.

    Строка с заголовком утверждения («Теорема 6.6.», «Theorem 4.1.») начинает новый кусок.
    """
    units, position = [], offset
    for line in text.split('\n'):
        if len(line) > CHUNK:
            units += [(position, part) for part in re.split(r'(?<=[.;])\s+(?=[A-ZА-Я\\$])', line)]
        else:
            units.append((position, line))
        position += len(line) + 1
    chunks, current, start = [], [], offset
    for position, unit in units:
        size = sum(len(part) + 1 for part in current)
        if current and (size + len(unit) > CHUNK or (not unit.strip() and size > 0.6 * CHUNK)
                        or HEADING.match(unit)):
            chunks.append((start, '\n'.join(current).strip()))
            current = []
        if not current:
            start = position
        current.append(unit)
    chunks.append((start, '\n'.join(current).strip()))
    return [(start, chunk) for start, chunk in chunks if len(chunk) >= 40]


def headed(kind: str, label: str, body: str) -> tuple[str, str]:
    """Тип и метка куска; у утверждения, набранного текстом, метка — его печатный номер."""
    heading = HEADING.match(body)
    if heading:
        return ENGLISH.get(heading.group(1), heading.group(1)), f'{heading.group(1)} {heading.group(2)}'
    return kind, label


def tex_chunks(text: str) -> list[dict]:
    """Куски LaTeX: окружения теорем и доказательств отдельно, остальной текст по разделам.

    В транскрипции у куска есть печатная страница: её задаёт последняя метка \\pagemark.
    """
    envs = {**ENVIRONMENTS, **{name: squash(title) for name, title in NEWTHEOREM.findall(text)}}
    marker = re.compile(
        r'\\(section|subsection|subsubsection)\*?\s*(?:\[[^\]]*\])?\s*\{|\\(begin|end)\{(%s)\*?\}'
        % '|'.join(map(re.escape, sorted(envs, key=len, reverse=True))))
    begin = text.find('\\begin{document}')
    position = begin + len('\\begin{document}') if begin >= 0 else 0
    stops = [m.start() for m in re.finditer(r'\\begin\{thebibliography\}|\\end\{document\}', text)]
    stop = min((s for s in stops if s > position), default=len(text))
    newlines = [i for i, char in enumerate(text) if char == '\n']
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'\\pagemark\{([^{}#]*)\}', text)]
    mark_starts = [at for at, _ in marks]
    chunks, section, stack = [], '', []

    def emit(kind: str, label: str, start: int, end: int) -> None:
        piece = text[start:end]
        parts = [(start, piece.strip())] if kind != 'text' and len(piece) <= 2 * CHUNK else pack(piece, start)
        for offset, body in parts:
            if kind == 'text':
                item, name = headed(kind, '', body)
            else:
                found = re.search(r'\\label\{([^{}]*)\}', body)
                item, name = kind, label or (found.group(1) if found else '')
            mark = bisect.bisect_right(mark_starts, offset + 12) - 1
            chunks.append(dict(kind=item, label=name, section=section, text=body,
                               loc=bisect.bisect_left(newlines, offset) + 1,
                               page=marks[mark][1] if mark >= 0 else ''))

    for match in marker.finditer(text, position, stop):
        if match.group(1):
            if stack:
                continue
            emit('text', '', position, match.start())
            title, position = balanced(text, match.end() - 1)
            section = squash(re.sub(r'\\label\{[^{}]*\}', '', title))[:120]
        elif match.group(2) == 'begin':
            if not stack:
                emit('text', '', position, match.start())
                position = match.start()
            stack.append(match.group(3))
        elif stack and stack[-1] == match.group(3):
            stack.pop()
            if not stack:
                kind, label = envs[match.group(3)], ''
                printed = re.match(r'\\begin\{statement\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}', text[position:match.end()])
                if printed:
                    kind = ENGLISH.get(printed.group(1), printed.group(1))
                    label = f'{printed.group(1)} {printed.group(2)}'
                emit(kind, label, position, match.end())
                position = match.end()
    emit('text', '', position, stop)
    return [chunk for chunk in chunks if len(chunk['text']) >= 40]


def txt_chunks(text: str) -> list[dict]:
    """Куски текста, извлечённого из PDF; loc — номер страницы файла."""
    chunks = []
    for number, page in enumerate(text.split('\f'), 1):
        for _, body in pack(page, 0):
            kind, label = headed('page', '', body)
            chunks.append(dict(kind=kind, label=label, section='', loc=number, page='', text=body))
    return chunks


# ---------- индекс ----------

_model = None
_corpus = None


def embed(texts: list[str], prefix: str):
    """Нормированные векторы e5: ONNX Runtime на процессоре, усреднение по токенам."""
    global _model
    import numpy as np
    if _model is None:
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        def cached(name: str) -> str:
            try:
                return hf_hub_download(MODEL, name, local_files_only=True)
            except OSError:
                return hf_hub_download(MODEL, name)

        tokenizer = Tokenizer.from_file(cached('tokenizer.json'))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id('<pad>') or 0, pad_token='<pad>')
        _model = tokenizer, onnxruntime.InferenceSession(cached('onnx/model.onnx'),
                                                         providers=['CPUExecutionProvider'])
    tokenizer, session = _model
    inputs = {item.name for item in session.get_inputs()}
    vectors = np.zeros((len(texts), 1), dtype='float32')
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # близкие длины — меньше дополнения
    for start in range(0, len(order), 16):
        batch = order[start:start + 16]
        encoded = tokenizer.encode_batch([prefix + texts[i] for i in batch])
        mask = np.array([item.attention_mask for item in encoded], dtype='int64')
        feed = {'input_ids': np.array([item.ids for item in encoded], dtype='int64'), 'attention_mask': mask}
        if 'token_type_ids' in inputs:
            feed['token_type_ids'] = np.zeros_like(mask)
        hidden = session.run(None, feed)[0]
        pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
        if vectors.shape[1] != pooled.shape[1]:
            vectors = np.zeros((len(texts), pooled.shape[1]), dtype='float32')
        vectors[batch] = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
    return vectors.astype('float16')


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute('create table if not exists meta(key text primary key, value text)')
    version = f'{MODEL}:{CHUNKER}'
    if db.execute("select value from meta where key = 'version'").fetchone() != (version,):
        with db:  # другая модель или нарезка: старый индекс несовместим
            for table in ('chunks', 'fts', 'papers'):
                db.execute(f'drop table if exists {table}')
            db.execute("insert or replace into meta values ('version', ?)", (version,))
    db.executescript('''
        create table if not exists papers(code text primary key, stamp text);
        create table if not exists chunks(id integer primary key, code text, seq integer, kind text,
            label text, section text, file text, loc integer, page text, text text, vec blob);
        create index if not exists chunks_code on chunks(code, seq);
        create virtual table if not exists fts using fts5(text, section, tokenize='unicode61 remove_diacritics 2');
    ''')
    return db


def text_file(row: dict) -> Path | None:
    """Файл для индекса: LaTeX, а без него текстовый слой PDF."""
    if row.get('tex') and (LIT / row['tex']).exists():
        return LIT / row['tex']
    if row.get('filename') and (LIT / row['filename']).with_suffix('.txt').exists():
        return (LIT / row['filename']).with_suffix('.txt')
    return None


def index(codes: list[str] | None = None, log=None) -> list[str]:
    """Индексирует новые и изменившиеся тексты; остальные пропускает."""
    db, report = connect(), []
    stamps = dict(db.execute('select code, stamp from papers'))
    for row in load():
        code, path = row['code'], text_file(row)
        if codes and code not in codes:
            continue
        if path is None:
            if codes:
                report.append(f'{code}: текста для индекса нет')
            continue
        raw = path.read_bytes()
        stamp = sha256(raw)
        if stamps.get(code) == stamp:
            continue
        text = raw.decode('utf-8').replace('\r\n', '\n')
        chunks = tex_chunks(text) if path.suffix == '.tex' else txt_chunks(text)
        if log:
            log(f'{code}: {len(chunks)} кусков, считаю векторы')
        title = f"{row['title']}. {row.get('title_en', '')}"
        vectors = embed([f"{title}. {chunk['section']}. {chunk['text']}" for chunk in chunks], 'passage: ')
        with db:
            db.execute('delete from fts where rowid in (select id from chunks where code = ?)', (code,))
            db.execute('delete from chunks where code = ?', (code,))
            for seq, (chunk, vector) in enumerate(zip(chunks, vectors)):
                rowid = db.execute(
                    'insert into chunks(code, seq, kind, label, section, file, loc, page, text, vec) '
                    'values (?,?,?,?,?,?,?,?,?,?)',
                    (code, seq, chunk['kind'], chunk['label'], chunk['section'], path.name, chunk['loc'],
                     chunk['page'], chunk['text'], vector.tobytes())).lastrowid
                db.execute('insert into fts(rowid, text, section) values (?,?,?)',
                           (rowid, chunk['text'], chunk['section']))
            db.execute('insert or replace into papers values (?,?)', (code, stamp))
        report.append(f'{code}: {len(chunks)} кусков из {path.name}')
    db.close()
    return report


def corpus(db: sqlite3.Connection):
    """Матрица векторов индекса; перечитывается после изменения базы."""
    global _corpus
    import numpy as np
    stamp = DB.stat().st_mtime_ns
    if _corpus is None or _corpus[0] != stamp:
        rows = db.execute('select id, code, kind, vec from chunks order by id').fetchall()
        matrix = np.frombuffer(b''.join(row[3] for row in rows), dtype='float16').reshape(len(rows), -1)
        _corpus = (stamp, [row[0] for row in rows], [row[1] for row in rows], [row[2] for row in rows],
                   matrix.astype('float32'))
    return _corpus[1:]


def place(file: str, loc: int, page: str) -> str:
    if file.endswith('.tex'):
        return f'output/literature/{file}:{loc}' + (f', печатная с. {page}' if page else '')
    return f'{Path(file).stem}.pdf, стр. файла {loc}'


def search(query: str, k: int = 8, codes: list[str] | None = None, kind: str | None = None,
           log=None) -> str:
    """Гибридный поиск: BM25 по словам и близость векторов, объединённые по рангам."""
    import numpy as np
    index(log=log)
    db = connect()
    ids, paper_codes, kinds, matrix = corpus(db)
    if not ids:
        return 'Индекс пуст: в output/literature/ нет текстов.'
    allowed = np.array([(not codes or code in codes) and (not kind or kind.lower() in item.lower())
                        for code, item in zip(paper_codes, kinds)])
    scores: dict[int, float] = {}
    similarity = np.where(allowed, matrix @ embed([query], 'query: ')[0].astype('float32'), -1.0)
    for rank, position in enumerate(np.argsort(-similarity)[:100]):
        if allowed[position]:
            scores[ids[position]] = 1 / (60 + rank)
    words = re.findall(r'\w{2,}', query.lower())
    if words:
        permitted = {chunk for chunk, ok in zip(ids, allowed) if ok}
        lexical = [rowid for (rowid,) in db.execute(
            'select rowid from fts where fts match ? order by bm25(fts) limit 2000',
            (' OR '.join(f'"{word}"' for word in words),)) if rowid in permitted][:100]
        for rank, rowid in enumerate(lexical):
            scores[rowid] = scores.get(rowid, 0) + 1 / (60 + rank)
    papers = {row['code']: row for row in load()}
    out = []
    for rowid in sorted(scores, key=scores.get, reverse=True)[:k]:
        code, item, label, section, file, loc, page, text = db.execute(
            'select code, kind, label, section, file, loc, page, text from chunks where id = ?', (rowid,)).fetchone()
        paper = papers[code]
        head = [f"#{rowid} {code} {paper['authors'].split(';')[0].split()[-1]}, «{paper['title'][:70]}»",
                item + (f' {label}' if label else '')]
        if section:
            head.append('§ ' + section[:70])
        out.append(' · '.join(head + [place(file, loc, page)]) + '\n    ' + squash(text)[:340])
    db.close()
    return '\n'.join(out) or 'Ничего не найдено.'


def show(rowid: int, around: int = 0) -> str:
    """Полный текст куска и его соседей по статье."""
    db = connect()
    found = db.execute('select code, seq from chunks where id = ?', (rowid,)).fetchone()
    if not found:
        return f'Куска #{rowid} нет в индексе.'
    out = []
    for ident, item, label, section, file, loc, page, text in db.execute(
            'select id, kind, label, section, file, loc, page, text from chunks where code = ? and seq between ? '
            'and ? order by seq', (found[0], found[1] - around, found[1] + around)):
        out.append(f"#{ident} {found[0]} · {item}{' ' + label if label else ''} · § {section} · "
                   f"{place(file, loc, page)}\n{text}\n")
    db.close()
    return '\n'.join(out)


# ---------- поиск новых работ ----------

def describe(papers: list[dict]) -> str:
    seen, out = known(load()), []
    for paper in papers:
        keys = [('arxiv:' + bare(paper['arxiv']), 'arXiv:' + paper['arxiv']) if paper.get('arxiv') else None,
                ('mathnet:' + paper['mathnet'], 'mathnet:' + paper['mathnet']) if paper.get('mathnet') else None,
                ('doi:' + paper['doi'].lower(), 'DOI:' + paper['doi']) if paper.get('doi') else None]
        keys = [key for key in keys if key]
        idents = [shown for _, shown in keys] + ([f"zbMATH:{paper['zbmath']}"] if paper.get('zbmath') else [])
        code = next((seen[key] for key, _ in keys if key in seen), None)
        authors = paper['authors'][:3] + (['et al.'] if len(paper['authors']) > 3 else [])
        out.append(f"{' · '.join(idents) or '—'} · {paper.get('year') or '?'} · {', '.join(authors)} · {paper['title']}"
                   + (f' · В РЕЕСТРЕ {code}' if code else '')
                   + ('\n    ' + paper['abstract'][:420] if paper.get('abstract') else ''))
    return '\n'.join(out) or 'Ничего не найдено.'


def find(query: str, where: str | None = None, limit: int = 15) -> str:
    """Кандидаты из zbMATH, arXiv и журналов MathNet.

    Простой текст без where идёт в zbMATH и arXiv. Синтаксис полей у каждого свой: в arXiv —
    all:, ti:, abs:, au:, AND, OR; в zbMATH — ti:, au:, py:, &, |. С такими полями нужен where.
    """
    out = []
    for engine in ([where] if where else ['zbmath', 'arxiv']):
        if engine == 'zbmath':
            found = zbmath_search(query, limit)
        elif engine == 'arxiv':
            words = query if re.search(r'\b(all|ti|abs|au|cat):', query) else \
                ' AND '.join('all:' + word for word in re.findall(r'"[^"]+"|\S+', query))
            found = arxiv_query(search_query=words, max_results=limit, sortBy='relevance')
        elif engine == 'mathnet':
            found = crossref_search(query, limit, '10.4213')
        else:
            raise SystemExit(f'Неизвестная база «{engine}»: zbmath, arxiv или mathnet.')
        out.append(f'== {engine} ==\n{describe(found)}')
    return '\n'.join(out)


def cites(ref: str, references: bool = False, limit: int = 60) -> str:
    """Работы, цитирующие источник (references — цитируемые им): MathNet или Semantic Scholar."""
    row = by_code(load(), ref) if re.fullmatch(r'[Ss]\d+', ref) else None
    if row:
        if row.get('mathnet') and not references:
            return describe(mathnet_citing(row['mathnet'])[:limit])
        ident = 'arXiv:' + bare(arxiv_id(row)) if arxiv_id(row) else \
            'DOI:' + (row.get('doi_en') or (dois_of(row) or [''])[0])
    else:
        kind, value = classify(ref)
        if kind == 'mathnet' and not references:
            return describe(mathnet_citing(value)[:limit])
        ident = {'arxiv': 'arXiv:' + bare(value), 'mathnet': 'DOI:10.4213/' + value, 'doi': 'DOI:' + value}[kind]
    return describe(scholar(ident, references, limit))


def listing() -> str:
    db = connect()
    counts = dict(db.execute('select code, count(*) from chunks group by code'))
    db.close()
    return '\n'.join(
        f"{row['code']} · {row['version']} · {row['authors'].split(';')[0]} · {row['title'][:80]} · "
        f"{counts.get(row['code'], 0)} кусков" for row in load()) or 'Реестр пуст.'


# ---------- командная строка ----------

def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)

    p = commands.add_parser('add', help='добавить источники: arXiv, mathnet:rm9740, DOI')
    p.add_argument('ids', nargs='+')
    p.add_argument('--role', required=True, help='связь с проектом, одна-две фразы')

    p = commands.add_parser('add-file', help='добавить PDF или LaTeX без arXiv, MathNet и DOI')
    p.add_argument('source', help='ссылка или путь к файлу')
    for name in ('title', 'authors', 'version', 'url', 'name', 'role'):
        p.add_argument('--' + name, required=True)

    p = commands.add_parser('attach', help='прикрепить к записи PDF или LaTeX, полученный вручную')
    p.add_argument('code')
    p.add_argument('source', help='ссылка или путь к файлу')

    p = commands.add_parser('fetch', help='восстановить недостающие файлы реестра')
    p.add_argument('codes', nargs='*')
    p = commands.add_parser('pdf', help='скачать PDF источника для сверки номеров и страниц')
    p.add_argument('code')
    p = commands.add_parser('pages', help='страницы PDF в PNG и текстовый слой: для транскрипции и сверки')
    p.add_argument('code')
    p.add_argument('--range', default='', help='страницы файла, например 3-10; по умолчанию все')
    p.add_argument('--dpi', type=int, default=170)
    p = commands.add_parser('tex', help='собрать транскрипцию из частей и записать её как LaTeX источника')
    p.add_argument('code')
    p.add_argument('--build', action='store_true', help='проверить сборку pdflatex')
    commands.add_parser('catalog', help='пересобрать catalog.md и статусы в papers.json')
    p = commands.add_parser('index', help='проиндексировать новые и изменившиеся тексты')
    p.add_argument('codes', nargs='*')

    p = commands.add_parser('search', help='поиск по полным текстам')
    p.add_argument('query')
    p.add_argument('-k', type=int, default=8)
    p.add_argument('--code', action='append', help='ограничить источником; можно повторять')
    p.add_argument('--kind', help='тип куска: theorem, lemma, proposition, definition, proof, text, page')
    p = commands.add_parser('show', help='полный текст куска по номеру из поиска')
    p.add_argument('id', type=int)
    p.add_argument('-n', type=int, default=0, help='сколько соседних кусков показать с каждой стороны')

    p = commands.add_parser('find', help='искать кандидатов в zbMATH, arXiv, журналах MathNet')
    p.add_argument('query')
    p.add_argument('--in', dest='where', choices=['zbmath', 'arxiv', 'mathnet'])
    p.add_argument('-n', type=int, default=15)
    p = commands.add_parser('cites', help='кто цитирует источник (MathNet, Semantic Scholar)')
    p.add_argument('ref', help='код из реестра, идентификатор arXiv, mathnet:… или DOI')
    p.add_argument('--refs', action='store_true', help='наоборот: список литературы источника')
    p.add_argument('-n', type=int, default=60)
    commands.add_parser('list', help='источники реестра и число кусков в индексе')

    args = parser.parse_args()
    log = lambda line: print(line, file=sys.stderr, flush=True)
    codes = [code.upper() for code in getattr(args, 'codes', None) or []] or None
    if args.command == 'add':
        result = add(args.ids, args.role)
    elif args.command == 'add-file':
        result = add_file(args.source, args.title, args.authors, args.version, args.url, args.name, args.role)
    elif args.command == 'attach':
        result = attach(args.code, args.source)
    elif args.command == 'fetch':
        result = fetch(codes)
    elif args.command == 'pdf':
        result = pdf(args.code)
    elif args.command == 'pages':
        first, _, last = args.range.partition('-')
        result = pages(args.code, int(first or 1), int(last or first) if (last or first) else None, args.dpi)
    elif args.command == 'tex':
        result = tex(args.code, build=args.build)
    elif args.command == 'catalog':
        result = [catalog()]
    elif args.command == 'index':
        result = index(codes, log) or ['Индекс актуален.']
    elif args.command == 'search':
        result = [search(args.query, args.k, [c.upper() for c in args.code] if args.code else None, args.kind, log)]
    elif args.command == 'show':
        result = [show(args.id, args.n)]
    elif args.command == 'find':
        result = [find(args.query, args.where, args.n)]
    elif args.command == 'cites':
        result = [cites(args.ref, args.refs, args.n)]
    else:
        result = [listing()]
    print('\n'.join(result))
    if any('ОШИБКА' in line for line in result):
        sys.exit(1)


if __name__ == '__main__':
    main()
