// Label and element geometry, all in mm. Nothing here touches the page: each
// function works on the numbers it's given, so the tests in tests/editor/ can
// run it anywhere.

import { r2, snap } from "./units.mjs";

// Canvas size in mm as designed (mirrors tapes.canvas_dots on the server).
// tape: one of /api/meta's tapes; dpmm: dots per mm.
export function canvasMM(tape, layout, dpmm) {
  let w = tape.dots[0] / dpmm;
  let hh = tape.endless ? +layout.length_mm : tape.dots[1] / dpmm;
  if (layout.orientation === "landscape") [w, hh] = [hh, w];
  return { w, h: hh };
}

// Cut label around the printable canvas, in mm and canvas orientation:
// side margins from the tape width, end margins from the feed (continuous)
// or the die-cut label length.
export function paperMM(tape, layout, dpmm) {
  const c = canvasMM(tape, layout, dpmm);
  const across = Math.max(0, (tape.tape_mm[0] - tape.dots[0] / dpmm) / 2);
  const along = tape.endless ? tape.feed_mm : Math.max(0, (tape.tape_mm[1] - tape.dots[1] / dpmm) / 2);
  const [mx, my] = layout.orientation === "landscape" ? [along, across] : [across, along];
  return { mx, my, w: c.w + 2 * mx, h: c.h + 2 * my };
}

// Bounding box of some elements
export function bounds(els) {
  const l = Math.min(...els.map((e) => e.x)), t = Math.min(...els.map((e) => e.y));
  const r = Math.max(...els.map((e) => e.x + e.w)), b = Math.max(...els.map((e) => e.y + e.h));
  return { l, t, r, b };
}

// Snap lines: the printable area's edges and centre, and the edges and centre
// of every element whose index isn't in `skip` (those being dragged)
export function snapTargets(elements, skip, canvas) {
  const xs = [0, canvas.w / 2, canvas.w], ys = [0, canvas.h / 2, canvas.h];
  elements.forEach((o, j) => {
    if (skip.has(j)) return;
    xs.push(o.x, o.x + o.w / 2, o.x + o.w);
    ys.push(o.y, o.y + o.h / 2, o.y + o.h);
  });
  return { xs, ys };
}

// Closest target to any of the points, within thr: {d: offset, at: target}
export function nearest(points, targets, thr) {
  let best = null;
  for (const p of points) for (const t of targets) {
    const d = t - p;
    if (Math.abs(d) <= thr && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, at: t };
  }
  return best;
}

// Drag a selection whose bounding box started at b0 by (dx, dy). The box
// snaps like a single element: its left, centre or right to a line in
// targets.xs, and likewise down the page; otherwise to the grid. thr is how
// close counts, 0 for no snapping at all (Alt held). Returns the box's new
// corner and the lines it snapped to, for the guides.
export function moveBox(b0, dx, dy, targets, thr) {
  const bw = b0.r - b0.l, bh = b0.b - b0.t, gx = [], gy = [];
  let x = b0.l + dx, y = b0.t + dy;
  const sx = thr && nearest([x, x + bw / 2, x + bw], targets.xs, thr);
  const sy = thr && nearest([y, y + bh / 2, y + bh], targets.ys, thr);
  if (sx) { x += sx.d; gx.push(sx.at); } else if (thr) x = snap(x);
  if (sy) { y += sy.d; gy.push(sy.at); } else if (thr) y = snap(y);
  return { x, y, gx, gy };
}

// The least a box may be resized to, in mm: enough left to pick it up by
export const MIN_W = 1, MIN_H = 0.5;

