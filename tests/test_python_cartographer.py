"""Specification of the Python cartographer (ADR-0002 world format)."""

# ---------------------------------------------------------------- structure


def test_definitions_become_nodes_in_a_hierarchy(world):
    w = world(
        {
            "src/shop/engine.py": """
            class Engine:
                def run(self):
                    pass

            def helper():
                pass
            """
        }
    )
    cls = w.nodes["py:src.shop.engine.Engine"]
    meth = w.nodes["py:src.shop.engine.Engine.run"]
    fn = w.nodes["py:src.shop.engine.helper"]
    assert cls["kind"] == "class" and cls["parent"] == "file:src/shop/engine.py"
    assert meth["kind"] == "function" and meth["parent"] == cls["id"] and meth["attrs"]["method"] is True
    assert fn["parent"] == "file:src/shop/engine.py" and fn["attrs"]["method"] is False
    assert w.nodes["file:src/shop/engine.py"]["parent"] == "group:shop"
    assert (meth["line"], meth["end_line"]) == (2, 3)


def test_group_naming_rules(world):
    w = world({"src/shop/a.py": "", "src/db.py": "", "tests/test_a.py": "", "app.py": ""})
    assert w.nodes["file:src/shop/a.py"]["group"] == "shop"
    assert w.nodes["file:src/db.py"]["group"] == "src"
    assert w.nodes["file:tests/test_a.py"]["group"] == "tests"
    assert w.nodes["file:app.py"]["group"] == "(root)"


# ---------------------------------------------------------------- call resolution


def test_imported_function_call_is_proven(world):
    w = world(
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def helper():\n    pass\n",
            "pkg/main.py": """
            from pkg.util import helper
            import pkg.util as u

            def run():
                helper()
                u.helper()
            """,
        }
    )
    e = w.edge("py:pkg.main.run", "py:pkg.util.helper", "calls")
    assert e and e["certainty"] == "proven" and e["count"] == 2
    assert w.edge("file:pkg/main.py", "file:pkg/util.py", "imports")


def test_reexport_through_package_init_is_followed(world):
    w = world(
        {
            "src/catalog/__init__.py": "from .engine import Engine\n",
            "src/catalog/engine.py": "class Engine:\n    pass\n",
            "src/api.py": """
            from src.catalog import Engine

            def make():
                return Engine()
            """,
        }
    )
    e = w.edge("py:src.api.make", "py:src.catalog.engine.Engine", "instantiates")
    assert e and e["certainty"] == "proven"


def test_relative_import(world):
    w = world(
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def helper():\n    pass\n",
            "pkg/main.py": "from .util import helper\n\ndef run():\n    helper()\n",
        }
    )
    assert w.edge("py:pkg.main.run", "py:pkg.util.helper", "calls")


def test_src_layout_import_name_without_src_prefix(world):
    w = world(
        {
            "src/mypkg/__init__.py": "",
            "src/mypkg/a.py": "def f():\n    pass\n",
            "src/mypkg/b.py": "from mypkg.a import f\n\ndef g():\n    f()\n",
        }
    )
    assert w.edge("py:src.mypkg.b.g", "py:src.mypkg.a.f", "calls")


def test_self_method_call_is_proven(world):
    w = world(
        {
            "m.py": """
            class C:
                def a(self):
                    self.b()

                def b(self):
                    pass
            """
        }
    )
    e = w.edge("py:m.C.a", "py:m.C.b", "calls")
    assert e and e["certainty"] == "proven"


def test_inherited_method_and_inherits_edge(world):
    w = world(
        {
            "m.py": """
            class Base:
                def ping(self):
                    pass

            class Child(Base):
                def go(self):
                    self.ping()
            """
        }
    )
    assert w.edge("py:m.Child", "py:m.Base", "inherits")
    assert w.edge("py:m.Child.go", "py:m.Base.ping", "calls")


def test_type_inference_from_constructor_return_annotation_param_and_global(world):
    w = world(
        {
            "m.py": """
            class Engine:
                def run(self):
                    pass

            def get_engine() -> Engine:
                return Engine()

            engine = Engine()

            def via_ctor():
                x = Engine()
                x.run()

            def via_return_annotation():
                get_engine().run()

            def via_param(e: Engine):
                e.run()

            def via_global():
                engine.run()
            """
        }
    )
    for fn in ("via_ctor", "via_return_annotation", "via_param", "via_global"):
        e = w.edge(f"py:m.{fn}", "py:m.Engine.run", "calls")
        assert e, fn
        assert e["certainty"] == "inferred", fn


def test_attribute_type_from_annotated_self_assignment(world):
    w = world(
        {
            "m.py": """
            class Conn:
                def query(self):
                    pass

            class Engine:
                def __init__(self):
                    self._con: Conn | None = None

                def run(self):
                    self._con.query()
            """
        }
    )
    assert w.edge("py:m.Engine.run", "py:m.Conn.query", "calls")


