# ADR-0002: Language-neutral world format `project-world/1` with honest link certainty

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

v5's world format (`bank-world/1`) was produced by a Roslyn (C#) analyser: Roslyn-specific IDs (`T:`, `M:`), C# kinds (ctor, property, field, column), bank-specific attributes (pii, constitution). The viewer and `world_diff` only need a graph: nodes with a parent hierarchy, file and line ranges, and typed edges.

## Decision

A world is a JSON document:

- **`nodes`:** `id`, `kind`, `name`, `parent`, `group`, `file`, `line`, `end_line`, `attrs`
  - kinds: `group` (top-level package), `file`, `class`, `function` (methods have `attrs.method = true`), `script` (top-level code of a file), `endpoint`, `table`
  - IDs: `group:<name>`, `file:<path>`, `py:<dotted.qualname>`, `endpoint:<VERB> <path>`, `table:<name>`
- **`edges`:** `source`, `target`, `kind`, `certainty`, `line`
  - kinds: `imports`, `calls`, `instantiates`, `inherits`, `routes`, `reads`, `writes`
- **`certainty`:**
  - `proven`: resolved through definitions and imports
  - `inferred`: resolved through simple type inference, e.g. `x = Foo()` then `x.bar()`, or a return annotation
  - `pattern`: found by text matching, e.g. table names inside SQL strings
- **Metadata:** `schema`, `generated_by`, `repo`, `commit`, `dirty`, `generated_at`, `stats`

## Reasoning

- Neutral kinds let other languages plug in later (for example a tree-sitter analyser).
- The certainty levels keep v5's best property: **the map never presents a guess as fact.** The viewer draws them differently.
- **No name-only "guess" edges in v1.** For example, `con.close()` would wrongly link to the only project method called `close`. Calls that can't be resolved are *counted* in `stats.unresolved_calls`, not drawn.

## Consequences

- The v5 viewer needs an adapter for these kinds (Phase 2).
- Some real links will be missing, because Python is dynamic. That's acceptable and visible in the stats.
- **Revisit if:** the unresolved rate is high on real projects. Then consider a precise indexer (for example SCIP or pyright-based).
