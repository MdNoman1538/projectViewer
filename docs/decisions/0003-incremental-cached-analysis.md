# ADR-0003: Two-pass analysis with a content-addressed per-file cache

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

v5 re-ran the full Roslyn analysis for every commit and stored a full world (~1.7 MB of JSON) per commit. projectViewer will map a project after every commit and every saved edit, and replay its whole history, so repeating the full work each time doesn't scale.

## Decision

- **Pass 1 (per file, pure):** `extract(path, source)` → *facts* about that one file: definitions, imports, raw call expressions, simple variable types, SQL table references, routes. Its result depends only on the file's content and the analyser version.
- **Cache:** facts are stored under `sha256(analyser_version + path + content)` in `~/.cache/projectviewer/` (outside the analysed project). Unchanged files are never parsed again, even across commits, branches or repos.
- **Pass 2 (whole project, in memory):** link the facts across files into nodes and edges. No parsing, so it's fast.

## Reasoning

A commit usually touches a few files, so pass 1 work becomes proportional to the *change*, not the codebase. The cache key includes the analyser version, so improving the analyser automatically invalidates old results. The key includes the path because module names (and therefore IDs) depend on it.

## Consequences

- The cache grows over time; a size limit or cleanup command is needed later.
- Pass 1 must stay pure: no reading other files. Anything cross-file belongs to pass 2.
- Measured speed (cold vs warm cache) is recorded in project-status.md.
