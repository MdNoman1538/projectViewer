// The project as a FOLDER tree: root › folders › files › classes › functions (+ a Database block for
// tables). The map shows one level of it at a time. Pure logic, unit-tested with `npm test`.

const CALLISH = new Set(["calls", "instantiates"]);
const DATA = new Set(["reads", "writes"]);
// Folders that only package code (src-layout) carry no meaning of their own: their contents are
// shown as top-level modules.
const TRANSPARENT_ROOTS = new Set(["src"]);
const EMPTY = () => ({ fn: 0, loc: 0, folders: 0, files: 0, testFiles: 0, classes: 0, functions: 0, tests: 0, endpoints: 0, tables: 0, tested: 0, data: 0 });

export function buildTree(ix, rootName = "project") {
  const T = new Map();
  const add = (id, kind, name, parent, n = null, path = "") => {
    const t = { id, kind, name, parent, children: [], n, path, stats: EMPTY() };
    T.set(id, t);
    if (parent) T.get(parent).children.push(t);
    return t;
  };
  const root = add("root", "root", rootName, null);

  // folders and files, from the file paths
  for (const n of ix.nodes) {
    if (n.kind !== "file") continue;
    let parent = "root";
    let acc = "";
    const dirs = n.file.split("/").slice(0, -1);
    dirs.forEach((part, i) => {
      acc = acc ? `${acc}/${part}` : part;
      if (i === 0 && TRANSPARENT_ROOTS.has(part)) return;
      const id = `dir:${acc}`;
      if (!T.has(id)) add(id, "folder", part, parent, null, acc);
      parent = id;
    });
    add(n.id, "file", n.name, parent, n, n.file);
  }
  const tables = ix.nodes.filter((n) => n.kind === "table");
  if (tables.length) {
    add("db", "database", "Database", "root");
    for (const n of tables) add(n.id, "table", n.name, "db", n);
  }
  // code inside files and classes (a parent always exists before its children are placed)
  let pending = ix.nodes.filter((n) => n.kind === "class" || n.kind === "function" || n.kind === "script" || n.kind === "endpoint");
  while (pending.length) {
    const next = [];
    for (const n of pending) {
      if (T.has(n.parent)) add(n.id, n.kind, n.kind === "script" ? "top-level code" : n.name, n.parent, n, n.file);
      else next.push(n);
    }
    if (next.length === pending.length) break; // orphans: skip rather than loop forever
    pending = next;
  }

  const touchesData = (id) => (ix.out.get(id) || []).some((e) => DATA.has(e.kind));
  const visit = (t) => {
    const s = t.stats;
    for (const c of t.children) {
      visit(c);
      for (const k of Object.keys(s)) s[k] += c.stats[k];
    }
    const n = t.n;
    if (t.kind === "folder") s.folders += 1;
    else if (t.kind === "file") {
      s.files += 1;
      if (n.attrs?.is_test) s.testFiles += 1;
      s.loc = n.attrs?.loc || s.loc; // the whole file, not only the code inside definitions
    } else if (t.kind === "class") {
      s.classes += 1;
      s.loc = Math.max(s.loc, n.end_line && n.line ? n.end_line - n.line + 1 : 1);
    } else if (t.kind === "function") {
      s.fn += 1;
      if (n.attrs?.is_test) s.tests += 1;
      else {
        s.functions += 1;
        if (ix.testedReach.has(n.id)) s.tested += 1;
      }
      if (touchesData(n.id)) s.data += 1;
      s.loc = n.attrs?.loc || 1;
    } else if (t.kind === "script") {
      if (touchesData(n.id)) s.data += 1;
      s.loc = n.attrs?.loc || 1;
    } else if (t.kind === "endpoint") {
      s.endpoints += 1;
      s.loc = 1;
    } else if (t.kind === "table") {
      s.tables += 1;
    }
    t.isTest = t.kind === "function" ? !!n.attrs?.is_test : s.files > 0 && s.testFiles === s.files;
  };
  visit(root);
  return { T, root };
}

export function treeAncestors(tree, id) {
  const res = [];
  let t = tree.T.get(id);
  while (t && t.parent) {
    res.unshift(t.parent);
    t = tree.T.get(t.parent);
  }
  return res;
}

export function subtreeIds(t, out = []) {
  out.push(t.id);
  for (const c of t.children) subtreeIds(c, out);
  return out;
}

// Map every world node inside `focus` to the child block of `focus` that contains it.
export function blockIndex(tree, focusId) {
  const blockOf = new Map();
  const focus = tree.T.get(focusId);
  for (const c of focus?.children || []) for (const id of subtreeIds(c)) blockOf.set(id, c.id);
  return blockOf;
}

// Dependencies between the blocks of one level, summed: calls, object creation, and data access.
export function levelLinks(ix, tree, focusId, kinds = ["calls", "instantiates", "reads", "writes"]) {
  const want = new Set(kinds);
  const blockOf = blockIndex(tree, focusId);
  const pairs = new Map();
  for (const e of ix.edges) {
    if (!want.has(e.kind)) continue;
    const a = blockOf.get(e.source);
    const b = blockOf.get(e.target);
    if (!a || !b || a === b) continue;
    const key = `${a}\u0000${b}`;
    pairs.set(key, (pairs.get(key) || 0) + (e.count || 1));
  }
  return [...pairs.entries()].map(([k, count]) => {
    const [source, target] = k.split("\u0000");
    return { source, target, count };
  });
}

// Links from a block to everything outside it, summed per sibling block at the current level. When the
// other end lies outside the current level, it is named by its top-level module, marked "@" (elsewhere).
export function blockDeps(ix, tree, focusId, blockId) {
  const sibling = blockIndex(tree, focusId);
  const top = focusId === "root" ? sibling : blockIndex(tree, "root");
  const blockOf = { get: (id) => sibling.get(id) || (top.get(id) ? `@${top.get(id)}` : undefined) };
  const inside = new Set(subtreeIds(tree.T.get(blockId)));
  const out = new Map();
  const inn = new Map();
  const bump = (m, k, e) => m.set(k, (m.get(k) || 0) + (e.count || 1));
  for (const id of inside) {
    for (const e of ix.out.get(id) || []) if (!inside.has(e.target) && (CALLISH.has(e.kind) || DATA.has(e.kind))) bump(out, blockOf.get(e.target) || "elsewhere", e);
    for (const e of ix.inn.get(id) || []) if (!inside.has(e.source) && (CALLISH.has(e.kind) || DATA.has(e.kind))) bump(inn, blockOf.get(e.source) || "elsewhere", e);
  }
  const sorted = (m) => [...m.entries()].sort((a, b) => b[1] - a[1]);
  return { out: sorted(out), in: sorted(inn) };
}

// Change overlay: a block is "changed" when anything inside it changed, else "affected" when anything
// inside it depends on or is reached by the change.
export function changeMarks(tree, cs) {
  const rank = { changed: 3, moved: 2, affected: 1 };
  const marks = new Map();
  const up = (id, v) => {
    for (let t = tree.T.get(id); t; t = t.parent ? tree.T.get(t.parent) : null) {
      if ((rank[marks.get(t.id)] || 0) >= rank[v]) break; // ancestors are already marked at least this strongly
      marks.set(t.id, v);
    }
  };
  for (const [id, how] of Object.entries(cs?.changed || {})) up(id, how === "moved" ? "moved" : "changed");
  for (const id of [...Object.keys(cs?.upstream || {}), ...Object.keys(cs?.downstream || {})]) up(id, "affected");
  return marks;
}
