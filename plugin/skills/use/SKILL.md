---
name: use
description: Work with projectViewer while coding in a Python project that has it set up. Check which code a change affects before finishing, explain impact to the user, find callers of a function, and write commit messages with a "Changes:" section so the viewer shows the reason behind every change. Use when the user asks what a change affects, who calls something, how the architecture fits together, or when committing in a project subscribed to projectViewer.
---

# Working with projectViewer

projectViewer maps **Python** code into a "world": modules, files, classes and functions (nodes), plus the links between them (calls, imports, endpoints, database tables). Every link carries a certainty: `proven`, `inferred` or `pattern`. Treat `pattern` links as hints, not facts. It runs locally at `http://127.0.0.1:8765` (start it with `projectviewer serve`).

Find the project's id with `projectviewer list` (or `GET /api/projects`).

## Before you finish a change: check its impact

With the viewer running, ask what the uncommitted work changes and affects:

```bash
curl -s "http://127.0.0.1:8765/api/p/<id>/changes?ref=working"
```

The answer lists:
- `changed`, `moved` and `removed` code
- `upstream`: code that **uses** what changed (it may break)
- `downstream`: code it uses
- `files`

Use it to:
- **Run the right tests:** those that reach the upstream code.
- **Tell the user what else is affected**, especially API endpoints and database tables in the upstream list.
- **Catch surprises:** a change you thought was local that reaches many modules deserves a second look.

For a commit instead of the working copy: `?ref=<sha>` or `?ref=HEAD`.

## Questions about the code

The whole world as JSON, without the server:

```bash
projectviewer map <project> -o world.json
```

- **Nodes** have `id` (e.g. `py:pkg.module.Class.method`), `kind`, `file`, `line`, and `attrs.params` (name, annotation, default).
- **Edges** have `source`, `target`, `kind` (`calls`, `imports`, `instantiates`, `inherits`, `routes`, `reads`, `writes`, `requests`) and `certainty`.
- **"Who calls X?"** means the edges whose `target` is X's id and whose `kind` is `calls`.

## Commit messages: say why, per changed function

projectViewer shows each line of a commit's `Changes:` section on the code it names, so the person reviewing sees the reason on the map, not only the diff. Write commits like this:

```
fix(tax): new VAT rate

Changes:
- shop/tax.py::rate: changed. Returns the new rate from the 2026 table.
- shop/tax.py::label: new. Name shown on receipts.
- shop/receipt.py: whole file; layout for the new label.
Refs #7
```

Rules:
- one line per changed symbol, as `path::Qualified.name: what and why`; use `path: …` for whole files
- `Refs #N` or `Closes #N` links an issue
- notes survive best when pull requests are merged with **merge commits** (squash folds them together); every `Changes:` section in a message is read

## Hand-written and AI-written code alike

- Hand edits appear live as the user saves.
- AI edits do too, plus the activity feed when the hook (or this plugin) is enabled.
- Nothing about the user's project needs to change; projectViewer only reads it.
