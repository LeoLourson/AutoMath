# AutoMath

[Русский](README.md) | [English](README.en.md) | [中文](README.zh.md)

[![CI](https://github.com/LeoLourson/AutoMath/actions/workflows/ci.yml/badge.svg)](https://github.com/LeoLourson/AutoMath/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](docs/howto/guide.md)

A kit for a research project carried by Claude Code or DeepSeek Harness agents: the problem
statement, sources, ideas with independent critique, proofs with refereeing, formalization in
Lean 4 with fidelity checks, and a paper. The kit does not depend on the topic: everything
topical lives in two files of a new project, `question.md` and `PROJECT.md`.

The working order and what a new user can do — in [docs/howto/guide.md](docs/howto/guide.md)
(Russian). How the kit itself is built — in
[docs/concept/architecture.md](docs/concept/architecture.md) (Russian).

## New project

```
python tools/create.py ..\Spectra --lib Spectra --title "Topic title"
cd ..\Spectra
lake exe cache get
lake build
python scripts/state/proj.py doctor
python scripts/state/proj.py check
python scripts/host/harness.py run web
```

`--lib` is the Lean library and namespace name. The Lean and Mathlib versions come from the
template; the `--pins-from PROJECT` key takes them from a working project. The next steps are in
the `README.md` of the created project.

DeepSeek Harness needs Node.js 22.19+ (the 22 branch) or 24+ and npm. The launch command prepares
the native skills, the roles, and MCP, then opens the Harness at a pinned version. The model and
the key are configured in the Harness. Details, headless mode, and checks —
[template/DEEPSEEK.md](template/DEEPSEEK.md) (Russian). Claude Code support stays.

## Updating the tools in a project

```
python tools/create.py --update ..\Spectra --dry-run
python tools/create.py --update ..\Spectra
```

The update rewrites only what the template owns: `AGENTS.md`, `CLAUDE.md`, `scripts/`, `tests/`,
`.claude/agents/`, `.claude/commands/`, `.claude/skills/`, `DEEPSEEK.md`, `sources/README.md`,
`experiments/README.md`, CI. The problem statement, records, ideas, sources, the Lean library,
the paper, `.mcp.json`, and `.claude/settings.json` are not touched. Files that are no longer in
the template are listed, not deleted. If the project has a skill named like a template command,
the update stops and names the `.claude/skills/NAME/` folder to delete: commands and skills share
one namespace.

After the update the derived `.dsh/skills/` and the Cordis patch for the Harness are rebuilt from
the current instructions and the local `.mcp.json`. `--dry-run` writes nothing.

## Changing the workflow

Commands, roles, and skills are edited in one place — `template/.claude/`; the MCP servers — in
`template/.mcp.json`. The DeepSeek Harness support is built from these files:
`template/scripts/host/harness.py` holds no command or role names, the tests take the expected
set from the same folders, and the docs refer to `python scripts/host/harness.py list`. After
editing the workflow, run the checks:

```
python -m unittest discover -s tests/template
python -m unittest discover -s tests/kit
python template/scripts/host/harness.py --root template list
```

The mapping table and the three cases where the adapter still has to be edited (a header field
without a rule, a new built-in Claude Code tool, a new Harness version) are in the "How the
Claude Code workflow is carried over" section of [template/DEEPSEEK.md](template/DEEPSEEK.md).
The workflow set is described in `template/AGENTS.md`; it lands in the created project too, so
neither this file nor the guide duplicates it.

## How the kit is built

| Layer | Where | What it is |
| --- | --- | --- |
| Product | `template/` | the project stub; creating a project copies it whole, substituting the library name and the title |
| Kit | `tools/` | `create.py` — creating and updating a project; `tests/kit/` checks it without the network and Lean |
| Product checks | `tests/template/` | the project tools, the Harness adapter, the consistency of the documentation |
| Description | `docs/`, `README.md` | the user guide, the architecture, this page |

The division is by purpose, not by file type: everything copied into a project lies whole in
`template/`, and everything that describes and checks the copying lies outside it. So `PROJECT.md`,
`question.md`, and the other stub files never appear in two places. The full analysis — in
[docs/concept/architecture.md](docs/concept/architecture.md) (Russian).

## Requirements

Python 3.11 or newer, `uv`, `elan` with `lake`, `git`; `pdflatex` — for the paper and the
transcription checks. The MCP servers from `.mcp.json` are launched through `uv` and install
their dependencies themselves.

## What is inside

| Part | Contents |
| --- | --- |
| `template/AGENTS.md` | the common rules: the project map, statuses, agent roles, checks |
| `template/scripts/state/proj.py` | record stubs, header fields, summaries, checks, the axiom audit, statement fingerprints, the paper build, the Aristotle packages |
| `template/scripts/records.py` | one parser of headered records for `proj.py` and `lit.py`: reading, writing, numbering, stubs |
| `template/scripts/sources/lit.py` | sources: zbMATH, arXiv, MathNet, DOI; transcriptions; hybrid search over full texts |
| `template/scripts/state/mcp.py` and `scripts/sources/mcp.py` | the same actions as the MCP servers `proj` and `lit` |
| `template/scripts/host/harness.py` | DeepSeek Harness: skills, roles and MCP from `.claude/` and `.mcp.json`, the Cordis patch, Web/Headless launch |
| `template/DEEPSEEK.md` | running the Harness, carrying over the Claude Code workflow, checks |
| `template/.claude/agents/` | idea generator, critic, experimenter, referee, formalizer, fidelity checker, Mathlib scout, literature scout, PDF transcriber, card verifier |
| `template/.claude/commands/` | `/day`, `/ideas`, `/referee`, `/formalize`, `/fidelity`, `/sources`, `/transcribe`, `/exposition` |
| `template/.claude/skills/` | the layers of a mathematical text: content — `math-rigor`, composition — `paper-canvas`, the author's style — `shkalikov-style`, language — `paper-de-ai`, typesetting — `math-typeset` |
| `tests/template/` | tests of the tools without the network and Lean; `harness_runtime.mjs` checks the patch against the Harness schemas |
| `tests/kit/` | tests of creating and updating a project |

## Contributing and license

Contributing rules and the release process are in [CONTRIBUTING.md](CONTRIBUTING.md);
vulnerabilities go through [SECURITY.md](SECURITY.md). The code is MIT-licensed, see
[LICENSE](LICENSE). Citations are described in [CITATION.cff](CITATION.cff), the version
history — in [CHANGELOG.md](CHANGELOG.md).
