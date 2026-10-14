"""Опознание источника и его описание словами сервисов.

Идентификатор приводится к виду (arxiv | mathnet | doi, нормальная форма) — по нему
`registry.py` решает, добавлять ли работу. Здесь же запросы к arXiv, MathNet, Crossref,
zbMATH и Semantic Scholar и разбор их ответов: ни один из них не источник истины, а запись
в реестре считается принятой только после карточки и её сверки с PDF.
"""
from __future__ import annotations

import gzip
import html
import io
import json
import re
import tarfile
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

from sources import registry, web

# Тег arXiv поверх Atom; нужен запросам списка работ.
ATOM = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}


def arxiv_query(**params) -> list[dict]:
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params)
    papers = []
    for entry in ET.fromstring(web.http_get(url)).findall('a:entry', ATOM):
        ident = entry.findtext('a:id', '', ATOM)
        if '/abs/' not in ident:
            continue
        papers.append(dict(
            arxiv=ident.rsplit('/abs/', 1)[1],
            title=web.squash(entry.findtext('a:title', '', ATOM)),
            authors=[web.squash(a.findtext('a:name', '', ATOM)) for a in entry.findall('a:author', ATOM)],
            year=entry.findtext('a:published', '', ATOM)[:4],
            abstract=web.squash(entry.findtext('a:summary', '', ATOM)),
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
def amsbib(page: str) -> dict:
    """Поля блока AMSBIB со страницы статьи; перевод (после \\transl) — с суффиксом _en."""
    block = re.search(r'<div class=showamsbib>(.*?)</div>', page, re.S)
    if not block:
        return {}
    fields, suffix = {}, ''
    for line in re.split(r'<br\s*/?>', block.group(1)):
        line = web.html_text(line).replace('~', ' ').replace('--', '–')
        if line == '\\transl':
            suffix = '_en'
        match = re.match(r'\\(\w+)\s*\{?(.*?)\}?$', line)
        if match and match.group(2):
            fields.setdefault(match.group(1) + suffix, match.group(2).strip())
    return fields


def mathnet_meta(pid: str) -> dict:
    journal, number = re.fullmatch(r'([a-z]+)(\d+)', pid).groups()
    page = web.http_get(f'https://www.mathnet.ru/rus/{pid}').decode('cp1251', 'replace')
    fields = amsbib(page)
    if not fields.get('paper'):
        raise ValueError(f'mathnet:{pid}: статья не найдена')
    english = amsbib(web.http_get(f'https://www.mathnet.ru/eng/{pid}').decode('cp1251', 'replace'))
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
        abstract=web.html_text(abstract.group(1)).replace('\\lt', '<').replace('\\gt', '>') if abstract else '',
        full_text=f'getFT.phtml?jrnid={journal}&paperid={number}&what=fullt&' in page.replace('&amp;', '&'),
        pdf_url=f'https://www.mathnet.ru/php/getFT.phtml?jrnid={journal}&paperid={number}&what=fullt&option_lang=rus',
    )


def mathnet_citing(pid: str) -> list[dict]:
    """Работы из списка цитирования на странице статьи."""
    page = web.http_get(f'https://www.mathnet.ru/paperfwl/rus/{pid}').decode('cp1251', 'replace')
    papers = []
    for item in re.split(r'<li\b', page)[1:]:
        text = web.html_text(item.split('>', 1)[1])
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
def crossref_meta(doi: str) -> dict:
    item = json.loads(web.http_get('https://api.crossref.org/works/' + urllib.parse.quote(doi)))['message']
    year = ((item.get('issued') or {}).get('date-parts') or [[None]])[0][0]
    place = ', '.join(part for part in (
        (item.get('container-title') or [''])[0],
        ' '.join(filter(None, [item.get('volume'), f"({item['issue']})" if item.get('issue') else ''])),
        item.get('page')) if part)
    return dict(
        doi=doi,
        title=web.squash((item.get('title') or ['?'])[0]),
        authors=[web.squash(f"{a.get('given', '')} {a.get('family', '')}") for a in item.get('author', [])],
        year=str(year or ''),
        version=f'{place} ({year})' if place else f'DOI:{doi}',
    )


def crossref_search(query: str, limit: int, prefix: str) -> list[dict]:
    params = urllib.parse.urlencode({'query.bibliographic': query, 'filter': 'prefix:' + prefix, 'rows': limit,
                                     'select': 'DOI,title,author,issued,container-title'})
    papers = []
    for item in json.loads(web.http_get('https://api.crossref.org/works?' + params))['message']['items']:
        doi = item['DOI']
        papers.append(dict(
            mathnet=doi.split('/', 1)[1].lower() if doi.startswith('10.4213/') else None,
            doi=doi,
            title=web.squash((item.get('title') or ['?'])[0]),
            authors=[web.squash(f"{a.get('given', '')} {a.get('family', '')}") for a in item.get('author', [])],
            year=((item.get('issued') or {}).get('date-parts') or [['']])[0][0],
            abstract=(item.get('container-title') or [''])[0],
        ))
    return papers


def zbmath_search(query: str, limit: int) -> list[dict]:
    """Поиск в zbMATH Open; запрос — в его синтаксисе (au:, ti:, py:, &, |)."""
    params = urllib.parse.urlencode({'search_string': query, 'results_per_page': limit})
    papers = []
    for item in json.loads(web.http_get('https://api.zbmath.org/v1/document/_search?' + params)).get('result') or []:
        links = {link.get('type'): link.get('identifier') for link in item.get('links') or []}
        notes = item.get('editorial_contributions') or [{}]
        papers.append(dict(
            zbmath=item.get('id'),
            arxiv=links.get('arxiv'),
            doi=links.get('doi'),
            title=web.squash((item.get('title') or {}).get('title')),
            authors=[a.get('name', '') for a in (item.get('contributors') or {}).get('authors', [])],
            year=item.get('year') or '',
            abstract=web.squash(f"{(item.get('source') or {}).get('source', '')} {notes[0].get('text') or ''}"),
        ))
    return papers


def scholar(ref: str, references: bool, limit: int) -> list[dict]:
    url = (f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(ref, safe=':/')}/"
           f"{'references' if references else 'citations'}?fields=title,year,authors,externalIds,abstract&limit={limit}")
    papers = []
    for item in json.loads(web.http_get(url)).get('data') or []:
        paper = item['citedPaper' if references else 'citingPaper']
        if paper.get('title'):
            external = paper.get('externalIds') or {}
            papers.append(dict(arxiv=external.get('ArXiv'), doi=external.get('DOI'), title=paper['title'],
                               year=paper.get('year'), authors=[a['name'] for a in paper.get('authors') or []],
                               abstract=web.squash(paper.get('abstract'))))
    return papers
def describe(papers: list[dict]) -> str:
    seen, out = registry.known(registry.load()), []
    for paper in papers:
        keys = [('arxiv:' + registry.bare(paper['arxiv']), 'arXiv:' + paper['arxiv']) if paper.get('arxiv') else None,
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
    row = registry.by_code(registry.load(), ref) if re.fullmatch(r'[Ss]\d+', ref) else None
    if row:
        if row.get('mathnet') and not references:
            return describe(mathnet_citing(row['mathnet'])[:limit])
        ident = 'arXiv:' + registry.bare(registry.arxiv_id(row)) if registry.arxiv_id(row) else \
            'DOI:' + (row.get('doi_en') or (registry.dois_of(row) or [''])[0])
    else:
        kind, value = registry.classify(ref)
        if kind == 'mathnet' and not references:
            return describe(mathnet_citing(value)[:limit])
        ident = {'arxiv': 'arXiv:' + registry.bare(value), 'mathnet': 'DOI:10.4213/' + value, 'doi': 'DOI:' + value}[kind]
    return describe(scholar(ident, references, limit))
