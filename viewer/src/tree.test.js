import assert from "node:assert/strict";
import { test } from "node:test";
import { layoutLevel, roofTiles } from "./layout.js";
import { indexWorld } from "./model.js";
import { blockDeps, buildTree, changeMarks, levelLinks, treeAncestors } from "./tree.js";

const node = (id, kind, name, parent, file, attrs = {}) => ({ id, kind, name, parent, group: "g", file, line: 1, end_line: 5, attrs });
const edge = (source, target, kind = "calls") => ({ source, target, kind, certainty: "proven", count: 1 });

const world = {
  nodes: [
    node("group:src", "group", "src", null),
    node("file:src/shop/cart.py", "file", "cart.py", "group:src", "src/shop/cart.py", { loc: 120 }),
    node("py:src.shop.cart.Cart", "class", "Cart", "file:src/shop/cart.py", "src/shop/cart.py"),
    node("py:src.shop.cart.Cart.total", "function", "total", "py:src.shop.cart.Cart", "src/shop/cart.py", { loc: 30 }),
    node("file:src/shop/tax.py", "file", "tax.py", "group:src", "src/shop/tax.py", { loc: 20 }),
    node("py:src.shop.tax.rate", "function", "rate", "file:src/shop/tax.py", "src/shop/tax.py", { loc: 8 }),
    node("file:src/api.py", "file", "api.py", "group:src", "src/api.py", { loc: 40 }),
    node("py:src.api.get_total", "function", "get_total", "file:src/api.py", "src/api.py", { loc: 6 }),
    node("endpoint:GET /total", "endpoint", "GET /total", "file:src/api.py", "src/api.py"),
    node("group:tests", "group", "tests", null),
    node("file:tests/test_cart.py", "file", "test_cart.py", "group:tests", "tests/test_cart.py", { loc: 10, is_test: true }),
    node("py:tests.test_cart.test_total", "function", "test_total", "file:tests/test_cart.py", "tests/test_cart.py", { loc: 3, is_test: true }),
    node("group:(data)", "group", "(data)", null),
    node("table:orders", "table", "orders", "group:(data)"),
  ],
  edges: [
    edge("py:src.api.get_total", "py:src.shop.cart.Cart.total"),
    edge("py:src.shop.cart.Cart.total", "py:src.shop.tax.rate"),
    edge("py:tests.test_cart.test_total", "py:src.shop.cart.Cart.total"),
    edge("py:src.shop.cart.Cart.total", "table:orders", "reads"),
    edge("endpoint:GET /total", "py:src.api.get_total", "routes"),
  ],
};

const setup = () => {
  const ix = indexWorld(world);
  return { ix, tree: buildTree(ix, "shop") };
};

test("the tree follows the folder structure; src/ is transparent; tables form a Database block", () => {
  const { tree } = setup();
  const names = (id) => tree.T.get(id).children.map((c) => c.name).sort();
  assert.deepEqual(names("root"), ["Database", "api.py", "shop", "tests"]);
  assert.ok(!tree.T.has("dir:src"));
  assert.deepEqual(names("dir:src/shop"), ["cart.py", "tax.py"]);
  assert.deepEqual(names("py:src.shop.cart.Cart"), ["total"]);
  assert.deepEqual(treeAncestors(tree, "py:src.shop.cart.Cart.total"), ["root", "dir:src/shop", "file:src/shop/cart.py", "py:src.shop.cart.Cart"]);
});

test("stats roll up: lines, files, functions, tests, endpoints, tested share", () => {
  const { tree } = setup();
  const s = tree.T.get("root").stats;
  assert.equal(s.loc, 190);
  assert.equal(s.files, 4);
  assert.equal(s.functions, 3);
  assert.equal(s.fn, 4); // all functions, tests included: the size measure
  assert.equal(s.endpoints, 1);
  assert.equal(s.tested, 2); // total (direct) + rate (indirect)
  assert.equal(s.data, 1);
  assert.equal(tree.T.get("dir:tests").isTest, true);
  assert.equal(tree.T.get("dir:src/shop").isTest, false);
});

test("level links are summed between the blocks on screen", () => {
  const { ix, tree } = setup();
  const root = levelLinks(ix, tree, "root").map((l) => `${l.source}>${l.target}:${l.count}`).sort();
  assert.deepEqual(root, ["dir:src/shop>db:1", "dir:tests>dir:src/shop:1", "file:src/api.py>dir:src/shop:1"]);
});

