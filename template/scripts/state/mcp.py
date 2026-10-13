# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2"]
# ///
"""MCP-сервер проекта: записи, идеи, сводки, проверки и формулировки Lean.

Запускается из корня проекта: `uv run --directory . --script scripts/state/mcp.py`.
Каталог скриптов попадает в sys.path при загрузке этого файла, корень проекта — из
`--directory`.
"""
import contextlib
import functools
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import proj  # noqa: E402

server = FastMCP('proj', instructions=(
    'Записи результатов (results/R*.md), идеи (ideas/I*.md), карточки источников и опыты проекта. '
    'Статус утверждения хранится в шапке его записи; blueprint.md и ideas/README.md собирает sync. '
    'Текст записи читается и правится обычными инструментами для файлов.'))


def tool(function):
    """Регистрирует инструмент; ошибку возвращает текстом, а не роняет сервер."""
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            # stdout занят протоколом MCP: случайная печать библиотеки уходит в stderr
            with contextlib.redirect_stdout(sys.stderr):
                return function(*args, **kwargs)
        except (SystemExit, ValueError, OSError, KeyError) as error:
            return f'ОШИБКА: {error}'
    return server.tool()(guarded)


@tool
def overview() -> str:
    """Все записи и идеи по одной строке: номер, статус, название, объявления Lean, зависимости."""
    return proj.overview()


@tool
def new(kind: str, title: str, depends: str = '', target: str = '', idea: str = '') -> str:
    """Создаёт запись со следующим свободным номером и возвращает путь к файлу-заготовке.

    kind: "result" (title — название утверждения; depends — записи через запятую),
    "idea" (target — запись или вопрос, к которому идея относится),
    "card" (title — код источника, например S4),
    "experiment" (idea — идея, которую проверяет опыт).
    """
    return proj.create(kind, title, depends, target, idea)


@tool
def set_field(id: str, key: str, value: str) -> str:
    """Меняет поле шапки записи или идеи: status, depends, sources, lean, review, fidelity, critic, result.

    Списки (depends, sources, lean) — через запятую. Статус записи: цель, набросок, доказано,
    опровергнуто. Статус идеи: новая, выдержала критику, в работе, отвергнута, перенесена.
    """
    return proj.set_field(id, key, value)


@tool
def sync() -> str:
    """Пересобирает blueprint.md, ideas/README.md и каталог источников из шапок записей."""
    return '\n'.join(proj.sync())


@tool
def check(lean: bool = False) -> str:
    """Проверки проекта: шапки записей, ссылки между ними, запрещённое в библиотеке, свежесть сводок.

    lean=True добавляет lake build и аудит аксиом; на большой библиотеке это минуты, тогда удобнее
    `python scripts/state/proj.py check` из командной строки.
    """
    return '\n'.join(proj.check(fast=not lean)[1])


@tool
def audit(names: list[str] | None = None) -> str:
    """Проверяет в Lean, что объявления существуют и зависят только от разрешённых аксиом.

    names — полные имена объявлений или номера записей (R05); без них — все записи.
    """
    return proj.audit_report(names or [])[1]


@tool
def statement(name: str) -> str:
    """Формулировка объявления Lean (или всех объявлений записи R05) без доказательства, с файлом и строкой."""
    return proj.statement_report(name)


@tool
def fingerprint(name: str) -> str:
    """Отпечаток формулировок записи (R05) или объявления: формулировка, действующие variable и
    определения проекта, от которых она зависит. Его последним словом записывают в поле fidelity."""
    return proj.fingerprint_report(name)


if __name__ == '__main__':
    proj.configure(proj.ROOT)
    server.run()