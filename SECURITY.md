# Security policy

## Supported versions

The latest release receives fixes. Versions before 0.1.0 are not supported.

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Use GitHub private reporting: **Security** tab → **Report a vulnerability**. Do not open a public
issue for an unfixed vulnerability.

Include the version, the platform, a minimal reproduction, and what an attacker gains. You will
get an answer within a week; a fix and a release follow when the report is valid.

## Scope

AutoMath runs locally: it copies a template, runs Python scripts, and drives coding agents. Its
attack surface:

- **Untrusted documents.** The source pipeline downloads pages and PDFs from zbMATH, arXiv,
  MathNet, DOI resolvers, and arbitrary web pages named by the user or the agent, and the
  transcription commands parse those PDFs into text and LaTeX. A hostile document is data: the
  parsers must not execute it, and the agents must not follow instructions found inside it as if
  they were the user's.
- **Generated code runs with your rights.** The created project's scripts, experiments, and the
  Harness launch all execute locally without a sandbox; an agent instructed by a poisoned
  source can write files in the project. Review `/transcribe` and experiment outputs before
  running them.
- **Secrets.** Model API keys and MCP credentials live in the Harness settings and the MCP
  client configuration, never in the repository. They must not be written to `question.md`,
  `PROJECT.md`, source cards, summaries, or logs.
- **The Harness adapter.** `harness.py` prepares native skills and a Cordis patch from
  `.claude/` and `.mcp.json` and runs a pinned Harness version through npm. It never sends the
  project anywhere on its own.

Out of scope: vulnerabilities in Claude Code, in the DeepSeek Harness itself, in upstream
sources, and in the Lean toolchain or Mathlib; reports that a proof is wrong or a fidelity check
missed an error (open a regular issue with the project and the command).
