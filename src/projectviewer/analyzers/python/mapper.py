"""Map a repository: find Python files, run pass 1 (cached) and pass 2, assemble the world."""

from __future__ import annotations

import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime
from pathlib import Path

from projectviewer import __version__
from projectviewer.cache import Cache

from .extract import EXTRACTOR_VERSION, extract
from .resolve import build_world

SKIP_DIRS = {"node_modules", "venv", "env", "__pycache__", "site-packages", "build", "dist"}
# Below this many cache misses, starting worker processes costs more than it saves (measured: see
# docs/project-status.md). Typical incremental updates touch a handful of files and stay serial.
PARALLEL_MIN_FILES = 64


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
        return r.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _keep(rel: str) -> bool:
    parts = rel.split("/")
    return rel.endswith(".py") and not any(p.startswith(".") or p in SKIP_DIRS for p in parts[:-1])


def discover(root: Path) -> list[str]:
    """Python files, as repo-relative posix paths. Uses git (respects .gitignore, includes new
    untracked files) when available, otherwise walks the directory."""
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if listed is not None:
        paths = [p for p in listed.split("\0") if p]
    else:
        paths = [p.relative_to(root).as_posix() for p in root.rglob("*.py")]
    return sorted(p for p in set(paths) if _keep(p) and (root / p).is_file())


def _extract_job(job: tuple[str, bytes]) -> dict:
    rel, data = job
    return extract(rel, data.decode("utf-8", errors="replace"))


def map_repo(root: Path, cache: Cache | None = None, workers: int | None = None) -> dict:
    """workers: processes for parsing cache misses. None = automatic (parallel only when there are
    enough misses to beat process start-up cost); 1 = always serial."""
    root = Path(root).resolve()
    t0 = time.perf_counter()
    paths = discover(root)
    files: list[dict | None] = [None] * len(paths)
    todo: list[tuple[int, str, bytes, str | None]] = []  # (index, path, bytes, cache key)
    for i, rel in enumerate(paths):
        data = (root / rel).read_bytes()
        key = Cache.key(EXTRACTOR_VERSION, rel, data) if cache else None
        facts = cache.get(key) if cache else None
        if facts is None:
            todo.append((i, rel, data, key))
        else:
            files[i] = facts

    n_workers = workers or (min(os.cpu_count() or 1, 8) if len(todo) >= PARALLEL_MIN_FILES else 1)
    jobs = [(rel, data) for _, rel, data, _ in todo]
    results = None
    if n_workers > 1:
        try:
            with ProcessPoolExecutor(max_workers=n_workers) as pool:  # pass 1 is pure: safe to parallelise
                results = list(pool.map(_extract_job, jobs, chunksize=16))
        except (BrokenProcessPool, OSError):
            # e.g. called from a REPL/stdin on macOS, where "spawn" workers cannot re-import __main__
            results = None
    if results is None:
        results = [_extract_job(j) for j in jobs]
    for (i, _, _, key), facts in zip(todo, results, strict=True):
        files[i] = facts
        if cache:
            cache.put(key, facts)
    hits, misses = len(paths) - len(todo), len(todo)
    t1 = time.perf_counter()
    nodes, edges, stats = build_world(files)
    t2 = time.perf_counter()

    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    stats.update(
        files={"total": len(files), "errors": sum(1 for f in files if f["error"])},
        cache={"enabled": cache is not None, "hits": hits, "misses": misses},
        seconds={"extract": round(t1 - t0, 4), "resolve": round(t2 - t1, 4), "total": round(t2 - t0, 4)},
    )
    return {
        "schema": "project-world/1",
        "generated_by": f"projectviewer {__version__} (python analyser v{EXTRACTOR_VERSION})",
        "repo": str(root),
        "commit": head.strip() if head else None,
        "dirty": bool(status.strip()) if status is not None else None,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "nodes": nodes,
        "edges": edges,
        "stats": stats,
    }
