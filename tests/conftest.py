import textwrap
from pathlib import Path

import pytest

from projectviewer.analyzers.python import map_repo


@pytest.fixture
def project(tmp_path):
    """Write a small fixture project: project({"pkg/a.py": "code", ...}) -> root path."""

    def make(files: dict[str, str]) -> Path:
        for rel, code in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(code).lstrip("\n"), encoding="utf-8")
        return tmp_path

    return make


class W:
    """Small query helper over a world dict, to keep assertions readable."""

    def __init__(self, world: dict):
        self.world = world
        self.nodes = {n["id"]: n for n in world["nodes"]}

    def edge(self, source: str, target: str, kind: str) -> dict | None:
        return next(
            (
                e
                for e in self.world["edges"]
                if e["source"] == source and e["target"] == target and e["kind"] == kind
            ),
            None,
        )

    def edges(self, kind: str) -> list[dict]:
        return [e for e in self.world["edges"] if e["kind"] == kind]


@pytest.fixture
def world(project):
    def build(files: dict[str, str], **kw) -> W:
        return W(map_repo(project(files), **kw))

    return build
