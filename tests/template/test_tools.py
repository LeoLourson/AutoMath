"""Тесты инструментов проекта. Сеть, Lean и модель поиска не нужны.

    python -m unittest discover -s tests/template

Обе группы работают на временном каталоге, поэтому состояние модулей задаёт
единственная точка настройки — `_as_template()`.
"""
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / 'template'
sys.path.insert(0, str(TEMPLATE / 'scripts'))
import records  # noqa: E402
from check import declarations as leandecl  # noqa: E402
from check import hygiene  # noqa: E402
from check import results as checks  # noqa: E402
from sources import lit  # noqa: E402
from state import proj  # noqa: E402


def _as_template() -> Path:
    """Настраивает proj и lit на каталог шаблона."""
    proj.configure(TEMPLATE)
    lit.configure(TEMPLATE)
    return TEMPLATE

LEAN = '''module

public import Mathlib.Basic.Real.Basic

/-! # Пример: theorem в комментарии не считается -/

public section

namespace Demo

/-- Чётность. В тексте есть слово sorry, но это комментарий. -/
def IsEvenFn (f : ℝ → ℝ) : Prop := ∀ x, f (-x) = f x

structure Pair where
  left : ℝ
  right : ℝ

section Local

variable (c : ℝ)

@[simp]
theorem scaled_even (f : ℝ → ℝ) (h : IsEvenFn f) :
    IsEvenFn (fun x => c * f x) := by
  intro x
  simp [h x]

end Local

open Function in
theorem const_even (c : ℝ) : IsEvenFn (fun _ => c) := fun _ => rfl

def swap : Pair → Pair
  | ⟨a, b⟩ => ⟨b, a⟩

end Demo
'''


class LeanDeclarations(unittest.TestCase):
    def setUp(self):
        self.decls = {decl.name: decl for decl in leandecl.parse(LEAN, 'Demo/Basic.lean')}

    def test_names_and_kinds(self):
        self.assertEqual(sorted(self.decls), ['Demo.IsEvenFn', 'Demo.Pair', 'Demo.const_even', 'Demo.scaled_even',
                                              'Demo.swap'])
        self.assertEqual(self.decls['Demo.Pair'].kind, 'structure')

    def test_statement_stops_before_proof(self):
        self.assertEqual(self.decls['Demo.scaled_even'].statement,
                         'theorem scaled_even (f : ℝ → ℝ) (h : IsEvenFn f) : IsEvenFn (fun x => c * f x)')
        self.assertEqual(self.decls['Demo.const_even'].statement,
                         'theorem const_even (c : ℝ) : IsEvenFn (fun _ => c)')

    def test_variables_follow_sections(self):
        self.assertEqual(self.decls['Demo.scaled_even'].variables, ['variable (c : ℝ)'])
        self.assertEqual(self.decls['Demo.const_even'].variables, [])

    def test_fingerprint_tracks_statement_and_definitions(self):
        index = self.decls
        base, used = leandecl.fingerprint(index, 'Demo.scaled_even')
        self.assertEqual(used, ['Demo.IsEvenFn'])
        proof = {d.name: d for d in leandecl.parse(LEAN.replace('simp [h x]', 'simpa using h x'))}
        self.assertEqual(leandecl.fingerprint(proof, 'Demo.scaled_even')[0], base)
        redefined = {d.name: d for d in leandecl.parse(LEAN.replace('f (-x) = f x', 'f (-x) = -f x'))}
        self.assertNotEqual(leandecl.fingerprint(redefined, 'Demo.scaled_even')[0], base)
        variable = {d.name: d for d in leandecl.parse(LEAN.replace('variable (c : ℝ)', 'variable (c : ℚ)'))}
        self.assertNotEqual(leandecl.fingerprint(variable, 'Demo.scaled_even')[0], base)
        unrelated = {d.name: d for d in leandecl.parse(LEAN.replace('⟨b, a⟩', '⟨a, b⟩'))}
        self.assertEqual(leandecl.fingerprint(unrelated, 'Demo.scaled_even')[0], base)

    def test_resolve_by_tail(self):
        self.assertEqual(leandecl.resolve(self.decls, 'const_even').name, 'Demo.const_even')
        self.assertIsNone(leandecl.resolve(self.decls, 'missing'))

    def test_compare_with_skeleton(self):
        skeleton = 'theorem a (x : Nat) : x = x := by\n  sorry\n\ntheorem b : 1 = 1 := by\n  sorry\n'
        answer = ('theorem helper : True := trivial\n\ntheorem a (x : Nat) : x = x := rfl\n\n'
                  'theorem b : 1 + 0 = 1 := by\n  sorry\n')
        report = leandecl.compare(skeleton, answer)
        self.assertEqual(report, {'changed': ['b'], 'missing': [], 'added': ['helper'], 'sorry': ['b']})


