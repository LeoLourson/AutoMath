"""Адаптер проекта для DeepSeek Harness: prepare, check, list, run [web|headless] [-- аргументы].

Исходники ролей, команд и навыков остаются в .claude/. Производные файлы
записываются в .dsh/skills/ и output/harness/, без ключей и глобальных настроек.
Состав команд, ролей, навыков и MCP адаптер читает из .claude/ и .mcp.json: имён
конкретных команд и ролей в этом файле нет, и при их изменении он не правится.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DSH_VERSION = '0.2.1-alpha.2'
DSH_PACKAGE = f'@deepseek-ai/dsh@{DSH_VERSION}'
UPSTREAM_REVISION = 'd743267388641bc76f17c45ce8b4c231aed1d32c'
PATCH = Path('output/harness/cordis.patch.yml')
MANIFEST = Path('output/harness/generated.json')
# Поля шапки, которые Harness понимает сам; остальные поля Claude Code перечислены ниже.
SKILL_FIELDS = {'name', 'description', 'whenToUse', 'disable-model-invocation', 'user-invocable'}
# `paths` переносится в whenToUse, `argument-hint` — подсказка интерфейса Claude Code.
SKILL_HANDLED = SKILL_FIELDS | {'paths', 'argument-hint'}
# `tools` и `omitClaudeMd` переносятся в инструкции роли; модель наследуется от сессии.
AGENT_HANDLED = {'name', 'description', 'tools', 'model', 'omitClaudeMd'}
# Словарь среды Claude Code. От состава команд, ролей и навыков он не зависит.
CLAUDE_TOOLS = {
    'Read': 'чтение файлов и изображений', 'Write': 'запись файла', 'Edit': 'правка файла',
    'Grep': 'поиск по содержимому файлов', 'Glob': 'поиск файлов по маске',
    'Bash': 'оболочка', 'WebSearch': 'поиск в интернете', 'WebFetch': 'загрузка веб-страницы',
    'Agent': 'вызов роли инструментом research_*', 'Task': 'вызов роли инструментом research_*',
}
CLAUDE_MODELS = ('opus', 'sonnet', 'haiku')
DELEGATING = {'Agent', 'Task'}

PROJECT_NOTE = 'Рабочая папка — корень этого исследовательского проекта.'
# Файлы правил проекта; в указание «прочитай» попадают те, что есть в проекте.
RULES = ('AGENTS.md', 'PROJECT.md')
DELEGATION = """Роли вызываются инструментами research_*; каждый вызов создаёт нового агента без
истории родителя. Передавай проверяющему только файлы и предмет проверки, без
рассуждений автора. Вызов возвращает id; дождись отчёта и проверь записанный файл
до изменения статусов или запуска зависимого шага. Независимую проверку не заменяй
самопроверкой."""
COMMON = """Команды Python выполняй из корня проекта. Если требуемого инструмента нет, сообщи об
этом. Для чтения PDF и сверки страниц нужна модель с поддержкой изображений."""


def frontmatter(path: Path) -> tuple[dict[str, str | bool], str]:
    """Read the scalar YAML subset used by this template; reject unsupported syntax."""
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    parts = text.split('---\n', 2)
    if len(parts) != 3 or parts[0]:
        raise ValueError(f'{path}: ожидается YAML-шапка')
    fields: dict[str, str | bool] = {}
    for line in parts[1].splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([\w-]+):\s*(.+)', line)
        if not match or match[1] in fields or match[2] in ('|', '>', '|-', '>-'):
            raise ValueError(f'{path}: неподдерживаемое поле шапки: {line}')
        key, value = match.groups()
        if value.startswith('"'):
            value = json.loads(value)
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        elif value in ('true', 'false'):
            value = value == 'true'
        fields[key] = value
    if not isinstance(fields.get('description'), str) or not fields['description']:
        raise ValueError(f'{path}: нужна description')
    return fields, parts[2].lstrip('\n')


def role_tool(name: str) -> str:
    return 'research_' + name.replace('-', '_')


def adapt(text: str, roles: list[str]) -> str:
    """Translate structural references; tool and model names are explained by host_notes."""
    text = text.replace('$ARGUMENTS', 'аргументы вызова из сообщения пользователя')
    text = re.sub(r'\.claude/commands/([\w-]+)\.md', r'.dsh/skills/\1/SKILL.md', text)
    text = text.replace('.claude/skills/', '.dsh/skills/')
    for role in roles:
        text = text.replace(f'`{role}`', f'`{role_tool(role)}`')
    return text


def mentioned(names, text: str) -> list[str]:
    return [name for name in names if re.search(rf'(?<![\w/.-]){name}(?![\w/.-])', text)]


def host_notes(text: str, tools: list[str] = ()) -> list[str]:
    """Explain only the Claude Code names that the instruction really uses."""
    found = mentioned(CLAUDE_TOOLS, text)
    used = [name for name in CLAUDE_TOOLS if name in tools or name in found]
    notes = []
    if used:
        notes.append('Инструкция написана для Claude Code и называет его инструменты; в Harness '
                     'бери аналог: ' + '; '.join(f'`{name}` — {CLAUDE_TOOLS[name]}' for name in used) + '.')
    models = mentioned(CLAUDE_MODELS, text)
    if models:
        notes.append('Названия моделей Claude Code (' + ', '.join(f'`{name}`' for name in models) +
                     ') в Harness не действуют: роли наследуют модель сессии. Где инструкция '
                     'требует другую модель, сообщи пользователю и не считай шаг выполненным.')
    return notes


def tool_list(fields: dict) -> list[str] | None:
    """Claude Code `tools`; None means that the role inherits every tool."""
    if 'tools' not in fields:
        return None
    return [item.strip() for item in str(fields['tools']).split(',') if item.strip()]


def read_note(root: Path) -> str:
    found = [name for name in RULES if (root / name).is_file()]
    return f'Перед работой прочитай {" и ".join(found)} из корня проекта.'


def mcp_note(servers: list[str]) -> list[str]:
    return ['MCP: ' + ', '.join(f'mcp__{name}__*' for name in servers) + '.'] if servers else []


def roster(agents: dict, skip: str = '') -> list[str]:
    return [DELEGATION, 'Роли:'] + [f'- `{role_tool(name)}` — {fields["description"]}'
                                    for name, (_, fields, _) in agents.items() if name != skip]


def sources(root: Path) -> tuple[dict, dict]:
    """Everything the adapter knows about the workflow: name -> (path, frontmatter, body)."""
    agents = {}
    for path in sorted((root / '.claude/agents').glob('*.md')):
        fields, body = frontmatter(path)
        if fields.get('name') != path.stem:
            raise ValueError(f'{path}: имя роли не совпадает с файлом')
        agents[path.stem] = (path, fields, body)
    if not agents:
        raise ValueError('Не найдены роли .claude/agents/')
    skills = {}
    paths = sorted((root / '.claude/commands').glob('*.md'))
    paths += sorted((root / '.claude/skills').glob('*/SKILL.md'))
    for path in paths:
        fields, body = frontmatter(path)
        name = path.stem if path.parent.name == 'commands' else path.parent.name
        if name in skills or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            raise ValueError(f'Повторное или недопустимое имя skill: {name}')
        if fields.get('name', name) != name:
            raise ValueError(f'{path}: имя skill не совпадает с папкой')
        skills[name] = (path, fields, body)
    if not skills:
        raise ValueError('Не найдены команды и навыки в .claude/')
    return agents, skills


def is_workflow(path: Path, fields: dict) -> bool:
    """Commands and user-only skills start a workflow and may call roles."""
    return path.parent.name == 'commands' or fields.get('disable-model-invocation') is True


def unported(root: Path) -> list[str]:
    """Frontmatter fields the adapter has no rule for; they do not reach Harness."""
    root = root.resolve()
    agents, skills = sources(root)
    notes = []
    for group, handled in ((agents, AGENT_HANDLED), (skills, SKILL_HANDLED)):
        for path, fields, _ in group.values():
            extra = sorted(set(fields) - handled)
            if extra:
                notes.append(f'{path.relative_to(root).as_posix()}: {", ".join(extra)}')
    return notes


def skill_files(root: Path, agents: dict, skills: dict, servers: list[str]) -> dict[Path, bytes]:
    # Self-ignoring directory also works in projects upgraded from older templates.
    result: dict[Path, bytes] = {Path('.dsh/skills/.gitignore'): b'*\n'}
    by_paths: dict[str, list[str]] = {}
    for name, (_, fields, _) in skills.items():
        if fields.get('paths'):
            by_paths.setdefault(str(fields['paths']), []).append(name)
    scoped = [f'Фильтры файлов Claude Code в Harness не действуют. Перед правкой `{mask}` загрузи skills: '
              + ', '.join(f'`{name}`' for name in names) + '.' for mask, names in by_paths.items()]
    for name, (source, fields, body) in skills.items():
        header = {k: v for k, v in fields.items() if k in SKILL_FIELDS}
        header['name'] = name
        if fields.get('paths') and 'whenToUse' not in header:
            header['whenToUse'] = f'При работе с файлами {fields["paths"]}.'
        lines = host_notes(body)
        if is_workflow(source, fields):
            lines = [PROJECT_NOTE + ' ' + read_note(root), *roster(agents), *mcp_note(servers), *scoped, *lines, COMMON]
        prefix = '\n'.join(lines) + '\n\n' if lines else ''
        yaml = '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in header.items())
        result[Path('.dsh/skills') / name / 'SKILL.md'] = (
            f'---\n{yaml}\n---\n\n{prefix}{adapt(body, list(agents))}').encode('utf-8')
        if source.name == 'SKILL.md':
            for resource in sorted(source.parent.rglob('*')):
                if resource.is_file() and resource != source and '__pycache__' not in resource.parts:
                    relative = resource.relative_to(source.parent)
                    result[Path('.dsh/skills') / name / relative] = resource.read_bytes()
    return result


def persona(root: Path, name: str, agents: dict, servers: list[str]) -> str:
    """Role instructions; the restrictions come from the Claude Code frontmatter of the role."""
    _, fields, body = agents[name]
    tools = tool_list(fields)
    lines = [PROJECT_NOTE if fields.get('omitClaudeMd') is True else PROJECT_NOTE + ' ' + read_note(root)]
    if tools is None or DELEGATING & set(tools):
        lines += roster(agents, skip=name)
    else:
        lines.append('Другие роли не вызывай. Собственную работу роль не проверяет.')
    if tools is not None:
        declared = [tool.split('__')[1] for tool in tools if tool.startswith('mcp__')]
        servers = [server for server in servers if server in declared]
        builtin = [tool for tool in tools if not tool.startswith('mcp__')]
        lines.append('Набор инструментов роли в Claude Code: ' + ', '.join(builtin) +
                     '. Пользуйся только их аналогами в Harness.')
    lines += mcp_note(servers) + host_notes(body, tools or []) + [COMMON]
    return '\n'.join(lines) + '\n\n' + adapt(body, list(agents))


def mcp_entries(root: Path) -> list[dict]:
    servers = json.loads((root / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']
    entries = []
    for name, original in servers.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', name):
            raise ValueError(f'Недопустимое имя MCP-сервера: {name}')
        if original.get('disabled'):
            continue
        # Do not silently lose authentication or unsupported transport settings.
        allowed = {'type', 'command', 'args', 'cwd', 'env', 'disabled', 'url', 'headers'}
        if set(original) - allowed:
            raise ValueError(f'MCP {name}: неподдерживаемые поля {sorted(set(original) - allowed)}')
        config = {'serverName': name, 'toolCallTimeoutMs': 600000, 'failOnStartupError': True}
        transport = original.get('type', 'stdio')
        if transport == 'stdio':
            config.update(transport='stdio', command=original['command'], args=original.get('args', []))
            cwd = Path(original.get('cwd', str(root)))
            config['cwd'] = str((root / cwd).resolve())
            # The patch stays in the ignored output/; headers below are still refused.
            if original.get('env'):
                config['env'] = original['env']
        elif transport in ('http', 'streamable-http'):
            config.update(transport='streamable-http', url=original['url'])
            if original.get('headers'):
                raise ValueError(f'MCP {name}: headers храните в отдельном локальном Cordis patch')
        else:
            raise ValueError(f'MCP {name}: транспорт {transport} не поддерживается Harness')
        entries.append({'id': f'research-mcp-{name}', 'name': '@deepseek-ai/dsh-mcp-client', 'config': config})
    return entries


def artifacts(root: Path) -> dict[Path, bytes]:
    root = root.resolve()
    if not (root / RULES[0]).is_file():
        raise ValueError(f'Нет {root / RULES[0]}; укажите корень проекта')
    agents, skills = sources(root)
    entries = mcp_entries(root)
    servers = [entry['config']['serverName'] for entry in entries]
    result = skill_files(root, agents, skills, servers)
    for name in agents:
        entries.append({
            'id': f'research-role-{name}',
            'name': '@deepseek-ai/dsh-tool-subagent',
            'config': {'provider': 'spawn', 'toolName': role_tool(name),
                       'maxDepth': 2, 'persona': persona(root, name, agents, servers)},
        })
    # A private provider makes skills discoverable even with --no-git or when the
    # project is nested inside another checkout. Avoid duplicate default-root scans.
    entries.append({'id': 'research-skills', 'name': '@deepseek-ai/dsh-skill-filesystem',
                    'config': {'providerName': 'research-template', 'includeDefaultRoots': False,
                               'customSkillDirs': [str(root / '.dsh/skills')]}})
    # JSON is a YAML subset: no YAML dependency, tags, interpolation or shell quoting.
    result[PATCH] = (json.dumps([{'insert': entries}], ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    inventory = {
        'skills': {name: {'source': path.relative_to(root).as_posix(),
                          'model_invocable': fields.get('disable-model-invocation') is not True,
                          'workflow': is_workflow(path, fields)}
                   for name, (path, fields, _) in sorted(skills.items())},
        'roles': {name: {'source': path.relative_to(root).as_posix(), 'tool': role_tool(name)}
                  for name, (path, _, _) in agents.items()},
        'mcp': servers,
    }
    manifest = {'dsh_version': DSH_VERSION, 'upstream_revision': UPSTREAM_REVISION, 'inventory': inventory,
                'files': {p.as_posix(): hashlib.sha256(data).hexdigest() for p, data in result.items()}}
    result[MANIFEST] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return result


def prepare(root: Path = ROOT, *, check: bool = False) -> list[str]:
    """Render first, then reconcile owned files, preserving unrelated user files."""
    root = root.resolve()
    generated = artifacts(root)
    stale = []
    if (root / MANIFEST).is_file():
        previous = json.loads((root / MANIFEST).read_text(encoding='utf-8'))['files']
        if isinstance(previous, dict):
            for name, digest in previous.items():
                relative = Path(name)
                if relative in generated:
                    continue
                target = (root / relative).resolve()
                skill_root = (root / '.dsh/skills').resolve()
                if not target.is_relative_to(skill_root) or target == skill_root:
                    raise ValueError(f'Недопустимый путь в манифесте: {name}')
                if target.is_file():
                    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                        raise ValueError(f'Устаревший производный файл изменён вручную: {target}; '
                                         'сохраните правки вне .dsh/skills/ перед подготовкой')
                    stale.append((relative, target))
    # Never follow generated-output symlinks outside this project.
    for relative in generated:
        if not (root / relative).resolve().is_relative_to(root):
            raise ValueError(f'Производный путь выходит за корень проекта: {relative}')
    changed = []

    def write_changed(relative: Path, data: bytes) -> None:
        target = root / relative
        if not target.is_file() or target.read_bytes() != data:
            changed.append(relative.as_posix())
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

    for relative, data in generated.items():
        if relative != MANIFEST:
            write_changed(relative, data)
    for relative, target in stale:
        changed.append(f'удалить {relative.as_posix()}')
        if not check:
            target.unlink()
    # Retain the old ownership ledger until every stale file has been reconciled.
    write_changed(MANIFEST, generated[MANIFEST])
    return changed


def inventory_text(root: Path) -> str:
    found = json.loads(artifacts(root)[MANIFEST])['inventory']
    lines = [f'DeepSeek Harness {DSH_VERSION}', f'Skills ({len(found["skills"])}):']
    for name, skill in found['skills'].items():
        mark = '' if skill['model_invocable'] else '  [только по вызову пользователя]'
        lines.append(f'  {"/" if skill["workflow"] else " "}{name:<18} {skill["source"]}{mark}')
    lines.append(f'Роли ({len(found["roles"])}):')
    lines += [f'  {role["tool"]:<28} {role["source"]}' for role in found['roles'].values()]
    lines.append(f'MCP ({len(found["mcp"])}): ' + ', '.join(found['mcp']))
    return '\n'.join(lines)


def runtime_command() -> list[str]:
    """Use npm's JS entrypoint directly, including on Windows (no cmd shell)."""
    node = shutil.which('node')
    npx = shutil.which('npx')
    if not node or not npx:
        raise ValueError('Для запуска нужны Node.js 22.19+ (или 24+) и npm/npx; см. DEEPSEEK.md')
    resolved = Path(npx).resolve()
    candidates = [resolved, resolved.parent / 'node_modules/npm/bin/npx-cli.js']
    entry = next((p for p in candidates if p.suffix == '.js' and p.is_file()), None)
    if entry is None:
        raise ValueError('Не найден npx-cli.js; выполните команду npx из DEEPSEEK.md вручную')
    return [node, str(entry), '--yes', DSH_PACKAGE]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', type=Path, default=ROOT, help='корень созданного проекта')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare', help='подготовить skills и Cordis patch без сети и запуска Harness')
    sub.add_parser('check', help='проверить, что производные файлы свежие; ничего не писать')
    sub.add_parser('list', help='показать skills, роли и MCP, которые получит Harness; ничего не писать')
    sub.add_parser('package', help='напечатать закреплённый npm-пакет Harness')
    run = sub.add_parser('run', help='подготовить интеграцию и запустить закреплённый Harness')
    run.add_argument('profile', choices=('web', 'headless'), nargs='?', default='web')
    run.add_argument('args', nargs=argparse.REMAINDER, help='аргументы Harness после --')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == 'package':
        print(DSH_PACKAGE)
        return 0
    try:
        if args.command == 'list':
            print(inventory_text(root))
            return 0
        for note in unported(root):
            print(f'Не перенесено в Harness, для поля шапки нет правила: {note}', file=sys.stderr)
        changed = prepare(root, check=args.command == 'check')
        if args.command == 'check':
            print('Требуют подготовки:\n' + '\n'.join(changed) if changed else 'DeepSeek Harness: файлы актуальны.')
            return int(bool(changed))
        if args.command == 'prepare':
            print(f'DeepSeek Harness {DSH_VERSION}: подготовлено файлов: {len(changed)}.\n'
                  f'Patch: {root / PATCH}\nЗапуск: python scripts/harness.py run web')
            return 0
        extra = args.args[1:] if args.args[:1] == ['--'] else args.args
        command = runtime_command() + [args.profile, '--patch', str(root / PATCH), *extra]
        return subprocess.call(command, cwd=root)
    except (OSError, ValueError, KeyError) as error:
        print(f'ОШИБКА: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
