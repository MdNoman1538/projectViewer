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
    linked = c["resolved"] / max(1, c["resolved"] + c["unresolved"])
    return (
        f"{s['files']['total']} files ({s['files']['errors']} with errors) · "
        f"{n.get('class', 0)} classes · {n.get('function', 0)} functions · "
        f"{n.get('endpoint', 0)} endpoints · {n.get('table', 0)} tables · {sum(s['edges'].values())} links\n"
        f"calls: {c['resolved']} linked, {c['unresolved']} unresolved ({linked:.0%} of project calls linked), "
        f"{c['external']} to libraries, {c['builtin']} builtin\n"
        f"cache: {s['cache']['hits']} hits / {s['cache']['misses']} misses · "
        f"{s['seconds']['total'] * 1000:.0f} ms (extract {s['seconds']['extract'] * 1000:.0f}, "
        f"resolve {s['seconds']['resolve'] * 1000:.0f})"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="projectviewer", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="Map a repository into a project-world/1 JSON document")
    m.add_argument("root", type=Path, help="repository to map")
    m.add_argument("-o", "--output", type=Path, help="write the world here (default: stdout)")
    m.add_argument("--no-cache", action="store_true", help="analyse every file again")
    m.add_argument("--cache-dir", type=Path, help="cache location (default: ~/.cache/projectviewer)")
    s = sub.add_parser("serve", help="Open a live map of a repository in the browser")
    s.add_argument("root", type=Path, help="repository to view")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open the browser")
    s.add_argument("--cache-dir", type=Path, help="cache location (default: ~/.cache/projectviewer)")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from projectviewer.server import make_server

        if not args.root.is_dir():
            ap.error(f"not a directory: {args.root}")
        srv = make_server(args.root, port=args.port, cache=Cache(args.cache_dir))
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        print(f"projectViewer: {args.root.resolve()} -> {url}   (Ctrl+C to stop)", file=sys.stderr)
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
