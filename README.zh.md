# AutoMath

[Русский](README.md) | [English](README.en.md) | [中文](README.zh.md)

[![CI](https://github.com/LeoLourson/AutoMath/actions/workflows/ci.yml/badge.svg)](https://github.com/LeoLourson/AutoMath/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](docs/howto/guide.md)

一套由 Claude Code 或 DeepSeek Harness 智能体主持的数学研究项目工具：问题设定、文献来源、
经过独立批评的想法、经过评审的证明、带一致性检验的 Lean 4 形式化，直到论文。套件不依赖
具体课题：所有与课题相关的内容都只存在于新项目的两个文件中 —— `question.md` 和 `PROJECT.md`。

工作流程和新用户可用的功能见 [docs/howto/guide.md](docs/howto/guide.md)（俄语）；套件本身的
构造见 [docs/concept/architecture.md](docs/concept/architecture.md)（俄语）。

## 新建项目

```
python tools/create.py ..\Spectra --lib Spectra --title "课题名称"
cd ..\Spectra
lake exe cache get
lake build
python scripts/state/proj.py doctor
python scripts/state/proj.py check
python scripts/host/harness.py run web
```

`--lib` 是 Lean 库和命名空间的名称。Lean 和 Mathlib 的版本取自模板；`--pins-from 项目` 参数
则取自一个正在使用的项目。后续步骤见所建项目的 `README.md`。

DeepSeek Harness 需要 Node.js 22.19+（22 分支）或 24+ 以及 npm。启动命令会准备原生 skills、
角色和 MCP，然后打开固定版本的 Harness。模型和密钥在 Harness 中设置。细节、headless 模式和
检查项见 [template/DEEPSEEK.md](template/DEEPSEEK.md)（俄语）。Claude Code 支持保持不变。

## 更新项目中的工具

```
python tools/create.py --update ..\Spectra --dry-run
python tools/create.py --update ..\Spectra
```

更新只重写模板拥有的内容：`AGENTS.md`、`CLAUDE.md`、`scripts/`、`tests/`、`.claude/agents/`、
`.claude/commands/`、`.claude/skills/`、`DEEPSEEK.md`、`sources/README.md`、
`experiments/README.md`、CI。问题设定、记录、想法、来源、Lean 库、论文、`.mcp.json` 和
`.claude/settings.json` 不会被改动。模板中已不存在的文件会被列出，但不会删除。如果项目中
存在与模板命令同名的 skill，更新会停止并指出需要删除的 `.claude/skills/名称/` 目录：命令和
skill 共用一个命名空间。

更新之后，会根据最新的指令和本地 `.mcp.json` 重新构建派生的 `.dsh/skills/` 和 Harness 的
Cordis patch。`--dry-run` 不写任何内容。

## 修改工作流

命令、角色和 skill 只在一处修改 —— `template/.claude/`；MCP 服务器在 `template/.mcp.json`。
DeepSeek Harness 支持由这些文件构建：`template/scripts/host/harness.py` 不包含命令和角色名，
测试从相同的目录取得预期清单，文档引用 `python scripts/host/harness.py list`。修改工作流之后
运行检查：

```
python -m unittest discover -s tests/template
python -m unittest discover -s tests/kit
python template/scripts/host/harness.py --root template list
```

对应关系表，以及适配器仍需修改的三种情况（无规则的头字段、新的 Claude Code 内置工具、新的
Harness 版本），见 [template/DEEPSEEK.md](template/DEEPSEEK.md) 的"Claude Code 工作流如何迁移"
一节。工作流的构成在 `template/AGENTS.md` 中描述；它也会进入所建的项目，因此本文件和指南都
不再重复它。

## 套件的结构

| 层 | 位置 | 内容 |
| --- | --- | --- |
| 产品 | `template/` | 项目底稿；创建项目时整体复制，并替换库名和标题 |
| 套件 | `tools/` | `create.py` —— 创建与更新项目；`tests/kit/` 在无网络、无 Lean 的条件下检查它 |
| 产品检查 | `tests/template/` | 项目工具、Harness 适配器、文档一致性 |
| 说明 | `docs/`、`README.md` | 用户指南、架构、本页面 |

这个划分按用途而不是按文件类型：所有复制进项目的内容完整地放在 `template/` 中，所有描述和
检查复制过程的内容都在它之外。因此 `PROJECT.md`、`question.md` 和其余底稿文件不会出现在两个
地方。完整分析见 [docs/concept/architecture.md](docs/concept/architecture.md)（俄语）。

## 环境要求

Python 3.11 或更新版本、`uv`、`elan`（含 `lake`）、`git`；`pdflatex` —— 用于论文和转录检查。
`.mcp.json` 中的 MCP 服务器通过 `uv` 启动并自行安装依赖。

## 包含的内容

| 部分 | 内容 |
| --- | --- |
| `template/AGENTS.md` | 通用规则：项目地图、状态、智能体角色、检查项 |
| `template/scripts/state/proj.py` | 记录底稿、头字段、摘要、检查、公理审计、陈述指纹、论文构建、Aristotle 包 |
| `template/scripts/records.py` | 为 `proj.py` 和 `lit.py` 提供的统一带头记录解析：读取、写入、编号、底稿 |
| `template/scripts/sources/lit.py` | 来源：zbMATH、arXiv、MathNet、DOI；转录；全文混合检索 |
| `template/scripts/state/mcp.py` 与 `scripts/sources/mcp.py` | 同样的操作，作为 MCP 服务器 `proj` 和 `lit` |
| `template/scripts/host/harness.py` | DeepSeek Harness：由 `.claude/` 和 `.mcp.json` 生成 skills、角色和 MCP，Cordis patch，Web/Headless 启动 |
| `template/DEEPSEEK.md` | Harness 启动、Claude Code 工作流的迁移、检查项 |
| `template/.claude/agents/` | 想法生成器、批评者、实验者、评审、形式化者、一致性检查、Mathlib 检索、文献检索、PDF 转录、卡片核对 |
| `template/.claude/commands/` | `/day`、`/ideas`、`/referee`、`/formalize`、`/fidelity`、`/sources`、`/transcribe`、`/exposition` |
| `template/.claude/skills/` | 数学文本的层次：内容 —— `math-rigor`，结构 —— `paper-canvas`，作者风格 —— `shkalikov-style`，语言 —— `paper-de-ai`，排版 —— `math-typeset` |
| `tests/template/` | 无网络、无 Lean 的工具测试；`harness_runtime.mjs` 将 patch 与 Harness 模式核对 |
| `tests/kit/` | 项目创建与更新的测试 |

## 参与与许可

贡献规则和发布流程见 [CONTRIBUTING.md](CONTRIBUTING.md)；漏洞通过 [SECURITY.md](SECURITY.md)
报告。代码以 MIT 许可证发布，见 [LICENSE](LICENSE)。学术引用见 [CITATION.cff](CITATION.cff)，
版本历史见 [CHANGELOG.md](CHANGELOG.md)。