def test_unresolvable_calls_are_counted_not_guessed(world):
    w = world(
        {
            "m.py": """
            import requests

            class Engine:
                def close(self):
                    pass

            def work(con):
                con.close()          # receiver type unknown: must NOT link to Engine.close
                requests.get()       # external library
                len([])              # builtin
            """
        }
    )
    assert not w.edge("py:m.work", "py:m.Engine.close", "calls")
    stats = w.world["stats"]
    assert stats["calls"]["unresolved"] == 1
    assert stats["calls"]["external"] == 1
    assert stats["calls"]["builtin"] == 1


def test_calls_on_library_and_builtin_objects_are_not_unresolved(world):
    w = world(
        {
            "m.py": """
            import requests
            from pathlib import Path

            def f(p: Path, s: str):
                con = requests.Session()
                con.get("x")
                p.glob("*")
                s.strip()
            """
        }
    )
    c = w.world["stats"]["calls"]
    assert (c["external"], c["builtin"], c["unresolved"]) == (3, 1, 0)


def test_pytest_fixture_parameters_get_the_fixture_type(world):
    w = world(
        {
            "pkg/__init__.py": "",
            "pkg/engine.py": "class Engine:\n    def run(self):\n        pass\n",
            "tests/conftest.py": """
            import pytest
            from pkg.engine import Engine

            @pytest.fixture
            def engine():
                eng = Engine()
                yield eng
            """,
            "tests/unit/test_engine.py": "def test_run(engine):\n    engine.run()\n",
            "tests/test_local.py": """
            import pytest
            from pkg.engine import Engine

            @pytest.fixture(scope="module")
            def eng():
                return Engine()

            def test_local(eng):
                eng.run()
            """,
        }
    )
    for src in ("py:tests.unit.test_engine.test_run", "py:tests.test_local.test_local"):
        e = w.edge(src, "py:pkg.engine.Engine.run", "calls")
        assert e and e["certainty"] == "inferred", src


# ---------------------------------------------------------------- endpoints, data, tests, scripts


def test_fastapi_endpoints(world):
    w = world(
        {
            "api.py": """
            from fastapi import FastAPI

            app = FastAPI()

            @app.get("/health")
            def health():
                return {}

            @app.post("/api/v1/orders")
            def create_order():
                return {}
            """
        }
    )
    ep = w.nodes["endpoint:GET /health"]
    assert ep["kind"] == "endpoint" and ep["attrs"]["verb"] == "GET"
    e = w.edge("endpoint:GET /health", "py:api.health", "routes")
    assert e and e["certainty"] == "proven"
    assert w.edge("endpoint:POST /api/v1/orders", "py:api.create_order", "routes")


def test_sql_tables_reads_writes_and_ctes_are_not_tables(world):
    w = world(
        {
            "db.py": '''
            def score(con, join):
                """Select rows FROM somewhere (docstrings are ignored)."""
                return con.execute(f"""
                    WITH target AS (SELECT 1 AS pt)
                    SELECT * FROM orders r CROSS JOIN target t {join}
                """)

            def ingest(con, path):
                con.execute(f"INSERT INTO orders SELECT * FROM read_csv('{path}')")
                con.execute("CREATE INDEX IF NOT EXISTS idx ON orders (id)")
            '''
        }
    )
    reads = {(e["source"], e["target"]) for e in w.edges("reads")}
    writes = {(e["source"], e["target"]) for e in w.edges("writes")}
    assert ("py:db.score", "table:orders") in reads
    assert ("py:db.ingest", "table:orders") in writes
    assert "table:target" not in w.nodes  # CTE, not a table
    assert "table:read_csv" not in w.nodes  # table function, not a table
    assert "table:somewhere" not in w.nodes  # docstring
    assert all(e["certainty"] == "pattern" for e in w.edges("reads") + w.edges("writes"))


def test_tests_are_marked_and_their_calls_recorded(world):
    w = world(
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def helper():\n    pass\n",
            "tests/test_util.py": "from pkg.util import helper\n\ndef test_helper():\n    helper()\n",
        }
    )
    t = w.nodes["py:tests.test_util.test_helper"]
    assert t["attrs"]["is_test"] is True
    assert w.nodes["file:tests/test_util.py"]["attrs"]["is_test"] is True
    assert w.edge("py:tests.test_util.test_helper", "py:pkg.util.helper", "calls")


def test_top_level_script_code_gets_a_script_node(world):
    w = world(
        {
            "util.py": "def load():\n    pass\n",
            "app.py": "from util import load\n\ndata = load()\n",
        }
    )
    assert w.nodes["py:app.<module>"]["kind"] == "script"
    assert w.edge("py:app.<module>", "py:util.load", "calls")


