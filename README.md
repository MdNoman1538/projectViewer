# projectViewer

A live, explorable map of your codebase that shows what every change touches, whether you write the code yourself or an AI agent does.

> **Python projects only, for now.** The analyser reads Python. Support for other languages is planned.

- **See the architecture.** Your folders as blocks, one level at a time, sized by how many functions they hold, with the links between them: calls, API endpoints, database tables, tests.
- **See the impact of any change.** For your uncommitted work or any commit: what changed (red), what moved (purple), and what it affects (orange). A text diff only shows the red part.
- **See the reason behind each change.** Commit messages with a `Changes:` section put a note on each changed function.
- **Watch the AI work.** With Claude Code, a live feed of every file the agent edits; "follow activity" flies to it.

Everything runs **on your machine** (`127.0.0.1`); nothing is sent anywhere.

## Quick start

```bash
uv tool install git+https://github.com/MdNoman1538/projectViewer   # Python 3.12+; no Node.js needed
projectviewer setup path/to/your/project                            # subscribe it and check everything
projectviewer serve --open                                          # http://127.0.0.1:8765 (keep it running)
```

No `uv`? `pipx install git+https://github.com/MdNoman1538/projectViewer` works too. Inside VS Code: *Simple Browser: Show* → `http://127.0.0.1:8765`.

**Writing code by hand?** That's all: save a file and the map updates.

**Using Claude Code?** Install the plugin (next section) and Claude knows how to set up and use projectViewer in any project, and the AI activity feed turns on by itself.

## With Claude Code (AI-driven development)

Install the plugin once (Claude Code 2.1.275 or later):

```
/plugin install projectviewer --marketplace MdNoman1538/projectViewer
```

On older versions: `/plugin marketplace add MdNoman1538/projectViewer`, then `/plugin install projectviewer@projectviewer`. Restart Claude Code once afterwards.

The plugin adds:
- **Skill `projectviewer:setup`:** "set up projectViewer for this project" installs, subscribes, starts and checks it, asking before it installs anything.
- **Skill `projectviewer:use`:** while coding, Claude checks which code a change affects before finishing, answers "who calls this?", and writes commit messages with `Changes:` notes.
- **The AI activity hook:** reports edits, prompts (without their text) and stops to your local viewer. It finishes within 0.3 s, prints nothing and always succeeds, so it can never slow down or block Claude.

**Without the plugin?** `projectviewer setup <project> --hook` adds the same hook to `~/.claude/settings.json`. It merges with your settings, keeps a backup, refuses to touch a broken file, and `projectviewer unhook` removes it again. Add `--prompts` only if you want the prompt text recorded too (it stays on your machine).

### If you're an AI agent

The user wants projectViewer for their project. Follow [plugin/skills/setup/SKILL.md](plugin/skills/setup/SKILL.md) step by step:
1. Check it's a Python project.
2. Install with `uv tool install git+https://github.com/MdNoman1538/projectViewer` (ask first).
3. `projectviewer setup <project>`, plus `--hook` only if the plugin isn't installed and the user wants the feed; `--prompts` only with explicit consent.
4. Start `projectviewer serve --open` in the background.
5. Confirm with `projectviewer doctor <project>`.

While coding, follow [plugin/skills/use/SKILL.md](plugin/skills/use/SKILL.md).

## Using the viewer

- **The map:** click a block to select it, click again (or Enter) to go inside, Backspace to go up.
- **Lenses:** Architecture, Tests (share of functions reached by tests, including over HTTP), Data (database tables), API (endpoints).
- **Changes:**
  - **Live:** uncommitted changes light up as files are saved
  - **Any commit:** shows the same, plus its message and per-function change notes
  - **▶ Show:** walks through the changes one by one, with each diff
- **Several projects:** a project switcher; **follow activity** shows whichever project is changing.

**Change notes:** add a `Changes:` section to commit messages; the viewer attaches each line to the code it names:

```
fix(tax): new VAT rate

Changes:
- shop/tax.py::rate: changed. Returns the new rate.
- shop/tax.py::label: new. Name shown on receipts.
Refs #7
```

## Commands

| Command | What it does |
|---|---|
| `projectviewer setup [project] [--hook] [--prompts]` | Subscribe a project and check everything; optionally add the Claude Code hook |
| `projectviewer doctor [project]` | Check that everything works, with a fix for each problem |
| `projectviewer serve [--open] [--port N]` | Run the live viewer for all subscribed projects |
| `projectviewer add / remove / list` | Manage subscribed projects |
| `projectviewer map <project> -o world.json` | Write the analysed project as JSON (nodes, edges, certainty of each link) |
| `projectviewer unhook` | Remove projectViewer's hook from Claude Code's settings (nothing else) |

## Status

Working: the Python analyser, the 2.5D viewer, live and per-commit changes with impact and notes, several projects, the Claude Code plugin and hook.

Planned: other languages, a background service with push updates, a history timeline, GitHub pull requests on the map. See [docs/roadmap.md](docs/roadmap.md) and [docs/project-status.md](docs/project-status.md).

> Successor of PR World v5, a demo where AI agents built a simulated bank and an AI reviewer judged each PR. projectViewer drops the simulation and the AI reviewer and works on your real projects. Background: [docs/decisions/](docs/decisions/).

## Developing projectViewer

```bash
uv sync                          # install exact locked versions
uv run pre-commit install        # checks on every commit
uv run pytest                    # tests
cd viewer && npm ci && npm run build   # rebuilds the viewer into src/projectviewer/web (commit the result)
```

- [docs/](docs/README.md): roadmap, status, architecture decision records (ADRs), development log
- [CONTRIBUTING.md](CONTRIBUTING.md): workflow (GitHub Flow, Conventional Commits, Definition of Done)
- [CLAUDE.md](CLAUDE.md): rules for AI agents **developing** projectViewer (to *use* it, see the plugin above)

## License

[CC BY-NC 4.0](LICENSE). **Free for non-commercial use** (personal, education, research, non-profit) with attribution. **Commercial use requires a paid license.** To request one, open an issue titled "Commercial license".
