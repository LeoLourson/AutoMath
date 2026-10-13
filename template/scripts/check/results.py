"""Проверки записей результата: шапки, ссылки между записями, источники, соответствие Lean."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import records  # noqa: E402
from check import declarations  # noqa: E402


def check_records(root: Path, records_: list, sources: set[str], carded: set[str], index: dict,
                  verified: set[str] | None = None) -> tuple[list, list]:
    """Ошибки — неверная шапка или ссылка, замечания — неполнота, которую видно из шапок."""
    errors, warnings = [], []
    by_id = {doc.id: doc for doc in records_}
    for doc in records_:
        where, meta = records.rel(root, doc.path), doc.meta
        if meta.get('id') != doc.id:
            errors.append(f'{where}: поле id не совпадает с именем файла')
        if not meta.get('title'):
            errors.append(f'{where}: нет title')
        status = meta.get('status')
        if status not in records.RESULT_STATUS:
            errors.append(f'{where}: статус «{status}» не из списка: {", ".join(records.RESULT_STATUS)}')
        for dep in doc.many('depends'):
            if dep not in by_id:
                errors.append(f'{where}: зависит от несуществующей записи {dep}')
            elif by_id[dep].meta.get('status') == 'опровергнуто' and status != 'опровергнуто':
                errors.append(f'{where}: зависит от опровергнутой записи {dep}')
            elif status == 'доказано' and by_id[dep].meta.get('status') in ('цель', 'набросок') \
                    and not by_id[dep].many('lean'):
                warnings.append(f'{where}: доказательство опирается на недоказанную запись {dep}')
        for code in doc.many('sources'):
            if code not in sources:
                errors.append(f'{where}: источника {code} нет в sources/papers.json')
            elif code not in carded:
                warnings.append(f'{where}: у источника {code} нет карточки, его теорема не проверена')
            elif verified is not None and code not in verified:
                warnings.append(f'{where}: карточка источника {code} не сверена с PDF')
        names = doc.many('lean')
        missing = [name for name in names if declarations.resolve(index, name) is None]
        errors += [f'{where}: объявления {name} нет в библиотеке' for name in missing]
        if names and not missing:
            stored = (meta.get('fidelity') or '').split()
            if not stored:
                warnings.append(f'{where}: соответствие формализации не проверено')
            elif stored[-1] != declarations.record_fingerprint(index, names):
                warnings.append(f'{where}: формулировка или определения изменились после проверки соответствия')
        if status == 'доказано' and not meta.get('review') and not names:
            warnings.append(f'{where}: доказательство без рецензии')

    seen: dict[str, int] = {}

    def visit(ident: str, trail: list[str]) -> None:
        if seen.get(ident) == 1:
            errors.append('цикл зависимостей: ' + ' → '.join(trail + [ident]))
        if ident in seen or ident not in by_id:
            return
        seen[ident] = 1
        for dep in by_id[ident].many('depends'):
            visit(dep, trail + [ident])
        seen[ident] = 2

    for ident in by_id:
        visit(ident, [])
    return errors, warnings


def check_ideas(root: Path, ideas: list, record_ids: set[str]) -> tuple[list, list]:
    """Идея: шапка со статусом, цель и след критика."""
    errors, warnings = [], []
    for doc in ideas:
        where, meta = records.rel(root, doc.path), doc.meta
        if meta.get('id') != doc.id:
            errors.append(f'{where}: поле id не совпадает с именем файла')
        if meta.get('status') not in records.IDEA_STATUS:
            errors.append(f"{where}: статус «{meta.get('status')}» не из списка: "
                          f'{", ".join(records.IDEA_STATUS)}')
        if not meta.get('target'):
            errors.append(f'{where}: нет target — вопроса или записи, к которой относится идея')
        if meta.get('status') == 'перенесена' and meta.get('result') not in record_ids:
            errors.append(f'{where}: статус «перенесена» требует поля result с номером записи')
        if meta.get('status') == 'новая' and not meta.get('critic'):
            warnings.append(f'{where}: идея не прошла критика')
    return errors, warnings
