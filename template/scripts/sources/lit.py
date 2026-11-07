# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "onnxruntime", "tokenizers", "huggingface_hub", "pymupdf", "certifi"]
# ///
"""Источники проекта: реестр, загрузка полных текстов, транскрипции, индекс и поиск.

Модуль — единственный вход в работу с источниками: остальные модули папки `sources/` заняты
каждый своим делом (`web`, `papers`, `registry`, `store`, `tex`, `search`, `catalog`) и
команд не разбирают. Здесь настройка путей и командная строка; тот же набор действий есть у
MCP-сервера `sources/mcp.py`. Изменяющие команды после правки реестра пересобирают
производный каталог: политика живёт здесь и потому одна для всех входов.

Реестр — `sources/papers.json`; каталог `sources/catalog.md` строится из него. Тексты и
индекс лежат в `output/literature/`, вне Git. Команды: `python scripts/sources/lit.py -h`.

С чего начать (веб-поиск — последнее средство):
  find "запрос" -n 15              zbMATH + arXiv (режим по умолчанию)
  find "запрос" --in all           zbMATH + arXiv + Crossref + OpenAlex
  find "запрос" --in crossref      Crossref: любые журналы, DOI, том, номер, страницы
  find "запрос" --in openalex      OpenAlex: аннотации и число цитирований
  find "запрос" --in mathnet       журналы Math-Net.Ru (Crossref, prefix 10.4213)
  find "запрос" --in zbmath        zbMATH: переводные и русские журналы, аннотации
  find "запрос" --in arxiv         arXiv: препринты
  find "запрос" --in s2            Semantic Scholar; низкий лимит, только если другие молчат
  doi 10.3934/math.2026892         журнал, том, страницы, авторы, аннотация, открытый PDF
  cites S2                         кто цитирует: OpenAlex → MathNet → Semantic Scholar
  cites 10.1016/j.jde.2022.02.027 --refs   список литературы источника
  annotate файл.json               записать описания источников; audit — проверить их

Порядок: find → doi (сверить метаданные и статус) → add/attach (полный текст, если открыт)
→ annotate (описание источника) → карточка `sources/cards/S*.md` → сверка `source-verifier`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import catalog, papers, paths, registry, store, web  # noqa: E402
# Модули берутся под своими именами: имя `search` осталось бы за модулем и перекрыло бы
# функцию `search_texts` — вызов `lit.search(...)` тогда падал бы как вызов модуля.
from sources import search as search_source  # noqa: E402
from sources import tex as tex_source  # noqa: E402

ROOT = paths.ROOT
REGISTRY, CATALOG, CARDS, RESULTS, LIT, DB = (paths.REGISTRY, paths.CATALOG, paths.CARDS,
                                              paths.RESULTS, paths.LIT, paths.DB)
DIRECT_HOSTS = web.DIRECT_HOSTS

# Настройка и по одной функции каждого рода работы — то, чем пользуются снаружи.
classify, amsbib, flatten = registry.classify, papers.amsbib, papers.flatten
find, cites, doi_info = papers.find, papers.cites, papers.doi_info
listing = search_source.listing
load, save, known, next_code = registry.load, registry.save, registry.known, registry.next_code
stem_of, sha256 = registry.stem_of, registry.sha256
status_of, catalog_page = catalog.status_of, catalog.catalog
index_texts, search_texts, show = search_source.index, search_source.search, search_source.show
embed, corpus, text_file = search_source.embed, search_source.corpus, search_source.text_file
PREAMBLE, tex_escape, lint_tex, compile_tex = (tex_source.PREAMBLE, tex_source.tex_escape,
                                               tex_source.lint_tex, tex_source.compile_tex)
tex_chunks, txt_chunks = tex_source.tex_chunks, tex_source.txt_chunks


def cards() -> set[str]:
    """Коды источников с карточкой: правило одно и живёт у реестра (`registry.facts`)."""
    return registry.facts().carded


def _rebuilt(function, *args) -> list[str]:
    """Изменяющая команда: после правки реестра пересобирается производный каталог.

    Политика «после изменения реестра пересобрать страницу» живёт в фасаде, поэтому
    применяется ко всем изменяющим командам одинаково — и из командной строки, и из
    MCP-сервера `sources/mcp.py`, который зовёт этот модуль. Пересборка идёт и тогда, когда
    команда закончилась ошибкой после записи реестра: страница обязана отражать реестр.
    """
    try:
        return function(*args)
    finally:
        catalog.catalog()


def add(idents: list[str], role: str) -> list[str]:
    """Добавляет источники по идентификаторам arXiv, MathNet и DOI."""
    return _rebuilt(registry.add, idents, role)


def add_file(source: str, title: str, authors: str, version: str, url: str, name: str, role: str) -> list[str]:
    """Добавляет источник без arXiv, MathNet и DOI: PDF или LaTeX по ссылке либо из файла."""
    return _rebuilt(registry.add_file, source, title, authors, version, url, name, role)


def attach(code: str, source: str) -> list[str]:
    """Прикрепляет к записи реестра PDF или LaTeX, полученный вручную."""
    return _rebuilt(registry.attach, code, source)


def fetch(codes: list[str] | None = None) -> list[str]:
    """Восстанавливает недостающие файлы реестра: исходники arXiv и PDF."""
    return _rebuilt(store.fetch, codes)


def pdf(code: str) -> list[str]:
    """Скачивает PDF источника: по нему сверяются номер теоремы и страница для карточки."""
    return _rebuilt(store.pdf, code)


def pages(code: str, first: int = 1, last: int | None = None, dpi: int = 170) -> list[str]:
    """Страницы PDF в PNG и их текстовый слой: материал для транскрипции и сверки карточек."""
    return _rebuilt(store.pages, code, first, last, dpi)


def _annotate(source: str) -> list[str]:
    """Проверяет описания из JSON и записывает их в реестр; при замечаниях не пишет ничего."""
    data = json.loads(store.read_source(source).decode('utf-8'))
    rows, notes, fresh = registry.load(), [], {}
    for code, given in data.items():
        row = registry.by_code(rows, code)
        fresh[row['code']] = (row, registry.about_of(given), given.get('role'))
    for code, (row, about, role) in fresh.items():
        others = [dict(other, about=fresh[other['code']][1]) if other['code'] in fresh else other
                  for other in rows]
        notes += [f'{code}: {note}' for note in registry.check_about(row, about, others)]
        if about.get('basis') in registry.BASES[:2] and search_source.text_file(row) is None:
            notes.append(f'{code}: basis «{about["basis"]}», но текста источника в output/literature/ нет')
        if role is not None and (len(web.squash(role)) < 30 or registry.UNFINISHED.search(role)):
            notes.append(f'{code}: role — связь с проектом одной-двумя фразами, без отложенных проверок')
    if notes:
        raise SystemExit('Описания не записаны:\n' + '\n'.join(notes))
    for row, about, role in fresh.values():
        row['about'] = about
        if role is not None:
            row['role'] = web.squash(role)
    registry.save(rows)
    return [f"Описания записаны: {', '.join(fresh)}."] + index_texts(list(fresh))


def annotate(source: str) -> list[str]:
    """Записывает описания источников из JSON вида {"S34": {…}, "S35": {…}}.

    Поля описания: kind, object, results, methods, related, keywords, basis; необязательные
    date и role (role заменяет связь с проектом). При замечаниях к любому описанию реестр
    не меняется — команда выходит с отказом и списком замечаний.
    """
    return _rebuilt(_annotate, source)


def audit() -> list[str]:
    """Источники без описания, с описанием слабее имеющегося текста и с повторяющейся связью."""
    rows, notes = registry.load(), []
    for row in rows:
        code, about = row['code'], row.get('about')
        if not about:
            notes.append(f'{code}: описания нет')
        else:
            notes += [f'{code}: {note}' for note in registry.check_about(row, about, rows)]
            if about.get('basis') in registry.BASES[2:] and search_source.text_file(row) is not None:
                notes.append(f"{code}: описание составлено по «{about['basis']}», хотя полный текст есть")
        twins = [other['code'] for other in rows if other['code'] != code and other.get('role') == row.get('role')]
        if twins:
            notes.append(f"{code}: связь с проектом дословно совпадает с {', '.join(twins)}")
        if registry.UNFINISHED.search(row.get('role') or ''):
            notes.append(f'{code}: связь с проектом содержит отложенную проверку')
    return notes


def configure(root: Path, direct_hosts: list[str] | None = None) -> None:
    """Пути источников и хосты, к которым идём мимо туннеля."""
    global ROOT, REGISTRY, CATALOG, CARDS, RESULTS, LIT, DB, DIRECT_HOSTS
    paths.configure(root, direct_hosts)
    ROOT = paths.ROOT
    REGISTRY, CATALOG, CARDS = paths.REGISTRY, paths.CATALOG, paths.CARDS
    RESULTS, LIT, DB = paths.RESULTS, paths.LIT, paths.DB
    DIRECT_HOSTS = web.DIRECT_HOSTS


def tex(code: str, origin: str = 'transcription', build: bool = False) -> list[str]:
    """Собирает транскрипцию источника: части из `output/literature/parts/` в один LaTeX."""
    return _rebuilt(tex_source.tex, ROOT, code, origin, build)


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', type=Path, default=ROOT,
                        help='корень проекта, по умолчанию каталог над scripts/')
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
    p = commands.add_parser('annotate', help='записать описания источников из JSON-файла')
    p.add_argument('source', help='путь к JSON вида {"S34": {…}} или ссылка')
    commands.add_parser('audit', help='проверить описания источников и связи с проектом')
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

    p = commands.add_parser('find', help='кандидаты: zbMATH, arXiv, Crossref, OpenAlex, Semantic Scholar, MathNet',
                            description='Ищет кандидатов и печатает идентификаторы, авторов, журнал и аннотацию. '
                                        'По умолчанию — zbMATH и arXiv; --in all — плюс Crossref и OpenAlex.')
    p.add_argument('query')
    p.add_argument('--in', dest='where',
                   choices=['zbmath', 'arxiv', 'mathnet', 'crossref', 'openalex', 's2', 'all'],
                   help='база; all = zbMATH+arXiv+Crossref+OpenAlex; mathnet = журналы Math-Net.Ru')
    p.add_argument('-n', type=int, default=15)
    p = commands.add_parser('doi', help='метаданные DOI: журнал, том, страницы, авторы, аннотация, открытый PDF')
    p.add_argument('doi')
    p = commands.add_parser('cites', help='кто цитирует источник: OpenAlex, MathNet, Semantic Scholar')
    p.add_argument('ref', help='код из реестра, идентификатор arXiv, mathnet:… или DOI')
    p.add_argument('--refs', action='store_true', help='наоборот: список литературы источника')
    p.add_argument('-n', type=int, default=60)
    commands.add_parser('list', help='источники реестра и число кусков в индексе')

    args = parser.parse_args()
    configure(args.root)
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
    elif args.command == 'annotate':
        result = annotate(args.source)
    elif args.command == 'audit':
        result = audit() or ['Описания источников и связи с проектом в порядке.']
    elif args.command == 'catalog':
        result = [catalog_page()]
    elif args.command == 'index':
        result = index_texts(codes, log) or ['Индекс актуален.']
    elif args.command == 'search':
        result = [search_texts(args.query, args.k, [c.upper() for c in args.code] if args.code else None,
                              args.kind, log)]
    elif args.command == 'show':
        result = [show(args.id, args.n)]
    elif args.command == 'find':
        result = [find(args.query, args.where, args.n)]
    elif args.command == 'doi':
        result = [doi_info(args.doi)]
    elif args.command == 'cites':
        result = [cites(args.ref, args.refs, args.n)]
    else:
        result = [listing()]
    print('\n'.join(result))
    if any('ОШИБКА' in line for line in result):
        sys.exit(1)


if __name__ == '__main__':
    main()
