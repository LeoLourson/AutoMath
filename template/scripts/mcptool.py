"""Регистрация инструментов MCP: одна защита на оба сервера.

`state/mcp.py` и `sources/mcp.py` регистрируют инструменты одинаково: результат отдаётся
текстом, а ошибка не роняет сервер. Правило было записано в обоих файлах копией, и копии
разошлись — один сервер ловил `KeyError`, другой нет. Поэтому правило живёт здесь одно.

Набор исключений выбран по назначению: ошибка ввода и состояния (неверный аргумент,
отсутствующий ключ, недоступный файл) возвращается текстом, чтобы одна неудачная команда
не убивала сервер целиком. Прочие отказы в этот список не входят и видны как есть.
"""
from __future__ import annotations

import contextlib
import functools
import sys


def guard(server):
    """Декоратор инструмента для `FastMCP`: печать уходит в stderr, ошибка — текстом."""
    def tool(function):
        @functools.wraps(function)
        def guarded(*args, **kwargs):
            try:
                # stdout занят протоколом MCP: случайная печать библиотеки уходит в stderr
                with contextlib.redirect_stdout(sys.stderr):
                    return function(*args, **kwargs)
            except (SystemExit, ValueError, TypeError, KeyError, OSError) as error:
                return f'ОШИБКА: {error}'
        return server.tool()(guarded)
    return tool