def test_syntax_error_is_reported_not_fatal(world):
    w = world({"good.py": "def f():\n    pass\n", "bad.py": "def broken(:\n"})
    assert "py:good.f" in w.nodes
    assert "SyntaxError" in w.nodes["file:bad.py"]["attrs"]["error"]
    assert w.world["stats"]["files"]["errors"] == 1


def test_ignores_virtualenvs_and_hidden_dirs(world):
    w = world({"a.py": "", ".venv/lib/x.py": "", "node_modules/y.py": "", ".hidden/z.py": ""})
    assert [n["id"] for n in w.world["nodes"] if n["kind"] == "file"] == ["file:a.py"]


# ---------------------------------------------------------------- cache (ADR-0003)


def test_cache_hits_on_second_run_and_misses_after_edit(project, tmp_path):
    from projectviewer.analyzers.python import map_repo
    from projectviewer.cache import Cache

    root = project({"a.py": "def f():\n    pass\n", "b.py": "def g():\n    pass\n"})
    cache = Cache(tmp_path / "cache")

    first = map_repo(root, cache=cache)["stats"]["cache"]
    assert (first["hits"], first["misses"]) == (0, 2)

    second = map_repo(root, cache=cache)["stats"]["cache"]
    assert (second["hits"], second["misses"]) == (2, 0)

    (root / "a.py").write_text("def f():\n    return 1\n")
    third = map_repo(root, cache=cache)["stats"]["cache"]
    assert (third["hits"], third["misses"]) == (1, 1)


def test_parallel_and_serial_parsing_give_identical_worlds(project):
    from projectviewer.analyzers.python import map_repo

    files = {
        f"pkg/m{i}.py": f"from pkg.m{(i + 1) % 6} import f{(i + 1) % 6}\n\ndef f{i}():\n    f{(i + 1) % 6}()\n"
        for i in range(6)
    }
    root = project({"pkg/__init__.py": "", **files})

    def strip(w):
        return {k: v for k, v in w.items() if k not in ("stats", "generated_at")}

    assert strip(map_repo(root, workers=3)) == strip(map_repo(root, workers=1))


def test_cached_and_uncached_worlds_are_identical(project, tmp_path):
    from projectviewer.analyzers.python import map_repo
    from projectviewer.cache import Cache

    root = project({"m.py": "class C:\n    def a(self):\n        self.b()\n    def b(self):\n        pass\n"})
    cache = Cache(tmp_path / "cache")
    map_repo(root, cache=cache)  # fill

    def strip(w):
        return {k: v for k, v in w.items() if k not in ("stats", "generated_at")}

    assert strip(map_repo(root, cache=cache)) == strip(map_repo(root))


# ---------------------------------------------------------------- analyser fixes (round 2)


def test_calls_to_nested_functions_are_local_not_unresolved(world):
    w = world(
        {
            "m.py": """
            def build():
                def node(x):
                    return x

                node(1)
                node(2)
            """
        }
    )
    c = w.world["stats"]["calls"]
    assert c["unresolved"] == 0
    assert c["local"] == 2


def test_literal_assignments_have_builtin_types(world):
    w = world(
        {
            "m.py": """
            def f():
                items = []
                index = {}
                name = "x"
                items.append(1)
                index.get("a")
                name.strip()
            """
        }
    )
    c = w.world["stats"]["calls"]
    assert (c["builtin"], c["unresolved"]) == (3, 0)


def test_http_calls_in_tests_link_to_endpoints(world):
    w = world(
        {
            "shop/__init__.py": "",
            "shop/api.py": """
            from fastapi import FastAPI

            app = FastAPI()

            @app.get("/orders/{order_id}")
            def get_order(order_id: int):
                return {}

            @app.post("/orders")
            def create_order():
                return {}
            """,
            "tests/test_api.py": """
            def test_get(client):
                client.get("/orders/42?verbose=1")

            def test_create(client):
                client.post("/orders", json={})

            def test_unknown(client):
                client.get("/nope")
            """,
        }
    )
    e = w.edge("py:tests.test_api.test_get", "endpoint:GET /orders/{order_id}", "requests")
    assert e and e["certainty"] == "pattern"
    assert w.edge("py:tests.test_api.test_create", "endpoint:POST /orders", "requests")
    assert not [x for x in w.edges("requests") if x["source"] == "py:tests.test_api.test_unknown"]
    assert w.world["stats"]["http"] == {"total": 3, "matched": 2}


def test_unresolved_calls_that_could_be_project_calls_are_counted(world):
    w = world(
        {
            "m.py": """
            def total():
                pass

            def get():
                pass

            def f(thing, other, d):
                thing.total()      # same name as a project function: maybe a missed link
                other.frobnicate() # no such project function
                d.get("k")         # also a project name, but far more likely dict.get: not counted
            """
        }
    )
    c = w.world["stats"]["calls"]
    assert c["unresolved"] == 3
    assert c["unresolved_named"] == 1
