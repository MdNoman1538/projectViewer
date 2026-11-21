"""What changed, where, why, and what it affects.

A change set compares two worlds: a commit with its parent, or the live working copy with HEAD.
- changed:    nodes whose lines changed ("modified"), that did not exist before ("new"), or that only
              contain changed members ("contains")
- removed:    nodes that no longer exist
- upstream:   who depends on the change (callers, endpoints, tests): {node: steps away}
- downstream: what the change reaches (callees, tables): {node: steps away}
- notes:      the author's explanation per symbol, from the commit message's "Changes:" section
              (`- path::Qualified.name: text` or `- path: text`). Ported and adapted from PR World
              v5's world_diff (same idea: line ranges of the diff, then impact through the graph).
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict, deque
from pathlib import Path

from projectviewer.analyzers.python.extract import module_name
from projectviewer.analyzers.python.mapper import _git, map_repo, map_revision
from projectviewer.cache import Cache

CODE_KINDS = {"function", "script", "endpoint", "class"}
FORWARD = {"calls", "instantiates", "routes", "reads", "writes", "requests"}  # what a change reaches
BACKWARD = {"calls", "instantiates", "routes", "requests"}  # who depends on a change
MAX_HOPS = 4
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's id for "no files": parent of a first commit

_NOTE = re.compile(r"^\s*[-*]\s+([^\s:]+?)(?:::([\w.<>]+))?:\s*(.*)$")
_REFS = re.compile(r"\b(?:refs|closes|fixes|resolves)\s+#(\d+)", re.I)


# ---------------------------------------------------------------- notes and refs from commit messages


def parse_notes(message: str) -> list[dict]:
    """The bullet lists under every line `Changes:` (each until a blank line or a non-bullet,
    non-indented line). Several sections occur when commits are squashed into one."""
    notes: list[dict] = []
    inside = False
    for line in message.splitlines():
        if line.strip().lower() == "changes:":
            inside = True
            continue
        if not inside:
            continue
        if not line.strip():
            inside = False
            continue
        m = _NOTE.match(line)
        if m:
            notes.append({"path": m.group(1), "symbol": m.group(2), "text": m.group(3).strip()})
        elif line.startswith((" ", "\t")) and notes:
            notes[-1]["text"] = f"{notes[-1]['text']} {line.strip()}"
        else:
            inside = False
    return notes


def parse_refs(message: str) -> list[int]:
    return sorted({int(n) for n in _REFS.findall(message)})


def note_target(note: dict) -> str:
    """Node id a note talks about: a symbol (py:module.Qual.name) or a whole file."""
    if note["symbol"]:
        return f"py:{module_name(note['path'])}.{note['symbol']}"
    return f"file:{note['path']}"


# ---------------------------------------------------------------- diff of two worlds


def changed_lines(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """`git diff -U0` -> {file: [(first, last)]} on the new side. Pure deletions mark the line where
    they happened."""
    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    cur = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            cur = None if line.endswith("/dev/null") else line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@") and cur:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                ranges[cur].append((start, start + max(count, 1) - 1))
    return dict(ranges)


def renames(root: Path, *revs: str) -> dict[str, str]:
    """{new path: old path} for files git sees as moved (rename detection, -M)."""
    out = _git(root, "diff", "-M", "--name-status", "-z", *revs, "--", "*.py") or ""
    parts = out.split("\0")
    moved, i = {}, 0
    while i < len(parts) - 1:
        status = parts[i]
        if status.startswith("R"):
            moved[parts[i + 2]] = parts[i + 1]
            i += 3
        elif status:
            i += 2
        else:
            i += 1
    return moved


def _old_id(nid: str, node: dict, moved: dict[str, str]) -> str | None:
    """The id the same thing had before its file was moved (ids are derived from paths)."""
    old_path = moved.get(node.get("file") or "")
    if not old_path:
        return None
    if nid.startswith("file:"):
        return f"file:{old_path}"
    new_mod, old_mod = module_name(node["file"]), module_name(old_path)
    if nid.startswith(f"py:{new_mod}."):
        return f"py:{old_mod}.{nid[len(new_mod) + 4 :]}"
    return None


def diff_worlds(
    before: dict, after: dict, diff_text: str, max_hops: int = MAX_HOPS, moved_files: dict | None = None
) -> dict:
    bn = {n["id"]: n for n in before.get("nodes", [])}
    an = {n["id"]: n for n in after.get("nodes", [])}
    moved_files = moved_files or {}
    moved: dict[str, str] = {}
    ranges = changed_lines(diff_text)
    kids: dict[str, list[str]] = defaultdict(list)
    for n in an.values():
        if n["parent"]:
            kids[n["parent"]].append(n["id"])

    changed: dict[str, str] = {}
    for nid, n in an.items():
        if n["kind"] == "group":
            continue
        if nid not in bn:
            old = _old_id(nid, n, moved_files)
            if old and old in bn:
                moved[nid] = old  # same code, new place: not new, not removed
            else:
                changed[nid] = "new"
                continue
        f, a, b = n.get("file"), n.get("line") or 0, n.get("end_line") or n.get("line") or 0
        touched = f in ranges and (
            n["kind"] == "file"
            or (n["kind"] in CODE_KINDS and any(a <= hi and lo <= b for lo, hi in ranges[f]))
        )
        if touched:
            changed[nid] = "modified"
        elif nid in moved:
            changed[nid] = "moved"
    # a container counts as changed by its members when they explain the change
    for nid, how in list(changed.items()):
        if (
            how == "modified"
            and an[nid]["kind"] in ("class", "file")
            and any(changed.get(k) in ("new", "modified", "contains") for k in kids[nid])
        ):
            changed[nid] = "contains"
    moved_from = set(moved.values())
    removed = sorted(
        nid for nid, n in bn.items() if nid not in an and n["kind"] != "group" and nid not in moved_from
    )

    fwd: dict[str, list[str]] = defaultdict(list)
    rev: dict[str, list[str]] = defaultdict(list)
    for e in after.get("edges", []):
        if e["kind"] in FORWARD:
            fwd[e["source"]].append(e["target"])
        if e["kind"] in BACKWARD:
            rev[e["target"]].append(e["source"])
    seeds = [
        nid for nid, how in changed.items() if how in ("new", "modified") and an[nid]["kind"] in CODE_KINDS
    ]

    def reach(graph):
        hop = {s: 0 for s in seeds}
        q = deque(seeds)
        while q:
            cur = q.popleft()
            if hop[cur] >= max_hops:
                continue
            for nxt in graph.get(cur, []):
                if nxt not in hop:
                    hop[nxt] = hop[cur] + 1
                    q.append(nxt)
        return {k: v for k, v in hop.items() if v > 0 and k not in changed}

    return {
        "changed": changed,
        "moved": moved,
        "removed": removed,
        "upstream": reach(rev),
        "downstream": reach(fwd),
        "files": sorted(set(ranges) | set(moved_files)),
    }


# ---------------------------------------------------------------- change sets for refs


MOVE_SIMILARITY = 0.6  # like git's default rename threshold (50%), a little stricter


def _untracked(root: Path) -> list[str]:
    out = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", "*.py") or ""
    return [p for p in out.split("\0") if p]


def _blob(root: Path, rev: str, path: str) -> str:
    return _git(root, "show", f"{rev}:{path}") or ""


def _unified(old: str, new: str, old_path: str, new_path: str, context: int = 0) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), f"a/{old_path}", f"b/{new_path}", n=context, lineterm=""
    )
    return "\n".join(lines) + "\n"


def plain_moves(root: Path, base: str, untracked: list[str]) -> dict[str, str]:
    """{new path: old path} for files moved WITHOUT git (plain `mv`, an editor rename): a tracked file
    that disappeared and an untracked file with similar content. git cannot see these yet."""
    deleted = [p for p in (_git(root, "ls-files", "--deleted", "-z", "--", "*.py") or "").split("\0") if p]
    if not deleted or not untracked:
        return {}
    olds = {d: _blob(root, base, d).splitlines() for d in deleted}
    pairs = []
    for u in untracked:
        new = (root / u).read_text(errors="replace").splitlines()
        for d, old in olds.items():
            ratio = 1.0 if old == new else difflib.SequenceMatcher(None, old, new).ratio()
            if ratio >= MOVE_SIMILARITY:
                pairs.append((ratio, u, d))
    moved, used = {}, set()
    for _, u, d in sorted(pairs, reverse=True):  # best matches first, each file used once
        if u not in moved and d not in used:
            moved[u] = d
            used.add(d)
    return moved


def working_moves(root: Path, base: str) -> dict[str, str]:
    """All moves in the working copy: git-tracked (`git mv`, staged) and plain ones."""
    return {**renames(root, base), **plain_moves(root, base, _untracked(root))}


def _message(root: Path, sha: str) -> str:
    return _git(root, "log", "-1", "--format=%B", sha) or ""


def change_set(root: Path, ref: str, cache: Cache | None = None, after: dict | None = None) -> dict:
    """ref = "working" (uncommitted changes vs HEAD, including untracked files) or a commit."""
    root = Path(root).resolve()
    if ref == "working":
        head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
        base = head.strip() if head else None
        before = map_revision(root, base, cache) if base else {"nodes": [], "edges": []}
        after = after or map_repo(root, cache)
        diff = _git(root, "diff", "-U0", "-M", base or EMPTY_TREE, "--", "*.py") or ""
        moves = working_moves(root, base) if base else {}
        for path in _untracked(root):
            text = (root / path).read_text(errors="replace")
            if path in moves:  # moved without git: only the real edits count as changed lines
                diff += "\n" + _unified(_blob(root, base, moves[path]), text, moves[path], path)
            else:  # a new file: every line is new
                diff += f"\n+++ b/{path}\n@@ -0,0 +1,{max(1, text.count(chr(10)))} @@\n"
        cs = diff_worlds(before, after, diff, moved_files=moves)
        cs.update(ref="working", sha=None, subject="Uncommitted changes", message="", refs=[], notes=[])
        return cs

    sha = (_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}") or "").strip()
    if not sha:
        raise ValueError(f"unknown revision: {ref}")
    parent = (_git(root, "rev-parse", "--verify", "-q", f"{sha}^") or "").strip()
    before = map_revision(root, parent, cache) if parent else {"nodes": [], "edges": []}
    after = map_revision(root, sha, cache)
    diff = _git(root, "diff", "-U0", "-M", parent or EMPTY_TREE, sha, "--", "*.py") or ""
    cs = diff_worlds(before, after, diff, moved_files=renames(root, parent, sha) if parent else {})
    message = _message(root, sha)
    ids = {n["id"] for n in after["nodes"]}
    notes = []
    for note in parse_notes(message):
        target = note_target(note)
        notes.append({**note, "node": target if target in ids else None})
    cs.update(
        ref=ref,
        sha=sha,
        subject=message.splitlines()[0] if message else "",
        message=message,
        refs=parse_refs(message),
        notes=notes,
    )
    return cs


def commit_list(root: Path, limit: int = 40) -> list[dict]:
    """Recent commits, newest first, with how many change notes and issue references each has."""
    sep, end = "\x1f", "\x1e"
    out = _git(Path(root), "log", f"-{limit}", f"--format=%H{sep}%h{sep}%an{sep}%aI{sep}%B{end}") or ""
    commits = []
    for rec in out.split(end):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, short, author, date, message = rec.split(sep, 4)
        commits.append(
            {
                "sha": sha,
                "short": short,
                "author": author,
                "date": date,
                "subject": message.splitlines()[0] if message else "",
                "notes": len(parse_notes(message)),
                "refs": parse_refs(message),
            }
        )
    return commits


def file_diff(root: Path, ref: str, path: str) -> str:
    """Unified diff of one file for a change set (the "how"). For a moved file it compares with the
    old path, so it shows only the real edits, not the whole file as new."""
    root = Path(root).resolve()
    if ref == "working":
        head = (_git(root, "rev-parse", "--verify", "-q", "HEAD") or "").strip()
        moves = working_moves(root, head) if head else {}
        tracked = _git(root, "ls-files", "--error-unmatch", "--", path) is not None
        if path in moves and not tracked:  # plain `mv`: git has no rename to show, so diff ourselves
            return _unified(
                _blob(root, head, moves[path]),
                (root / path).read_text(errors="replace"),
                moves[path],
                path,
                3,
            )
        if not tracked:  # a new untracked file: all of it is added
            text = (root / path).read_text(errors="replace")
            return "".join(f"+{line}\n" for line in text.splitlines())
        paths = [moves[path], path] if path in moves else [path]
        return _git(root, "diff", "-M", head or EMPTY_TREE, "--", *paths) or ""
    parent = (_git(root, "rev-parse", "--verify", "-q", f"{ref}^") or "").strip()
    moves = renames(root, parent, ref) if parent else {}
    paths = [moves[path], path] if path in moves else [path]
    return _git(root, "diff", "-M", parent or EMPTY_TREE, ref, "--", *paths) or ""
