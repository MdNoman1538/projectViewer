"""projectviewer command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from projectviewer.analyzers.python import map_repo
from projectviewer.cache import Cache


def _summary(world: dict) -> str:
    s = world["stats"]
    n, c = s["nodes"], s["calls"]
    linked = c["resolved"] / max(1, c["resolved"] + c["unresolved_named"])
    return (
        f"{s['files']['total']} files ({s['files']['errors']} with errors) · "
        f"{n.get('class', 0)} classes · {n.get('function', 0)} functions · "
        f"{n.get('endpoint', 0)} endpoints · {n.get('table', 0)} tables · {sum(s['edges'].values())} links\n"
        f"calls: {c['resolved']} linked, {c['unresolved']} unresolved, of which {c['unresolved_named']} "
        f"look like project calls ({linked:.0%} linked) · {c['external']} to libraries, {c['builtin']} builtin, "
        f"{c['local']} to inner functions · HTTP: {s['http']['matched']}/{s['http']['total']} test requests "
        f"matched to endpoints\n"
        f"cache: {s['cache']['hits']} hits / {s['cache']['misses']} misses · "
        f"{s['seconds']['total'] * 1000:.0f} ms (extract {s['seconds']['extract'] * 1000:.0f}, "
        f"resolve {s['seconds']['resolve'] * 1000:.0f})"
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:  # Claude Code hook: fast path, never fails (see hook.py)
        from projectviewer.hook import main as hook_main

        return hook_main(argv[1:])
    ap = argparse.ArgumentParser(prog="projectviewer", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="Map a repository into a project-world/1 JSON document")
    m.add_argument("root", type=Path, help="repository to map")
    m.add_argument("-o", "--output", type=Path, help="write the world here (default: stdout)")
    m.add_argument("--no-cache", action="store_true", help="analyse every file again")
    m.add_argument("--cache-dir", type=Path, help="cache location (default: ~/.cache/projectviewer)")
    s = sub.add_parser("serve", help="Open the live viewer for your subscribed projects (and any given here)")
    s.add_argument("roots", type=Path, nargs="*", help="repositories to add before serving")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open the browser")
    s.add_argument("--cache-dir", type=Path, help="cache location (default: ~/.cache/projectviewer)")
    a = sub.add_parser("add", help="Subscribe a repository (shown in the viewer)")
    a.add_argument("root", type=Path)
    r = sub.add_parser("remove", help="Unsubscribe a repository (by id or path)")
    r.add_argument("project")
    sub.add_parser("list", help="List subscribed repositories")
    sub.add_parser(
        "hook", help="Claude Code hook: report AI activity to the viewer (reads the event on stdin)"
    )
    args = ap.parse_args(argv)

    if args.cmd in ("add", "remove", "list"):
        from projectviewer import registry

        if args.cmd == "add":
            if not args.root.is_dir():
                ap.error(f"not a directory: {args.root}")
            p = registry.add(args.root)
            print(f"subscribed: {p['id']}  {p['path']}")
        elif args.cmd == "remove":
            print("removed" if registry.remove(args.project) else f"not subscribed: {args.project}")
        for p in registry.load() if args.cmd == "list" else []:
            print(f"{p['id']:24s} {p['path']}")
        return 0

    if args.cmd == "serve":
        from projectviewer import registry
        from projectviewer.server import make_server

        for root in args.roots:
            if not root.is_dir():
                ap.error(f"not a directory: {root}")
            registry.add(root)
        subscribed = registry.load()
        if not subscribed:
            ap.error("no projects yet: run `projectviewer add <repo>` or `projectviewer serve <repo>`")
        srv = make_server(
            [Path(p["path"]) for p in subscribed],
            port=args.port,
            cache=Cache(args.cache_dir),
            ids=[p["id"] for p in subscribed],
        )
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        names = ", ".join(p["id"] for p in subscribed)
        print(f"projectViewer: {names} -> {url}   (Ctrl+C to stop)", file=sys.stderr)
        if args.open:
            import webbrowser

            webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
        return 0

    if args.cmd == "map":
        if not args.root.is_dir():
            ap.error(f"not a directory: {args.root}")
        world = map_repo(args.root, cache=None if args.no_cache else Cache(args.cache_dir))
        text = json.dumps(world, separators=(",", ":"))
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text + "\n")
        print(_summary(world), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
