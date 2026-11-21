// One place for every colour on the map (RGB arrays for deck.gl).

export const BASE = {
  group: [22, 30, 46],
  file: [31, 43, 64],
  class: [46, 63, 92],
  function: [66, 88, 126],
  method: [76, 100, 142],
  script: [92, 80, 126],
  endpoint: [52, 98, 184],
  table: [34, 118, 106],
  test: [44, 92, 70],
};

export const SEL = [133, 183, 235];
export const OUT = [104, 168, 255]; // what the selection uses
export const IN = [240, 168, 80]; // what uses the selection
export const GOOD = [70, 150, 92];
export const OK = [62, 116, 82];
export const BAD = [150, 72, 72];
export const TEXT = [228, 236, 248];
export const TEXT_DIM = [140, 158, 189];

export const CERTAINTY_ALPHA = { proven: 235, inferred: 165, pattern: 120 };

export function baseColor(n) {
  if (n.kind === "function") {
    if (n.attrs?.is_test) return BASE.test;
    return n.attrs?.method ? BASE.method : BASE.function;
  }
  if (n.kind === "file" && n.attrs?.is_test) return [30, 52, 46];
  return BASE[n.kind] || BASE.file;
}

export const mix = (a, b, t) => [0, 1, 2].map((i) => Math.round(a[i] * (1 - t) + b[i] * t));
export const dim = (c, f = 0.45) => [c[0] * f, c[1] * f, c[2] * f];
