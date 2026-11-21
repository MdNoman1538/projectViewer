# ADR-0004: Development workflow: GitHub Flow, small PRs, test-first fixes, human review of AI-written code

- **Status:** Accepted; merge strategy superseded by ADR-0007 (merge commits)
- **Date:** 2026-11-21

## Context

projectViewer's predecessor (PR World v1–v5, a private prototype) had no version control: versions were zip files, with no history, no review and no CI. projectViewer is meant to be maintainable, public, and largely written with an AI coding agent.

## Options considered

1. **Git Flow** (develop/release branches): built for scheduled releases. Too heavy for one maintainer.
2. **Trunk-based development:** needs a strong test suite first.
3. **GitHub Flow:** `main` always works; every change goes on a short-lived branch, through a PR with CI, and is squash-merged.

## Decision

GitHub Flow, with:
- squash merges and Conventional Commits
- small single-purpose PRs; test-first bug fixes
- a Definition of Done that includes docs
- CI (ruff + pytest) and pre-commit (which refuses commits on `main`)
- branch protection with CI required (approvals set to 0: GitHub doesn't let authors approve their own PRs; human review is enforced by the process)
- agent rules kept in `CLAUDE.md`, so they're versioned and visible to every contributor and tool

The **only commit made directly on `main` is the initial scaffold**, because an empty repository has no base for a PR.

## Consequences

- Each change costs a few extra minutes (branch, PR, CI). Accepted.
- **With AI-written code, review and tests are the bottleneck on purpose:** code arrives faster than a human can verify it.
- **Revisit if** more maintainers join (then add required approvals and CODEOWNERS).