class ProjectRecords(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        (root / 'project.toml').write_text('[project]\nlib = "Demo"\n', encoding='utf-8')
        (root / 'Demo').mkdir()
        (root / 'Demo' / 'Basic.lean').write_text(LEAN, encoding='utf-8')
        (root / 'Demo.lean').write_text('import Demo.Basic\n', encoding='utf-8')
        proj.configure(root)
        self.root = root
        self.index = leandecl.library(root, 'Demo')

    def tearDown(self):
        self.folder.cleanup()
        _as_template()

    def test_new_numbers_and_front_matter(self):
        first = proj.new('result', 'Первая: с двоеточием')
        second = proj.new('result', 'Вторая', depends='R01')
        self.assertEqual((first.name, second.name), ('R01.md', 'R02.md'))
        doc = records.read_doc(second)
        self.assertEqual((doc.meta['id'], doc.meta['status'], doc.meta['depends']), ('R02', 'цель', ['R01']))
        self.assertEqual(records.read_doc(first).meta['title'], 'Первая: с двоеточием')
        proj.set_field('R02', 'lean', 'Demo.const_even, Demo.scaled_even')
        self.assertEqual(proj.find_doc('R02').meta['lean'], ['Demo.const_even', 'Demo.scaled_even'])
        with self.assertRaises(SystemExit):
            proj.set_field('R02', 'status', 'почти доказано')

    def test_record_checks(self):
        proj.new('result', 'Опора')
        proj.new('result', 'Следствие', depends='R01, R07')
        proj.set_field('R01', 'depends', 'R02')
        proj.set_field('R02', 'lean', 'Demo.const_even, Demo.absent')
        proj.set_field('R02', 'sources', 'S3')
        errors, _ = checks.check_records(self.root, proj.docs('results', 'R'), {'S1'}, set(), self.index)
        text = '\n'.join(errors)
        for expected in ('несуществующей записи R07', 'цикл зависимостей', 'Demo.absent нет в библиотеке',
                         'источника S3 нет'):
            self.assertIn(expected, text)

    def test_fidelity_goes_stale(self):
        proj.new('result', 'Чётность постоянной')
        proj.set_field('R01', 'lean', 'Demo.const_even')
        _, warnings = checks.check_records(self.root, proj.docs('results', 'R'), set(), set(), self.index)
        self.assertIn('соответствие формализации не проверено', '\n'.join(warnings))
        mark = leandecl.record_fingerprint(self.index, ['Demo.const_even'])
        proj.set_field('R01', 'fidelity', f'2026-01-01 соответствует {mark}')
        _, warnings = checks.check_records(self.root, proj.docs('results', 'R'), set(), set(), self.index)
        self.assertEqual(warnings, [])
        changed = {d.name: d for d in leandecl.parse(LEAN.replace('f (-x) = f x', 'f (-x) = -f x'))}
        _, warnings = checks.check_records(self.root, proj.docs('results', 'R'), set(), set(), changed)
        self.assertIn('изменились после проверки соответствия', '\n'.join(warnings))

    def test_views_are_built_from_headers(self):
        proj.new('result', 'Опора')
        proj.new('result', 'Следствие', depends='R01')
        proj.new('idea', 'Попробовать индукцию', target='R02')
        views = proj.views(proj.docs('results', 'R'), proj.docs('ideas', 'I'), self.index)
        self.assertIn('| [R02](results/R02.md) | Следствие | цель |', views['blueprint.md'])
        self.assertIn('R01 --> R02', views['blueprint.md'])
        self.assertIn('| `Demo/Basic.lean` | Пример: theorem в комментарии не считается', views['blueprint.md'])
        self.assertIn('| [I01](I01.md) | Попробовать индукцию | R02 | новая |', views['ideas/README.md'])

    def test_hygiene_ignores_comments(self):
        errors, _ = hygiene.check_hygiene(self.root, 'Demo')
        self.assertEqual(errors, [])
        path = self.root / 'Demo' / 'Basic.lean'
        path.write_text(LEAN.replace('fun _ => rfl', 'by sorry'), encoding='utf-8')
        errors, _ = hygiene.check_hygiene(self.root, 'Demo')
        self.assertEqual(len(errors), 1)
        self.assertIn('sorry', errors[0])


class Sources(unittest.TestCase):
    def test_configure_points_paths_at_the_project(self):
        """Пути источников выводятся из корня, а не из места установки скрипта."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'project.toml').write_text('[project]\nlib = "Demo"\n[sources]\ndirect_hosts = ["example.org"]\n',
                                               encoding='utf-8')
            (root / 'sources' / 'cards').mkdir(parents=True)
            (root / 'sources' / 'papers.json').write_text('[]', encoding='utf-8')
            records.card_for(root, 'S7', 'Теорема о базисах')
            try:
                lit.configure(root)
                self.assertEqual(lit.REGISTRY, root / 'sources' / 'papers.json')
                self.assertEqual(lit.DB, root / 'output' / 'literature' / 'index' / 'lit.sqlite')
                self.assertEqual(lit.DIRECT_HOSTS, ['example.org'])
                self.assertEqual(lit.cards(), {'S7'})
            finally:
                _as_template()

    def test_identifiers(self):
        cases = {
            '2107.12209v2': ('arxiv', '2107.12209v2'),
            'arXiv:math/0601001': ('arxiv', 'math/0601001'),
            'https://arxiv.org/abs/0906.2631v1': ('arxiv', '0906.2631v1'),
            'mathnet:rm9740': ('mathnet', 'rm9740'),
            'https://www.mathnet.ru/rus/mzm12557': ('mathnet', 'mzm12557'),
            'https://www.mathnet.ru/php/archive.phtml?wshow=paper&jrnid=sm&paperid=1167': ('mathnet', 'sm1167'),
            '10.4213/rm9740': ('mathnet', 'rm9740'),
            'https://doi.org/10.1070/RM9740': ('doi', '10.1070/RM9740'),
            '10.48550/arXiv.2107.12209': ('arxiv', '2107.12209'),
        }
        for given, expected in cases.items():
            self.assertEqual(lit.classify(given), expected, given)
        with self.assertRaises(ValueError):
            lit.classify('теорема Маркуса')

    def test_amsbib(self):
        page = ('<div class=showamsbib><code>\\RBibitem{Shk16}<br />\n\\by А.~А.~Шкаликов<br />\n'
                '\\paper Возмущения операторов с~дискретным спектром<br />\n\\jour УМН<br />\n\\yr 2016<br />\n'
                '\\vol 71<br />\n\\issue 5(431)<br />\n\\pages 113--174<br />\n'
                '\\crossref{https://doi.org/10.4213/rm9740}<br />\n\\transl<br />\n\\jour Russian Math. Surveys<br />\n'
                '\\pages 907--964<br />\n\\crossref{https://doi.org/10.1070/RM9740}<br />\n</code></div>')
        fields = lit.amsbib(page)
        self.assertEqual(fields['by'], 'А. А. Шкаликов')
        self.assertEqual(fields['paper'], 'Возмущения операторов с дискретным спектром')
        self.assertEqual((fields['pages'], fields['pages_en']), ('113–174', '907–964'))
        self.assertEqual(fields['crossref_en'], 'https://doi.org/10.1070/RM9740')

    def test_flatten_inlines_inputs_and_bibliography(self):
        files = {
            'main.tex': b'\\documentclass{article}\n\\begin{document}\n% note\n\\input{sec/one}\n'
                        b'\\bibliography{refs}\n\\end{document}\n',
            'sec/one.tex': b'First section. % trailing\n',
            'main.bbl': b'\\begin{thebibliography}{1}\\bibitem{a} A.\\end{thebibliography}\n',
        }
        text = lit.flatten(files)
        self.assertIn('First section.', text)
        self.assertNotIn('note', text)
        self.assertNotIn('trailing', text)
        self.assertIn('\\bibitem{a}', text)

    def test_chunks_keep_printed_numbers_and_pages(self):
        text = (lit.PREAMBLE + '\\begin{document}\n\\section{Базисы}\n\\pagemark{140}\n'
                '\\begin{statement}{Теорема}{6.6}\nПусть $T$ --- нормальный оператор порядка $\\alpha$. '
                'Тогда корневые векторы образуют безусловный базис со скобками.\n\\end{statement}\n\n'
                '\\begin{proof}\nДостаточно оценить резольвенту вне углов, содержащих лучи спектра.\n\\end{proof}\n'
                '\\pagemark{141}\nЗамечание 6.7. Условие на порядок нельзя ослабить, как показывает пример '
                'оператора умножения.\n\\end{document}\n')
        chunks = lit.tex_chunks(text)
        self.assertEqual([(c['kind'], c['label'], c['page']) for c in chunks],
                         [('Theorem', 'Теорема 6.6', '140'), ('Proof', '', '140'), ('Remark', 'Замечание 6.7', '141')])
        self.assertEqual(chunks[0]['section'], 'Базисы')

    def test_lint_reports_mechanical_problems(self):
        text = (lit.PREAMBLE + '\\begin{document}\n\\pagemark{1}\n\\begin{statement}{Лемма}{1}\n$a_{n$\n'
                '\\unsure{x}\n\\end{document}\n')
        notes = '\n'.join(lit.lint_tex(text, pages=2))
        for expected in ('statement', 'фигурные скобки', 'меток \\pagemark: 1, страниц в PDF: 2', '(\\unsure): 1'):
            self.assertIn(expected, notes)
        clean = lit.PREAMBLE + '\\begin{document}\n\\pagemark{1}\nТекст.\n\\end{document}\n'
        self.assertEqual(lit.lint_tex(clean, pages=1), [])

    def test_text_layer_headings_start_chunks(self):
        page = ('Введение, в котором нет утверждений, но есть достаточно длинный текст для отдельного куска.\n'
                'Theorem 4.1. Let $a$ be even. Then the eigenfunctions form a Riesz basis in $L_2(-1,1)$.\n')
        chunks = lit.txt_chunks(page)
        self.assertEqual([(c['kind'], c['label'], c['loc']) for c in chunks],
                         [('page', '', 1), ('Theorem', 'Theorem 4.1', 1)])


if __name__ == '__main__':
    unittest.main()
