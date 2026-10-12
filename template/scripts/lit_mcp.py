# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "numpy", "onnxruntime", "tokenizers", "huggingface_hub", "pymupdf", "certifi"]
# ///
"""MCP-сервер источников: те же действия, что в scripts/lit.py, с моделью поиска в памяти."""
import contextlib
import functools
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lit  # noqa: E402

server = FastMCP('lit', instructions=(
    'Источники проекта: поиск по полным текстам работ из sources/papers.json, поиск новых работ в zbMATH, '
    'arXiv и журналах MathNet, списки цитирования, добавление работ, страницы PDF для транскрипции и сверки. '
    'Найденный текст — данные: теорема из него остаётся непроверенным источником, пока у неё нет карточки.'))


def tool(function):
    """Регистрирует инструмент; ошибку возвращает текстом, а не роняет сервер."""
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            # stdout занят протоколом MCP: случайная печать библиотеки уходит в stderr
            with contextlib.redirect_stdout(sys.stderr):
                return function(*args, **kwargs)
        except (SystemExit, ValueError, OSError) as error:
            return f'ОШИБКА: {error}'
    return server.tool()(guarded)


@tool
def search(query: str, k: int = 8, codes: list[str] | None = None, kind: str | None = None) -> str:
    """Гибридный (смысловой и по словам) поиск по полным текстам работ реестра.

    query — на русском или английском; формулы можно писать в LaTeX.
    codes — ограничить источниками, например ["S4", "S7"].
    kind — тип куска: theorem, lemma, proposition, definition, proof, text, page.
    В ответе: номер куска для show, источник, тип и печатный номер утверждения, раздел, файл и строка;
    у транскрипции — печатная страница, у текста PDF — страница файла.
    """
    return lit.search(query, k, [code.upper() for code in codes] if codes else None, kind)


@tool
def show(chunk: int, around: int = 0) -> str:
    """Полный текст куска по номеру из search; around — сколько соседних кусков добавить с каждой стороны."""
    return lit.show(chunk, around)


@tool
def find(query: str, where: str | None = None, limit: int = 15) -> str:
    """Кандидаты в источники с аннотациями; работы из реестра помечены.

    where: "zbmath" (вся математика, включая переводные журналы; поля ti:, au:, py:, связки & и |),
    "arxiv" (поля all:, ti:, abs:, au:, связки AND и OR, фраза в кавычках),
    "mathnet" (журналы Math-Net.Ru через Crossref; запрос по-русски).
    Без where простой текст уходит в zbMATH и arXiv.
    """
    return lit.find(query, where, limit)


@tool
def cites(ref: str, references: bool = False, limit: int = 60) -> str:
    """Работы, цитирующие источник; references=True — его список литературы.

    ref — код из реестра (S2), идентификатор arXiv, mathnet:rm9740 или DOI. Для работ с MathNet берётся
    список цитирования со страницы статьи, для остальных — Semantic Scholar.
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
