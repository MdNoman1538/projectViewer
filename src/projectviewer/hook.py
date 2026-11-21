"""`projectviewer hook`: a Claude Code hook that tells the local viewer what the AI is doing.

Configured in Claude Code settings for PostToolUse (Edit|Write|MultiEdit), UserPromptSubmit and Stop.
Claude Code passes the event as JSON on stdin (fields per the Claude Code hooks reference:
hook_event_name, session_id, cwd, tool_name, tool_input.file_path, prompt).

Rules (ADR-0001): it must never slow down or break the developer. It sends one small local request
with a short timeout, ignores every error, prints nothing and always exits 0, so Claude Code sees
"no decision" and carries on, whether or not the viewer is running. Prompt text is sent only with
--prompts, and stays on this machine.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765/api/events"
MAX_PROMPT = 500


def event_from_hook(raw: dict, prompts: bool) -> dict:
    ev = {
        "event": raw.get("hook_event_name"),
        "session": raw.get("session_id"),
        "cwd": raw.get("cwd"),
    }
    if raw.get("tool_name"):
        ev["tool"] = raw["tool_name"]
    file_path = (raw.get("tool_input") or {}).get("file_path")
    if file_path:
        ev["file"] = file_path
    if prompts and raw.get("prompt"):
        ev["prompt"] = raw["prompt"][:MAX_PROMPT]
    return {k: v for k, v in ev.items() if v is not None}


def send(event: dict, url: str = DEFAULT_URL, timeout: float = 0.3) -> None:
    try:
        req = urllib.request.Request(url, data=json.dumps(event).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-ProjectViewer", "1")
        urllib.request.urlopen(req, timeout=timeout).close()
    except Exception:  # noqa: BLE001 - the viewer may be closed; never disturb the developer
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        ap = argparse.ArgumentParser(prog="projectviewer hook")
        ap.add_argument("--prompts", action="store_true", help="also send the prompt text (local only)")
        ap.add_argument("--url", default=DEFAULT_URL)
        args = ap.parse_args(argv)
        raw = json.loads(sys.stdin.read() or "{}")
        if isinstance(raw, dict):
            send(event_from_hook(raw, args.prompts), args.url)
    except BaseException:  # noqa: BLE001 - including SystemExit from argparse: always exit 0
        pass
    return 0
