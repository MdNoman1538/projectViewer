# Project Status

**As of:** 2026-11-21 · **Phase:** 1 (Python cartographer) done. Next: Phase 2 (viewer).

## What exists

| Part | File | What it does |
|---|---|---|
| Pass 1: per-file facts | `src/projectviewer/analyzers/python/extract.py` | Definitions, imports (incl. relative), call chains, simple variable/attribute types, return/yield types (for pytest fixtures), FastAPI routes, SQL table references. Pure, so cacheable and parallelisable. |
| Pass 2: linking | `src/projectviewer/analyzers/python/resolve.py` | Resolves imports (incl. re-exports via `__init__.py`, src-layout names), `self`, inheritance, type inference (constructors, annotations, return types, module globals, pytest fixtures). Classifies every call as linked / external / builtin / unresolved. |
| Cache | `src/projectviewer/cache.py` | Content-addressed per-file cache in `~/.cache/projectviewer`, written atomically |
| Mapper | `src/projectviewer/analyzers/python/mapper.py` | File discovery (git-aware), parallel parsing for ≥64 cache misses with serial fallback, world assembly |
| CLI | `src/projectviewer/cli.py` | `projectviewer map <repo> [-o out.world.json] [--no-cache]` |
| Tests | `tests/` | 22 behaviour tests on small made-up fixture projects |

## Accuracy

- **On a real private project (checked by hand):** 13/13 known links found, with sensible certainty labels:
  - endpoint→handler `proven`
  - API→service through a module-level instance `inferred`
  - table reads/writes `pattern`
  - test→code through a pytest fixture `inferred`
- **On projectViewer itself:** 106 calls linked, 112 unresolved (49%), 84 to libraries, 138 builtin. Main real cause: calls to **nested functions** (not yet registered). Most of the rest are builtin methods on untyped values. Only 39 unresolved calls share a name with a project function. See the devlog.

## Performance

Apple M3 (8 cores), Python 3.12, best of N runs.

| Case | Time | Notes |
|---|---|---|
| projectViewer itself (10 files), no cache / warm | **45 ms / 18 ms** | `uv run projectviewer map .` |
| pandas 3.1.1 source (1,440 files, 30,954 functions, 76,288 links), serial, no cache | 11.9 s | parsing 11.8 s |
| pandas, **parallel**, no cache | **4.3 s** | 8 worker processes; parsing 3.2 s |
| pandas, **warm cache** | **1.6 s** | 0.9 s re-reading 1,440 cache entries + 0.9 s linking |
| pandas, **1 file edited** | **1.65 s** | 1 cache miss |

## Reused from PR World v5 (to be moved over in later phases)

| v5 part | Plan |
|---|---|
| `viewer2/` (React + deck.gl, ~3,200 lines) | Phase 2: move over; remove bank, AI-review and people/roles parts; adapt to `project-world/1` |
| `agents/world_diff.py` (153 lines, language-neutral) | Phase 3: move over almost unchanged |
| Roslyn Cartographer, simulation, AI reviewer, server roles/sign-off | Dropped |

## Known issues and limits

| # | Issue | Plan |
|---|---|---|
| 1 | The pandas world is **31 MB** of JSON, too much for the browser at once | Phase 2: compressed transport + load each group on demand |
| 2 | Linking (pass 2) re-runs over the whole project, ~0.9 s on pandas | Phase 4: keep facts in memory in the service; re-link incrementally if needed |
| 3 | The warm path re-reads every cache entry (~0.9 s on pandas) | Phase 4: in-memory facts; skip unchanged files by mtime + size (like git's index) |
| 4 | SQL is detected only in UPPERCASE keywords. SQL inside test fixtures and registered DataFrames show up as tables. | Accepted; certainty is `pattern` |
| 5 | Imports inside functions are treated as module-wide | Accepted approximation |
| 6 | Nested functions are not registered (~28 missed calls in our own code); literal-typed values (`x = {}`) count as unresolved; the headline "% linked" metric overstates misses | Next PR (test-first) |
| 7 | Parallel parsing fails when called from stdin/REPL on macOS ("spawn") | Handled: automatic fallback to serial |
