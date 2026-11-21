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


def git_files(root: Path, rev: str) -> list[tuple[str, bytes]]:
    """(path, content) of the Python files in a commit, read from git objects: the working tree is
    never touched. One `git cat-file --batch` process for all files."""
    listed = _git(root, "ls-tree", "-r", "-z", "--name-only", rev)
    if listed is None:
        return []
    paths = sorted(p for p in listed.split("\0") if p and _keep(p))
    if not paths:
        return []
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(f"{rev}:{p}\n" for p in paths).encode(),
        capture_output=True,
        check=True,
    )
    out, pos, items = proc.stdout, 0, []
    for p in paths:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":  # "missing" or not a file
            continue
        size = int(header[2])
        items.append((p, out[pos : pos + size]))
        pos += size + 1  # content is followed by a newline
    return items


def _analyse(
    items: list[tuple[str, bytes]], cache: Cache | None, workers: int | None
) -> tuple[list[dict], int]:
    """Pass 1 for (path, bytes) items: from the cache when possible, parsed (maybe in parallel) otherwise."""
    files: list[dict | None] = [None] * len(items)
    todo: list[tuple[int, str, bytes, str | None]] = []  # (index, path, bytes, cache key)
    for i, (rel, data) in enumerate(items):
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
    return files, len(todo)


def _world(root: Path, items, cache, workers, commit, dirty) -> dict:
    t0 = time.perf_counter()
    files, misses = _analyse(items, cache, workers)
    t1 = time.perf_counter()
    nodes, edges, stats = build_world(files)
    t2 = time.perf_counter()
    stats.update(
        files={"total": len(files), "errors": sum(1 for f in files if f["error"])},
        cache={"enabled": cache is not None, "hits": len(files) - misses, "misses": misses},
        seconds={"extract": round(t1 - t0, 4), "resolve": round(t2 - t1, 4), "total": round(t2 - t0, 4)},
    )
    return {
        "schema": "project-world/1",
        "generated_by": f"projectviewer {__version__} (python analyser v{EXTRACTOR_VERSION})",
        "repo": str(root),
        "commit": commit,
        "dirty": dirty,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "nodes": nodes,
        "edges": edges,
        "stats": stats,
    }


def map_repo(root: Path, cache: Cache | None = None, workers: int | None = None) -> dict:
    """The working tree (including uncommitted and untracked files). workers: processes for parsing
    cache misses. None = automatic (parallel only when there are enough misses); 1 = always serial."""
    root = Path(root).resolve()
    items = [(rel, (root / rel).read_bytes()) for rel in discover(root)]
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    dirty = bool(status.strip()) if status is not None else None
    return _world(root, items, cache, workers, head.strip() if head else None, dirty)


def map_revision(root: Path, rev: str, cache: Cache | None = None, workers: int | None = None) -> dict:
    """A commit, read from git objects (the working tree is not touched)."""
    root = Path(root).resolve()
    sha = _git(root, "rev-parse", rev)
    return _world(root, git_files(root, rev), cache, workers, sha.strip() if sha else None, False)
