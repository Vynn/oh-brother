// Sizes for a chosen image. The page (app.mjs) draws it at each of these in
// turn, until it fits what a template may hold.

// Longest side in px: where an image starts, and the least it's shrunk to
export const IMAGE_MAX = 600, IMAGE_MIN = 128;

// The sizes to try, largest first, for an image w0 x h0 px, and the least of
// them, for the message when none fits. An image never grows, so one smaller
// than IMAGE_MIN is tried once, at its own size: the loop used to stop before
// its first pass for such an image, and a 40 px icon was refused as too
// large. An SVG has no size of its own and starts at IMAGE_MAX.
export function sidesToTry(w0, h0, svg = false) {
  const start = svg ? IMAGE_MAX : Math.min(IMAGE_MAX, Math.max(w0, h0)), least = Math.min(IMAGE_MIN, start);
  const sides = [];
  for (let side = start; side >= least; side = Math.floor(side * 0.8)) sides.push(side);
  return { sides, least };
}

// The image's width and height in px when its longest side is `side`
export function sizeAt(w0, h0, side) {
  const k = side / Math.max(w0, h0);
  return { width: Math.max(1, Math.round(w0 * k)), height: Math.max(1, Math.round(h0 * k)) };
}
