"""Сторожевая проверка исходников `template/scripts/`: имена, атрибуты модулей, слои.

Разбор статический и без импорта: `scripts/state/mcp.py` и `scripts/sources/mcp.py` при
импорте поднимают сервер, а пакет `mcp` может быть не установлен. Поэтому оставшееся
после переноса кода имя вроде `REGISTRY` вместо `paths.REGISTRY` или `proj.ROOT` вместо
`proj._ROOT` видит только разбор исходников, а не запуск команд.

Проверяются три класса ошибок:
* имя, которое читается, но нигде не определено: `symtable` по модулю и всем вложенным
  таблицам (функции, методы, вложенные функции, классы); назначенные, импортированные,
  параметры, локальные имена и имена из замыканий не в счёт, встроенные — тоже;
* обращение `модуль.атрибут` в серверах MCP: атрибут должен быть определён на верхнем
  уровне целевого модуля из `template/scripts/`;
* направление импортов: слой импортирует только нижние слои, а внутри `sources/` — только
  модули левее по ряду. Оставшиеся кольца перечислены явно вместе с причиной.

Не ловит: обращение к несуществующему атрибуту не модуля, а объекта (например, поля
записи); имена, пришедшие из `from … import *`; имена, встречающиеся только в аннотациях
локальных переменных; опечатки в именах, определённых в самом модуле-потребителе;
ошибки типов и значений.

    python -m unittest discover -s tests/template
"""
import ast
import builtins
import symtable
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / 'template'
SCRIPTS = TEMPLATE / 'scripts'
BUILTINS = set(dir(builtins))
# Заполняет загрузчик модуля, а не сам исходник: в `dir(builtins)` их нет.
MODULE_GLOBALS = {'__file__', '__name__', '__doc__', '__package__', '__spec__', '__loader__',
                  '__builtins__', '__path__'}
# `ast.TypeAlias` появился в 3.12, а набор тестов идёт и на 3.11.
TYPE_ALIAS = getattr(ast, 'TypeAlias', None)


def scripts() -> list[Path]:
    """Все исходники скриптов, кроме кеша байт-кода."""
    return sorted(path for path in SCRIPTS.rglob('*.py') if '__pycache__' not in path.parts)


def shown(path: Path) -> str:
    return path.relative_to(TEMPLATE.parent).as_posix()


def name_lines(source: str) -> dict[str, int]:
    """Первая строка каждого читаемого имени: у `symtable` номеров строк нет."""
    lines: dict[str, int] = {}

    def note(name: str, number: int) -> None:
        lines[name] = min(lines.get(name, number), number)

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            note(node.id, node.lineno)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                note(name, node.lineno)
    return lines


def undefined(source: str, filename: str) -> list[tuple[int, str]]:
    """Имена, которые модуль читает, но нигде не определяет: строка и имя.

    У имени из вложенной таблицы нет пометки «определено на уровне модуля»: и `X` из
    `X = 1` в модуле, и потерянное имя внутри функции выглядят одинаково. Поэтому имена
    верхнего уровня собираются отдельно и служат списком определённого.
    """
    lines, found = name_lines(source), []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and any(alias.name == '*' for alias in node.names):
            return []  # `from … import *`: состав имён модуля статически неизвестен
    table = symtable.symtable(source, filename, 'exec')
    defined = {symbol.get_name() for symbol in table.get_symbols()
               if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()}
    defined |= BUILTINS | MODULE_GLOBALS

    def visit(current) -> None:
        for symbol in current.get_symbols():
            name = symbol.get_name()
            if not (symbol.is_referenced() and symbol.is_global()):
                continue
            if (symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
                    or symbol.is_parameter() or symbol.is_free() or symbol.is_local()):
                continue
            if name in defined or name not in lines:
                continue  # определённое имя или служебное имя компилятора, которого нет в тексте
            found.append((lines[name], name))
        for child in current.get_children():
            visit(child)

    visit(table)
    return sorted(set(found))


