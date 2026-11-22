"""Pass 1: facts about ONE Python file (ADR-0003).

Pure function of (path, source): it never reads other files, so its result can be cached by
content hash. Everything that needs other files (resolving names, types, calls) is pass 2.

Facts are plain JSON-serialisable dicts:
  imports    [{alias, target, line}]              alias bound in this module -> dotted target
  classes    [{name, line, end_line, bases, decorators, doc, attr_types}]
  functions  [{qualname, name, cls, line, end_line, params, returns, is_async, decorators,
               doc, calls, vars, sql}]          (+ one "<module>" pseudo-function for top-level code)
  module_vars {name: type_spec}                    type_spec = {"ann": str} | {"call": chain}
  routes     [{verb, path, function, receiver, line}]
A call "chain" is the callee written as tokens: `a.b().c` -> ["a", "b", "()", "c"].
"""

from __future__ import annotations

import ast
import re

EXTRACTOR_VERSION = "4"  # bump whenever the facts change shape: invalidates cached results (ADR-0003)
SCRIPT = "<module>"
HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}

# ---------------------------------------------------------------- module naming


def module_name(path: str) -> str:
    """'src/shop/orders.py' -> 'src.shop.orders'; '__init__.py' names the package."""
    parts = path[:-3].split("/") if path.endswith(".py") else path.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        path.startswith("tests/")
        or "/tests/" in path
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


# ---------------------------------------------------------------- SQL table references (certainty: pattern)

