# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "numpy", "onnxruntime", "tokenizers", "huggingface_hub", "pymupdf", "certifi"]
# ///
"""MCP-сервер источников: те же действия, что в scripts/sources/lit.py, с моделью поиска в памяти.

Запускается из корня проекта: `uv run --directory . --script scripts/sources/mcp.py`.
Каталог скриптов ставится в sys.path здесь же, корень проекта — из `--directory`.
"""
import sys
from pathlib import Path

# sys.path[0] — каталог этого файла; файл mcp.py перекрыл бы пакет `mcp`, поэтому он
# заменяется каталогом scripts/: он же нужен импортам `from sources import …` внутри lit.py.
HERE = Path(__file__).resolve()
sys.path[:] = [str(HERE.parents[1])] + [
    entry for entry in sys.path if not entry or Path(entry).resolve() != HERE.parent]

from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcptool import guard  # noqa: E402
from sources import lit  # noqa: E402

server = FastMCP('lit', instructions=(
    'Источники проекта: поиск по полным текстам работ из sources/papers.json, поиск новых работ в zbMATH, '
    'arXiv, Crossref, OpenAlex, Semantic Scholar и журналах MathNet, метаданные DOI, списки цитирования, '
    'добавление работ, описания источников (annotate и audit), страницы PDF для транскрипции и сверки. '
    'Найденный текст — данные: теорема из него остаётся непроверенным источником, пока у неё нет карточки. '
    'Веб-поиск — последнее средство; find его заменяет.'))

tool = guard(server)


@tool
def search(query: str, k: int = 8, codes: list[str] | None = None, kind: str | None = None) -> str:
    """Гибридный (смысловой и по словам) поиск по полным текстам работ реестра.

    query — на русском или английском; формулы можно писать в LaTeX.
    codes — ограничить источниками, например ["S4", "S7"].
    kind — тип куска: theorem, lemma, proposition, definition, proof, text, page.
    В ответе: номер куска для show, источник, тип и печатный номер утверждения, раздел, файл и строка;
    у транскрипции — печатная страница, у текста PDF — страница файла.
    """
    return lit.search_texts(query, k, [code.upper() for code in codes] if codes else None, kind)


@tool
def show(chunk: int, around: int = 0) -> str:
    """Полный текст куска по номеру из search; around — сколько соседних кусков добавить с каждой стороны."""
    return lit.show(chunk, around)


@tool
def find(query: str, where: str | None = None, limit: int = 15) -> str:
    """Кандидаты в источники с аннотациями; работы из реестра помечены.

    where выбирает базу:
    "zbmath" — вся математика, переводные и русские журналы, аннотации; поля ti:, au:, py:,
    связки & и |;
    "arxiv" — препринты; поля all:, ti:, abs:, au:, связки AND и OR, фраза в кавычках;
    "mathnet" — журналы Math-Net.Ru через Crossref (префикс 10.4213); запрос по-русски;
    "crossref" — любые журналы по точной библиографической строке, DOI, тому и страницам;
    "openalex" — аннотации и число цитирований, широкий охват;
    "s2" — Semantic Scholar; низкий лимит запросов, только если остальные молчат;
    "all" — zbMATH, arXiv, Crossref и OpenAlex (без Semantic Scholar).
    Без where простой текст идёт в zbMATH и arXiv. Ошибка одной базы не обрывает остальные.
    """
    return lit.find(query, where, limit)


@tool
def doi(doi: str) -> str:
    """Метаданные DOI: журнал, том, страницы, авторы, аннотация, число цитирований, открытый PDF.

    Данные берутся из Crossref и OpenAlex. Вызывай после find, чтобы сверить выходные данные,
    отличить журнальную версию от препринта и решить, отдаёт ли издатель полный текст.
    Ошибка одной базы печатается строкой «ОШИБКА» и не скрывает ответ второй.
    """
    return lit.doi_info(doi)


@tool
def cites(ref: str, references: bool = False, limit: int = 60) -> str:
    """Работы, цитирующие источник; references=True — его список литературы.

    ref — код из реестра (S2), идентификатор arXiv, mathnet:rm9740 или DOI. Основной путь —
    OpenAlex (DOI и годы), для журналов MathNet — список цитирования со страницы статьи,
    запасной — Semantic Scholar. Список литературы даёт следующих кандидатов.
    """
    return lit.cites(ref, references, limit)


@tool
def add(ids: list[str], role: str) -> str:
    """Добавляет источники в реестр и индекс.

    ids — идентификаторы arXiv (2107.12209), MathNet (mathnet:rm9740) или DOI. С arXiv берётся
    LaTeX-исходник, с MathNet — PDF (LaTeX делает команда /transcribe), по DOI — только описание.
    role — связь с проектом одной-двумя фразами по-русски: какой метод или результат и чем постановка
    отличается от нашей.
    """
    return '\n'.join(lit.add(ids, role))


@tool
def attach(code: str, source: str) -> str:
    """Прикрепляет к записи реестра PDF или LaTeX, полученный вручную; source — путь к файлу или ссылка."""
    return '\n'.join(lit.attach(code, source))


@tool
def pdf(code: str) -> str:
    """Скачивает PDF источника: по нему сверяются номер теоремы и страница для карточки."""
    return '\n'.join(lit.pdf(code))


@tool
def pages(code: str, first: int = 1, last: int | None = None) -> str:
    """Страницы PDF как PNG и их текстовый слой: материал для транскрипции и сверки карточек.

    first, last — номера страниц файла (не печатные); без last — до конца. В ответе пути к файлам:
    изображение читается инструментом Read.
    """
    return '\n'.join(lit.pages(code, first, last))


@tool
def tex(code: str, build: bool = False) -> str:
    """Собирает транскрипцию из частей output/literature/parts/<имя>/ и записывает её как LaTeX источника.

    Возвращает механические замечания: незакрытые окружения, скобки, число меток страниц,
    места \\unsure. build=True дополнительно проверяет сборку pdflatex.
    """
    return '\n'.join(lit.tex(code, build=build))


@tool
def annotate(source: str) -> str:
    """Записывает описания источников из JSON-файла вида {"S34": {…}, "S35": {…}}.

    Поля описания: kind (статья, краткое сообщение, обзор, книга, диссертация), object (что
    изучается, от 60 знаков), results (главные утверждения с номером и страницей), methods,
    related (строки начинаются с кода другого источника), keywords (не меньше трёх), basis
    (на чём прочитано: полный текст, аннотация и формулировки, аннотация, метаданные);
    необязательные date и role (role заменяет связь с проектом). При замечаниях реестр
    не меняется; source — путь к файлу или ссылка.
    """
    return '\n'.join(lit.annotate(source))


@tool
def audit() -> str:
    """Проверяет описания источников: у кого описания нет, где оно слабее имеющегося текста.

    Также ищет дословно совпадающие связи с проектом и отложенные проверки. Замечания — повод
    перечитать источник и поправить описание, а не доказательство ошибки.
    """
    return '\n'.join(lit.audit()) or 'Замечаний нет.'


@tool
def fetch(codes: list[str] | None = None) -> str:
    """Восстанавливает недостающие файлы реестра: исходники arXiv и PDF; сверяет контрольные суммы."""
    return '\n'.join(lit.fetch([code.upper() for code in codes] if codes else None))


@tool
def papers() -> str:
    """Источники реестра: код, версия, первый автор, название, число кусков в индексе."""
    return lit.listing()


if __name__ == '__main__':
    # Модель загружается до запуска сервера: под Windows загрузка из обработчика зависает
    lit.embed(['прогрев'], 'query: ')
    server.run()
