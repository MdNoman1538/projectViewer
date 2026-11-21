// The world as an index: lookups, test reach, links for a selection, group-level overview links.
// Pure functions (no React, no DOM), unit-tested with `npm test`.

const CALLISH = new Set(["calls", "instantiates"]);

function push(map, key, value) {
  if (!map.has(key)) map.set(key, []);
  map.get(key).push(value);
}

export function indexWorld(world) {
  const byId = new Map();
  const kids = new Map();
  const out = new Map();
  const inn = new Map();
  for (const n of world.nodes) byId.set(n.id, n);
  for (const n of world.nodes) push(kids, n.parent ?? null, n);
  for (const e of world.edges) {
    push(out, e.source, e);
    push(inn, e.target, e);
  }

  // Which code do the tests reach? Direct = called by a test; reach = within 4 calls of a test.
  const testedDirect = new Set();
  for (const n of world.nodes) {
    if (!n.attrs?.is_test) continue;
    for (const e of out.get(n.id) || []) if (CALLISH.has(e.kind)) testedDirect.add(e.target);
  }
  const testedReach = new Set(testedDirect);
  let frontier = [...testedDirect];
  for (let hop = 0; hop < 4 && frontier.length; hop++) {
    const next = [];
    for (const id of frontier)
      for (const e of out.get(id) || [])
        if (CALLISH.has(e.kind) && !testedReach.has(e.target)) {
          testedReach.add(e.target);
          next.push(e.target);
        }
    frontier = next;
  }

  return { world, nodes: world.nodes, edges: world.edges, byId, kids, out, inn, testedDirect, testedReach };
}

export function children(ix, id) {
  return ix.kids.get(id) || [];
}

export function descendants(ix, id) {
  const res = [];
  const stack = [id];
  while (stack.length) {
    for (const k of children(ix, stack.pop())) {
      res.push(k.id);
      stack.push(k.id);
    }
  }
  return res;
}

export function ancestors(ix, id) {
  const res = [];
  let n = ix.byId.get(id);
  while (n && n.parent) {
    res.unshift(n.parent);
    n = ix.byId.get(n.parent);
  }
  return res;
}

// Links between the selected thing (including everything inside it) and the rest of the world.
export function linksFor(ix, selId, max = 600) {
  const inside = new Set([selId, ...descendants(ix, selId)]);
  const res = [];
  for (const id of inside) {
    for (const e of ix.out.get(id) || []) if (!inside.has(e.target)) res.push({ e, dir: "out" });
    for (const e of ix.inn.get(id) || []) if (!inside.has(e.source)) res.push({ e, dir: "in" });
    if (res.length >= max) break;
  }
  return { inside, links: res.slice(0, max) };
}

// Overview: how the top-level groups depend on each other (calls, instantiation, data access).
export function groupLinks(ix, kinds = ["calls", "instantiates", "reads", "writes"]) {
  const want = new Set(kinds);
  const pairs = new Map();
  for (const e of ix.edges) {
    if (!want.has(e.kind)) continue;
    const s = ix.byId.get(e.source);
    const t = ix.byId.get(e.target);
    if (!s || !t || s.group === t.group) continue;
    const key = `group:${s.group}\u0000group:${t.group}`;
    pairs.set(key, (pairs.get(key) || 0) + e.count);
  }
  return [...pairs.entries()].map(([k, count]) => {
    const [source, target] = k.split("\u0000");
    return { source, target, count };
  });
}

// Short human name: methods get their class, scripts their file.
export function displayName(ix, n) {
  if (!n) return "?";
  if (n.kind === "script") return `${n.file} (top level)`;
  if (n.kind === "function") {
    const p = ix.byId.get(n.parent);
    return p && p.kind === "class" ? `${p.name}.${n.name}()` : `${n.name}()`;
  }
  return n.name;
}

export function search(ix, query, limit = 12) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const rank = { function: 0, class: 1, endpoint: 2, table: 3, file: 4, group: 5, script: 6 };
  return ix.nodes
    .filter((n) => n.name.toLowerCase().includes(q) || (n.kind === "file" && n.file.toLowerCase().includes(q)))
    .sort(
      (a, b) =>
        (a.name.toLowerCase() === q ? -1 : 0) - (b.name.toLowerCase() === q ? -1 : 0) ||
        (rank[a.kind] ?? 9) - (rank[b.kind] ?? 9) ||
        a.name.length - b.name.length,
    )
    .slice(0, limit);
}
