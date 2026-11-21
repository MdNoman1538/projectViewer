"""Pass 2: link per-file facts into one world: nodes + edges (ADR-0002).

No parsing happens here, only lookups in memory, so it is fast even when every file came from
the cache. Resolution is deliberately conservative: a call is linked only when the target can be
derived from definitions, imports, `self`, or simple type information. Everything else is
*counted* (external / builtin / unresolved), never guessed.
"""

from __future__ import annotations

import ast
import builtins
from collections import Counter
from dataclasses import dataclass, field

from .extract import SCRIPT

PROVEN, INFERRED, PATTERN = "proven", "inferred", "pattern"
_RANK = {PROVEN: 0, INFERRED: 1, PATTERN: 2}
_BUILTINS = set(dir(builtins))
_MAX_DEPTH = 12
_TYPING_NOISE = {"None", "Optional", "Union", "typing.Optional", "typing.Union"}

Thing = tuple[str, str]  # (kind, qualified name): kind in module | class | function | instance


def _weaker(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def group_of(path: str) -> str:
    """Top-level grouping shown as a district on the map."""
    parts = path.split("/")
    if parts[0] == "src":
        return parts[1] if len(parts) > 2 else "src"
    return parts[0] if len(parts) > 1 else "(root)"


@dataclass
class Ctx:
    """Where a name is being resolved."""

    module: str
    vars: dict = field(default_factory=dict)  # local name -> type spec
    cls: str | None = None  # qualified name of the enclosing class, for `self`
    params: frozenset = frozenset()  # unannotated parameters: they shadow globals; may be pytest fixtures
    path: str | None = None  # file path, to find conftest.py fixtures


# A resolution result is one of:
#   (thing, certainty)  a project module / class / function / instance-of-a-project-class
#   EXTERNAL | BUILTIN  a library or builtin object (counted, not drawn)
#   None                unknown (counted as unresolved)
EXTERNAL, BUILTIN = "external", "builtin"


class Resolver:
    def __init__(self, files: list[dict]):
        self.files = files
        self.mods = {f["module"]: f for f in files}
        self.alias = {}  # import name without a leading "src." (src-layout projects) -> real module
        for m in self.mods:
            if m.startswith("src.") and m[4:] not in self.mods:
                self.alias.setdefault(m[4:], m)
        self.defs: dict[str, dict[str, Thing]] = {}
        self.classes: dict[str, tuple[str, dict]] = {}
        self.funcs: dict[str, tuple[str, dict]] = {}
        self.imports: dict[str, dict[str, str]] = {}
        self.fixtures: dict[str, list[tuple[str, dict]]] = {}  # fixture name -> [(module, function facts)]
        self.path_of = {f["module"]: f["path"] for f in files}
        for f in files:
            m, d = f["module"], {}
            for c in f["classes"]:
                q = f"{m}.{c['name']}"
                d[c["name"]] = ("class", q)
                self.classes[q] = (m, c)
            for fn in f["functions"]:
                q = f"{m}.{fn['qualname']}"
                self.funcs[q] = (m, fn)
                if fn["cls"] is None and fn["name"] != SCRIPT:
                    d[fn["name"]] = ("function", q)
                    if any("fixture" in dec for dec in fn["decorators"]):
                        self.fixtures.setdefault(fn["name"], []).append((m, fn))
            self.defs[m] = d
            self.imports[m] = {i["alias"]: i["target"] for i in f["imports"] if i["alias"]}
        self._mro_cache: dict[str, list[str]] = {}

    # ------------------------------------------------------------ helpers

    def canonical(self, module: str) -> str | None:
        if module in self.mods:
            return module
        return self.alias.get(module)

    def _instance(self, t):
        """type_of() result -> resolution result."""
        if t in (EXTERNAL, BUILTIN):
            return t
        return (("instance", t), INFERRED) if t else None

    # ------------------------------------------------------------ lookups

    def resolve_dotted(self, dotted: str, depth: int = 0):
        """'pkg.mod.Class.method' -> result, following re-exports."""
        if depth > _MAX_DEPTH:
            return None
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            mod = self.canonical(".".join(parts[:i]))
            if mod is None:
                continue
            thing, cert = ("module", mod), PROVEN
            for attr in parts[i:]:
                r = self.member(thing, attr, depth + 1)
                if not isinstance(r, tuple):
                    return r
                thing, c = r
                cert = _weaker(cert, c)
            return thing, cert
        return None

    def member(self, thing: Thing, attr: str, depth: int):
        if depth > _MAX_DEPTH:
            return None
        kind, q = thing
        if kind == "module":
            sub = self.canonical(f"{q}.{attr}")
            if sub:
                return ("module", sub), PROVEN
            if attr in self.defs.get(q, {}):
                return self.defs[q][attr], PROVEN
            if attr in self.imports.get(q, {}):  # re-export, e.g. a package __init__
                return self.resolve_dotted(self.imports[q][attr], depth + 1) or EXTERNAL
            spec = self.mods[q]["module_vars"].get(attr)
            return self._instance(self.type_of(spec, Ctx(q), depth + 1)) if spec else None
        if kind in ("class", "instance"):
            for c in self.mro(q):
                if f"{c}.{attr}" in self.funcs:
                    return ("function", f"{c}.{attr}"), PROVEN
            for c in self.mro(q):
                cmod, cfacts = self.classes[c]
                spec = cfacts["attr_types"].get(attr)
                if spec:
                    return self._instance(self.type_of(spec, Ctx(cmod, cls=c), depth + 1))
        return None

    def mro(self, cls: str) -> list[str]:
        """The class and its project-defined base classes, breadth first."""
        if cls in self._mro_cache:
            return self._mro_cache[cls]
        out, queue = [], [cls]
        while queue:
            c = queue.pop(0)
            if c in out or c not in self.classes:
                continue
            out.append(c)
            cmod, cfacts = self.classes[c]
            for base in cfacts["bases"]:
                r = self.lookup_expr(base, Ctx(cmod))
                if isinstance(r, tuple) and r[0][0] == "class":
                    queue.append(r[0][1])
        self._mro_cache[cls] = out
        return out

    def fixture_type(self, name: str, ctx: Ctx, depth: int):
        """Type of a pytest fixture parameter: same module first, then the nearest conftest.py."""
        cands = self.fixtures.get(name, [])
        chosen = next(((m, fn) for m, fn in cands if m == ctx.module), None)
        if chosen is None and ctx.path:
            dirs = ctx.path.split("/")[:-1]
            for i in range(len(dirs), -1, -1):
                conftest = "/".join(dirs[:i] + ["conftest.py"])
                chosen = next(((m, fn) for m, fn in cands if self.path_of.get(m) == conftest), None)
                if chosen:
                    break
        if chosen is None:
            return None
        fmod, fn = chosen
        fctx = Ctx(fmod, fn["vars"], path=self.path_of.get(fmod))
        if fn["returns"]:
            t = self.type_of({"ann": fn["returns"]}, fctx, depth + 1)
            if t and t not in (EXTERNAL, BUILTIN):
                return t
        return self.type_of(fn["result_spec"], fctx, depth + 1) if fn["result_spec"] else None

    def scope(self, name: str, ctx: Ctx, depth: int):
        """Resolve the first token of a chain, following Python's lookup order."""
        if name == "self" and ctx.cls:
            return ("instance", ctx.cls), PROVEN
        if name in ctx.vars:
            return self._instance(self.type_of(ctx.vars[name], ctx, depth + 1))
        if name in ctx.params:  # parameters shadow globals; unannotated ones are known only as fixtures
            return self._instance(self.fixture_type(name, ctx, depth + 1))
        mod = ctx.module
        if name in self.defs.get(mod, {}):
            return self.defs[mod][name], PROVEN
        if name in self.imports.get(mod, {}):
            return self.resolve_dotted(self.imports[mod][name], depth + 1) or EXTERNAL
        spec = self.mods[mod]["module_vars"].get(name)
        if spec:
            return self._instance(self.type_of(spec, Ctx(mod, path=ctx.path), depth + 1))
        if name in _BUILTINS:
            return BUILTIN
        return None

    def lookup_expr(self, dotted: str, ctx: Ctx):
        """Resolve a written name like 'Base' or 'pkg.Base' (no calls)."""
        return self.resolve_chain(dotted.split("."), ctx, 0)

    def resolve_chain(self, chain: list[str], ctx: Ctx, depth: int):
        """A callee chain such as ['engine', 'evaluate_point'] -> result."""
        if depth > _MAX_DEPTH or not chain:
            return None
        r = self.scope(chain[0], ctx, depth)
        if not isinstance(r, tuple):
            return r
        thing, cert = r
        for tok in chain[1:]:
            r = self.call_result(thing, depth + 1) if tok == "()" else self.member(thing, tok, depth + 1)
            if not isinstance(r, tuple):
                return r
            thing, c = r
            cert = _weaker(cert, c)
        return thing, cert

    def call_result(self, thing: Thing, depth: int):
        """What calling `thing` returns."""
        kind, q = thing
        if kind == "class":
            return ("instance", q), PROVEN
        if kind == "function":
            fmod, fn = self.funcs[q]
            cls = q.rpartition(".")[0] if fn["cls"] else None
            fctx = Ctx(fmod, fn["vars"], cls, path=self.path_of.get(fmod))
            if fn["returns"]:
                return self._instance(self.type_of({"ann": fn["returns"]}, fctx, depth + 1))
            if fn["result_spec"]:
                return self._instance(self.type_of(fn["result_spec"], fctx, depth + 1))
        return None

    def type_of(self, spec: dict | None, ctx: Ctx, depth: int):
        """Project class (qualified name), EXTERNAL, BUILTIN, or None."""
        if depth > _MAX_DEPTH or not spec:
            return None
        if "call" in spec:
            r = self.resolve_chain(spec["call"], ctx, depth + 1)
            if not isinstance(r, tuple):
                return r
            res = self.call_result(r[0], depth + 1)
            if not isinstance(res, tuple):
                return res
            return res[0][1] if res[0][0] == "instance" else None
        classes, markers = set(), set()
        for name in _annotation_names(spec["ann"]):
            if name in _TYPING_NOISE:
                continue
            r = self.lookup_expr(name, Ctx(ctx.module, cls=ctx.cls))
            if isinstance(r, tuple) and r[0][0] == "class":
                classes.add(r[0][1])
            elif r in (EXTERNAL, BUILTIN):
                markers.add(r)
        if len(classes) == 1:
            return classes.pop()
        if not classes and markers:
            return EXTERNAL if EXTERNAL in markers else BUILTIN
        return None


def _annotation_names(ann: str) -> list[str]:
    """Dotted names inside an annotation string, e.g. 'requests.Session | None' -> ['requests.Session', 'None']."""
    try:
        tree = ast.parse(ann, mode="eval")
    except SyntaxError:
        return []
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):  # forward reference "Foo"
            names += _annotation_names(n.value)
        elif isinstance(n, (ast.Name, ast.Attribute)):
            try:
                names.append(ast.unparse(n))
            except Exception:  # noqa: BLE001 - unparse of exotic nodes; skip them
                continue
    # an Attribute contains its own Name: keep only maximal dotted names
    return [n for n in names if not any(o != n and o.startswith(n + ".") for o in names)]


