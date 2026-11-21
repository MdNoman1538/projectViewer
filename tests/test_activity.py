"""Live AI activity: the Claude Code hook -> server -> viewer feed."""

import io
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from projectviewer.hook import event_from_hook, send
from projectviewer.server import make_server


def post(url, payload, header=True):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if header:
        req.add_header("X-ProjectViewer", "1")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "shop"
    (root / "shop").mkdir(parents=True)
    (root / "shop/cart.py").write_text("def total():\n    return 1\n")
    srv = make_server([root], port=0, web_dir=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root
    srv.shutdown()
    srv.server_close()


def test_hook_event_for_an_edit():
    ev = event_from_hook(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "cwd": "/w/shop",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/w/shop/shop/cart.py", "old_string": "x", "new_string": "y"},
        },
        prompts=False,
    )
    assert ev == {
        "event": "PostToolUse",
        "session": "s1",
        "cwd": "/w/shop",
        "tool": "Edit",
        "file": "/w/shop/shop/cart.py",
    }


def test_prompts_are_only_recorded_when_switched_on():
    raw = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "cwd": "/w",
        "prompt": "fix the tax " * 100,
    }
    assert "prompt" not in event_from_hook(raw, prompts=False)
    ev = event_from_hook(raw, prompts=True)
    assert ev["prompt"].startswith("fix the tax") and len(ev["prompt"]) <= 500


def test_send_never_fails_or_blocks_when_no_viewer_runs():
    t = time.perf_counter()
    send(
        {"event": "PostToolUse"}, url="http://127.0.0.1:9/api/events", timeout=0.3
    )  # nothing listens on port 9
    assert time.perf_counter() - t < 1.0


def test_hook_main_always_exits_zero(monkeypatch):
    from projectviewer import hook

    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert hook.main([]) == 0


def test_events_reach_the_right_project_and_are_listed(served):
    base, root = served
    post(
        base + "/api/events",
        {
            "event": "PostToolUse",
            "session": "s1",
            "cwd": str(root),
            "tool": "Edit",
            "file": str(root / "shop/cart.py"),
        },
    )
    post(
        base + "/api/events",
        {
            "event": "PostToolUse",
            "session": "s1",
            "cwd": "/elsewhere",
            "tool": "Edit",
            "file": "/elsewhere/x.py",
        },
    )
    events = json.loads(urllib.request.urlopen(base + "/api/p/shop/events").read())
    assert [e["file"] for e in events] == ["shop/cart.py"]  # repo-relative; the unrelated event was dropped
    assert events[0]["tool"] == "Edit" and events[0]["at"] > 0
    projects = json.loads(urllib.request.urlopen(base + "/api/projects").read())
    assert projects[0]["last_activity"] == events[0]["at"]


def test_events_without_the_header_are_refused(served):
    base, root = served
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/api/events", {"event": "PostToolUse", "cwd": str(root)}, header=False)
    assert e.value.code == 403


def test_oversized_events_are_refused(served):
    base, root = served
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/api/events", {"event": "x", "cwd": str(root), "pad": "a" * 100_000})
    assert e.value.code == 413
