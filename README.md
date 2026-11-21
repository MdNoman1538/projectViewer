# projectViewer

A live, explorable map of a codebase that records how it is being built, by you and by AI.

- **See the architecture.** Packages, files, classes and functions as a map, with the links between them: calls, API endpoints, database tables, tests.
- **See the impact of any change.** For a commit, a PR or an AI session: what changed (red) and what it affects (orange). A text diff only shows the red part.
- **See how it was built.** A timeline you can replay. Every change is marked as AI or human, and keeps the prompt that caused it.

It runs **locally** as a small background service. Projects *subscribe*; nothing is sent anywhere else.

> Successor of PR World v5, which was a demo where AI agents built a simulated bank and an AI reviewer judged each PR. projectViewer drops the simulation and the AI reviewer and works on your real projects. Background: [docs/decisions/](docs/decisions/).

## Status

Early development. See [docs/roadmap.md](docs/roadmap.md) and [docs/project-status.md](docs/project-status.md).

## Use

**Live viewer** for all your projects (updates as you, or an AI, edit code):

```bash
(cd viewer && npm ci && npm run build)            # once
uv run projectviewer add path/to/project-a        # subscribe projects (stored in ~/.config/projectviewer)
uv run projectviewer add path/to/project-b
uv run projectviewer serve --open                 # http://127.0.0.1:8765
```

- **The map:** your folders as blocks, one level at a time. Size and height = number of functions; the roof shows what's inside. Click to select, click again to go in; Backspace goes up.
- **Lenses:** Architecture, Tests (share of functions reached by tests, including over HTTP), Data (tables), API (endpoints).
- **Changes:**
  - **Live: uncommitted changes** lights up what is being changed (red), moved (purple) and affected (orange) as files are saved
  - any **commit** shows the same, plus its message and per-symbol **change notes**
  - **▶ Show** walks through the changes one by one, with each diff
- **Several projects:** a project switcher, and **follow activity** shows whichever project is changing.
- **Inside VS Code:** run *Simple Browser: Show* and enter `http://127.0.0.1:8765`.

**Watch the AI work (Claude Code):** add a hook to `~/.claude/settings.json` (all projects). Use the full path to `projectviewer` (e.g. `~/Projects/projectViewer/.venv/bin/projectviewer`):

```json
{ "hooks": {
  "PostToolUse":      [{ "matcher": "Edit|Write|MultiEdit", "hooks": [{ "type": "command", "command": "/path/to/projectviewer hook", "timeout": 5 }] }],
  "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "/path/to/projectviewer hook", "timeout": 5 }] }],
  "Stop":             [{ "hooks": [{ "type": "command", "command": "/path/to/projectviewer hook", "timeout": 5 }] }]
} }
```

The viewer then shows an **AI activity** feed, and with **follow** on it flies to each file the AI edits, with the live changes in red. The hook never blocks or slows Claude: about 0.1 s, it ignores errors, and always exits 0. Prompt text is sent only with `hook --prompts`, and stays on your machine.

**Change notes:** add a `Changes:` section to commit messages; the viewer attaches each line to the code it names:

```
fix(tax): new VAT rate

Changes:
- shop/tax.py::rate: changed. Returns the new rate.
- shop/tax.py::label: new. Name shown on receipts.
Refs #7
```

**Command line:** `projectviewer map <repo> -o out.world.json` writes the analysed world (JSON).

## Quick start (developers)

```bash
uv sync                      # install exact locked versions
uv run pre-commit install    # checks on every commit
uv run pytest                # tests
```

## Documentation

- [docs/](docs/README.md): roadmap, status, architecture decision records (ADRs), development log
- [CONTRIBUTING.md](CONTRIBUTING.md): workflow (GitHub Flow, Conventional Commits, Definition of Done)
- [CLAUDE.md](CLAUDE.md): rules for AI coding agents

## License

[CC BY-NC 4.0](LICENSE). **Free for non-commercial use** (personal, education, research, non-profit) with attribution. **Commercial use requires a paid license.** To request one, open an issue titled "Commercial license".