test("a block's dependencies: siblings by name, others by their top-level module (@)", () => {
  const { ix, tree } = setup();
  const d = blockDeps(ix, tree, "dir:src/shop", "file:src/shop/cart.py");
  assert.deepEqual(d.out, [
    ["file:src/shop/tax.py", 1],
    ["@db", 1],
  ]);
  assert.deepEqual(d.in.map(([k]) => k).sort(), ["@dir:tests", "@file:src/api.py"]);
});

test("block size follows the number of functions", () => {
  const { tree } = setup();
  const L = layoutLevel(tree.T.get("root"));
  const shop = L.rects.get("dir:src/shop"); // 2 functions
  const api = L.rects.get("file:src/api.py"); // 1 function
  assert.ok(shop.h > api.h);
  assert.ok((shop.x1 - shop.x0) * (shop.y1 - shop.y0) > (api.x1 - api.x0) * (api.y1 - api.y0));
});

test("level layout: one block per child; one-function blocks fall back to lines; deterministic", () => {
  const { tree } = setup();
  const L = layoutLevel(tree.T.get("dir:src/shop"));
  assert.equal(L.blocks.length, 2);
  const cart = L.rects.get("file:src/shop/cart.py");
  const tax = L.rects.get("file:src/shop/tax.py");
  assert.ok(cart.h > tax.h);
  assert.ok(cart.x1 - cart.x0 > 0 && cart.y1 - cart.y0 > 0);
  const again = layoutLevel(tree.T.get("dir:src/shop"));
  assert.deepEqual(
    again.blocks.map((b) => [b.id, b.x0, b.y0]),
    L.blocks.map((b) => [b.id, b.x0, b.y0]),
  );
  assert.equal(layoutLevel(tree.T.get("py:src.shop.tax.rate")).blocks.length, 0);
});

test("roof tiles divide a block's top into its children, inside the block", () => {
  const { tree } = setup();
  const L = layoutLevel(tree.T.get("root"));
  const shop = L.rects.get("dir:src/shop");
  const tiles = roofTiles(shop);
  assert.deepEqual(tiles.map((t) => t.id).sort(), ["file:src/shop/cart.py", "file:src/shop/tax.py"]);
  for (const t of tiles) {
    assert.ok(t.x0 >= shop.x0 && t.x1 <= shop.x1 && t.y0 >= shop.y0 && t.y1 <= shop.y1, t.id);
    assert.equal(t.z, shop.h);
    assert.equal(t.parent, "dir:src/shop");
  }
  assert.deepEqual(roofTiles(L.rects.get("file:src/api.py")).length, 2); // a function and an endpoint
  assert.deepEqual(roofTiles({ ...shop, t: { ...shop.t, children: [shop.t.children[0]] } }), []); // one child: nothing to divide
});

test("change marks: changed blocks and every block containing them; affected ones too", () => {
  const { tree } = setup();
  const marks = changeMarks(tree, {
    changed: { "py:src.shop.tax.rate": "modified" },
    upstream: { "py:src.shop.cart.Cart.total": 1, "py:src.api.get_total": 2 },
    downstream: {},
  });
  assert.equal(marks.get("py:src.shop.tax.rate"), "changed");
  assert.equal(marks.get("file:src/shop/tax.py"), "changed");
  assert.equal(marks.get("dir:src/shop"), "changed"); // contains a change: changed wins over affected
  assert.equal(marks.get("file:src/shop/cart.py"), "affected");
  assert.equal(marks.get("file:src/api.py"), "affected");
  assert.equal(marks.get("dir:tests"), undefined);
});

test("change marks: moved is its own mark, weaker than changed, stronger than affected", () => {
  const { tree } = setup();
  const marks = changeMarks(tree, {
    changed: { "file:src/shop/tax.py": "moved", "py:src.shop.tax.rate": "moved", "py:src.shop.cart.Cart.total": "modified" },
    upstream: { "py:src.shop.tax.rate": 1 },
    downstream: {},
  });
  assert.equal(marks.get("file:src/shop/tax.py"), "moved");
  assert.equal(marks.get("file:src/shop/cart.py"), "changed");
  assert.equal(marks.get("dir:src/shop"), "changed");
});
