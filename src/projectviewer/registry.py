"""Subscribed projects: a small JSON list in ~/.config/projectviewer/projects.json (local only)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def config_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "projectviewer" / "projects.json"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def load() -> list[dict]:
    try:
        data = json.loads(config_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [p for p in data.get("projects", []) if Path(p["path"]).is_dir()]


def _save(projects: list[dict]) -> None:
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"projects": projects}, indent=2))
    tmp.replace(f)


def unique_id(path: Path, taken: set[str]) -> str:
    base = slug(path.name)
    pid, n = base, 2
    while pid in taken:
        pid, n = f"{base}-{n}", n + 1
    return pid


def add(path: Path) -> dict:
    path = Path(path).resolve()
    projects = load()
    for p in projects:
        if p["path"] == str(path):
            return p
    entry = {"id": unique_id(path, {p["id"] for p in projects}), "path": str(path)}
    _save([*projects, entry])
    return entry


def remove(id_or_path: str) -> bool:
    projects = load()
    target = str(Path(id_or_path).resolve()) if os.sep in id_or_path else None
    keep = [p for p in projects if p["id"] != id_or_path and p["path"] != target]
    if len(keep) == len(projects):
        return False
    _save(keep)
    return True
