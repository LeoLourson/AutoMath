"""Offline behavioral checks for the DeepSeek Harness adapter.

Expected names and counts are read from .claude/ and .mcp.json, so adding, renaming or
removing a command, role, skill or MCP server needs no change here.
"""
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / 'scripts'))
import harness


class HarnessAdapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='research harness ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project with spaces'
        shutil.copytree(PROJECT, self.root, ignore=shutil.ignore_patterns(
            '.git', '.lake', '.dsh', 'output', '__pycache__'))

    def entries(self):
        return json.loads((self.root / harness.PATCH).read_text(encoding='utf-8'))[0]['insert']

    def roles(self):
        return {e['id'].removeprefix('research-role-'): e['config'] for e in self.entries()
                if e['name'].endswith('dsh-tool-subagent')}

    def command(self):
        return sorted((self.root / '.claude/commands').glob('*.md'))[0]

    def agent(self):
        return sorted((self.root / '.claude/agents').glob('*.md'))[0]

    def write(self, relative, text):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def test_every_command_and_skill_becomes_a_native_skill(self):
        harness.prepare(self.root)
        agents, sources = harness.sources(self.root)
        skills = {p.parent.name: harness.frontmatter(p) for p in (self.root / '.dsh/skills').glob('*/SKILL.md')}
        expected = {p.stem for p in (self.root / '.claude/commands').glob('*.md')}
        expected |= {p.parent.name for p in (self.root / '.claude/skills').glob('*/SKILL.md')}
        self.assertEqual(set(skills), expected)
        for name, (fields, body) in skills.items():
            _, source, original = sources[name]
            self.assertEqual(fields['name'], name)
            self.assertEqual(fields['description'], source['description'])
            self.assertEqual(fields.get('disable-model-invocation'), source.get('disable-model-invocation'))
            self.assertLessEqual(set(fields), harness.SKILL_FIELDS)
            if source.get('paths'):
                self.assertIn(source['paths'], fields['whenToUse'])
            self.assertNotIn('$ARGUMENTS', body)
            self.assertNotIn('.claude/commands/', body)
            for tool in harness.mentioned(harness.CLAUDE_TOOLS, original):
                self.assertIn(f'`{tool}` — {harness.CLAUDE_TOOLS[tool]}', body)
            if harness.mentioned(harness.CLAUDE_MODELS, original):
                self.assertIn('Названия моделей Claude Code', body)
            if harness.is_workflow(sources[name][0], source):
                for role in agents:
                    self.assertIn(f'`{harness.role_tool(role)}` — ', body)
            for link in re.findall(r'\]\((reference/[^)]+)\)', body):
                self.assertTrue((self.root / '.dsh/skills' / name / link).is_file(), link)
        for source in (self.root / '.claude/skills').rglob('*'):
            if source.is_file() and source.name != 'SKILL.md':
                copy = self.root / '.dsh/skills' / source.relative_to(self.root / '.claude/skills')
                self.assertEqual(copy.read_bytes(), source.read_bytes())

    def test_every_agent_becomes_a_fresh_native_role(self):
        harness.prepare(self.root)
        agents, _ = harness.sources(self.root)
        roles = self.roles()
        servers = json.loads((self.root / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']
        self.assertEqual(set(roles), {p.stem for p in (self.root / '.claude/agents').glob('*.md')})
        for name, role in roles.items():
            _, fields, _ = agents[name]
            tools = harness.tool_list(fields)
            self.assertEqual(role['toolName'], harness.role_tool(name))
            self.assertEqual(role['provider'], 'spawn')
            self.assertEqual(role['maxDepth'], 2)
            self.assertNotIn('agentOptions', role)
            self.assertEqual('Перед работой прочитай AGENTS.md' in role['persona'].split('\n')[0],
                             fields.get('omitClaudeMd') is not True)
            delegates = tools is None or bool(harness.DELEGATING & set(tools))
            self.assertEqual('Роли вызываются инструментами research_*' in role['persona'], delegates)
            self.assertNotIn(f'- `{role["toolName"]}` — ', role['persona'])
            for tool in tools or []:
                if tool.startswith('mcp__'):
                    if tool.split('__')[1] not in servers:
                        continue
                    self.assertIn(f'{tool}__*', role['persona'])
                else:
                    self.assertIn(f'`{tool}` — ', role['persona'])
            for other in agents:
                self.assertNotIn(f'`{other}`', role['persona'])

    def test_new_workflow_parts_need_no_adapter_changes(self):
        self.write('.claude/commands/survey.md', '---\ndescription: Обзор по теме\n---\n'
                   'Поручи `digest-writer` обзор: $ARGUMENTS\n')
        self.write('.claude/agents/digest-writer.md', '---\nname: digest-writer\ndescription: Пишет обзор\n'
                   'model: sonnet\ntools: Read, Agent, mcp__lit\n---\nСобери обзор; чертежи читай через `Read`.\n')
        self.write('.claude/skills/figure-style/SKILL.md', '---\nname: figure-style\ndescription: Подписи рисунков\n'
                   'paths: "figures/**/*.tex"\ndisable-model-invocation: true\n---\nМодель `haiku` не годится.\n')
        self.write('.claude/skills/figure-style/reference/sizes.md', 'ширина')
        config = self.root / '.mcp.json'
        data = json.loads(config.read_text(encoding='utf-8'))
        data['mcpServers']['plots'] = {'command': 'uv', 'args': ['run', 'plots.py']}
        config.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(harness.unported(self.root), [])
        harness.prepare(self.root)

        survey = (self.root / '.dsh/skills/survey/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Поручи `research_digest_writer` обзор', survey)
        self.assertIn('- `research_digest_writer` — Пишет обзор', survey)
        self.assertIn('mcp__plots__*', survey)
        self.assertIn('Перед правкой `figures/**/*.tex` загрузи skills: `figure-style`', survey)
        fields, body = harness.frontmatter(self.root / '.dsh/skills/figure-style/SKILL.md')
        self.assertIs(fields['disable-model-invocation'], True)
        self.assertEqual(fields['whenToUse'], 'При работе с файлами figures/**/*.tex.')
        self.assertIn('Названия моделей Claude Code (`haiku`)', body)
        self.assertEqual((self.root / '.dsh/skills/figure-style/reference/sizes.md').read_text(), 'ширина')
        role = self.roles()['digest-writer']
        self.assertEqual(role['toolName'], 'research_digest_writer')
        self.assertIn('Роли вызываются инструментами research_*', role['persona'])
        self.assertIn('MCP: mcp__lit__*.', role['persona'])
        self.assertIn('`Read` — чтение файлов и изображений', role['persona'])
        servers = {e['config']['serverName'] for e in self.entries() if e['name'].endswith('dsh-mcp-client')}
        self.assertIn('plots', servers)
        inventory = json.loads((self.root / harness.MANIFEST).read_text(encoding='utf-8'))['inventory']
        self.assertFalse(inventory['skills']['figure-style']['model_invocable'])
        self.assertTrue(inventory['skills']['survey']['workflow'])
        self.assertEqual(inventory['roles']['digest-writer']['tool'], 'research_digest_writer')
        self.assertIn('research_digest_writer', harness.inventory_text(self.root))

    def test_frontmatter_without_a_rule_is_reported(self):
        clean = harness.unported(self.root)
        source = self.agent()
        note = f'.claude/agents/{source.name}: hooks'
        source.write_text(source.read_text(encoding='utf-8').replace('---\n', '---\nhooks: stop\n', 1),
                          encoding='utf-8')
        self.assertEqual(harness.unported(self.root), [note, *clean])
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            self.assertEqual(harness.main(['--root', str(self.root), 'prepare']), 0)
        self.assertIn(note, errors.getvalue())

    def test_documentation_names_the_pinned_harness(self):
        text = (PROJECT / 'DEEPSEEK.md').read_text(encoding='utf-8')
        self.assertIn(harness.UPSTREAM_REVISION, text)
        packages = set(re.findall(r'@deepseek-ai/dsh@[\w.-]+', text))
        self.assertEqual(packages, {harness.DSH_PACKAGE})

    def test_mcp_uses_project_cwd_and_preserves_local_commands(self):
        config = self.root / '.mcp.json'
        data = json.loads(config.read_text(encoding='utf-8'))
        first = next(iter(data['mcpServers']))
        data['mcpServers'][first]['args'].insert(0, '--offline')
        config.write_text(json.dumps(data), encoding='utf-8')
        harness.prepare(self.root)
        servers = {e['config']['serverName']: e['config'] for e in self.entries()
                   if e['name'].endswith('dsh-mcp-client')}
        self.assertEqual(set(servers), set(data['mcpServers']))
        for server in servers.values():
            self.assertEqual(Path(server['cwd']), self.root)
            self.assertEqual(server['transport'], 'stdio')
        self.assertEqual(servers[first]['args'][0], '--offline')
        for name, original in data['mcpServers'].items():
            self.assertEqual(servers[name].get('env'), original.get('env'))
        self.assertEqual(json.loads(config.read_text(encoding='utf-8')), data)

    def test_prepare_is_idempotent_and_check_does_not_write(self):
        self.assertTrue(harness.prepare(self.root, check=True))
        self.assertFalse((self.root / '.dsh').exists())
        harness.prepare(self.root)
        self.assertEqual(harness.prepare(self.root), [])
        source = self.command()
        skill = f'.dsh/skills/{source.stem}/SKILL.md'
        source.write_text(source.read_text(encoding='utf-8') + '\nНовая инструкция.\n', encoding='utf-8')
        self.assertIn(skill, harness.prepare(self.root, check=True))
        self.assertNotIn('Новая инструкция.', (self.root / skill).read_text(encoding='utf-8'))
        harness.prepare(self.root)
        self.assertEqual(harness.prepare(self.root, check=True), [])

    def test_invalid_source_fails_before_any_writes(self):
        self.agent().write_text('broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            harness.prepare(self.root)
        self.assertFalse((self.root / '.dsh').exists())

    def test_removed_workflow_is_pruned_but_custom_skills_are_preserved(self):
        harness.prepare(self.root)
        custom = self.root / '.dsh/skills/custom.md'
        custom.write_text('user skill', encoding='utf-8')
        stale = self.root / '.dsh/skills' / self.command().stem / 'SKILL.md'
        self.command().unlink()
        self.assertTrue(harness.prepare(self.root, check=True))
        self.assertTrue(stale.exists())
        harness.prepare(self.root)
        self.assertFalse(stale.exists())
        self.assertEqual(custom.read_text(encoding='utf-8'), 'user skill')

    def test_modified_stale_output_is_not_deleted(self):
        harness.prepare(self.root)
        stale = self.root / '.dsh/skills' / self.command().stem / 'SKILL.md'
        self.command().unlink()
        stale.write_text('manual changes', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'изменён вручную'):
            harness.prepare(self.root)
        self.assertEqual(stale.read_text(encoding='utf-8'), 'manual changes')

    def test_manifest_cannot_delete_outside_generated_skills(self):
        harness.prepare(self.root)
        before = (self.root / 'AGENTS.md').read_bytes()
        manifest = self.root / harness.MANIFEST
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['files']['AGENTS.md'] = harness.hashlib.sha256(before).hexdigest()
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Недопустимый путь'):
            harness.prepare(self.root)
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), before)

    def test_explicit_skill_root_works_without_git(self):
        harness.prepare(self.root)
        provider = next(e['config'] for e in self.entries() if e['name'].endswith('dsh-skill-filesystem'))
        self.assertFalse(provider['includeDefaultRoots'])
        self.assertEqual(provider['customSkillDirs'], [str(self.root / '.dsh/skills')])

    def test_launcher_passes_arguments_without_shell_and_propagates_failure(self):
        prompt = 'Проверь "текст" & $HOME; не исполняй это как shell'
        with patch.object(harness, 'runtime_command', return_value=['node', 'npx-cli.js', harness.DSH_PACKAGE]), \
             patch.object(harness.subprocess, 'call', return_value=7) as call:
            status = harness.main(['--root', str(self.root), 'run', 'headless', '--', prompt])
        self.assertEqual(status, 7)
        command = call.call_args.args[0]
        self.assertEqual(command[-1], prompt)
        self.assertEqual(command[-4:-1], ['headless', '--patch', str(self.root / harness.PATCH)])
        self.assertEqual(call.call_args.kwargs, {'cwd': self.root})

    def test_check_cli_exit_status(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main(['--root', str(self.root), 'check']), 1)
            self.assertEqual(harness.main(['--root', str(self.root), 'prepare']), 0)
            self.assertEqual(harness.main(['--root', str(self.root), 'check']), 0)


if __name__ == '__main__':
    unittest.main()
