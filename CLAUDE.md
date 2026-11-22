# CLAUDE.md

Instructions for AI coding agents **developing** projectViewer. Humans: see [CONTRIBUTING.md](CONTRIBUTING.md).

> **Asked to *use* projectViewer for another project?** This file isn't for that. Follow [plugin/skills/setup/SKILL.md](plugin/skills/setup/SKILL.md), then [plugin/skills/use/SKILL.md](plugin/skills/use/SKILL.md). projectViewer maps Python projects only.

## Things that must stay true (tests enforce them)

- **The hook can never block Claude:** every hook command (plugin and `setup --hook`) ends in `>/dev/null 2>&1 || true`; `hook.py` always exits 0.
- **Users' settings are merged, never replaced;** broken settings files are refused and left untouched.
- **Recording prompt text is opt-in** (`--prompts`), never a default.
- **The shipped viewer (`src/projectviewer/web`) matches `viewer/` source;** rebuild with `npm run build` in `viewer/` and commit the result (CI checks it).
- **The plugin's name matches its marketplace entry.**

## What this is

**projectViewer:** a local tool that turns a codebase into an explorable map, shows the impact of every change, and records how the code is built (AI vs human, with prompts). Keep scope tight: small, well-tested steps.

**Explain the why, what, how and where** of new concepts and decisions, not just the code. The docs double as a learning record.

**This repository is public.** Never put details of the projects it is used on into code, tests, docs or commit messages. Use made-up fixture projects (shops, libraries, etc.) in tests and examples.

Read before non-trivial work: [docs/roadmap.md](docs/roadmap.md), [docs/project-status.md](docs/project-status.md), [docs/decisions/](docs/decisions/).

## Design rules

1. **Recording is deterministic, never an LLM.** Events come from the git reflog, a file watcher and Claude Code hooks. LLMs may only *summarise* recorded facts. ([ADR-0001](docs/decisions/0001-local-subscription-service.md))
2. **Never slow down or break the developer.** Hooks must be tiny, use short timeouts, and fail silently when the service is down.
3. **Honest links.** Every edge carries a `certainty` (`proven`, `inferred`, `pattern`). Never present a guess as fact. ([ADR-0002](docs/decisions/0002-world-format.md))
4. **Incremental and cached.** Analyse a file only when its content changes. ([ADR-0003](docs/decisions/0003-incremental-cached-analysis.md))
5. **Local only.** Nothing leaves the machine. Prompts and code stay local.
6. **Language-neutral format, pluggable analysers.** Python first.

## Workflow rules for agents

- Follow [CONTRIBUTING.md](CONTRIBUTING.md). Never commit to `main`; use `<type>/<short-description>` branches.
- Bug fixes are test-first. Measure, don't guess.
- Ask the owner before pushing, opening or merging PRs, or changing GitHub settings.
- Documentation duty every session: devlog entry, ADR for significant decisions, status update.

## Layout

| Path | Purpose |
|---|---|
| `src/projectviewer/cli.py` | `projectviewer` command line |
| `src/projectviewer/cache.py` | Content-addressed cache of per-file analysis results |
| `src/projectviewer/analyzers/python/extract.py` | Pass 1: facts from ONE file (pure, cacheable) |
| `src/projectviewer/analyzers/python/resolve.py` | Pass 2: link facts across files into a world (nodes + edges) |
| `tests/` | pytest; small fixture projects built in `tmp_path` |

## Commands

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run projectviewer map <repo> -o out.world.json
```