def module_file(name: str, origin: Path) -> Path | None:
    """Файл модуля `sources.paths` или `proj` внутри `template/scripts/`; None, если его нет."""
    parts = name.split('.')
    for base in (SCRIPTS, origin.parent):
        for candidate in (base.joinpath(*parts[:-1], parts[-1] + '.py'),
                          base.joinpath(*parts, '__init__.py')):
            if candidate.is_file() and candidate != origin:
                return candidate
    nearby = [path for path in SCRIPTS.rglob(parts[-1] + '.py') if path != origin]
    return nearby[0] if len(nearby) == 1 else None  # однофамильцы (summaries.py) не разбираются


def imported_modules(tree: ast.AST, origin: Path) -> dict[str, Path]:
    """Локальное имя импортированного модуля -> его файл. Пакеты и внешние модули пропускаются."""
    found: dict[str, Path] = {}
    for node in ast.walk(tree):
        imports = []
        if isinstance(node, ast.Import):
            # `import A.B` связывает пакет A, а не модуль: его разбирает не этот тест
            imports = [(alias.asname or alias.name, alias.name) for alias in node.names
                       if alias.asname or '.' not in alias.name]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            imports = [(alias.asname or alias.name, f'{node.module}.{alias.name}')
                       for alias in node.names if alias.name != '*']
        for local, name in imports:
            target = module_file(name, origin)
            if target:
                found[local] = target
    return found


