# 2026-11-21 — Start of projectViewer, and the Python cartographer

## Why this project exists

projectViewer grows out of a private prototype, PR World v1–v5: a codebase written by AI agents and reviewed by an AI reviewer, explored as a map. projectViewer keeps the best idea, the map plus "changed / affected", and drops the simulation and the AI reviewer. It points the map at real development.

What we found reading v5 before starting:
- the viewer (React + deck.gl, ~3,200 lines) is reusable
- the diff logic is language-neutral
- the analyser was C#-only (Roslyn)
- **v5 was not under version control**: its versions were zip files

## Decisions

- ADR-0001: a local service projects subscribe to. Recording is deterministic (git reflog, file watcher, a global Claude Code hook), never an LLM.
- ADR-0002: language-neutral `project-world/1` format, every link labelled `proven` / `inferred` / `pattern`, **no name-only guesses**.
- ADR-0003: two-pass analysis with a content-addressed per-file cache.
- ADR-0004: GitHub Flow. The initial scaffold is the only commit directly on `main`.

## Test-first, and what the tests didn't catch

We wrote 19 behaviour tests as the specification first, then the code; all passed on the first full run. **Passing our own tests proved little, so we checked against a real project whose links we know.** We mapped it and verified 13 known links by hand: 12/13 found.

The miss was important: its tests receive objects through **pytest fixtures**, parameters pytest fills in by matching their names to fixture functions. Without fixture support, a "tests" view would miss most test→code links. We added a failing test, then the support: fixtures in the same module or in the nearest `conftest.py`, typed by return annotation or by the value they return/yield. After that, 13/13.

## The misleading "30% linked"

The first summary on that project said only 30% of project calls were linked. Grouping the unresolved calls by receiver showed the truth: database-connection methods, string methods (`val.strip`), `Path.glob`. They were **library and builtin calls on variables whose type we didn't track**, not missed project calls.

The fix tracks when a value comes from a library or builtin type (`lib.connect()`, `: str`, `: Path`) and counts its calls accordingly. Unresolved went from 146 to 37. *Lesson:* before trusting a metric, look at what's inside it.

## Speed: measure, then parallelise only what's needed

- Cold mapping of pandas (1,440 files) took 11.9 s, almost all of it parsing on one core.
- Pass 1 is pure, so parsing in a process pool is safe: 4.3 s with 8 workers. That's 2.8×, not 8×, because of process start-up and copying data between processes.
- Parallel only kicks in at ≥64 cache misses. Typical incremental updates touch a few files, where starting processes would cost more than it saves.
- **A real bug found while benchmarking:** running from piped input crashed the worker processes. On macOS, workers are started fresh ("spawn") and must re-import `__main__`, which doesn't exist for stdin, REPLs or notebooks. The library now falls back to serial instead of crashing.
- A warm cache gives 1.6 s and one edited file 1.65 s. What remains (re-reading cache entries + linking) is best solved by the Phase 4 service keeping facts in memory, so we recorded it rather than optimising early.

## Mapping ourselves

projectViewer maps its own code in 45 ms (cold) / 18 ms (warm), but links only 49% of its own project calls. The reason is instructive: the analyser passes plain `dict`s around (`facts["imports"].append(...)`), and a dictionary's values have no type to follow. **Dict-heavy code limits static linking**; typed objects (dataclasses, TypedDicts) would help both readers and tools.

## Smaller decisions

- **The cache lives in `~/.cache/projectviewer`**, never inside the analysed repo, so subscribing a project never adds files to it.
- **The cache key includes the path,** because module names (and so node IDs) depend on it.
- **The analyser version is in the cache key.** We bumped it from 1 to 2 when the facts changed shape (fixture support), which invalidated old entries automatically.
- **`conftest.py` counts as test code.**

## Going public

The repository is public under CC BY-NC 4.0: free for non-commercial use, commercial use needs a paid license. Before the first push, all references to the private project used for validation were removed from code, tests, docs **and commit messages**. Local history was rebuilt, which is safe only because nothing had been pushed yet. Test fixtures use made-up projects (shops, catalogs, orders), and CLAUDE.md now forbids details of analysed projects in this repo.

## Next

Phase 2: move the v5 viewer over, adapt it to `project-world/1`, compute the layout from groups, and add click-to-open-in-VS-Code. The 31 MB pandas world shows that loading on demand is needed from the start.
