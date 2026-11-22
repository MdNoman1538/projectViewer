# ADR-0008: Agent-ready distribution: a Claude Code plugin, one-command setup, and a packaged viewer

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

Someone who finds projectViewer on GitHub should be able to tell Claude "use this for my project" and have it work, whether they then code by hand or with an AI agent. Before this change:
- `CLAUDE.md` only told agents how to **develop** projectViewer. Claude Code reads the `CLAUDE.md` of the project the user is working in, not projectViewer's, so there were no usable instructions.
- Installing needed a clone, `uv sync`, and an npm build of the viewer.
- The AI activity hook had to be pasted into `~/.claude/settings.json` by hand.
- The analyser reads Python only, and the README didn't say so.

## Options considered

1. **Better README only.** Simple; agents can read it if pointed at it, but nothing is automatic.
2. **A Claude Code plugin in the repository**, with skills and hooks, installable from a marketplace file at the repo root, plus CLI commands that do the setup safely.
3. **A separate plugin repository.** Cleaner separation, but two repos to keep in step for one tool.

## Decision

Option 2, plus the README as a fallback:
- **`.claude-plugin/marketplace.json`** at the root and **`plugin/`** containing:
  - skill **`setup`**: check Python, install (asking first), subscribe, start, verify
  - skill **`use`**: check impact before finishing, find callers, write `Changes:` notes
  - **`hooks/hooks.json`**: the AI activity hook, without prompt text

  Users install it with `/plugin install projectviewer --marketplace MdNoman1538/projectViewer`.
- **`projectviewer setup`** (subscribe plus a checklist; `--hook` merges the hook into settings for non-plugin users), **`doctor`** (every requirement with its fix) and **`unhook`**.
- **The built viewer ships inside the Python package** (`src/projectviewer/web`), so `uv tool install git+…` is the whole installation. CI rebuilds it and fails if the committed bundle differs from the source; Vite's output is deterministic.
- **"Python projects only"** is stated in the README, the skills and the doctor.

## Reasoning

- **Plugins are how Claude Code carries reusable instructions across projects.** A skill's description tells Claude when to use it, and hooks shipped with the plugin need no settings editing.
- **One repository keeps the tool and its instructions in step**; a test checks that the plugin's name matches its marketplace entry.
- **Safety rules carried over from ADR-0001 and enforced by tests:**
  - every hook command ends in `>/dev/null 2>&1 || true`
  - settings are merged, backed up and written atomically
  - a broken settings file is refused, never "repaired"
  - prompt text is never recorded by default

## Consequences

- **Committing build output** adds about 1.1 MB per viewer change to history. Accepted for a no-Node.js install; the freshness check keeps it honest.
- **Plugin users who also ran `setup --hook`** would report each event twice. The setup skill and `doctor` say not to combine them.
- **Revisit when:** other languages arrive (the same plugin, more analysers), or a PyPI release makes `pip install projectviewer` possible.
