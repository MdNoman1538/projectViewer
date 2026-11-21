// Nested treemap: groups contain files, files contain classes/functions, classes contain methods.
// Area follows code size (lines), so big code looks big. Coordinates are "world units"; the map
// view zooms and pans over them.
import { hierarchy, treemap, treemapSquarify } from "d3-hierarchy";

export const WIDTH = 1600;
export const HEIGHT = 1000;
const MIN_WEIGHT = 4;

export function weight(n) {
  if (n.kind === "function" || n.kind === "script") return Math.max(MIN_WEIGHT, n.attrs?.loc || 1);
  if (n.kind === "class" || n.kind === "file") {
    const lines = n.attrs?.loc || (n.end_line && n.line ? n.end_line - n.line + 1 : 1);
    return Math.max(MIN_WEIGHT, lines);
  }
  return MIN_WEIGHT * 2; // endpoints, tables, empty groups
}

// Space reserved at the top of a container for its label, by depth (1 = group, 2 = file, 3 = class).
export const LABEL_SPACE = [0, 22, 14, 9, 6];

export function layout(ix) {
  const make = (n) => ({ n, children: (ix.kids.get(n.id) || []).map(make) });
  const tree = { n: { id: "__root__", kind: "root", name: "" }, children: (ix.kids.get(null) || []).map(make) };

  const root = hierarchy(tree)
    .sum((d) => (d.children.length ? 0 : weight(d.n)))
    // biggest first (best squarified shapes); id as tie-breaker keeps the order deterministic
    .sort((a, b) => b.value - a.value || (a.data.n.id < b.data.n.id ? -1 : 1));

  treemap()
    .tile(treemapSquarify.ratio(1.15))
    .size([WIDTH, HEIGHT])
    .paddingTop((d) => LABEL_SPACE[d.depth] ?? 4)
    .paddingInner((d) => (d.depth === 0 ? 10 : d.depth === 1 ? 4 : 1.5))
    .paddingOuter((d) => (d.depth === 0 ? 0 : d.depth === 1 ? 4 : 1.5))
    .round(false)(root);

  const rects = new Map();
  const list = [];
  root.each((d) => {
    if (d.depth === 0) return;
    const r = { id: d.data.n.id, n: d.data.n, depth: d.depth, x0: d.x0, y0: d.y0, x1: d.x1, y1: d.y1, leaf: !d.children };
    rects.set(r.id, r);
    list.push(r);
  });
  list.sort((a, b) => a.depth - b.depth); // parents drawn first, so children sit on top (and get picked)

  // 2.5D: every block stands on top of its parent. Containers are slabs (a little thicker when they
  // hold more code); leaves are towers whose height grows with their size.
  for (const r of list) {
    const parent = r.n.parent ? rects.get(r.n.parent) : null;
    r.z0 = parent ? parent.z0 + parent.h : 0;
    r.h = r.leaf ? towerHeight(r.n) : (SLAB[r.depth] ?? 3) + Math.min(6, 0.6 * Math.log2(1 + subtreeWeight(r, rects)));
  }
  // highest point inside each box (for framing the camera on it)
  for (const r of list) r.zTop = r.z0 + r.h;
  for (let i = list.length - 1; i >= 0; i--) {
    const r = list[i];
    const parent = r.n.parent ? rects.get(r.n.parent) : null;
    if (parent && r.zTop > parent.zTop) parent.zTop = r.zTop;
  }
  const zTop = Math.max(0, ...list.filter((r) => r.depth === 1).map((r) => r.zTop));
  return { rects, list, width: WIDTH, height: HEIGHT, zTop };
}

const SLAB = [0, 5, 4, 3, 3];
const towerHeight = (n) => 3 + Math.min(90, 4.5 * Math.sqrt(weight(n)));
const subtreeWeight = (r) => (r.x1 - r.x0) * (r.y1 - r.y0) * 0.01; // area is proportional to code size

// Arc between two block tops, lifted in the middle in proportion to its length.
export function curve3d(a, b, lift = 0.22, steps = 20) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    pts.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t + Math.sin(Math.PI * t) * len * lift]);
  }
  pts[steps] = [...b];
  return pts;
}

export const centre = (r) => [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2];

// Curved link between two points (quadratic Bézier), as a polyline for deck.gl's PathLayer.
export function curve(a, b, bend = 0.18, steps = 18) {
  const [x0, y0] = a;
  const [x1, y1] = b;
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const cx = mx - dy * bend;
  const cy = my + dx * bend;
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const u = 1 - t;
    pts.push([u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1]);
  }
  return pts;
}

// Camera that fits a rectangle into a viewport of (width x height) pixels.
export function fit(r, width, height, margin = 1.12) {
  const w = Math.max(1, r.x1 - r.x0);
  const h = Math.max(1, r.y1 - r.y0);
  const zoom = Math.log2(Math.min(width / (w * margin), height / (h * margin)));
  return { target: [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, 0], zoom: Math.max(-4, Math.min(9, zoom)) };
}