# ---------------------------------------------------------------- world assembly


def build_world(files: list[dict]) -> tuple[list[dict], list[dict], dict]:
    R = Resolver(files)
    nodes: list[dict] = []
    edges: dict[tuple[str, str, str], dict] = {}
    calls = Counter()

    def node(id_, kind, name, parent, group, file=None, line=None, end_line=None, **attrs):
        nodes.append(
            {
                "id": id_,
                "kind": kind,
                "name": name,
                "parent": parent,
                "group": group,
                "file": file,
                "line": line,
                "end_line": end_line,
                "attrs": attrs,
            }
        )

    def edge(source, target, kind, certainty, line=None):
        k = (source, target, kind)
        if k in edges:
            e = edges[k]
            e["count"] += 1
            if _RANK[certainty] < _RANK[e["certainty"]]:
                e["certainty"] = certainty
        else:
            edges[k] = {
                "source": source,
                "target": target,
                "kind": kind,
                "certainty": certainty,
                "line": line,
                "count": 1,
            }

    groups = sorted({group_of(f["path"]) for f in files})
    for g in groups:
        node(f"group:{g}", "group", g, None, g)

    file_of_module = {f["module"]: f["path"] for f in files}
    tables: dict[str, None] = {}

    for f in files:
        path, mod, g = f["path"], f["module"], group_of(f["path"])
        fid = f"file:{path}"
        node(
            fid,
            "file",
            path.rsplit("/", 1)[-1],
            f"group:{g}",
            g,
            path,
            1,
            f["loc"],
            module=mod,
            loc=f["loc"],
            is_test=f["is_test"],
            error=f["error"],
        )
        if f["error"]:
            continue

        # imports -> file edges
        for imp in f["imports"]:
            r = R.resolve_dotted(imp["target"])
            if isinstance(r, tuple):
                kind, q = r[0]
                target_mod = q if kind == "module" else _module_of(q, R)
                tpath = file_of_module.get(target_mod)
                if tpath and tpath != path:
                    edge(fid, f"file:{tpath}", "imports", PROVEN, imp["line"])

        for c in f["classes"]:
            cq = f"{mod}.{c['name']}"
            node(
                f"py:{cq}",
                "class",
                c["name"],
                fid,
                g,
                path,
                c["line"],
                c["end_line"],
                bases=c["bases"],
                decorators=c["decorators"],
                doc=c["doc"],
            )
            for base in c["bases"]:
                r = R.lookup_expr(base, Ctx(mod))
                if isinstance(r, tuple) and r[0][0] == "class":
                    edge(f"py:{cq}", f"py:{r[0][1]}", "inherits", PROVEN, c["line"])

        for fn in f["functions"]:
            fq = f"{mod}.{fn['qualname']}"
            is_script = fn["name"] == SCRIPT
            parent = f"py:{mod}.{fn['cls']}" if fn["cls"] else fid
            node(
                f"py:{fq}",
                "script" if is_script else "function",
                fn["name"],
                parent,
                g,
                path,
                fn["line"],
                fn["end_line"],
                method=fn["cls"] is not None,
                is_test=f["is_test"] and (is_script or fn["name"].startswith("test")),
                params=fn["params"],
                returns=fn["returns"],
                is_async=fn["is_async"],
                decorators=fn["decorators"],
                doc=fn["doc"],
                loc=(fn["end_line"] or fn["line"]) - fn["line"] + 1,
            )
            ctx = Ctx(
                mod,
                fn["vars"],
                f"{mod}.{fn['cls']}" if fn["cls"] else None,
                frozenset(p["name"] for p in fn["params"] if not p["ann"]),
                path,
            )
            for call in fn["calls"]:
                calls["total"] += 1
                r = R.resolve_chain(call["chain"], ctx, 0)
                if r in (EXTERNAL, BUILTIN):
                    calls[r] += 1
                    continue
                if r is None or r[0][0] not in ("function", "class"):
                    calls["unresolved"] += 1
                    continue
                (kind, q), cert = r
                calls["resolved"] += 1
                edge(
                    f"py:{fq}",
                    f"py:{q}",
                    "calls" if kind == "function" else "instantiates",
                    cert,
                    call["line"],
                )
            for s in fn["sql"]:
                tables[s["table"]] = None
                edge(f"py:{fq}", f"table:{s['table']}", s["op"], PATTERN, s["line"])

        for rt in f["routes"]:
            eid = f"endpoint:{rt['verb']} {rt['path']}"
            if not any(n["id"] == eid for n in nodes):
                node(
                    eid,
                    "endpoint",
                    f"{rt['verb']} {rt['path']}",
                    fid,
                    g,
                    path,
                    rt["line"],
                    rt["line"],
                    verb=rt["verb"],
                    route=rt["path"],
                )
            spec = f["module_vars"].get(rt["receiver"]) or {}
            origin = R.imports[mod].get((spec.get("call") or [""])[0], "")
            cert = PROVEN if origin.startswith("fastapi.") else PATTERN
            edge(eid, f"py:{mod}.{rt['function']}", "routes", cert, rt["line"])

    if tables:
        node("group:(data)", "group", "(data)", None, "(data)")
        for t in sorted(tables):
            node(f"table:{t}", "table", t, "group:(data)", "(data)")

    stats = {
        "nodes": dict(Counter(n["kind"] for n in nodes)),
        "edges": dict(Counter(e["kind"] for e in edges.values())),
        "calls": {k: calls.get(k, 0) for k in ("total", "resolved", "external", "builtin", "unresolved")},
    }
    return nodes, list(edges.values()), stats


def _module_of(qual: str, R: Resolver) -> str | None:
    if qual in R.classes:
        return R.classes[qual][0]
    if qual in R.funcs:
        return R.funcs[qual][0]
    return None
