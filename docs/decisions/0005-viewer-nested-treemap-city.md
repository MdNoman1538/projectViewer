# ADR-0005: New viewer, a nested treemap shown as a 2.5D city (not a port of the v5 viewer)

- **Status:** Superseded by ADR-0006 (one level at a time, folder blocks)
- **Date:** 2026-11-21

## Context

The roadmap said "move the v5 viewer over". Reading it closely:
- v5's world view used a **hard-coded grid of module positions** (bank modules) and C#-specific layers (Api / Application / Domain…).
- It had separate screens per level (world → module → class).
- Much of its code is PR review, trust levels and people/roles, which projectViewer dropped.

projectViewer must lay out **any** project automatically and stay readable from 20 to 1,500+ files. The owner liked v5's **2.5D look where bigger modules are taller**.

## Options considered

1. **Port v5's viewer and generalise its layout.** Most of the code would be removed or rewritten anyway; the hard-coded grid is its core.
2. **Graph layout** (nodes and edges, e.g. ELK or force-directed). Shows links well, but hides the containment hierarchy and code size; unstable as code changes.
3. **Nested treemap:** packages contain files, files contain classes and functions; area is proportional to lines of code. Shown flat (2D) or as a **2.5D city**: each level stands on its parent, and towers are taller for bigger code.

## Decision

Option 3, written new, with v5's visual language and exact library versions (React 18.3.1, deck.gl 9.4.1, Vite 5.4.21), plus d3-hierarchy 3.1.2 for the squarified treemap.

- **2.5D is the default:** a tilted orthographic orbit camera as in v5 (pitch 35°), with right-drag to rotate.
- **Labels are placed by screen-space collision avoidance**, by priority: packages, files, classes, then the biggest functions.
- **Links appear on demand:** for a selection (blue = what it uses, orange = what uses it), or per lens.
- **Opacity shows certainty:** proven / inferred / pattern.

## Reasoning

- **A treemap needs no project-specific configuration, and shows hierarchy and size at once.** Code size is what the owner wants to see (height = size).
- **One continuous map, flown around with zoom, replaces v5's separate screens.** Labels appear as you zoom in ("semantic zoom").
- **Showing links on demand keeps the map readable.** v5 showed lens links all the time, which doesn't scale to large projects.

## Consequences

- **Layout stability:** sorting by size means the layout can shift as code grows. The history timeline (Phase 3) will need a stable ordering.
- **Large worlds** (pandas: 31 MB, ~34k blocks) need on-demand loading per group before the viewer handles them smoothly.
- **v5's PR overlay features** are not yet present: changed/affected lists, guided "show" tour, findings. They return with history (Phase 3) and the PR view (Phase 5).
