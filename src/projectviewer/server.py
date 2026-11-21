"""Local viewer server: serves the world of ONE repository, live.

- GET /api/version  -> {"version": v}   cheap fingerprint of the repo's Python files (paths, mtimes, sizes)
- GET /api/world    -> the world (gzip if accepted; ETag = version, 304 when unchanged)
- GET /api/source?file=<repo-relative path>  -> {"file", "lines"}  only files the analyser itself found
- everything else   -> the built viewer (viewer/dist), with single-page-app fallback to index.html

Binds to 127.0.0.1 only: nothing is reachable from other machines.
The browser polls /api/version and re-fetches the world when it changes. The Phase 4 service will
push changes instead (Server-Sent Events).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from projectviewer.analyzers.python import map_repo
from projectviewer.analyzers.python.mapper import discover
from projectviewer.cache import Cache

DEFAULT_WEB_DIR = Path(__file__).resolve().parents[2] / "viewer" / "dist"
MAX_SOURCE_BYTES = 2_000_000
NOT_BUILT = (
    "<!doctype html><meta charset=utf-8><title>projectViewer</title>"
    "<body style='font:15px system-ui;background:#0f1622;color:#e4ecf8;padding:40px'>"
    "<h2>The viewer is not built yet</h2><p>Run once:</p>"
    "<pre>cd viewer &amp;&amp; npm ci &amp;&amp; npm run build</pre>"
    "<p>The API is running: <a style='color:#85b7eb' href='/api/world'>/api/world</a></p>"
)


class LiveWorld:
    """The current world of a repo, rebuilt only when its files change."""

    def __init__(self, root: Path, cache: Cache | None):
        self.root = Path(root).resolve()
        self.cache = cache
        self._lock = threading.Lock()
        self._version: str | None = None
        self._body: bytes = b""
        self._gz: bytes = b""
        self._files: frozenset[str] = frozenset()

    def version(self) -> str:
        h = hashlib.sha1()
        for rel in discover(self.root):
            try:
                st = (self.root / rel).stat()
            except FileNotFoundError:
                continue
            h.update(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
        return h.hexdigest()[:16]

    def current(self) -> tuple[str, bytes, bytes]:
        """(version, json bytes, gzipped json bytes); re-maps only if the version changed."""
        with self._lock:
            v = self.version()
            if v != self._version:
                world = map_repo(self.root, cache=self.cache)
                world["version"] = v
                self._body = json.dumps(world, separators=(",", ":")).encode()
                self._gz = gzip.compress(self._body, compresslevel=5)
                self._files = frozenset(n["file"] for n in world["nodes"] if n["kind"] == "file")
                self._version = v
            return self._version, self._body, self._gz

    def is_project_file(self, rel: str) -> bool:
        if not self._files:
            self.current()
        return rel in self._files


def make_server(
    root: Path,
    port: int = 8765,
    web_dir: Path | None = None,
    cache: Cache | None = None,
) -> ThreadingHTTPServer:
    live = LiveWorld(root, cache)
    web = Path(web_dir or DEFAULT_WEB_DIR).resolve()

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
            try:
                if path == "/api/version":
                    return self._json({"version": live.version()})
                if path == "/api/world":
                    return self._world()
                if path == "/api/source":
                    return self._source(parse_qs(url.query).get("file", [""])[0])
                return self._static(path)
            except BrokenPipeError:
                return None

        do_HEAD = do_GET

        def _world(self):
            version, body, gz = live.current()
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

        def _source(self, rel: str):
            # Only files the analyser found in this repo: no paths outside it, no other file types.
            if not rel or not live.is_project_file(rel):
                return self._json({"error": "not a project file"}, HTTPStatus.NOT_FOUND)
            f = live.root / rel
            if f.stat().st_size > MAX_SOURCE_BYTES:
                return self._json({"error": "file too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            text = f.read_text(encoding="utf-8", errors="replace")
            self._json({"file": rel, "lines": text.splitlines()})

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

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