def defined_names(path: Path) -> set[str] | None:
    """Имена верхнего уровня модуля; None, если модуль отдаёт имена через `import *`."""
    names: set[str] = set()
    star = False

    def targets(nodes) -> None:
        for node in nodes:
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Starred):
                targets([node.value])
            elif isinstance(node, (ast.Tuple, ast.List)):
                targets(node.elts)

    def body(nodes: list[ast.stmt]) -> None:
        nonlocal star
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                targets(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets([node.target])
            elif TYPE_ALIAS is not None and isinstance(node, TYPE_ALIAS):
                names.add(node.name.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    star = star or alias.name == '*'
                    names.add(alias.asname or alias.name)
            elif isinstance(node, (ast.If, ast.Try, ast.TryStar)):
                body(node.body)
                body(node.orelse)
                body(getattr(node, 'finalbody', []))
                for handler in getattr(node, 'handlers', []):
                    body(handler.body)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                body(node.body)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                targets([node.target])
                body(node.body)
                body(node.orelse)
            elif isinstance(node, ast.While):
                body(node.body)
                body(node.orelse)
            elif isinstance(node, ast.Match):
                for case in node.cases:
                    body(case.body)

    body(ast.parse(path.read_text(encoding='utf-8')).body)
    return None if star else names


def bad_attributes(path: Path) -> list[tuple[int, str, str]]:
    """Обращения `модуль.атрибут` к модулю из scripts/, у которого такого имени нет: строка, модуль, атрибут."""
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    modules = imported_modules(tree, path)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            continue
        target = modules.get(node.value.id)
        if target is None or (node.attr.startswith('__') and node.attr.endswith('__')):
            continue
        names = defined_names(target)
        if names is not None and node.attr not in names:
            found.append((node.lineno, node.value.id, node.attr))
    return sorted(found)


def imported_only(path: Path) -> set[str]:
    """Имена верхнего уровня, связанные только импортом, а не определением или присваиванием."""
    imported: set[str] = set()
    defined: set[str] = set()

    def targets(nodes) -> None:
        for node in nodes:
            if isinstance(node, ast.Name):
                defined.add(node.id)
            elif isinstance(node, (ast.Tuple, ast.List)):
                targets(node.elts)

    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            imported |= {alias.asname or alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported |= {alias.asname or alias.name for alias in node.names if alias.name != '*'}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            targets(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets([node.target])
    return imported - defined


def called_modules(path: Path) -> list[tuple[int, str, str]]:
    """Вызовы `модуль.имя(...)`, где `имя` — сам вложенный модуль: строка, модуль, имя.

    Так выглядел `lit.search(...)`: в фасаде `lit.py` имя `search` принадлежало модулю
    `sources/search.py`, поэтому вызов падал как вызов модуля. Проверки наличия атрибута
    здесь мало — имя есть, а вызвать его нельзя.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    modules = imported_modules(tree, path)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attribute = node.func
        if not isinstance(attribute.value, ast.Name):
            continue
        target = modules.get(attribute.value.id)
        if target is None:
            continue
        if (target.parent / f'{attribute.attr}.py').is_file() and attribute.attr in imported_only(target):
            found.append((node.lineno, attribute.value.id, attribute.attr))
    return sorted(found)


# Слои скриптов: общие основания (формат записи, запуск инструментов MCP) и `host` — низ,
# `sources` и `check` — середина, `state` — верх. Модуль импортирует только тех, кто ниже;
# внутри своего пакета — кого угодно.
LEVELS = {'records': 0, 'mcptool': 0, 'host': 0, 'sources': 1, 'check': 1, 'state': 2}
# Ряд внутри слоя источников: модуль импортирует только стоящих левее. Производные
# (catalog, search, tex) упорядочены так, чтобы исключений было меньше.
SOURCES_ORDER = ('web', 'paths', 'papers', 'store', 'registry', 'catalog', 'search', 'tex', 'lit', 'mcp')
# Оставшиеся кольца внутри `sources/`. Снять их — значит переносить функции между модулями,
# а это шире правки; поэтому они названы явно и с причиной. Новое кольцо в список не попадёт:
# он закрытый, а его актуальность проверяет `test_allowed_rings_are_still_real`.
SOURCES_ALLOWED = {
    ('papers', 'registry'):
        'кольцо papers ↔ registry: registry.add зовёт papers.arxiv_query, а papers.describe и '
        'papers.cites читают реестр',
    ('store', 'registry'):
        'кольцо store ↔ registry: store читает реестр (load, save, sha256, arxiv_id), registry '
        'зовёт store.store_pdf и store.store_eprint',
    ('registry', 'search'):
        'кольцо registry → search → tex → registry: registry индексирует добавленное, search и '
        'tex читают реестр',
    ('search', 'tex'):
        'кольцо search ↔ tex: search режет текст через tex.tex_chunks и tex.txt_chunks, tex '
        'берёт search.CHUNK и зовёт search.index',
}


def placed(path: Path, root: Path = SCRIPTS) -> tuple[str, str]:
    """Пакет модуля и его имя внутри пакета: `sources/papers.py` -> ('sources', 'papers')."""
    parts = path.relative_to(root).parts
    return (parts[0][:-3], parts[0][:-3]) if len(parts) == 1 else (parts[0], path.stem)


def label(path: Path, root: Path = SCRIPTS) -> str:
    """Путь модуля для сообщения: в заготовке — от её корня, иначе — от корня разбора."""
    return shown(path) if root == SCRIPTS else path.relative_to(root).as_posix()


def module_path(name: str, root: Path) -> Path | None:
    """Файл модуля `sources.paths` или `records` внутри root; None, если модуль внешний."""
    parts = name.split('.')
    for candidate in (root.joinpath(*parts[:-1], parts[-1] + '.py'), root.joinpath(*parts, '__init__.py')):
        if candidate.is_file():
            return candidate
    return None


def imports_of(source: Path, root: Path = SCRIPTS) -> set[Path]:
    """Файлы модулей из root, которые импортирует исходник."""
    found: set[Path] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names = [f'{node.module}.{alias.name}' for alias in node.names if alias.name != '*']
        for name in names:
            target = module_path(name, root)
            if target and target != source:
                found.add(target)
    return found


def package_problems(paths: list[Path], root: Path = SCRIPTS) -> list[str]:
    """Импорты, идущие не вниз по слоям: `sources` не знает `check` и `state` и так далее."""
    problems = []
    for source in paths:
        package = placed(source, root)[0]
        for target in sorted(imports_of(source, root)):
            other = placed(target, root)[0]
            if package in LEVELS and other in LEVELS and other != package \
                    and LEVELS[other] >= LEVELS[package]:
                problems.append(f'{label(source, root)}: {package} импортирует {other} '
                                f'({label(target, root)})')
    return sorted(set(problems))


def sources_problems(paths: list[Path], root: Path = SCRIPTS) -> list[str]:
    """Импорты внутри `sources/`, идущие не влево по ряду, и модули вне ряда."""
    problems = []
    for source in paths:
        package, importer = placed(source, root)
        if package != 'sources':
            continue
        for target in sorted(imports_of(source, root)):
            other, imported = placed(target, root)
            if other != 'sources' or imported == importer:
                continue
            if importer not in SOURCES_ORDER or imported not in SOURCES_ORDER:
                problems.append(f'{label(source, root)}: модуль вне ряда sources/ — {importer} → {imported}')
            elif SOURCES_ORDER.index(imported) >= SOURCES_ORDER.index(importer) \
                    and (importer, imported) not in SOURCES_ALLOWED:
                problems.append(f'{label(source, root)}: {importer} импортирует стоящий правее {imported}')
    return sorted(set(problems))


class ScriptsHaveNoUndefinedNames(unittest.TestCase):
    def test_every_referenced_name_is_defined(self):
        problems = [f'{shown(path)}:{line}: имя {name!r} не определено'
                    for path in scripts()
                    for line, name in undefined(path.read_text(encoding='utf-8'), path.name)]
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_guard_notices_a_lost_name(self):
        """Сторож видит имя без определения и не срабатывает на определённых."""
        self.assertEqual(undefined('def f():\n    return REGISTRY\n', 'sample.py'), [(2, 'REGISTRY')])
        self.assertEqual(undefined('def f():\n    return OUTER\nOUTER = 1\n', 'sample.py'), [])
        self.assertEqual(undefined('import os\n\n\ndef f(p):\n    y = len(os.sep) + p\n    return y\n',
                                   'sample.py'), [])

    def test_guard_follows_nested_scopes(self):
        """Имя внутри метода, вложенной функции и класса тоже проверяется."""
        source = ('class A:\n    def method(self):\n        return LOST\n'
                  '\n\ndef outer():\n    def inner():\n        return DEEP\n    return inner\n')
        self.assertEqual(undefined(source, 'sample.py'), [(3, 'LOST'), (8, 'DEEP')])


class McpServersUseExistingAttributes(unittest.TestCase):
    """`proj.ROOT` при `_ROOT` в proj.py ронял сервер при запуске, и этого не видел ни один тест."""

    def test_every_module_attribute_exists(self):
        problems = []
        for path in scripts():
            if path.name != 'mcp.py':
                continue
            for line, module, attribute in bad_attributes(path):
                problems.append(f'{shown(path)}:{line}: у модуля {module} нет имени {attribute!r}')
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_guard_notices_a_lost_attribute(self):
        """Сторож видит обращение к имени, которого в целевом модуле нет."""
        proj = SCRIPTS / 'state' / 'proj.py'
        self.assertIn('ROOT', defined_names(proj))  # это имя зовёт scripts/state/mcp.py
        self.assertEqual(module_file('proj', SCRIPTS / 'state' / 'mcp.py'), proj)
        with tempfile.TemporaryDirectory() as folder:
            sample = Path(folder) / 'mcp.py'
            sample.write_text('import proj\n\n\ndef main():\n    return proj.LOST_NAME\n', encoding='utf-8')
            self.assertEqual(bad_attributes(sample), [(5, 'proj', 'LOST_NAME')])

    def test_no_tool_calls_a_module(self):
        """Инструмент MCP не вызывает имя, которое в целевом модуле принадлежит модулю."""
        problems = []
        for path in scripts():
            if path.name != 'mcp.py':
                continue
            for line, module, attribute in called_modules(path):
                problems.append(f'{shown(path)}:{line}: {module}.{attribute} — модуль, а не функция')
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_guard_notices_a_called_module(self):
        """Сторож видит вызов модуля: `lit.search(...)` при `search` — модуле внутри фасада."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'inner.py').write_text('def work():\n    return 1\n', encoding='utf-8')
            (root / 'facade.py').write_text('import inner\n', encoding='utf-8')
            sample = root / 'mcp.py'
            sample.write_text('import facade\n\n\ndef tool():\n    return facade.inner()\n', encoding='utf-8')
            self.assertEqual(called_modules(sample), [(5, 'facade', 'inner')])
            (root / 'facade.py').write_text('import inner\n\n\ndef inner():\n    return 1\n', encoding='utf-8')
            self.assertEqual(called_modules(sample), [])


class ImportsFollowTheLayers(unittest.TestCase):
    """Слой импортирует только нижние, а внутри `sources/` — только модули левее по ряду."""

    def test_every_script_stands_in_a_layer(self):
        """Новый пакет или файл в `scripts/` должен быть назван в LEVELS, а не пропущен."""
        unknown = sorted(shown(path) for path in scripts() if placed(path)[0] not in LEVELS)
        self.assertEqual(unknown, [], '\n' + '\n'.join(unknown))

    def test_package_layers(self):
        problems = package_problems(scripts())
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_sources_row(self):
        problems = sources_problems(scripts())
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_every_sources_module_stands_in_the_row(self):
        names = sorted({placed(path)[1] for path in scripts() if placed(path)[0] == 'sources'})
        beyond = [name for name in names if name not in SOURCES_ORDER]
        self.assertEqual(beyond, [], f'вне ряда sources/: {", ".join(beyond)}')

    def test_allowed_rings_are_still_real(self):
        """Список исключений не должен пережить само кольцо: иначе он скрывает новое."""
        edges = {(placed(source)[1], placed(target)[1]) for source in scripts()
                 for target in imports_of(source)
                 if placed(source)[0] == placed(target)[0] == 'sources'}
        self.assertEqual(sorted(set(SOURCES_ALLOWED) - edges), [])

    def test_guard_notices_a_forbidden_dependency(self):
        """Сторож видит `from check import …` в слое источников."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'sources').mkdir()
            (root / 'check').mkdir()
            (root / 'check' / 'structure.py').write_text('X = 1\n', encoding='utf-8')
            papers = root / 'sources' / 'papers.py'
            papers.write_text('from check import structure\n', encoding='utf-8')
            self.assertEqual(package_problems([papers], root),
                             ['sources/papers.py: sources импортирует check (check/structure.py)'])

    def test_guard_notices_a_new_ring(self):
        """Сторож видит обратный импорт, которого нет в списке исключений."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'sources').mkdir()
            catalog = root / 'sources' / 'catalog.py'
            catalog.write_text('from sources import registry\n', encoding='utf-8')
            registry = root / 'sources' / 'registry.py'
            registry.write_text('from sources import catalog\n', encoding='utf-8')
            self.assertEqual(sources_problems([catalog], root), [])  # влево по ряду — можно
            self.assertEqual(sources_problems([registry, catalog], root),
                             ['sources/registry.py: registry импортирует стоящий правее catalog'])

    def test_guard_notices_a_module_outside_the_row(self):
        """Новый модуль в `sources/` без места в ряду тоже виден."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'sources').mkdir()
            (root / 'sources' / 'extra.py').write_text('X = 1\n', encoding='utf-8')
            importer = root / 'sources' / 'lit.py'
            importer.write_text('from sources import extra\n', encoding='utf-8')
            self.assertEqual(sources_problems([importer], root),
                             ['sources/lit.py: модуль вне ряда sources/ — lit → extra'])


if __name__ == '__main__':
    unittest.main()
