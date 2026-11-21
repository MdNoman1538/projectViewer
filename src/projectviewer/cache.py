"""Content-addressed cache of per-file analysis results (ADR-0003).

Key = sha256(analyser version, file path, file bytes). Unchanged files are never parsed twice,
across commits, branches and repositories. Lives outside analysed projects (~/.cache/projectviewer).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def default_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "projectviewer"


class Cache:
    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory) if directory else default_dir()

    @staticmethod
    def key(version: str, path: str, data: bytes) -> str:
        h = hashlib.sha256()
        h.update(version.encode())
        h.update(b"\0")
        h.update(path.encode())
        h.update(b"\0")
        h.update(data)
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        try:
            return json.loads(self._path(key).read_bytes())
        except (FileNotFoundError, json.JSONDecodeError):
            return None  # a corrupt entry is treated as a miss and rewritten

    def put(self, key: str, value: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, p)  # atomic: readers never see a half-written file
