"""Local viewer server for one or more projects, live.

- GET /api/projects                         -> [{id, name, path, version, last_change}]   (activity)
- GET /api/p/<id>/version                   -> {"version": v}  fingerprint of the Python files (paths, mtimes, sizes)
- GET /api/p/<id>/world                     -> the world (gzip if accepted; ETag = version, 304 when unchanged)
- GET /api/p/<id>/source?file=<path>        -> {"file", "lines"}  only files the analyser itself found
- GET /api/p/<id>/commits                   -> recent commits (subject, notes count, issue refs)
- GET /api/p/<id>/changes?ref=working|<sha> -> changed / affected / notes (see changes.py)
- GET /api/p/<id>/diff?ref=…&file=<path>    -> {"diff"} unified diff of one file in that change set
- GET /api/p/<id>/events?since=<ms>         -> recent AI activity (from the Claude Code hook)
- POST /api/events                          <- `projectviewer hook` (needs header X-ProjectViewer: 1)
- everything else                           -> the built viewer (viewer/dist), single-page-app fallback

Binds to 127.0.0.1 only: nothing is reachable from other machines. The browser polls; the Phase 4
service will push changes instead (Server-Sent Events).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import re
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from projectviewer.analyzers.python import map_repo
from projectviewer.analyzers.python.mapper import _git, discover
from projectviewer.cache import Cache
from projectviewer.changes import change_set, commit_list, file_diff
from projectviewer.registry import unique_id

DEFAULT_WEB_DIR = Path(__file__).resolve().parents[2] / "viewer" / "dist"
MAX_SOURCE_BYTES = 2_000_000
MAX_EVENT_BYTES = 16_384
EVENTS_KEPT = 200
REF = re.compile(r"^(working|[0-9a-fA-F]{4,40}|HEAD(~\d{1,4})?)$")  # never pass anything else to git
NOT_BUILT = (
    "<!doctype html><meta charset=utf-8><title>projectViewer</title>"
    "<body style='font:15px system-ui;background:#0f1622;color:#e4ecf8;padding:40px'>"
    "<h2>The viewer is not built yet</h2><p>Run once:</p>"
    "<pre>cd viewer &amp;&amp; npm ci &amp;&amp; npm run build</pre>"
    "<p>The API is running: <a style='color:#85b7eb' href='/api/projects'>/api/projects</a></p>"
)


class Project:
    """One repository: its current world (rebuilt only when files change) and its change sets."""

    def __init__(self, pid: str, root: Path, cache: Cache | None):
        self.id = pid
        self.root = Path(root).resolve()
        self.name = self.root.name
        self.cache = cache
        self._lock = threading.Lock()
        self._version: str | None = None
        self._world: dict | None = None
        self._body = b""
        self._gz = b""
        self._files: frozenset[str] = frozenset()
        self._changes: dict[tuple[str, str], dict] = {}
        self.events: deque[dict] = deque(maxlen=EVENTS_KEPT)  # recent AI activity (memory only)
        self.last_activity = 0

    def fingerprint(self) -> tuple[str, int]:
        """(version, last change in ms): cheap, from paths + mtimes + sizes of the Python files."""
        h = hashlib.sha1()
        last = 0
        for rel in discover(self.root):
            try:
                st = (self.root / rel).stat()
            except FileNotFoundError:
                continue
            last = max(last, st.st_mtime_ns)
            h.update(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
        return h.hexdigest()[:16], last // 1_000_000

    def current(self) -> tuple[str, bytes, bytes]:
        """(version, json bytes, gzipped json bytes); re-maps only if the version changed."""
        with self._lock:
            v, _ = self.fingerprint()
            if v != self._version:
                world = map_repo(self.root, cache=self.cache)
                world["version"] = v
                self._world = world
                self._body = json.dumps(world, separators=(",", ":")).encode()
                self._gz = gzip.compress(self._body, compresslevel=5)
                self._files = frozenset(n["file"] for n in world["nodes"] if n["kind"] == "file")
                self._version = v
            return self._version, self._body, self._gz

    def is_project_file(self, rel: str) -> bool:
        self.current()
        return rel in self._files

    def changes(self, ref: str) -> dict:
        version, _, _ = self.current()
        if ref != "working":  # HEAD / HEAD~n move with every commit: cache by the commit they name now
            sha = (_git(self.root, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}") or "").strip()
            if not sha:
                raise ValueError(f"unknown revision: {ref}")
            ref = sha
        key = (ref, version if ref == "working" else "")  # commits never change; the working copy does
        with self._lock:
            hit = self._changes.get(key)
        if hit is None:
            hit = change_set(self.root, ref, self.cache, after=self._world if ref == "working" else None)
            with self._lock:
                if len(self._changes) > 200:
                    self._changes.clear()
                self._changes[key] = hit
        return hit


def make_server(
    roots: Path | list[Path],
    port: int = 8765,
    web_dir: Path | None = None,
    cache: Cache | None = None,
    ids: list[str] | None = None,
) -> ThreadingHTTPServer:
    roots = [roots] if isinstance(roots, (str, Path)) else list(roots)
    projects: dict[str, Project] = {}
    for i, root in enumerate(roots):
        pid = ids[i] if ids else unique_id(Path(root).resolve(), set(projects))
        projects[pid] = Project(pid, root, cache)
    web = Path(web_dir or DEFAULT_WEB_DIR).resolve()

    def record_event(ev: dict) -> bool:
        """Attach an event to the project it happened in (by file, else working directory)."""
        where = ev.get("file") or ev.get("cwd") or ""
        try:
            where_path = Path(str(where)).resolve()
        except (OSError, ValueError):
            return False
        for p in projects.values():
            if where_path == p.root or where_path.is_relative_to(p.root):
                now = int(time.time() * 1000)
                clean = {
                    k: str(v)[:500] for k, v in ev.items() if k in ("event", "session", "tool", "prompt")
                }
                clean["at"] = now
                if ev.get("file"):
                    clean["file"] = where_path.relative_to(p.root).as_posix()
                p.events.append(clean)
                p.last_activity = now
                return True
        return False

    class Handler(BaseHTTPRequestHandler):
        server_version = "projectViewer"

        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, status, body: bytes, ctype="application/json", headers=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status=HTTPStatus.OK):
            self._send(status, json.dumps(obj).encode())

        def do_GET(self):  # noqa: N802 - http.server naming
            url = urlparse(self.path)
            path = unquote(url.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if path == "/api/projects":
                    return self._projects()
                m = re.match(r"^/api/p/([^/]+)/(\w+)$", path)
                if m:
                    p = projects.get(m.group(1))
                    if p is None:
                        return self._json({"error": "unknown project"}, HTTPStatus.NOT_FOUND)
                    return self._project(p, m.group(2), q)
                if path.startswith("/api/"):
                    return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return self._static(path)
            except BrokenPipeError:
                return None

        do_HEAD = do_GET

        def do_POST(self):  # noqa: N802 - http.server naming
            if urlparse(self.path).path != "/api/events":
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            # A custom header cannot be sent by a plain cross-site form: web pages can't inject events.
            if self.headers.get("X-ProjectViewer") != "1":
                return self._json({"error": "missing X-ProjectViewer header"}, HTTPStatus.FORBIDDEN)
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_EVENT_BYTES:
                return self._json({"error": "event too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            try:
                ev = json.loads(self.rfile.read(size) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, HTTPStatus.BAD_REQUEST)
            if not isinstance(ev, dict):
                return self._json({"error": "bad event"}, HTTPStatus.BAD_REQUEST)
            accepted = record_event(ev)
            return self._json({"accepted": accepted}, HTTPStatus.ACCEPTED)

        def _projects(self):
            out = []
            for p in projects.values():
                version, last = p.fingerprint()
                out.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "path": str(p.root),
                        "version": version,
                        "last_change": last,
                        "last_activity": p.last_activity,
                    }
                )
            self._json(out)

        def _project(self, p: Project, what: str, q: dict):
            if what == "version":
                return self._json({"version": p.fingerprint()[0]})
            if what == "world":
                return self._world(p)
            if what == "source":
                return self._source(p, q.get("file", ""))
            if what == "events":
                since = int(q.get("since", "0") or 0) if q.get("since", "0").isdigit() else 0
                return self._json([e for e in list(p.events) if e["at"] > since])
            if what == "commits":
                return self._json(commit_list(p.root))
            if what in ("changes", "diff"):
                ref = q.get("ref", "")
                if not REF.match(ref):
                    return self._json({"error": "bad ref"}, HTTPStatus.BAD_REQUEST)
                try:
                    cs = p.changes(ref)
                except ValueError as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                if what == "changes":
                    return self._json(cs)
                rel = q.get("file", "")
                if rel not in cs["files"] and not p.is_project_file(rel):
                    return self._json({"error": "not a file of this change"}, HTTPStatus.NOT_FOUND)
                return self._json({"file": rel, "diff": file_diff(p.root, ref, rel)})
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def _world(self, p: Project):
            version, body, gz = p.current()
            etag = f'"{version}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            headers = {"ETag": etag}
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                headers["Content-Encoding"] = "gzip"
                body = gz
            self._send(HTTPStatus.OK, body, headers=headers)

        def _source(self, p: Project, rel: str):
            # Only files the analyser found in this repo: no paths outside it, no other file types.
            if not rel or not p.is_project_file(rel):
                return self._json({"error": "not a project file"}, HTTPStatus.NOT_FOUND)
            f = p.root / rel
            if f.stat().st_size > MAX_SOURCE_BYTES:
                return self._json({"error": "file too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            self._json({"file": rel, "lines": f.read_text(encoding="utf-8", errors="replace").splitlines()})

        def _static(self, path: str):
            if not (web / "index.html").is_file():
                return self._send(HTTPStatus.OK, NOT_BUILT.encode(), "text/html; charset=utf-8")
            target = (web / path.lstrip("/")).resolve()
            if not target.is_relative_to(web):
                return self._json({"error": "bad path"}, HTTPStatus.BAD_REQUEST)
            if not target.is_file():
                target = web / "index.html"  # single-page app: client-side routes
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(HTTPStatus.OK, target.read_bytes(), ctype)

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.projects = projects
    return srv
