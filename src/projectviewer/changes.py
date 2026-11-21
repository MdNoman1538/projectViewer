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
    """The bullet list under a line `Changes:` (until a blank line or a non-bullet, non-indented line)."""
    notes: list[dict] = []
    inside = False
    for line in message.splitlines():
        if line.strip().lower() == "changes:":
            inside = True
            continue
        if not inside:
            continue
        if not line.strip():
            break
        m = _NOTE.match(line)
        if m:
            notes.append({"path": m.group(1), "symbol": m.group(2), "text": m.group(3).strip()})
        elif line.startswith((" ", "\t")) and notes:
            notes[-1]["text"] = f"{notes[-1]['text']} {line.strip()}"
        else:
            break
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


def diff_worlds(before: dict, after: dict, diff_text: str, max_hops: int = MAX_HOPS) -> dict:
    bn = {n["id"]: n for n in before.get("nodes", [])}
    an = {n["id"]: n for n in after.get("nodes", [])}
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
            changed[nid] = "new"
            continue
        f, a, b = n.get("file"), n.get("line") or 0, n.get("end_line") or n.get("line") or 0
        touched = f in ranges and (
            n["kind"] == "file"
            or (n["kind"] in CODE_KINDS and any(a <= hi and lo <= b for lo, hi in ranges[f]))
        )
        if touched:
            changed[nid] = "modified"
    # a container counts as changed by its members when they explain the change
    for nid, how in list(changed.items()):
        if (
            how == "modified"
            and an[nid]["kind"] in ("class", "file")
            and any(k in changed for k in kids[nid])
        ):
            changed[nid] = "contains"
    removed = sorted(nid for nid, n in bn.items() if nid not in an and n["kind"] != "group")

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
        "removed": removed,
        "upstream": reach(rev),
        "downstream": reach(fwd),
        "files": sorted(ranges),
    }


# ---------------------------------------------------------------- change sets for refs


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
        diff = _git(root, "diff", "-U0", base or EMPTY_TREE, "--", "*.py") or ""
        untracked = (_git(root, "ls-files", "--others", "--exclude-standard", "--", "*.py") or "").split()
        for path in untracked:  # new files: every line is new
            diff += f"\n+++ b/{path}\n@@ -0,0 +1,{max(1, (root / path).read_text(errors='replace').count(chr(10)))} @@\n"
        cs = diff_worlds(before, after, diff)
        cs.update(ref="working", sha=None, subject="Uncommitted changes", message="", refs=[], notes=[])
        return cs

    sha = (_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}") or "").strip()
    if not sha:
        raise ValueError(f"unknown revision: {ref}")
    parent = (_git(root, "rev-parse", "--verify", "-q", f"{sha}^") or "").strip()
    before = map_revision(root, parent, cache) if parent else {"nodes": [], "edges": []}
    after = map_revision(root, sha, cache)
    diff = _git(root, "diff", "-U0", parent or EMPTY_TREE, sha, "--", "*.py") or ""
    cs = diff_worlds(before, after, diff)
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
    """Unified diff of one file for a change set (the "how")."""
    root = Path(root).resolve()
    if ref == "working":
        tracked = _git(root, "ls-files", "--error-unmatch", "--", path)
        if tracked is None:  # untracked: show the whole file as added
            text = (root / path).read_text(errors="replace")
            return "".join(f"+{line}\n" for line in text.splitlines())
        return _git(root, "diff", "HEAD", "--", path) or ""
    parent = (_git(root, "rev-parse", "--verify", "-q", f"{ref}^") or "").strip()
    return _git(root, "diff", parent or EMPTY_TREE, ref, "--", path) or ""
