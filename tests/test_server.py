"""The local viewer server: world API, live version, source access, static files."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from projectviewer.server import make_server


@pytest.fixture
def served(project, tmp_path):
    """Start a server on a free port for a small fixture project; yield (base_url, root)."""
    root = project({"shop/__init__.py": "", "shop/orders.py": "def total():\n    return 1\n"})
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>viewer</html>")
    srv = make_server(root, port=0, web_dir=web)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root
    srv.shutdown()
    srv.server_close()


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, dict(r.headers), r.read()


def test_world_endpoint_returns_the_mapped_project(served):
    base, _ = served
    status, headers, body = get(base + "/api/world")
    world = json.loads(body)
    assert status == 200
    assert world["schema"] == "project-world/1"
    assert "py:shop.orders.total" in {n["id"] for n in world["nodes"]}
    assert headers["ETag"].strip('"') == world["version"]


def test_world_is_gzipped_when_the_client_accepts_it(served):
    import gzip

    base, _ = served
    status, headers, body = get(base + "/api/world", {"Accept-Encoding": "gzip"})
    assert headers.get("Content-Encoding") == "gzip"
    assert json.loads(gzip.decompress(body))["schema"] == "project-world/1"


def test_unchanged_world_answers_304(served):
    base, _ = served
    _, headers, _ = get(base + "/api/world")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/world", {"If-None-Match": headers["ETag"]})
    assert e.value.code == 304


def test_version_changes_when_a_file_changes(served):
    base, root = served
    v1 = json.loads(get(base + "/api/version")[2])["version"]
    time.sleep(0.01)
    (root / "shop/orders.py").write_text("def total():\n    return 2\n\ndef tax():\n    return 0\n")
    v2 = json.loads(get(base + "/api/version")[2])["version"]
    assert v1 != v2
    world = json.loads(get(base + "/api/world")[2])
    assert world["version"] == v2
    assert "py:shop.orders.tax" in {n["id"] for n in world["nodes"]}


def test_source_returns_lines_of_a_project_file(served):
    base, _ = served
    body = json.loads(get(base + "/api/source?file=shop/orders.py")[2])
    assert body["lines"][0] == "def total():"


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "shop/../../secret.py", "nope.py"])
def test_source_refuses_anything_outside_the_projects_files(served, bad):
    base, _ = served
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/source?file=" + urllib.request.quote(bad))
    assert e.value.code == 404


def test_static_files_and_spa_fallback(served):
    base, _ = served
    assert get(base + "/")[2] == b"<html>viewer</html>"
    assert get(base + "/some/client/route")[2] == b"<html>viewer</html>"
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/../pyproject.toml")
    assert e.value.code in (400, 404)


def test_missing_viewer_build_shows_instructions(project, tmp_path):
    root = project({"a.py": ""})
    srv = make_server(root, port=0, web_dir=tmp_path / "does-not-exist")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        body = get(f"http://127.0.0.1:{srv.server_address[1]}/")[2].decode()
        assert "npm run build" in body
    finally:
        srv.shutdown()
        srv.server_close()


def test_binds_to_localhost_only(project, tmp_path):
    srv = make_server(project({"a.py": ""}), port=0, web_dir=tmp_path)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()
