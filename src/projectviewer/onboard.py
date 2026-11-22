"""Getting a project ready for projectViewer: `setup`, `doctor` and the Claude Code hook (ADR-0008).

Two rules shape everything here:
- **Never damage the user's settings.** The settings file is merged, never replaced. An existing file
  that isn't valid JSON is refused and left untouched, a backup is written before any change, and
  the write is atomic.
- **Never block Claude.** Every hook command ends in `>/dev/null 2>&1 || true`, so it exits 0 and
  prints nothing whatever happens (exit code 2 would block the agent; see hook.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from projectviewer import registry

HOOK_EVENTS = {  # event -> matcher (None = all)
    "PostToolUse": "Edit|Write|MultiEdit",
    "UserPromptSubmit": None,
    "Stop": None,
}
GUARD = ">/dev/null 2>&1 || true"
WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".tox"}


class SettingsError(RuntimeError):
    """The settings file exists but can't be read safely; it was not changed."""


def executable() -> str:
    """An absolute command for this installation: hooks run with Claude Code's PATH, not the user's shell."""
    found = shutil.which("projectviewer")
    return found if found else f"{sys.executable} -m projectviewer.cli"


def hook_command(exe: str | None = None, prompts: bool = False) -> str:
    exe = exe or executable()
    quoted = f'"{exe}"' if " " in exe and not exe.endswith(".cli") else exe
    return f"{quoted} hook{' --prompts' if prompts else ''} {GUARD}"


def _is_ours(command: str) -> bool:
    return "projectviewer" in command and " hook" in command


def _read(settings: Path) -> dict:
    if not settings.exists():
        return {}
    try:
        data = json.loads(settings.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{settings} is not valid JSON ({exc}); not changed.") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{settings} is not a JSON object; not changed.")
    return data


def _write(settings: Path, data: dict) -> None:
    settings.parent.mkdir(parents=True, exist_ok=True)
    if settings.exists():
        shutil.copy2(settings, settings.with_name(settings.name + ".projectviewer-backup"))
    tmp = settings.with_name(settings.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, settings)  # atomic: Claude Code never reads a half-written file


def install_hook(settings: Path = DEFAULT_SETTINGS, command: str | None = None) -> list[str]:
    """Add (or update) projectViewer's hook for each event. Other settings and hooks are kept.
    Returns what changed; an empty list means it was already installed exactly like this."""
    command = command or hook_command()
    data = _read(settings)
    hooks = data.setdefault("hooks", {})
    changes = []
    for event, matcher in HOOK_EVENTS.items():
        groups = hooks.setdefault(event, [])
        mine = [h for g in groups for h in g.get("hooks", []) if _is_ours(h.get("command", ""))]
        if mine:
            for h in mine:
                if h["command"] != command or h.get("timeout") != 5:
                    h.update(command=command, timeout=5)
                    changes.append(f"updated {event}")
            continue
        group: dict = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
        if matcher:
            group = {"matcher": matcher, **group}
        groups.append(group)
        changes.append(f"added {event}")
    if changes:
        _write(settings, data)
    return changes


def uninstall_hook(settings: Path = DEFAULT_SETTINGS) -> int:
    """Remove only projectViewer's hook commands. Returns how many were removed."""
    data = _read(settings)
    removed = 0
    for event, groups in list(data.get("hooks", {}).items()):
        for g in groups:
            before = len(g.get("hooks", []))
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h.get("command", ""))]
            removed += before - len(g["hooks"])
        data["hooks"][event] = [g for g in groups if g.get("hooks")]
        if not data["hooks"][event]:
            del data["hooks"][event]
    if removed:
        _write(settings, data)
    return removed


def python_files(root: Path, limit: int = 1) -> int:
    """How many Python files the project has (stops at `limit`): projectViewer maps Python only."""
    n = 0
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        n += sum(1 for f in filenames if f.endswith(".py"))
        if n >= limit:
            return n
    return n


@dataclass
class Check:
    status: str  # "ok" | "warn" | "fail"
    label: str
    detail: str = ""


def doctor(root: Path, port: int = 8765, settings: Path = DEFAULT_SETTINGS) -> list[Check]:
    """Everything that has to be true for projectViewer to work on `root`, with how to fix it."""
    root = root.resolve()
    out = []
    ok = sys.version_info >= (3, 12)
    out.append(
        Check(
            "ok" if ok else "fail",
            f"Python {sys.version.split()[0]}",
            "" if ok else "projectViewer needs Python 3.12 or newer.",
        )
    )
    built = (WEB_DIR / "index.html").exists()
    out.append(
        Check(
            "ok" if built else "fail",
            "Viewer files installed",
            "" if built else "Reinstall projectViewer, or run `npm ci && npm run build` in viewer/.",
        )
    )
    is_git = (
        subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"], capture_output=True).returncode
        == 0
    )
    out.append(
        Check(
            "ok" if is_git else "warn",
            "Git repository",
            "" if is_git else "The map works, but changes and commit notes need git.",
        )
    )
    has_py = python_files(root) > 0
    out.append(
        Check(
            "ok" if has_py else "fail",
            "Python code found",
            "" if has_py else "projectViewer maps Python projects only (other languages are planned).",
        )
    )
    subscribed = any(Path(p["path"]).resolve() == root for p in registry.load())
    out.append(
        Check(
            "ok" if subscribed else "fail",
            "Project subscribed",
            "" if subscribed else f"Run `projectviewer setup {root}`.",
        )
    )
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects", timeout=0.5).close()
        out.append(Check("ok", f"Viewer running on http://127.0.0.1:{port}"))
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        out.append(
            Check(
                "warn", "Viewer not running", "Start it with `projectviewer serve --open` (it keeps running)."
            )
        )
    try:
        configured = any(
            _is_ours(h.get("command", ""))
            for groups in _read(settings).get("hooks", {}).values()
            for g in groups
            for h in g.get("hooks", [])
        )
    except SettingsError as exc:
        out.append(Check("fail", "Claude Code settings readable", str(exc)))
    else:
        out.append(
            Check(
                "ok" if configured else "warn",
                "AI activity hook",
                ""
                if configured
                else "Not in settings. Fine for manual coding, or if the Claude Code plugin is installed (it brings its own hook). Otherwise: `projectviewer setup --hook`.",
            )
        )
    return out
