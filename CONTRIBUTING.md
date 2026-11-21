# Contributing

Reasoning behind this workflow: [ADR-0004](docs/decisions/0004-development-workflow.md).

By contributing you agree that your contribution is licensed under this repository's [license](LICENSE) (CC BY-NC 4.0), and that the copyright holder may also offer it under a commercial license.

## Workflow: GitHub Flow

`main` always works. Every change goes through a pull request.

```
Issue → branch → test first (for bugs) → code → local checks → Conventional Commit → push → PR → CI green → human review → merge commit (ADR-0007)
```

- **Branches:** `<type>/<short-description>`, for example `feat/python-cartographer`, `fix/cache-key`.
- **Commits and PR titles:** [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`. Explain *why* in the body.
- **PRs:** one purpose each, small (aim for under ~400 changed lines of code), with the [PR template](.github/pull_request_template.md) filled in.

## Definition of Done

- [ ] Tests cover the change; for a bug fix, a test that failed before now passes
- [ ] `ruff` and `pytest` pass locally; CI is green
- [ ] Docs updated: devlog entry; an ADR for any significant decision; `docs/project-status.md` if status changed
- [ ] Performance claims come from a measurement that was actually run, with the method stated
- [ ] No secrets or personal data in the diff
- [ ] A human has read the whole diff

## Setup and checks

```bash
uv sync
uv run pre-commit install
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

## Working with AI coding agents

Plan before code. Tests are the contract. Never merge code you haven't read. Agent rules: [CLAUDE.md](CLAUDE.md).
