---
name: setup
description: Install and set up projectViewer for the current Python project, so the user gets a live, explorable map of the codebase (folders as blocks, links between functions, impact of each change) and, optionally, a live feed of what the AI is doing. Use when the user asks to set up, install, start or use projectViewer, to "show a map / visualise the architecture of this code", or to "watch what the AI is changing".
---

# Set up projectViewer for this project

projectViewer is a local tool: it runs on this machine at `http://127.0.0.1:8765` and sends nothing anywhere else. It works for **Python projects only** (other languages are planned). It works the same whether the user writes the code by hand or with an AI agent.

Follow these steps in order. **Ask before installing software or changing the user's settings.**

## 1. Check it's a Python project

Look for `.py` files in the project (ignore virtual environments). If there are none, stop and tell the user: *"projectViewer currently maps Python projects only; support for other languages is planned."*

## 2. Make sure projectViewer is installed

Run `projectviewer --help`. If the command isn't found, ask the user, then install it:

```bash
uv tool install git+https://github.com/MdNoman1538/projectViewer
```

No `uv`? Use `pipx install git+https://github.com/MdNoman1538/projectViewer`, or install uv first (https://docs.astral.sh/uv/). Python 3.12 or newer is required. The viewer comes prebuilt; Node.js is not needed.

## 3. Subscribe the project and check everything

```bash
projectviewer setup <path-to-project>
```

This subscribes the project (several projects can be subscribed; the viewer has a project switcher) and prints a checklist. Each `✗` comes with the fix.

**The AI activity feed (optional):**
- **This plugin is installed?** Then the feed is already on: the plugin brings its own hook. **Do not** add `--hook`, or every event would be reported twice.
- **Using these instructions without the plugin?** Ask the user whether they want the feed. If yes, run `projectviewer setup <path> --hook`. Add `--prompts` **only if the user explicitly agrees** to recording their prompt text. It stays on this machine, but it is their choice.

The hook is safe by design: it finishes within 0.3 seconds, prints nothing and always succeeds, so it can never slow down or block Claude, even when the viewer isn't running. `projectviewer unhook` removes it and nothing else.

## 4. Start the viewer

`projectviewer serve --open` keeps running, so start it **in the background** (or ask the user to run it in a terminal of their own). It opens the browser at `http://127.0.0.1:8765`. Inside VS Code: *Simple Browser: Show* → `http://127.0.0.1:8765`.

## 5. Verify, and tell the user what they'll see

```bash
projectviewer doctor <path-to-project>
```

All `✓` (a `!` for "viewer not running" is fine before step 4). Then explain briefly:
- **The map:** the project's folders as blocks, one level at a time. Size and height = number of functions; click to select, click again to go inside, Backspace to go up. Lenses: Architecture, Tests, Data, API.
- **Live changes:** saving a file lights up what changed (red), moved (purple) and what it affects (orange). It works for hand edits and AI edits alike.
- **Commits:** each commit shows its changes; commit messages with a `Changes:` section show a note on each changed function (see the *use* skill).
- **AI activity** (if enabled): every file the AI edits; "follow activity" flies to it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `projectviewer: command not found` after installing | Open a new terminal, or run `uv tool update-shell` |
| Browser shows "The viewer is not built yet" | You're running from a source checkout: `cd viewer && npm ci && npm run build` |
| Map is empty | Not a Python project, or the files are git-ignored |
| AI activity stays empty | Plugin users: restart Claude Code once after installing. Others: `projectviewer setup --hook`, then open `/hooks` once or restart |
| Port 8765 busy | `projectviewer serve --port 8766 --open` |