_NAME = r"([A-Za-z_][\w.]*)\b"
_SQL_HINT = re.compile(
    r"\b(SELECT|INSERT|CREATE|UPDATE|DELETE|DROP|ALTER)\b"
)  # uppercase SQL only (documented limit)
_READ = re.compile(r"\b(?:FROM|JOIN)\s+" + _NAME + r"(?!\s*\()")
_WRITES = [
    re.compile(r"\bINSERT\s+INTO\s+" + _NAME),
    re.compile(
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _NAME
    ),
    re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\w+\s+ON\s+" + _NAME),
    re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _NAME),
    re.compile(r"\bALTER\s+TABLE\s+" + _NAME),
    re.compile(r"\bUPDATE\s+" + _NAME + r"\s+SET\b"),
    re.compile(r"\bDELETE\s+FROM\s+" + _NAME),
]
_CTE = re.compile(r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)([A-Za-z_]\w*)\s+AS\s*\(")
_NOT_TABLES = {"SELECT", "VALUES", "LATERAL", "UNNEST", "TABLE"}


def sql_tables(text: str) -> list[tuple[str, str]]:
    """[(table, 'reads'|'writes')] found in one SQL string."""
    if not _SQL_HINT.search(text):
        return []
    ctes = {m.group(1).lower() for m in _CTE.finditer(text)}
    found: list[tuple[str, str]] = []
    for rx in _WRITES:
        found += [(m.group(1), "writes") for m in rx.finditer(text)]
    for m in _READ.finditer(text):
        if text[: m.start()].rstrip().upper().endswith("DELETE"):
            continue  # DELETE FROM x is a write, already counted
        found.append((m.group(1), "reads"))
    out = []
    for name, op in found:
        name = name.strip('"').lower()
        if name in ctes or name.upper() in _NOT_TABLES:
            continue
        out.append((name, op))
    return out


# ---------------------------------------------------------------- helpers


def chain_of(expr: ast.AST) -> list[str] | None:
    """Callee expression as tokens, or None when it isn't a simple name/attribute/call chain."""
    if isinstance(expr, ast.Name):
        return [expr.id]
    if isinstance(expr, ast.Attribute):
        base = chain_of(expr.value)
        return base + [expr.attr] if base is not None else None
    if isinstance(expr, ast.Call):
        base = chain_of(expr.func)
        return base + ["()"] if base is not None else None
    return None


def _doc(node: ast.AST) -> str | None:
    d = ast.get_docstring(node)  # type: ignore[arg-type]
    return d.strip().splitlines()[0] if d else None


def _strings(nodes: list[ast.stmt]):
    """String constants and f-strings inside statements (f-string holes become a space)."""
    for stmt in nodes:
        for n in ast.walk(stmt):
            if isinstance(n, ast.JoinedStr):
                parts = [
                    v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else " "
                    for v in n.values
                ]
                yield "".join(parts), n.lineno
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                yield n.value, n.lineno


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return body


_LITERALS = (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.JoinedStr, ast.ListComp, ast.DictComp, ast.SetComp)


def _type_spec(value: ast.AST | None, annotation: ast.AST | None) -> dict | None:
    if annotation is not None:
        return {"ann": ast.unparse(annotation)}
    if isinstance(value, _LITERALS) or (isinstance(value, ast.Constant) and value.value is not None):
        return {"builtin": True}  # [], {}, "", 1, f"…": a builtin object
    if isinstance(value, ast.Call):
        ch = chain_of(value.func)
        if ch:
            return {"call": ch}
    return None


def _body_facts(body: list[ast.stmt]) -> dict:
    """Calls, local variable types, SQL tables, HTTP requests and nested definitions found in a list
    of statements. Nested function/class bodies are included: their effects belong to the enclosing code."""
    calls, vars_, sql, http, local_defs = [], {}, [], [], []
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local_defs.append(n.name)
            if isinstance(n, ast.Call):
                ch = chain_of(n.func)
                if ch:
                    calls.append({"chain": ch, "line": n.lineno})
                req = _http_request(n)
                if req:
                    http.append(req)
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                spec = _type_spec(n.value, None)
                if spec:
                    vars_[n.targets[0].id] = spec
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                vars_[n.target.id] = _type_spec(n.value, n.annotation)
            elif isinstance(n, ast.withitem) and isinstance(n.optional_vars, ast.Name):
                spec = _type_spec(n.context_expr, None)
                if spec:
                    vars_[n.optional_vars.id] = spec
    for text, line in _strings(body):
        sql += [{"table": t, "op": op, "line": line} for t, op in sql_tables(text)]
    return {"calls": calls, "vars": vars_, "sql": sql, "http": http, "local_defs": sorted(set(local_defs))}


def _http_request(call: ast.Call) -> dict | None:
    """`client.get("/orders/42?x=1")` -> {"verb": "GET", "path": "/orders/42"}: a test talking to an API."""
    f = call.func
    if (
        isinstance(f, ast.Attribute)
        and f.attr in HTTP_VERBS
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and call.args[0].value.startswith("/")
    ):
        return {"verb": f.attr.upper(), "path": call.args[0].value.split("?", 1)[0], "line": call.lineno}
    return None


def _self_attr_types(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    out = {}
    for n in ast.walk(fn):
        target, value, ann = None, None, None
        if isinstance(n, ast.AnnAssign):
            target, value, ann = n.target, n.value, n.annotation
        elif isinstance(n, ast.Assign) and len(n.targets) == 1:
            target, value = n.targets[0], n.value
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            spec = _type_spec(value, ann)
            if spec and (target.attr not in out or "ann" in spec):  # an annotation beats an assignment
                out[target.attr] = spec
    return out


def _result_spec(fn: ast.FunctionDef | ast.AsyncFunctionDef, vars_: dict) -> dict | None:
    """Type spec of the first value returned or yielded: used when there is no return annotation,
    e.g. pytest fixtures (`eng = Engine(); yield eng`)."""
    for n in ast.walk(fn):
        value = n.value if isinstance(n, (ast.Return, ast.Yield)) else None
        if isinstance(value, ast.Call):
            ch = chain_of(value.func)
            if ch:
                return {"call": ch}
        if isinstance(value, ast.Name) and value.id in vars_:
            return vars_[value.id]
    return None


def _route(dec: ast.AST, fn_name: str) -> dict | None:
    if (
        isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and dec.func.attr in HTTP_VERBS
        and isinstance(dec.func.value, ast.Name)
        and dec.args
        and isinstance(dec.args[0], ast.Constant)
        and isinstance(dec.args[0].value, str)
    ):
        return {
            "verb": dec.func.attr.upper(),
            "path": dec.args[0].value,
            "function": fn_name,
            "receiver": dec.func.value.id,
            "line": dec.lineno,
        }
    return None


def _param(a: ast.arg, default: ast.expr | None) -> dict:
    p = {"name": a.arg, "ann": ast.unparse(a.annotation) if a.annotation else None}
    if default is not None:
        p["default"] = ast.unparse(default)
    return p


def _function(fn: ast.FunctionDef | ast.AsyncFunctionDef, cls: str | None) -> dict:
    args = fn.args
    params = []
    positional = args.posonlyargs + args.args
    # Defaults belong to the *last* positional parameters; keyword-only defaults line up one to one.
    pos_defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for a, d in zip(positional, pos_defaults, strict=True):
        params.append(_param(a, d))
    if args.vararg:
        params.append({**_param(args.vararg, None), "kind": "*args"})
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        params.append({**_param(a, d), "kind": "keyword-only"})
    if args.kwarg:
        params.append({**_param(args.kwarg, None), "kind": "**kwargs"})
    facts = _body_facts(_without_docstring(fn.body))
    for p in params:  # annotated parameters are typed variables too
        if p["ann"] and p["name"] not in facts["vars"]:
            facts["vars"][p["name"]] = {"ann": p["ann"]}
    return {
        "result_spec": _result_spec(fn, facts["vars"]),
        "qualname": f"{cls}.{fn.name}" if cls else fn.name,
        "name": fn.name,
        "cls": cls,
        "line": fn.lineno,
        "end_line": fn.end_lineno,
        "params": params,
        "returns": ast.unparse(fn.returns) if fn.returns else None,
        "is_async": isinstance(fn, ast.AsyncFunctionDef),
        "decorators": [ast.unparse(d) for d in fn.decorator_list],
        "doc": _doc(fn),
        **facts,
    }


def _imports(tree: ast.Module, module: str, is_package: bool) -> list[dict]:
    out = []
    package = module if is_package else module.rpartition(".")[0]
    for n in ast.walk(tree):  # includes function-local imports (treated as module-wide: an approximation)
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    out.append({"alias": a.asname, "target": a.name, "line": n.lineno})
                else:  # `import a.b` binds `a`
                    top = a.name.split(".")[0]
                    out.append({"alias": top, "target": top, "line": n.lineno})
                    if "." in a.name:  # keep the full name for import edges
                        out.append({"alias": None, "target": a.name, "line": n.lineno})
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base_parts = package.split(".") if package else []
                base_parts = base_parts[: len(base_parts) - (n.level - 1)] if n.level > 1 else base_parts
                base = ".".join(base_parts + ([n.module] if n.module else []))
            else:
                base = n.module or ""
            for a in n.names:
                if a.name == "*":
                    continue
                out.append(
                    {
                        "alias": a.asname or a.name,
                        "target": f"{base}.{a.name}" if base else a.name,
                        "line": n.lineno,
                    }
                )
    return out


# ---------------------------------------------------------------- entry point


def extract(path: str, source: str) -> dict:
    module = module_name(path)
    is_package = path.endswith("__init__.py")
    facts: dict = {
        "path": path,
        "module": module,
        "is_package": is_package,
        "is_test": is_test_path(path),
        "loc": source.count("\n") + (0 if source.endswith("\n") or not source else 1),
        "error": None,
        "imports": [],
        "classes": [],
        "functions": [],
        "module_vars": {},
        "routes": [],
    }
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        facts["error"] = f"SyntaxError: {exc.msg} (line {exc.lineno})"
        return facts

    facts["imports"] = _imports(tree, module, is_package)
    top_level: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts["functions"].append(_function(node, None))
            facts["routes"] += [r for d in node.decorator_list if (r := _route(d, node.name))]
        elif isinstance(node, ast.ClassDef):
            attr_types: dict = {}
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    facts["functions"].append(_function(item, node.name))
                    for k, v in _self_attr_types(item).items():
                        if k not in attr_types or "ann" in v:
                            attr_types[k] = v
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    attr_types[item.target.id] = {"ann": ast.unparse(item.annotation)}
            facts["classes"].append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "decorators": [ast.unparse(d) for d in node.decorator_list],
                    "doc": _doc(node),
                    "attr_types": attr_types,
                }
            )
        elif not isinstance(node, (ast.Import, ast.ImportFrom)):
            top_level.append(node)

    script = _body_facts(_without_docstring(top_level))
    facts["module_vars"] = script["vars"]
    if script["calls"] or script["sql"] or script["http"]:
        lines = [s.lineno for s in top_level]
        ends = [s.end_lineno or s.lineno for s in top_level]
        facts["functions"].append(
            {
                "result_spec": None,
                "qualname": SCRIPT,
                "name": SCRIPT,
                "cls": None,
                "line": min(lines),
                "end_line": max(ends),
                "params": [],
                "returns": None,
                "is_async": False,
                "decorators": [],
                "doc": None,
                **script,
            }
        )
    return facts
