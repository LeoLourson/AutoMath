# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "onnxruntime", "tokenizers", "huggingface_hub", "pymupdf", "certifi"]
# ///
"""Источники проекта: реестр, загрузка полных текстов, транскрипции, индекс и поиск.

Модуль — единственный вход в работу с источниками: остальные модули папки `sources/` заняты
каждый своим делом (`http`, `papers`, `registry`, `store`, `tex`, `search`, `catalog`) и
команд не разбирают. Здесь настройка путей и командная строка; тот же набор действий есть у
MCP-сервера `sources/mcp.py`.

Реестр — `sources/papers.json`; каталог `sources/catalog.md` строится из него. Тексты и
индекс лежат в `output/literature/`, вне Git. Команды: `python scripts/sources/lit.py -h`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import catalog, papers, paths, registry, search, store, web  # noqa: E402
from sources import tex as tex_source  # noqa: E402

ROOT = paths.ROOT
REGISTRY, CATALOG, CARDS, RESULTS, LIT, DB = (paths.REGISTRY, paths.CATALOG, paths.CARDS,
                                              paths.RESULTS, paths.LIT, paths.DB)
DIRECT_HOSTS = web.DIRECT_HOSTS

# Настройка и по одной функции каждого рода работы — то, чем пользуются снаружи.
classify, amsbib, flatten = registry.classify, papers.amsbib, papers.flatten
find, cites = papers.find, papers.cites
listing = search.listing
load, save, known, next_code = registry.load, registry.save, registry.known, registry.next_code
stem_of, sha256 = registry.stem_of, registry.sha256
cards, add, add_file, attach = catalog.cards, registry.add, registry.add_file, registry.attach
fetch = store.fetch
pdf, pages = store.pdf, store.pages
status_of, catalog_page = catalog.status_of, catalog.catalog
index_texts, search_texts, show = search.index, search.search, search.show
embed, corpus, text_file = search.embed, search.corpus, search.text_file
PREAMBLE, tex_escape, lint_tex, compile_tex = (tex_source.PREAMBLE, tex_source.tex_escape,
                                               tex_source.lint_tex, tex_source.compile_tex)
tex_chunks, txt_chunks = tex_source.tex_chunks, tex_source.txt_chunks


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
    return tex_source.tex(ROOT, code, origin, build)


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
    elif args.command == 'cites':
        result = [cites(args.ref, args.refs, args.n)]
    else:
        result = [listing()]
    print('\n'.join(result))
    if any('ОШИБКА' in line for line in result):
        sys.exit(1)


if __name__ == '__main__':
    main()
