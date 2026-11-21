# ADR-0006: Show one folder level at a time; blocks sized by number of functions

- **Status:** Accepted (supersedes ADR-0005's "everything at once" map)
- **Date:** 2026-11-21

## Context

ADR-0005's map drew every package, file, class and function at once (a nested treemap). After using it, the owner found it **cluttered and hard to navigate and understand**, and preferred v5, which showed **modules only**, with height by size.

They also asked for:
- **Blocks that follow the actual folder structure**, where `src/` is not a module of its own: `ui`, `scoring`, `spatial`, `api`, `tests` … are the modules.
- **Block size by the number of functions.**

## Decision

- **One level at a time.** The map shows only the children of the current *focus*, as separate blocks with streets between them:
  - top level: modules and a Database block
  - inside a folder: subfolders and files
  - inside a file: classes and functions
  - inside a class: methods
- **Navigation:** click selects; click again (or Enter) goes inside; Backspace, Esc or the breadcrumb goes up.
- **Folders come from file paths.** `src/` is transparent: its contents are the top-level modules (a src-layout convention, not a module).
- **Size and height = number of functions** in the block (tests included), relative to the biggest block on the same level. When every block on a level is a single function, lines of code are used instead.
- **Arcs show dependencies summed between the blocks on screen** (calls, object creation, data access).
- **The side panel names dependencies outside the current level by their top-level module** ("i18n · elsewhere").
- **Each block has a badge line** for the current lens: "12 functions · 6 files", "62% tested", "3 API endpoints", "uses data".

## Reasoning

- **One level at a time is "progressive disclosure"**: show the overview, give detail on demand. A person can compare roughly 5–15 things at once, not hundreds.
- **Function count is a better size measure than lines** for "how much does this module *do*". Lines also count blank lines, comments and long SQL strings.
- **Summing links between visible blocks answers the architecture question directly** ("which modules depend on which?") instead of drawing hundreds of function-to-function lines.

## Consequences

- The **within-level layout is still a squarified treemap**, which is fine for a handful of blocks. Positions can shift as a module grows; the history timeline will need stable ordering.
- **The analyser is unchanged.** The folder tree is derived in the viewer from file paths.
- **The structure shown is only as good as the project's own folder structure.** That's intended: it makes a messy structure visible.
