import { PathLayer, PolygonLayer, ScatterplotLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import DeckGL from "@deck.gl/react";
import { useMemo } from "react";
import { BAD, baseColor, CERTAINTY_ALPHA, dim, GOOD, IN, mix, OK, OUT, SEL, TEXT, TEXT_DIM } from "./colors.js";
import { centre, curve, curve3d, LABEL_SPACE } from "./layout.js";
import { fromDeck, makeViewport, toDeck, VIEW_2D, VIEW_3D } from "./view.js";

const CONTROLLER = { inertia: 250, scrollZoom: { speed: 0.012, smooth: false }, doubleClickZoom: false, keyboard: true };
// 2.5D: left-drag pans, right-drag (or Ctrl/Shift-drag) rotates
const CONTROLLER_3D = { ...CONTROLLER, dragMode: "pan", dragRotate: true };
const FONT = "Inter, -apple-system, 'Segoe UI', sans-serif";
const MAX_PX = 18; // largest label, in pixels

const rect2d = (r) => [
  [r.x0, r.y0],
  [r.x1, r.y0],
  [r.x1, r.y1],
  [r.x0, r.y1],
];
const rect3d = (r) => [
  [r.x0, -r.y0, r.z0],
  [r.x1, -r.y0, r.z0],
  [r.x1, -r.y1, r.z0],
  [r.x0, -r.y1, r.z0],
];
const top3d = (r) => {
  const [x, y] = centre(r);
  return [x, -y, r.z0 + r.h];
};
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function fillFor(r, ctx) {
  const n = r.n;
  let c = baseColor(n);
  if (ctx.lens === "tests" && n.kind === "function" && !n.attrs?.is_test) {
    c = ctx.ix.testedDirect.has(n.id) ? GOOD : ctx.ix.testedReach.has(n.id) ? OK : BAD;
  } else if (ctx.lens === "data") {
    if (n.kind === "table") c = [44, 172, 150];
    else if (ctx.lensSet.has(n.id)) c = [50, 138, 126];
    else if (r.leaf) c = dim(c, 0.6);
  } else if (ctx.lens === "api") {
    if (n.kind === "endpoint") c = [74, 132, 238];
    else if (ctx.lensSet.has(n.id)) c = [62, 98, 164];
    else if (r.leaf) c = dim(c, 0.6);
  }
  if (ctx.sel) {
    if (ctx.inside.has(n.id)) c = mix(c, SEL, 0.45);
    else if (ctx.relOut.has(n.id)) c = mix(c, OUT, 0.55);
    else if (ctx.relIn.has(n.id)) c = mix(c, IN, 0.55);
    else if (r.depth >= 2) c = dim(c, 0.55);
  }
  return [...c, 255];
}

// Labels in screen pixels, placed without overlapping: candidates are projected to the screen and
// placed by priority (packages, files, classes, then the biggest leaves); one that would overlap an
// already placed label is skipped. Containers label their top band; leaves are labelled at their top.
const PRIORITY = { 1: 0, 2: 1, 3: 2 };
function labelsFor(L, vs, size, is3d) {
  const vp = makeViewport(vs, is3d, size);
  const s = 2 ** vs.zoom;
  const cands = [];
  for (const r of L.list) {
    const wpx = (r.x1 - r.x0) * s;
    if (wpx < 36) continue;
    const name = r.n.kind === "script" ? "top-level code" : r.n.kind === "function" ? `${r.n.name}()` : r.n.name;
    let px;
    if (!r.leaf) px = Math.min((LABEL_SPACE[r.depth] ?? 4) * s * 0.8, r.depth === 1 ? 14 : 12);
    else px = Math.min((r.y1 - r.y0) * s * 0.3, wpx / (name.length * 0.62 + 1), MAX_PX);
    if (px < 8) continue;
    const maxChars = Math.max(3, Math.floor((wpx - 4) / (px * 0.6)));
    const text = name.length > maxChars ? `${name.slice(0, maxChars - 1)}…` : name;
    let pos;
    if (r.leaf) pos = is3d ? top3d(r) : centre(r);
    else pos = is3d ? [r.x0 + 2 / s, -(r.y0 + 2 / s), r.z0 + r.h] : [r.x0 + 2 / s, r.y0 + 1.5 / s];
    const [sx, sy] = vp.project(pos);
    if (sx < -200 || sy < -50 || sx > size.width + 50 || sy > size.height + 50) continue;
    const w = text.length * px * 0.6;
    const h = px * 1.25;
    // screen box of the text, matching anchor/baseline used by the TextLayer below
    const box = r.leaf
      ? [sx - w / 2, sy - (is3d ? h + 3 : h / 2), sx + w / 2, sy + (is3d ? -3 : h / 2)]
      : [sx, sy, sx + w, sy + h];
    cands.push({ id: r.id, text, px, pos, leaf: r.leaf, depth: r.depth, box, prio: r.leaf ? 3 + 1 / (1 + px) : PRIORITY[r.depth] ?? 2.5 });
  }
  cands.sort((a, b) => a.prio - b.prio);
  const placed = [];
  const free = (b) => placed.every((p) => b[2] < p.box[0] || b[0] > p.box[2] || b[3] < p.box[1] || b[1] > p.box[3]);
  for (const c of cands) if (free(c.box)) placed.push(c);
  return placed;
}

export default function MapView({ L, ix, sel, lens, lensSet, selLinks, overview, viewState, onViewState, size, onSelect, mode }) {
  const is3d = mode === "3d";

  const ctx = useMemo(() => {
    const relOut = new Set();
    const relIn = new Set();
    for (const { e, dir } of selLinks?.links || []) (dir === "out" ? relOut : relIn).add(dir === "out" ? e.target : e.source);
    return { sel, lens, lensSet, ix, inside: selLinks?.inside || new Set(), relOut, relIn };
  }, [sel, lens, lensSet, ix, selLinks]);

  const paths = useMemo(() => {
    const res = [];
    const add = (sId, tId, color, width) => {
      const a = L.rects.get(sId);
      const b = L.rects.get(tId);
      if (!a || !b) return;
      if (is3d) res.push({ path: curve3d(top3d(a), top3d(b)), color, width, end: top3d(b) });
      else res.push({ path: curve(centre(a), centre(b)), color, width, end: centre(b) });
    };
    if (sel && selLinks) {
      for (const { e, dir } of selLinks.links)
        add(e.source, e.target, [...(dir === "out" ? OUT : IN), CERTAINTY_ALPHA[e.certainty] ?? 150], e.certainty === "proven" ? 2 : 1.4);
    } else {
      for (const g of overview) add(g.source, g.target, [150, 172, 214, 140], 1 + Math.log2(g.count));
    }
    return res;
  }, [L, sel, selLinks, overview, is3d]);

  // Labels depend on the camera: recompute only when it moves by a visible amount.
  const zoomKey = Math.round(viewState.zoom * 4) / 4;
  const posKey = viewState.target.map((v) => Math.round(v / (40 / 2 ** zoomKey))).join(",");
  const rotKey = `${Math.round(viewState.rotationX ?? 0)}:${Math.round((viewState.rotationOrbit ?? 0) / 3)}`;
  // biome-ignore lint: deliberate coarse dependencies
  const labels = useMemo(() => labelsFor(L, viewState, size, is3d), [L, zoomKey, posKey, rotKey, size.width, size.height, is3d]);

  const fillTrigger = [ctx];
  const lineColor = (r) => (r.id === sel ? [...SEL, 255] : r.depth === 1 ? [70, 92, 128, 255] : [255, 255, 255, 26]);
  const blocks = is3d
    ? new SolidPolygonLayer({
        id: "blocks",
        data: L.list,
        getPolygon: rect3d,
        extruded: true,
        wireframe: true,
        getElevation: (r) => r.h,
        getFillColor: (r) => fillFor(r, ctx),
        getLineColor: lineColor,
        material: { ambient: 0.6, diffuse: 0.55, shininess: 12 },
        pickable: true,
        autoHighlight: true,
        highlightColor: [133, 183, 235, 70],
        updateTriggers: { getFillColor: fillTrigger, getLineColor: [sel] },
      })
    : new PolygonLayer({
        id: "blocks",
        data: L.list,
        getPolygon: rect2d,
        getFillColor: (r) => fillFor(r, ctx),
        getLineColor: lineColor,
        getLineWidth: (r) => (r.id === sel ? 2.5 : 1),
        lineWidthUnits: "pixels",
        stroked: true,
        filled: true,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 36],
        updateTriggers: { getFillColor: fillTrigger, getLineColor: [sel], getLineWidth: [sel] },
      });

  const layers = [
    blocks,
    new PathLayer({
      id: "links",
      data: paths,
      getPath: (d) => d.path,
      getColor: (d) => d.color,
      getWidth: (d) => d.width,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      parameters: { depthTest: !is3d }, // in 2.5D arcs stay visible over the blocks
    }),
    new ScatterplotLayer({
      id: "link-ends",
      data: paths,
      getPosition: (d) => d.end,
      getFillColor: (d) => d.color,
      getRadius: 3,
      radiusUnits: "pixels",
      billboard: true,
      parameters: { depthTest: false },
    }),
    new TextLayer({
      id: "labels",
      data: labels,
      getPosition: (d) => d.pos,
      getText: (d) => d.text,
      getSize: (d) => d.px,
      sizeUnits: "pixels",
      getColor: (d) => (sel && !ctx.inside.has(d.id) && !ctx.relOut.has(d.id) && !ctx.relIn.has(d.id) && d.depth >= 2 ? TEXT_DIM : TEXT),
      getTextAnchor: (d) => (d.leaf ? "middle" : "start"),
      getAlignmentBaseline: (d) => (d.leaf ? (is3d ? "bottom" : "center") : "top"),
      getPixelOffset: (d) => (d.leaf && is3d ? [0, -3] : [0, 0]),
      billboard: true,
      fontFamily: FONT,
      fontWeight: 600,
      characterSet: "auto",
      parameters: { depthTest: false },
      updateTriggers: { getColor: [ctx], getAlignmentBaseline: [is3d], getPixelOffset: [is3d] },
    }),
  ];

  return (
    <DeckGL
      views={is3d ? VIEW_3D : VIEW_2D}
      viewState={toDeck(viewState, is3d)}
      onViewStateChange={({ viewState: v }) => onViewState(fromDeck(v, is3d, viewState))}
      controller={is3d ? CONTROLLER_3D : CONTROLLER}
      layers={layers}
      onClick={(info) => onSelect(info.object ? info.object.id : null, { fromMap: true })}
      getCursor={({ isHovering, isDragging }) => (isDragging ? "grabbing" : isHovering ? "pointer" : "grab")}
      getTooltip={({ object }) =>
        object && {
          html: `<b>${escapeHtml(object.n.name)}</b><br/>${escapeHtml(object.n.kind)}${object.n.file ? ` · ${escapeHtml(object.n.file)}${object.n.line ? `:${object.n.line}` : ""}` : ""}${object.n.attrs?.loc ? ` · ${object.n.attrs.loc} lines` : ""}`,
          style: { background: "#1b2638", color: "#e4ecf8", fontSize: "12px", borderRadius: "6px", padding: "6px 8px" },
        }
      }
    />
  );
}
