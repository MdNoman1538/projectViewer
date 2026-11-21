"""The local viewer server: several projects, world API, live version, source, changes, static files."""

import gzip
import json
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from projectviewer.server import make_server


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, dict(r.headers), r.read()


def getj(url):
    return json.loads(get(url)[2])


def start(roots, web):
    srv = make_server(roots, port=0, web_dir=web)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def two_projects(tmp_path):
    shop = tmp_path / "shop"
    (shop / "shop").mkdir(parents=True)
    (shop / "shop/__init__.py").write_text("")
    (shop / "shop/orders.py").write_text("def total():\n    return 1\n")
    lib = tmp_path / "library"
    (lib / "books").mkdir(parents=True)
    (lib / "books/loans.py").write_text("def lend():\n    pass\n")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>viewer</html>")
    srv, base = start([shop, lib], web)
    yield base, shop, lib
    srv.shutdown()
    srv.server_close()


def test_projects_are_listed_with_ids_and_activity(two_projects):
    base, shop, lib = two_projects
    projects = getj(base + "/api/projects")
    assert [p["id"] for p in projects] == ["shop", "library"]
    assert projects[0]["path"] == str(shop.resolve())
    assert all(p["last_change"] > 0 and p["version"] for p in projects)


def test_each_project_has_its_own_world(two_projects):
    base, _, _ = two_projects
    shop = getj(base + "/api/p/shop/world")
    lib = getj(base + "/api/p/library/world")
    assert "py:shop.orders.total" in {n["id"] for n in shop["nodes"]}
    assert "py:books.loans.lend" in {n["id"] for n in lib["nodes"]}


def test_unknown_project_is_404(two_projects):
    base, _, _ = two_projects
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/p/nope/world")
    assert e.value.code == 404


def test_world_is_gzipped_and_cached_with_etag(two_projects):
    base, _, _ = two_projects
    _, headers, body = get(base + "/api/p/shop/world", {"Accept-Encoding": "gzip"})
    assert headers.get("Content-Encoding") == "gzip"
    assert json.loads(gzip.decompress(body))["schema"] == "project-world/1"
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/p/shop/world", {"If-None-Match": headers["ETag"]})
    assert e.value.code == 304


def test_activity_follows_the_project_that_changed(two_projects):
    base, shop, _ = two_projects
    before = {p["id"]: p for p in getj(base + "/api/projects")}
    time.sleep(0.02)
    (shop / "shop/orders.py").write_text("def total():\n    return 2\n\ndef tax():\n    return 0\n")
    after = {p["id"]: p for p in getj(base + "/api/projects")}
    assert after["shop"]["version"] != before["shop"]["version"]
    assert after["shop"]["last_change"] > before["shop"]["last_change"]
    assert after["library"]["version"] == before["library"]["version"]
    world = getj(base + "/api/p/shop/world")
    assert world["version"] == after["shop"]["version"]
    assert "py:shop.orders.tax" in {n["id"] for n in world["nodes"]}


def test_source_returns_lines_of_a_project_file(two_projects):
    base, _, _ = two_projects
    assert getj(base + "/api/p/shop/source?file=shop/orders.py")["lines"][0] == "def total():"


@pytest.mark.parametrize(
    "bad", ["../etc/passwd", "/etc/passwd", "shop/../../secret.py", "nope.py", "books/loans.py"]
)
def test_source_refuses_anything_outside_the_projects_files(two_projects, bad):
    base, _, _ = two_projects
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/p/shop/source?file=" + urllib.parse.quote(bad))
    assert e.value.code == 404


def test_changes_commits_and_diff(two_projects):
    base, shop, _ = two_projects

    def git(*a):
        subprocess.run(
            ["git", "-C", str(shop), "-c", "user.name=T", "-c", "user.email=t@example.com", *a],
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "feat: orders\n\nChanges:\n- shop/orders.py::total: new. Order total.")
    commits = getj(base + "/api/p/shop/commits")
    assert commits[0]["subject"] == "feat: orders" and commits[0]["notes"] == 1
    cs = getj(base + f"/api/p/shop/changes?ref={commits[0]['sha']}")
    assert cs["changed"]["py:shop.orders.total"] == "new"
    assert cs["notes"][0]["node"] == "py:shop.orders.total"
    (shop / "shop/orders.py").write_text("def total():\n    return 3\n")
    live = getj(base + "/api/p/shop/changes?ref=working")
    assert live["changed"]["py:shop.orders.total"] == "modified"
    patch = getj(base + "/api/p/shop/diff?ref=working&file=shop/orders.py")["diff"]
    assert "-    return 1" in patch and "+    return 3" in patch


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "HEAD;rm", "../x", ""])
def test_changes_refuse_odd_refs(two_projects, ref):
    base, _, _ = two_projects
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/p/shop/changes?ref=" + urllib.parse.quote(ref))
    assert e.value.code == 400


def test_static_files_and_spa_fallback(two_projects):
    base, _, _ = two_projects
    assert get(base + "/")[2] == b"<html>viewer</html>"
    assert get(base + "/some/client/route")[2] == b"<html>viewer</html>"


def test_missing_viewer_build_shows_instructions(tmp_path):
    (tmp_path / "a.py").write_text("")
    srv, base = start([tmp_path], tmp_path / "does-not-exist")
    try:
        assert "npm run build" in get(base + "/")[2].decode()
    finally:
        srv.shutdown()
        srv.server_close()


def test_binds_to_localhost_only(tmp_path):
    srv = make_server([tmp_path], port=0, web_dir=tmp_path)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_registry_add_list_remove(tmp_path, monkeypatch):
    from projectviewer import registry

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert registry.add(tmp_path / "a")["id"] == "a"
    assert registry.add(tmp_path / "a")["id"] == "a"  # adding twice is harmless
    registry.add(tmp_path / "b")
    assert [p["id"] for p in registry.load()] == ["a", "b"]
    assert registry.remove("a") is True
    assert [p["id"] for p in registry.load()] == ["b"]
