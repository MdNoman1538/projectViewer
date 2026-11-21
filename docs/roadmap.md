# Roadmap

**Created:** 2026-11-21

## Goal

Make a codebase's architecture, and the impact of each change, visible at a glance, and record how it is built (AI vs human, and why). Built in small, tested steps.

## Phases (each phase is one or more PRs)

| # | Phase | Delivers | Exit criteria |
|---|---|---|---|
| 1 | **Python cartographer** | `projectviewer map <repo>` → a world (packages, files, classes, functions, imports, calls, FastAPI endpoints, SQL tables, tests), incremental and cached | Correct on tested fixtures and on a real project checked by hand; measured speed |
| 2 | **Viewer** | v5's React + deck.gl viewer, moved over: bank, AI-review and people/roles parts removed; layout computed from the package structure; click opens the code in VS Code | Explore a real project's map in the browser |
| 3 | **Changes** | For the live working copy, any commit and any GitHub issue (via `Closes #N` / `Refs #N`): changed blocks (red), affected blocks (orange, via v5's `world_diff`), the diff ("how"), and **change notes** explaining each change, written in the commit message (`path::symbol: note`) by whoever made it, human or AI. Plus a guided **Show** tour through a change and a timeline slider. | See exactly what changed, where, why and what it affects |
| 4 | **Service + recorder** | Background service (launchd), `subscribe` / `unsubscribe`, reflog + file-watcher + Claude Code hook events, SQLite event log, live updates (Server-Sent Events) | AI vs human changes appear live with their prompts |
| 5 | **PR view** | GitHub PRs + CI status as overlays; `/code-review` findings placed on the map, with right/wrong marks | Review a real PR from the map |
| 6 | **Summaries** (optional) | Local Qwen summaries of sessions and days; answers to "what changed in X?" | Summaries checked against the recorded facts |

## Performance principles (vs v5)

1. **Incremental:** a file is analysed once per unique content (content-addressed cache). A commit touching 2 files re-analyses 2 files.
2. **Two passes:** pass 1 (per file) is pure and cacheable; pass 2 (linking files together) runs in memory and is cheap.
3. **Store once:** worlds are assembled from per-file pieces; identical content is never stored twice.
4. **Compressed transport, served on demand**, instead of v5's ~1.7 MB JSON file per commit.
5. **Stable layout across time**, so replaying history does not make the map jump.
6. **Measure everything:** each phase records cold and warm timings.
