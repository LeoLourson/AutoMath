# Contributing

Issues and pull requests are welcome. Small fixes can go straight to a pull request; for a new
command, agent role, or skill layer, open an issue first so the workflow stays coherent.

## Setup

Python 3.11 or newer is enough for the checks; `uv`, `elan` with `lake`, and `pdflatex` matter
only when you touch the Lean or LaTeX parts of the template. The tests need neither the network
nor Lean:

```powershell
python -X utf8 -m unittest discover -s tests/template
python -X utf8 -m unittest discover -s tests/kit
python template/scripts/host/harness.py --root template list
```

The Harness contract check compiles the adapter output against the Harness schemas; CI runs it
with Node 24.

## Layout

`template/` is the product: a project stub that `tools/create.py` copies whole, substituting the
Lean library name and the title. `tools/` and `tests/kit/` create and update projects without the
network or Lean. `tests/template/` checks the project scripts, the Harness adapter, and the
consistency of the documentation with the actual `.claude/` contents. `docs/` explains the kit to
its user and reader; each concern has its own folder, see [docs/README.md](docs/README.md). The
division is by purpose, not by file type — the reasoning is in
[docs/concept/architecture.md](docs/concept/architecture.md).

## Style

- The template scripts stay on the standard library; the source and MCP scripts may add
  dependencies because `uv` installs them per script.
- Tests never reach the network and never call `lake`: sources are mocked, documents are
  generated from known parameters.
- A change to the workflow is made in one place — `template/.claude/` and `template/.mcp.json`.
  `template/scripts/host/harness.py` must not learn command or role names; the docs name them,
  and the tests take the expected set from the same folders.
- Russian is the language of the docs, comments, and commit subjects; code identifiers, tool
  names, and the commit type prefixes are in English.
- Every documented `/command` and every named path must exist — `tests/template/test_docs.py`
  enforces it.

## Commits and pull requests

Write the subject as `type: description` (`docs:`, `fix:`, `chore:`, `test:`, `ci:`) in the
imperative and explain the reason in the body when it is not obvious. Keep one topic per commit:
a fix, a feature, and a docs update are three commits.

Before opening a pull request, run the three checks from Setup and confirm that CI stays green.
A pull request that changes a command, an agent, a script, or the layout updates `docs/` and adds
an entry under `Unreleased` in `CHANGELOG.md`.

## Releasing

1. Move the `Unreleased` entries in `CHANGELOG.md` under the new version and set the date.
2. Set the same `version` and `date-released` in `CITATION.cff`.
3. Commit, tag `vX.Y.Z`, and push the tag.
4. Publish a GitHub release from the tag, with the changelog section as the body.

There is no package to publish: the version exists so that issues, projects created from the
template, and citations can name a state of the tools.

## License

Contributions are accepted under the MIT license in [LICENSE](LICENSE).
