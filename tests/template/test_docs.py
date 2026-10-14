"""Согласованность документации с составом воркфлоу.

Документация называет команды, роли и пути словами. Тест читает её и сверяет с
фактическим составом `.claude/`: упомянутая команда должна существовать, каждый навык
должен быть назван, названный путь — существовать. Новых сущностей тест не закрепляет.

Инструкции проекта (`AGENTS.md`, `DEEPSEEK.md`, `README.md` шаблона) читаются в раскладке
созданного проекта: имена команд и ролей от неё не зависят, а пути к производным файлам
в наборе и в проекте лежат в разных местах.

    python -m unittest discover -s tests/template
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / 'template'
REPO = TEMPLATE.parent
sys.path.insert(0, str(TEMPLATE / 'scripts'))
sys.path.insert(0, str(TEMPLATE / 'scripts' / 'host'))
import harness  # noqa: E402

# Инструкции набора: адресованы тому, кто создаёт проект, поэтому лежат вне заготовки.
KIT_DOCS = (REPO / 'README.md', REPO / 'docs/guide.md')
# Инструкции проекта: создание копирует их в корень нового проекта.
PROJECT_DOCS = (TEMPLATE / 'README.md', TEMPLATE / 'AGENTS.md', TEMPLATE / 'DEEPSEEK.md')
# Появляются при работе: сводки собирает proj.py sync, каталог — sources/catalog.py, записи
# и опыты создают команды. Их в заготовке нет по замыслу.
GENERATED = {'blueprint.md', 'ideas/README.md', 'sources/catalog.md',
             'experiments/E01/run.py'}


class DocumentationMatchesWorkflow(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project = Path(self.folder.name) / 'project'
        self.project.mkdir()
        self.docs = {}
        # Путь ищут там, откуда его называют. Документ набора говорит и о наборе, и о том,
        # что получает проект; документ проекта — только о проекте (иначе он обещает то,
        # чего в проекте нет); роль или навык — о своей папке и о проекте.
        self.located: list[tuple[tuple[Path, ...], str]] = []
        for path in KIT_DOCS:
            self.docs[path.name] = path.read_text(encoding='utf-8')
            self.located.append(((REPO, TEMPLATE), self.docs[path.name]))
        for path in PROJECT_DOCS:
            self.docs[path.name] = path.read_text(encoding='utf-8')
            self.located.append(((TEMPLATE,), self.docs[path.name]))
        self.instructed = '\n'.join(self.docs.values())
        self.agents, self.skills = harness.sources(TEMPLATE)
        for path, _, body in list(self.agents.values()) + list(self.skills.values()):
            self.located.append(((path.parent, TEMPLATE), body))
        self.bodies = [body for _, body in self.located]

    def test_mentioned_commands_exist(self):
        """`/имя` в документации — команда, которая есть в составе воркфлоу."""
        for name, text in self.docs.items():
            for command in set(re.findall(r'`/([a-z][\w-]+)', text)):
                self.assertIn(command, self.skills, f'{name}: команды /{command} нет')

    def test_every_skill_is_named_somewhere(self):
        for name in self.skills:
            self.assertIn(name, self.instructed, f'навык `{name}` не упомянут в документации')

    def test_documented_paths_exist(self):
        """Путь, названный в инструкции, есть там, откуда его называют; маски имён не в счёт."""
        pattern = re.compile(r'(?<![\w/.-])((?:\.claude|\.dsh|\.github|scripts|tests|sources|results|ideas|'
                             r'experiments|paper)/[^`\s]*[\w./-])')
        for roots, body in self.located:
            for named in sorted(set(pattern.findall(body))):
                named = named.rstrip('.,;:')  # точка в конце фразы принадлежит фразе, а не пути
                if not named or named.endswith('/') or any(mark in named for mark in '*?[]…'):
                    continue  # папка, маска имён или многоточие вместо номера
                if named in GENERATED:
                    continue
                if any(part.isupper() for part in named.replace('.', '/').split('/')):
                    continue  # ЗАГЛАВНЫМИ пишут подстановку: `NAME` в таблице соответствия
                if not named.rsplit('/', 1)[-1].endswith(('.md', '.py', '.json', '.toml',
                                                          '.yml', '.mjs', '.lean', '.tex')):
                    continue
                where = ', '.join(str(root.relative_to(REPO)) or '.' for root in roots)
                self.assertTrue(any((root / named).exists() for root in roots),
                                f'нет пути `{named}` (искали в {where})')

    def test_commands_are_named_in_the_project_rules(self):
        """Состав команд проекта описан в AGENTS.md — инструкция читается агентом целиком."""
        for name in self.skills:
            if (TEMPLATE / '.claude/commands' / f'{name}.md').exists():
                self.assertIn(f'`/{name}', self.docs['AGENTS.md'], f'команда /{name} не описана в AGENTS.md')


if __name__ == '__main__':
    unittest.main()
