import { PathLayer, PolygonLayer, ScatterplotLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import DeckGL from "@deck.gl/react";
import { useMemo } from "react";
import { AMBER, BAD, BLUE, dim, GOOD, GROUND, IN, KIND, mix, OK, OUT, SEL, TEAL, TEXT, TEXT_DIM } from "./colors.js";
import { centre, curve, curve3d, roofTiles } from "./layout.js";
import { fromDeck, makeViewport, toDeck, VIEW_2D, VIEW_3D } from "./view.js";

const CONTROLLER = { inertia: 250, scrollZoom: { speed: 0.012, smooth: false }, doubleClickZoom: false, keyboard: false };
const CONTROLLER_3D = { ...CONTROLLER, dragMode: "pan", dragRotate: true }; // right-drag / Ctrl-drag rotates
const FONT = "Inter, -apple-system, 'Segoe UI', sans-serif";
const NAME_PX = 14;
const CHANGED = [204, 72, 72];
const AFFECTED = [222, 150, 60];
const SUB_PX = 11;

const flat = (r) => [
  [r.x0, r.y0],
  [r.x1, r.y0],
  [r.x1, r.y1],
  [r.x0, r.y1],
];
const ground3d = (r) => flat(r).map(([x, y]) => [x, -y, 0]);
const top3d = (b) => {
  const [x, y] = centre(b);
  return [x, -y, b.h];
};
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmt = (n) => n.toLocaleString("en");

// Facts about a block (tooltips, lists): functions, files, lines.
export function describe(t) {
  return badge(t, "facts");
}

// The second line under a block's name, for the current lens. The architecture lens shows names only:
// the block's size already tells how big it is.
export function badge(t, lens, ix) {
  const s = t.stats;
  if (lens === "map") return "";
  if (lens === "tests") {
    if (t.kind === "function") return t.isTest ? "test" : ix.testedDirect.has(t.id) ? "tested" : ix.testedReach.has(t.id) ? "tested indirectly" : "no test";
    if (t.isTest) return `${s.tests} tests`;
    return s.functions ? `${Math.round((100 * s.tested) / s.functions)}% tested` : "";
  }
  if (lens === "api") return s.endpoints ? `${s.endpoints} API endpoint${s.endpoints > 1 ? "s" : ""}` : "";
  if (lens === "data") return t.kind === "database" ? `${s.tables} tables` : s.data ? `${s.data} use data` : "";
  const fns = `${s.fn} function${s.fn === 1 ? "" : "s"}`;
  switch (t.kind) {
    case "folder":
      return `${fns} · ${s.files} file${s.files === 1 ? "" : "s"}`;
    case "file":
      return `${fns} · ${fmt(s.loc)} lines`;
    case "class":
      return `${s.fn} method${s.fn === 1 ? "" : "s"} · ${fmt(s.loc)} lines`;
    case "function":
    case "script":
      return `${fmt(s.loc)} lines`;
    case "database":
      return `${s.tables} tables`;
    case "endpoint":
      return "API endpoint";
    default:
      return "";
  }
}

function fillFor(t, ctx) {
  let c = t.isTest ? KIND.test : KIND[t.kind] || KIND.file;
  const s = t.stats;
  if (ctx.lens === "tests") {
    if (t.kind === "function") c = t.isTest ? KIND.test : ctx.ix.testedDirect.has(t.id) ? GOOD : ctx.ix.testedReach.has(t.id) ? OK : BAD;
    else if (!t.isTest && s.functions) {
      const r = s.tested / s.functions;
      c = r >= 0.6 ? GOOD : r >= 0.3 ? AMBER : BAD;
    } else if (!t.isTest) c = dim(c, 0.6);
  } else if (ctx.lens === "data") {
    c = t.kind === "database" || t.kind === "table" ? TEAL : s.data ? mix(c, TEAL, 0.6) : dim(c, 0.6);
  } else if (ctx.lens === "api") {
    c = s.endpoints || ctx.lensSet.has(t.id) ? mix(c, BLUE, 0.65) : dim(c, 0.6);
  }
  if (ctx.marks) {
    const m = ctx.marks.get(t.id);
    c = m === "changed" ? CHANGED : m === "affected" ? AFFECTED : dim(c, 0.42);
  }
  if (ctx.sel) {
    if (t.id === ctx.sel) c = mix(c, SEL, 0.4);
    else if (ctx.relOut.has(t.id)) c = mix(c, OUT, 0.5);
    else if (ctx.relIn.has(t.id)) c = mix(c, IN, 0.5);
    else c = dim(c, 0.62);
  }
  return [...c, 255];
}

// Names and badges in screen pixels, placed without overlap (biggest blocks first).
function labelsFor(L, vs, size, is3d, lens, ix, marks) {
  const vp = makeViewport(vs, is3d, size);
  const s = 2 ** vs.zoom;
  const cands = [];
  for (const b of L.blocks) {
    const wpx = (b.x1 - b.x0) * s;
    if (wpx < 34) continue;
    const maxChars = Math.max(4, Math.floor((wpx + 30) / (NAME_PX * 0.58)));
    const name = b.t.kind === "function" ? `${b.t.name}()` : b.t.name;
    const text = name.length > maxChars ? `${name.slice(0, maxChars - 1)}…` : name;
    const mark = marks?.get(b.id);
    const sub = marks ? (mark === "changed" ? "changed" : mark === "affected" ? "affected" : "") : badge(b.t, lens, ix);
    const pos = is3d ? top3d(b) : centre(b);
    const [sx, sy] = vp.project(pos);
    if (sx < -100 || sy < -60 || sx > size.width + 100 || sy > size.height + 60) continue;
    const w = Math.max(text.length * NAME_PX * 0.58, sub.length * SUB_PX * 0.55);
    const top = is3d ? sy - 34 : sy - 16;
    cands.push({ id: b.id, text, sub, pos, box: [sx - w / 2, top, sx + w / 2, top + 32], area: (b.x1 - b.x0) * (b.y1 - b.y0) });
  }
  cands.sort((a, b) => b.area - a.area);
  const placed = [];
  const free = (bx) => placed.every((p) => bx[2] < p.box[0] || bx[0] > p.box[2] || bx[3] < p.box[1] || bx[1] > p.box[3]);
  for (const c of cands) if (free(c.box)) placed.push(c);
  return placed;
}

export default function MapView({ L, ix, sel, lens, lensSet, links, viewState, onViewState, size, onSelect, onTile, mode, marks }) {
  const is3d = mode === "3d";

  const ctx = useMemo(() => {
    const relOut = new Set();
    const relIn = new Set();
    if (sel)
      for (const l of links) {
        if (l.source === sel) relOut.add(l.target);
        if (l.target === sel) relIn.add(l.source);
      }
    return { sel, lens, lensSet, ix, relOut, relIn, marks };
  }, [sel, lens, lensSet, ix, links, marks]);

  const paths = useMemo(() => {
    const res = [];
    for (const l of links) {
      const a = L.rects.get(l.source);
      const b = L.rects.get(l.target);
      if (!a || !b) continue;
      const touches = sel && (l.source === sel || l.target === sel);
      const color = touches ? [...(l.source === sel ? OUT : IN), 235] : [160, 180, 220, sel ? 35 : 150];
      const width = (touches ? 1.5 : 1) * (1 + Math.log2(l.count));
      res.push(
        is3d
          ? { path: curve3d(top3d(a), top3d(b)), color, width, end: top3d(b) }
          : { path: curve(centre(a), centre(b)), color, width, end: centre(b) },
      );
    }
    return res;
  }, [L, links, sel, is3d]);

  // Labels depend on the camera: recompute only when it moves by a visible amount.
  const zoomKey = Math.round(viewState.zoom * 4) / 4;
  const posKey = viewState.target.map((v) => Math.round(v / (40 / 2 ** zoomKey))).join(",");
  const rotKey = `${Math.round(viewState.rotationX ?? 0)}:${Math.round((viewState.rotationOrbit ?? 0) / 3)}`;
  // biome-ignore lint: deliberate coarse dependencies
  const labels = useMemo(() => labelsFor(L, viewState, size, is3d, lens, ix, marks), [L, zoomKey, posKey, rotKey, size.width, size.height, is3d, lens, ix, marks]);

  const tiles = useMemo(() => L.blocks.flatMap((b) => roofTiles(b)), [L]);
  const tileFill = (tile) => {
    const own = fillFor(tile.t, { ...ctx, sel: null }); // the tile's own lens colour (e.g. its % tested)
    let c = mix(own, [255, 255, 255], 0.07);
    if (ctx.sel && tile.parent !== ctx.sel && !ctx.relOut.has(tile.parent) && !ctx.relIn.has(tile.parent)) c = dim(c, 0.62);
    else if (ctx.sel && tile.parent === ctx.sel) c = mix(c, SEL, 0.3);
    return [...c, 255];
  };
  const groundRect = { x0: -30, y0: -30, x1: L.width + 30, y1: L.height + 30 };
  const lineColor = (b) => (b.id === sel ? [...SEL, 255] : [255, 255, 255, 40]);
  const layers = [
    is3d
      ? new SolidPolygonLayer({ id: "ground", data: [groundRect], getPolygon: ground3d, getFillColor: GROUND })
      : new PolygonLayer({ id: "ground", data: [groundRect], getPolygon: flat, getFillColor: GROUND, stroked: false }),
    is3d
      ? new SolidPolygonLayer({
          id: "blocks",
          data: L.blocks,
          getPolygon: (b) => ground3d(b),
          extruded: true,
          wireframe: true,
          getElevation: (b) => b.h,
          getFillColor: (b) => fillFor(b.t, ctx),
          getLineColor: lineColor,
          material: { ambient: 0.55, diffuse: 0.6, shininess: 16 },
          pickable: true,
          autoHighlight: true,
          highlightColor: [133, 183, 235, 80],
          updateTriggers: { getFillColor: [ctx], getLineColor: [sel] },
        })
      : new PolygonLayer({
          id: "blocks",
          data: L.blocks,
          getPolygon: flat,
          getFillColor: (b) => fillFor(b.t, ctx),
          getLineColor: lineColor,
          getLineWidth: (b) => (b.id === sel ? 2.5 : 1),
          lineWidthUnits: "pixels",
          stroked: true,
          pickable: true,
          autoHighlight: true,
          highlightColor: [255, 255, 255, 40],
          updateTriggers: { getFillColor: [ctx], getLineColor: [sel], getLineWidth: [sel] },
        }),
    new PolygonLayer({
      id: "roofs",
      data: tiles,
      getPolygon: (d) => (is3d ? flat(d).map(([x, y]) => [x, -y, d.z + 0.4]) : flat(d)),
      getFillColor: tileFill,
      getLineColor: [8, 13, 22, 230],
      getLineWidth: 1.2,
      lineWidthUnits: "pixels",
      stroked: true,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 60],
      updateTriggers: { getFillColor: [ctx], getPolygon: [is3d] },
    }),
    new PathLayer({
      id: "links",
      data: paths,
      getPath: (d) => d.path,
      getColor: (d) => d.color,
      getWidth: (d) => d.width,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      parameters: { depthTest: !is3d },
    }),
    new ScatterplotLayer({
      id: "link-ends",
      data: paths,
      getPosition: (d) => d.end,
      getFillColor: (d) => d.color,
      getRadius: 3.5,
      radiusUnits: "pixels",
      billboard: true,
      parameters: { depthTest: false },
    }),
    new TextLayer({
      id: "names",
      data: labels,
      getPosition: (d) => d.pos,
      getText: (d) => d.text,
      getSize: NAME_PX,
      sizeUnits: "pixels",
      getColor: (d) => (sel && d.id !== sel && !ctx.relOut.has(d.id) && !ctx.relIn.has(d.id) ? TEXT_DIM : TEXT),
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      getPixelOffset: is3d ? [0, -18] : [0, -1],
      billboard: true,
      fontFamily: FONT,
      fontWeight: 700,
      characterSet: "auto",
      parameters: { depthTest: false },
      updateTriggers: { getColor: [ctx], getPixelOffset: [is3d] },
    }),
    new TextLayer({
      id: "badges",
      data: labels.filter((d) => d.sub),
      getPosition: (d) => d.pos,
      getText: (d) => d.sub,
      getSize: SUB_PX,
      sizeUnits: "pixels",
      getColor: TEXT_DIM,
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      getPixelOffset: is3d ? [0, -4] : [0, 14],
      billboard: true,
      fontFamily: FONT,
      characterSet: "auto",
      parameters: { depthTest: false },
      updateTriggers: { getPixelOffset: [is3d] },
    }),
  ];

  return (
    <DeckGL
      views={is3d ? VIEW_3D : VIEW_2D}
      viewState={toDeck(viewState, is3d)}
      onViewStateChange={({ viewState: v }) => onViewState(fromDeck(v, is3d, viewState))}
      controller={is3d ? CONTROLLER_3D : CONTROLLER}
      layers={layers}
      onClick={(info) => {
        if (info.object && info.layer?.id === "roofs") return onTile(info.object);
        onSelect(info.object && info.layer?.id === "blocks" ? info.object.id : null, { fromMap: true });
      }}
      getCursor={({ isHovering, isDragging }) => (isDragging ? "grabbing" : isHovering ? "pointer" : "grab")}
      getTooltip={({ object, layer }) =>
        (layer?.id === "blocks" || layer?.id === "roofs") &&
        object && {
          html: `<b>${escapeHtml(object.t.name)}</b><br/>${escapeHtml(describe(object.t))}${lens !== "map" && badge(object.t, lens, ix) ? `<br/>${escapeHtml(badge(object.t, lens, ix))}` : ""}<br/><i>${layer.id === "roofs" ? "click to open" : object.t.children.length ? "click again to open" : "click to select"}</i>`,
          style: { background: "#1b2638", color: "#e4ecf8", fontSize: "12px", borderRadius: "6px", padding: "6px 8px" },
        }
      }
    />
  );
}
