# ADR-0007: Merge pull requests with a merge commit, so per-commit change notes survive

- **Status:** Accepted (supersedes the "squash merge" part of ADR-0004)
- **Date:** 2026-11-21

## Context

ADR-0004 chose **squash merges**: one commit per PR on `main`. Since then, each commit message carries a `Changes:` section of per-symbol notes, which the viewer shows on the changed code (ADR-0001's "why" behind every change). A squash folds a PR's 5–15 commits into one. Each change would no longer show its own message and notes; they would be mixed into one long text.

Also, stacked PRs (#2 on #1, #3 on #2) are awkward to squash: the next PR has to be rebased each time.

## Options considered

1. **Keep squash merges.** `main` history is short, but per-commit notes and the step-by-step story are lost.
2. **Rebase and merge.** Keeps every commit, with no merge commits, but rewrites the commits' ids, so links to them break.
3. **Merge commit.** Keeps every commit unchanged, plus one commit recording "PR #N merged".

## Decision

Option 3 (GitHub's "Create a merge commit") for all PRs. Commits inside a PR must each be meaningful and carry their own `Changes:` notes, which our workflow already requires.

As a safety net, the notes parser reads **every** `Changes:` section in a message, so notes also survive if a PR is ever squashed.

## Consequences

- **`main` keeps the full history,** and each commit can be shown in the viewer with its notes.
- **Reading `main` alone is noisier.** `git log --first-parent main` shows one line per merged PR.
- **The GitHub repository setting** "Allow merge commits" must stay enabled.
