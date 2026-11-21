// Cameras: 2D flat map and the 2.5D city (tilted orthographic orbit view, as in PR World v5).
// The app keeps the camera in LAYOUT coordinates (y grows downwards). deck.gl's orbit view has y
// pointing up, so y is negated when talking to it.
import { OrbitView, OrthographicView } from "@deck.gl/core";
import { fit } from "./layout.js";

export const VIEW_2D = new OrthographicView({ id: "map", flipY: true });
export const VIEW_3D = new OrbitView({ id: "map", orbitAxis: "Z", orthographic: true });
export const PITCH = 35;
export const ORBIT = -30;
const LIMITS = { minZoom: -4, maxZoom: 10 };

export function toDeck(vs, is3d) {
  const [tx, ty, tz = 0] = vs.target;
  return is3d
    ? { ...vs, ...LIMITS, target: [tx, -ty, tz], rotationX: vs.rotationX ?? PITCH, rotationOrbit: vs.rotationOrbit ?? ORBIT }
    : { ...vs, ...LIMITS, target: [tx, ty, 0] };
}

export function fromDeck(v, is3d, prev) {
  return {
    target: is3d ? [v.target[0], -v.target[1], v.target[2] || 0] : [v.target[0], v.target[1], 0],
    zoom: v.zoom,
    rotationX: is3d ? v.rotationX : prev?.rotationX,
    rotationOrbit: is3d ? v.rotationOrbit : prev?.rotationOrbit,
  };
}

export function makeViewport(vs, is3d, size) {
  return (is3d ? VIEW_3D : VIEW_2D).makeViewport({ width: size.width, height: size.height, viewState: toDeck(vs, is3d) });
}

// Camera that frames box r (with its towers, up to r.zTop) in the current view mode.
export function fitView(r, size, is3d, prev, margin = 1.12) {
  if (!is3d) return fit(r, size.width, size.height, margin);
  const base = {
    target: [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, 0],
    zoom: 0,
    rotationX: prev?.rotationX ?? PITCH,
    rotationOrbit: prev?.rotationOrbit ?? ORBIT,
  };
  const vp = makeViewport(base, true, size);
  const top = r.zTop ?? 0;
  const xs = [];
  const ys = [];
  for (const [x, y] of [
    [r.x0, r.y0],
    [r.x1, r.y0],
    [r.x1, r.y1],
    [r.x0, r.y1],
  ])
    for (const z of [0, top]) {
      const [px, py] = vp.project([x, -y, z]);
      xs.push(px);
      ys.push(py);
    }
  const bw = Math.max(1, Math.max(...xs) - Math.min(...xs));
  const bh = Math.max(1, Math.max(...ys) - Math.min(...ys));
  const zoom = Math.max(-4, Math.min(9, Math.log2(Math.min(size.width / (bw * margin), size.height / (bh * margin)))));
  // aim at the point under the centre of the projected box
  const mid = vp.unproject([(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2], { targetZ: 0 });
  return { ...base, target: [mid[0], -mid[1], 0], zoom };
}
