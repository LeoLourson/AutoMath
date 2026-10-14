"""Generator and upgrade regression tests; no network, Git initialization or Lean.

    python -m unittest discover -s tests/kit
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('create_project', REPO / 'tools/create.py')
create_project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_project)


class ProjectGeneration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='research upgrade ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Spectra'
        with contextlib.redirect_stdout(io.StringIO()):
            create_project.create(self.root, 'Spectra', 'Спектральная задача', None, False)

    def load_harness(self):
        spec = importlib.util.spec_from_file_location('harness',
                                                      create_project.TEMPLATE / 'scripts/host/harness.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

    def test_create_prepares_native_integration(self):
        claude = create_project.TEMPLATE / '.claude'
        skills = len(list(claude.glob('commands/*.md'))) + len(list(claude.glob('skills/*/SKILL.md')))
        servers = json.loads((create_project.TEMPLATE / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']
        self.assertTrue((self.root / 'Spectra/Basic.lean').is_file())
        self.assertEqual(len(list((self.root / '.dsh/skills').glob('*/SKILL.md'))), skills)
        self.assertTrue((self.root / 'DEEPSEEK.md').is_file())
        self.assertIn('Спектральная задача', (self.root / 'PROJECT.md').read_text(encoding='utf-8'))
        patch = json.loads((self.root / 'output/harness/cordis.patch.yml').read_text(encoding='utf-8'))
        # MCP servers, roles and one skill provider
        self.assertEqual(len(patch[0]['insert']), len(servers) + len(list(claude.glob('agents/*.md'))) + 1)

    def test_template_frontmatter_has_adapter_rules(self):
        harness = self.load_harness()
        self.assertEqual(harness.unported(create_project.TEMPLATE), [])

    def test_dry_update_preserves_every_byte(self):
        (self.root / 'scripts/host/harness.py').write_text('old adapter', encoding='utf-8')
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            create_project.update(self.root, True)
        self.assertEqual(self.snapshot(), before)

    def test_update_stops_on_a_project_skill_named_like_a_template_command(self):
        command = sorted((create_project.TEMPLATE / '.claude/commands').glob('*.md'))[0].stem
        skill = self.root / '.claude/skills' / command / 'SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text(f'---\nname: {command}\ndescription: Свой навык\n---\nТекст.\n', encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            create_project.update(self.root, True)
        self.assertIn(f'Навык проекта носит имя команды шаблона: {command}', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            create_project.update(self.root, False)
        self.assertIn(command, str(stopped.exception))
        self.assertTrue(skill.is_file())

    def test_upgrade_adds_deepseek_and_preserves_research_and_user_settings(self):
        owned = ('question.md', 'PROJECT.md', 'project.toml', 'paper/main.tex',
                 'results/R01.md', 'Spectra/Basic.lean', 'lean-toolchain', 'lake-manifest.json',
                 '.claude/settings.json')
        saved = {name: (self.root / name).read_bytes() for name in owned}
        mcp_file = self.root / '.mcp.json'
        mcp = json.loads(mcp_file.read_text(encoding='utf-8'))
        mcp['mcpServers']['lit']['args'].insert(0, '--offline')
        mcp_file.write_text(json.dumps(mcp), encoding='utf-8')
        saved['.mcp.json'] = mcp_file.read_bytes()
        (self.root / 'scripts/host/harness.py').unlink()
        (self.root / 'DEEPSEEK.md').unlink()
        (self.root / '.dsh/skills/day/SKILL.md').unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            create_project.update(self.root, False)
        self.assertEqual({name: (self.root / name).read_bytes() for name in saved}, saved)
        self.assertTrue((self.root / '.dsh/skills/day/SKILL.md').is_file())
        patch = json.loads((self.root / 'output/harness/cordis.patch.yml').read_text(encoding='utf-8'))
        lit = next(e for e in patch[0]['insert'] if e['id'] == 'research-mcp-lit')
        self.assertEqual(lit['config']['args'][0], '--offline')


if __name__ == '__main__':
    unittest.main()
