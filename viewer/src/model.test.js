// Unit tests for the viewer's pure logic. Run: npm test  (Node's built-in test runner)
import assert from "node:assert/strict";
import { test } from "node:test";
import { curve, curve3d, fit } from "./layout.js";
import { ancestors, descendants, groupLinks, indexWorld, linksFor, search } from "./model.js";

const node = (id, kind, name, parent, group, attrs = {}) => ({ id, kind, name, parent, group, file: "x.py", line: 1, end_line: 5, attrs });
const edge = (source, target, kind = "calls") => ({ source, target, kind, certainty: "proven", count: 1 });

const world = {
  nodes: [
    node("group:shop", "group", "shop", null, "shop"),
    node("group:tests", "group", "tests", null, "tests"),
    node("file:shop/a.py", "file", "a.py", "group:shop", "shop", { loc: 40 }),
    node("py:shop.a.Cart", "class", "Cart", "file:shop/a.py", "shop"),
    node("py:shop.a.Cart.total", "function", "total", "py:shop.a.Cart", "shop", { loc: 10 }),
    node("py:shop.a.helper", "function", "helper", "file:shop/a.py", "shop", { loc: 5 }),
    node("py:shop.a.deep", "function", "deep", "file:shop/a.py", "shop", { loc: 5 }),
    node("file:tests/t.py", "file", "t.py", "group:tests", "tests", { loc: 10 }),
    node("py:tests.t.test_total", "function", "test_total", "file:tests/t.py", "tests", { loc: 3, is_test: true }),
  ],
  edges: [
    edge("py:tests.t.test_total", "py:shop.a.Cart.total"),
    edge("py:shop.a.Cart.total", "py:shop.a.helper"),
    edge("py:shop.a.helper", "py:shop.a.deep"),
  ],
};

test("index: hierarchy and lookups", () => {
  const ix = indexWorld(world);
  assert.deepEqual(ancestors(ix, "py:shop.a.Cart.total"), ["group:shop", "file:shop/a.py", "py:shop.a.Cart"]);
  assert.ok(descendants(ix, "group:shop").includes("py:shop.a.Cart.total"));
});

test("test reach: direct vs indirect", () => {
  const ix = indexWorld(world);
  assert.ok(ix.testedDirect.has("py:shop.a.Cart.total"));
  assert.ok(!ix.testedDirect.has("py:shop.a.helper"));
  assert.ok(ix.testedReach.has("py:shop.a.deep"));
});

test("links of a container only cross its boundary", () => {
  const ix = indexWorld(world);
  const { links } = linksFor(ix, "file:shop/a.py");
  assert.deepEqual(
    links.map((l) => [l.e.source, l.dir]),
    [["py:tests.t.test_total", "in"]],
  );
});

test("group overview aggregates cross-group links", () => {
  const ix = indexWorld(world);
  assert.deepEqual(groupLinks(ix), [{ source: "group:tests", target: "group:shop", count: 1 }]);
});

test("search ranks exact names and functions first", () => {
  const ix = indexWorld(world);
  assert.equal(search(ix, "total")[0].id, "py:shop.a.Cart.total");
});

test("curve starts and ends at the endpoints; fit centres the box", () => {
  const pts = curve([0, 0], [10, 0]);
  assert.deepEqual(pts[0], [0, 0]);
  assert.deepEqual(pts.at(-1), [10, 0]);
  const v = fit({ x0: 0, y0: 0, x1: 100, y1: 50 }, 1000, 500);
  assert.deepEqual(v.target, [50, 25, 0]);
});

test("3D curve lifts in the middle and ends on the targets", () => {
  const pts = curve3d([0, 0, 10], [100, 0, 20]);
  assert.deepEqual(pts[0], [0, 0, 10]);
  assert.deepEqual(pts.at(-1), [100, 0, 20]);
  assert.ok(pts[Math.floor(pts.length / 2)][2] > 20);
});
