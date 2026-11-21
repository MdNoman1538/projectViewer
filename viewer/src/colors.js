// One place for every colour on the map (RGB arrays for deck.gl).

export const KIND = {
  root: [40, 52, 76],
  folder: [58, 80, 116],
  database: [34, 118, 106],
  file: [70, 94, 134],
  class: [64, 104, 142],
  function: [86, 112, 156],
  script: [102, 88, 138],
  endpoint: [52, 98, 184],
  table: [34, 118, 106],
  test: [46, 98, 74],
};

export const GROUND = [20, 29, 44];
export const SEL = [133, 183, 235];
export const OUT = [104, 168, 255]; // what the selection uses
export const IN = [240, 168, 80]; // what uses the selection
export const GOOD = [70, 150, 92];
export const OK = [62, 116, 82];
export const AMBER = [172, 132, 58];
export const BAD = [160, 74, 70];
export const TEAL = [44, 172, 150];
export const BLUE = [74, 132, 238];
export const TEXT = [232, 239, 250];
export const TEXT_DIM = [150, 166, 196];

export const CERTAINTY_ALPHA = { proven: 235, inferred: 165, pattern: 120 };

export const mix = (a, b, t) => [0, 1, 2].map((i) => Math.round(a[i] * (1 - t) + b[i] * t));
export const dim = (c, f = 0.5) => [c[0] * f, c[1] * f, c[2] * f];
export const css = (c) => `rgb(${c.join(",")})`;
