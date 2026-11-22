# 2026-11-23: Agent-ready: plugin, setup and doctor, packaged viewer

## The question

"If someone loads projectViewer from GitHub and tells Claude to use it, will Claude know what to do, for hand-written and AI-written code alike?" The honest answer was *partly*:
- a person could follow the README
- Claude had no instructions written for **using** the tool, and couldn't see projectViewer's CLAUDE.md from the user's project anyway

## What was built (ADR-0008)

- **A Claude Code plugin inside the repo,** checked against the official docs before building:
  - `.claude-plugin/marketplace.json` and `plugin/.claude-plugin/plugin.json`
  - two skills: `setup` and `use`
  - `hooks/hooks.json`
  - both manifests pass `claude plugin validate`
- **`projectviewer setup`, `doctor`, `unhook`**, in a new module `onboard.py`.
- **The viewer is built into the package.** A wheel built and installed into a fresh virtual environment reports "✓ Viewer files installed", with no Node.js.
- **"Python projects only"** everywhere it matters.

## Details worth remembering

- **Hooks run with Claude Code's PATH, not the user's shell's.** So `setup --hook` writes the absolute path of the `projectviewer` it finds, falling back to `python -m projectviewer.cli`. The plugin's hooks use the bare command plus the guard: if it isn't installed, they do nothing.
- **Settings merging is idempotent:**
  - running it twice changes nothing
  - an older projectViewer hook is updated in place instead of duplicated
  - other hooks and settings are untouched
  - a backup is written before every change
- **The README had over-claimed** ("a timeline you can replay", "keeps the prompt that caused it"). Neither is built yet. The README now says only what works and lists the rest as planned.
- **The status file was stale:** it still named an old branch and listed nested-function support as open, though PR #3 fixed it. Both corrected.

## Tests

81 pass (13 new):
- **Settings merge:** missing file, other settings kept, idempotent, update-not-duplicate, broken file refused, unhook removes only ours
- **Doctor:** a ready project; a non-Python project told "Python projects only"; virtual environments ignored
- **Fitness tests for the plugin:**
  - manifest and marketplace names agree
  - every hook command is guarded and records no prompt text
  - every skill has a description, mentions Python and stays under 500 lines