// Resize a box that started as s0 ({l, t, r, b}) by dragging the handle hd
// ("n", "se", …) by (dx, dy). Only the dragged edges move, each snapping on
// its own, and the box keeps its least size. square: a QR code, which stays
// square, anchored at the corner opposite the handle.
export function resizeBox(s0, hd, dx, dy, targets, thr, square = false) {
  let gx = [], gy = [];
  const edge = (v, list, guides) => {
    if (!thr) return v;
    const s = nearest([v], list, thr);
    if (s) { guides.push(s.at); return s.at; }
    return snap(v);
  };
  let { l, t, r, b } = s0;
  if (hd.includes("w")) l = Math.min(edge(l + dx, targets.xs, gx), r - MIN_W);
  if (hd.includes("e")) r = Math.max(edge(r + dx, targets.xs, gx), l + MIN_W);
  if (hd.includes("n")) t = Math.min(edge(t + dy, targets.ys, gy), b - MIN_H);
  if (hd.includes("s")) b = Math.max(edge(b + dy, targets.ys, gy), t + MIN_H);
  if (square) {
    // Keep only the guides still on an edge
    const s = Math.max(r - l, b - t);
    if (hd.includes("w")) l = r - s; else r = l + s;
    if (hd.includes("n")) t = b - s; else b = t + s;
    gx = gx.filter((v) => Math.abs(v - l) < 1e-6 || Math.abs(v - r) < 1e-6);
    gy = gy.filter((v) => Math.abs(v - t) < 1e-6 || Math.abs(v - b) < 1e-6);
  }
  return { l, t, r, b, gx, gy };
}

// Align: each entry is [id, button title, move element e within the box R]
export const ALIGN = [
  ["left", "Align left", (e, R) => { e.x = R.l; }],
  ["hcenter", "Centre horizontally", (e, R) => { e.x = (R.l + R.r - e.w) / 2; }],
  ["right", "Align right", (e, R) => { e.x = R.r - e.w; }],
  null,
  ["top", "Align top", (e, R) => { e.y = R.t; }],
  ["vcenter", "Centre vertically", (e, R) => { e.y = (R.t + R.b - e.h) / 2; }],
  ["bottom", "Align bottom", (e, R) => { e.y = R.b - e.h; }],
];

// Align elements within the box R, by an entry of ALIGN
export function alignEls(els, entry, R) {
  for (const e of els) {
    entry[2](e, R);
    e.x = r2(e.x); e.y = r2(e.y);
  }
}

// Distribute: equal gaps between three or more elements, across or (vert)
// down; the two outermost stay put
export function distribute(els, vert) {
  const [p, s] = vert ? ["y", "h"] : ["x", "w"];
  els = els.slice().sort((a, b) => a[p] - b[p]);
  if (els.length < 3) return;
  const first = els[0], end = Math.max(...els.map((e) => e[p] + e[s]));
  const gap = (end - first[p] - els.reduce((n, e) => n + e[s], 0)) / (els.length - 1);
  let at = first[p] + first[s] + gap;
  for (const e of els.slice(1, -1)) { e[p] = r2(at); at += e[s] + gap; }
}

// Move elements by (dx, dy)
export function nudge(els, dx, dy) {
  for (const e of els) { e.x = r2(e.x + dx); e.y = r2(e.y + dy); }
}

// Resize elements from the keyboard: each grows or shrinks by (dw, dh) at its
// right and bottom edges, down to the least size. A QR code stays square, so
// it takes the one change it was given.
export function resizeBy(els, dw, dh) {
  for (const e of els) {
    if (e.type === "qr") e.w = e.h = r2(Math.max(MIN_W, e.w + (dw || dh)));
    else { e.w = r2(Math.max(MIN_W, e.w + dw)); e.h = r2(Math.max(MIN_H, e.h + dh)); }
  }
}

// Scale every element when the label changes shape, so the layout still fits
// the new canvas. QR codes stay square, centred in the space they had.
export function rescale(elements, kx, ky) {
  if (Math.abs(kx - 1) <= 1e-6 && Math.abs(ky - 1) <= 1e-6) return;
  for (const e of elements) {
    e.x = r2(e.x * kx); e.w = r2(e.w * kx);
    e.y = r2(e.y * ky); e.h = r2(e.h * ky);
    if (e.type === "qr") {
      const s = Math.min(e.w, e.h);
      e.x = r2(e.x + (e.w - s) / 2); e.y = r2(e.y + (e.h - s) / 2); e.w = e.h = s;
    }
  }
}
