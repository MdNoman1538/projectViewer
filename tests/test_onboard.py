"""Getting a project ready: the settings merge never damages anything, the doctor tells the truth,
and the Claude Code plugin can never block the agent (ADR-0008)."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from projectviewer import onboard, registry

REPO = Path(__file__).resolve().parents[1]
CMD = "/opt/pv/bin/projectviewer hook >/dev/null 2>&1 || true"


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """Keep the registry out of the real ~/.config."""
    monkeypatch.setattr(registry, "config_file", lambda: tmp_path / "config" / "projects.json")
    return tmp_path


def commands(data: dict) -> list[str]:
    return [h["command"] for groups in data.get("hooks", {}).values() for g in groups for h in g["hooks"]]


# ------------------------------------------------------------------ settings merge


def test_install_into_a_missing_settings_file(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    changes = onboard.install_hook(settings, CMD)
    data = json.loads(settings.read_text())
    assert sorted(changes) == ["added PostToolUse", "added Stop", "added UserPromptSubmit"]
    assert data["hooks"]["PostToolUse"][0]["matcher"] == "Edit|Write|MultiEdit"
    assert commands(data) == [CMD] * 3


def test_install_keeps_every_other_setting_and_hook(tmp_path):
    settings = tmp_path / "settings.json"
    mine = {
        "model": "opus",
        "hooks": {
            "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "prettier"}]}]
        },
    }
    settings.write_text(json.dumps(mine))
    onboard.install_hook(settings, CMD)
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert "prettier" in commands(data)
    assert commands(data).count(CMD) == 3
    assert json.loads((tmp_path / "settings.json.projectviewer-backup").read_text()) == mine


def test_install_twice_changes_nothing_the_second_time(tmp_path):
    settings = tmp_path / "settings.json"
    onboard.install_hook(settings, CMD)
    before = settings.read_text()
    assert onboard.install_hook(settings, CMD) == []
    assert settings.read_text() == before


def test_install_updates_an_older_projectviewer_hook_instead_of_duplicating(tmp_path):
    settings = tmp_path / "settings.json"
    onboard.install_hook(settings, "/old/projectviewer hook")
    changes = onboard.install_hook(settings, CMD)
    assert sorted(changes) == ["updated PostToolUse", "updated Stop", "updated UserPromptSubmit"]
    assert commands(json.loads(settings.read_text())) == [CMD] * 3


def test_invalid_settings_are_refused_and_left_untouched(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus",')  # broken JSON: someone else's problem, not ours to "fix"
    with pytest.raises(onboard.SettingsError):
        onboard.install_hook(settings, CMD)
    assert settings.read_text() == '{"model": "opus",'


def test_unhook_removes_only_projectviewer(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {"matcher": "Write", "hooks": [{"type": "command", "command": "prettier"}]}
                    ]
                }
            }
        )
    )
    onboard.install_hook(settings, CMD)
    assert onboard.uninstall_hook(settings) == 3
    data = json.loads(settings.read_text())
    assert commands(data) == ["prettier"]
    assert set(data["hooks"]) == {"PostToolUse"}


def test_every_generated_hook_command_is_guarded():
    for prompts in (False, True):
        assert onboard.hook_command("/x/projectviewer", prompts=prompts).endswith(">/dev/null 2>&1 || true")
    assert "--prompts" in onboard.hook_command("/x/projectviewer", prompts=True)
    assert "--prompts" not in onboard.hook_command("/x/projectviewer")


# ------------------------------------------------------------------ doctor


def _status(checks, label_start):
    return next(c.status for c in checks if c.label.startswith(label_start))


def test_doctor_on_a_ready_project(tmp_path, config_home):
    project = tmp_path / "shop"
    project.mkdir()
    (project / "app.py").write_text("def main():\n    pass\n")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    registry.add(project)
    settings = tmp_path / "settings.json"
    onboard.install_hook(settings, CMD)
    checks = onboard.doctor(project, port=1, settings=settings)  # port 1: nothing listens
    assert _status(checks, "Python code") == "ok"
    assert _status(checks, "Project subscribed") == "ok"
    assert _status(checks, "Git repository") == "ok"
    assert _status(checks, "AI activity hook") == "ok"
    assert _status(checks, "Viewer not running") == "warn"
    assert _status(checks, "Viewer files") == "ok"  # the built viewer ships inside the package


def test_doctor_says_python_only_and_how_to_subscribe(tmp_path, config_home):
    project = tmp_path / "webapp"
    project.mkdir()
    (project / "index.ts").write_text("export const x = 1;\n")
    checks = onboard.doctor(project, port=1, settings=tmp_path / "none.json")
    py = next(c for c in checks if c.label.startswith("Python code"))
    assert py.status == "fail" and "Python projects only" in py.detail
    sub = next(c for c in checks if c.label.startswith("Project subscribed"))
    assert sub.status == "fail" and "projectviewer setup" in sub.detail


def test_python_files_ignores_virtual_environments(tmp_path):
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.py").write_text("")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.py").write_text("")
    assert onboard.python_files(tmp_path) == 0


# ------------------------------------------------------------------ the Claude Code plugin (fitness checks)


def test_marketplace_and_plugin_agree():
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    entry = next(p for p in market["plugins"] if p["name"] == "projectviewer")
    plugin_dir = REPO / entry["source"]
    manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == entry["name"]  # a mismatch makes the plugin uninstallable
    assert entry["source"].startswith("./")


def test_every_plugin_hook_is_guarded_so_it_can_never_block_claude():
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]
    cmds = [h["command"] for groups in hooks.values() for g in groups for h in g["hooks"]]
    assert cmds
    for c in cmds:
        assert c.endswith(">/dev/null 2>&1 || true"), c
        assert "--prompts" not in c  # recording prompt text is opt-in, never a plugin default


def test_every_skill_has_a_description_and_says_python_only():
    skills = sorted((REPO / "plugin" / "skills").glob("*/SKILL.md"))
    assert len(skills) >= 2
    for path in skills:
        text = path.read_text()
        front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        assert front and re.search(r"^description: .{40,}", front.group(1), re.M), path
        assert "Python" in text, path
        assert len(text.splitlines()) < 500, path
