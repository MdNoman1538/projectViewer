# projectViewer

A live, explorable map of a codebase that records how it is being built, by you and by AI.

- **See the architecture.** Packages, files, classes and functions as a map, with the links between them: calls, API endpoints, database tables, tests.
- **See the impact of any change.** For a commit, a PR or an AI session: what changed (red) and what it affects (orange). A text diff only shows the red part.
- **See how it was built.** A timeline you can replay. Every change is marked as AI or human, and keeps the prompt that caused it.

It runs **locally** as a small background service. Projects *subscribe*; nothing is sent anywhere else.

> Successor of PR World v5, which was a demo where AI agents built a simulated bank and an AI reviewer judged each PR. projectViewer drops the simulation and the AI reviewer and works on your real projects. Background: [docs/decisions/](docs/decisions/).

## Status

Early development. See [docs/roadmap.md](docs/roadmap.md) and [docs/project-status.md](docs/project-status.md).

## Quick start (developers)

```bash
uv sync                      # install exact locked versions
uv run pre-commit install    # checks on every commit
uv run pytest                # tests
```

## Documentation

- [docs/](docs/README.md): roadmap, status, architecture decision records (ADRs), development log
- [CONTRIBUTING.md](CONTRIBUTING.md): workflow (GitHub Flow, Conventional Commits, Definition of Done)
- [CLAUDE.md](CLAUDE.md): rules for AI coding agents

## License

[CC BY-NC 4.0](LICENSE). **Free for non-commercial use** (personal, education, research, non-profit) with attribution. **Commercial use requires a paid license.** To request one, open an issue titled "Commercial license".
