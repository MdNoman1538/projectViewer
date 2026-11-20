# ADR-0001: A local background service that projects subscribe to; recording is deterministic

- **Status:** Accepted (built in Phase 4)
- **Date:** 2026-11-21

## Context

We want every change to a project recorded: by the human in VS Code, or by an AI agent (Claude Code), including the prompt behind it. It should work for any project, without changing the project's code or workflow, and without slowing development down.

PR World v5 created worlds only from PRs built by its own simulation. That is not how real development happens.

## Options considered

1. **An LLM agent that watches and records.** Misses events, adds latency, may describe changes that never happened. Rejected for recording; kept for *summaries* only (Phase 6).
2. **Per-repo git hooks.** Has to be installed into every repo, and conflicts with pre-commit, which manages `.git/hooks`.
3. **A global git hooks path (`core.hooksPath`).** Disables each repo's own hooks; pre-commit refuses to install while it is set. Rejected.
4. **A local background service plus passive event sources:**
   - commits from the **git reflog** (`.git/logs/HEAD`), which git appends to on every commit, checkout, merge and rebase; no install needed
   - hand edits from a **file watcher**
   - AI edits and prompts from **one global Claude Code hook** in user settings, which posts to the service
   - Projects **subscribe** with `projectviewer subscribe <path>`.

## Decision

Option 4. The service runs as a macOS launchd LaunchAgent, listens on 127.0.0.1 only, and stores events in SQLite. The event log is the source of truth (event sourcing): worlds and diffs are derived from it and can be rebuilt. Viewers subscribe to a project's event stream (Server-Sent Events).

## Consequences

- Subscribed projects need no changes and no new dependencies.
- **The hook must never hurt the developer:** a tiny payload, a timeout of a few hundred ms, and silent failure when the service is down.
- **Prompts are stored locally only.** Recording them is the *recommended default*; it needs the owner's explicit confirmation before Phase 4 ships. An opt-out setting will exist either way.
- The exact Claude Code hook input fields must be checked against the docs when Phase 4 is built.
- **Revisit if:** teams need shared history (that would mean a server, authentication and privacy review).
