// Layout of ONE level of the folder tree: the children of the current focus become blocks on a
// ground plane, separated by "streets". Size = number of functions inside (lines of code when every
// block on the level is a single function). Footprint grows gently with size, so small things stay
// clickable; height grows with size relative to the biggest sibling (bigger = clearly taller).
import { hierarchy, treemap, treemapSquarify } from "d3-hierarchy";

export const WIDTH = 1000;
export const HEIGHT = 640;
const STREET = 22; // gap between blocks
const MIN_H = 12;
const MAX_H = 170;

export function layoutLevel(focus) {
  const kids = focus?.children || [];
  const rects = new Map();
  if (!kids.length) return { blocks: [], rects, width: WIDTH, height: HEIGHT, zTop: 0 };
  const byFunctions = Math.max(...kids.map((k) => k.stats.fn)) > 1;
  const size = (t) => Math.max(byFunctions ? 0.5 : 1, byFunctions ? t.stats.fn : t.stats.loc);
  const maxSize = Math.max(1, ...kids.map(size));

  const root = hierarchy({ children: kids.map((t) => ({ t })) })
    .sum((d) => (d.t ? 2 + 3 * Math.sqrt(size(d.t)) : 0))
    .sort((a, b) => b.value - a.value || (a.data.t?.id < b.data.t?.id ? -1 : 1));
  treemap().tile(treemapSquarify.ratio(1.4)).size([WIDTH, HEIGHT]).paddingInner(STREET).paddingOuter(STREET).round(false)(root);

  const blocks = root.leaves().map((d) => {
    const t = d.data.t;
    const b = { id: t.id, t, x0: d.x0, y0: d.y0, x1: d.x1, y1: d.y1, z0: 0, h: MIN_H + (MAX_H - MIN_H) * Math.sqrt(size(t) / maxSize) };
    b.zTop = b.h;
    rects.set(b.id, b);
    return b;
  });
  return { blocks, rects, width: WIDTH, height: HEIGHT, zTop: Math.max(...blocks.map((b) => b.h)), measure: byFunctions ? "functions" : "lines" };
}

export const centre = (r) => [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2];

// Curved link between two points (quadratic Bézier), as a polyline for deck.gl's PathLayer.
export function curve(a, b, bend = 0.18, steps = 18) {
  const [x0, y0] = a;
  const [x1, y1] = b;
  const cx = (x0 + x1) / 2 - (y1 - y0) * bend;
  const cy = (y0 + y1) / 2 + (x1 - x0) * bend;
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const u = 1 - t;
    pts.push([u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1]);
  }
  return pts;
}

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

// Camera that fits a rectangle into a viewport of (width x height) pixels (flat map).
export function fit(r, width, height, margin = 1.12) {
  const w = Math.max(1, r.x1 - r.x0);
  const h = Math.max(1, r.y1 - r.y0);
  const zoom = Math.log2(Math.min(width / (w * margin), height / (h * margin)));
  return { target: [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, 0], zoom: Math.max(-4, Math.min(9, zoom)) };
}
