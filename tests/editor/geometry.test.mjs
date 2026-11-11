import { eq, near, suite, test } from "./harness.mjs";
import * as g from "../../app/static/geometry.mjs";

suite("geometry");

// As /api/meta gives them: 300 dpi, and two of the server's tapes
const DPMM = 300 / 25.4;
const ENDLESS = { dots: [696, 0], endless: true, tape_mm: [62, 0], feed_mm: 2.96 };
const DIE_CUT = { dots: [306, 991], endless: false, tape_mm: [29, 90], feed_mm: 0 };
const size = (o, keys = ["w", "h"]) => keys.map((k) => Math.round(o[k] * 1000) / 1000);

// A label 60 x 30 mm: lines at its edges and centre
const LABEL = { xs: [0, 30, 60], ys: [0, 15, 30] };
const NEAR = 0.5;   // how close counts as snapping, in mm

test("continuous tape is as long as the layout says", () => {
  eq(size(g.canvasMM(ENDLESS, { length_mm: 30, orientation: "portrait" }, DPMM)), [58.928, 30]);
  eq(size(g.canvasMM(ENDLESS, { length_mm: "45", orientation: "portrait" }, DPMM)), [58.928, 45]);
});

test("a die-cut label has its own length", () => {
  eq(size(g.canvasMM(DIE_CUT, { length_mm: 30, orientation: "portrait" }, DPMM)), [25.908, 83.905]);
});

test("text along the tape swaps width and height", () => {
  eq(size(g.canvasMM(ENDLESS, { length_mm: 30, orientation: "landscape" }, DPMM)), [30, 58.928]);
});

test("the cut label adds the tape's margins", () => {
  const keys = ["mx", "my", "w", "h"];
  eq(size(g.paperMM(ENDLESS, { length_mm: 30, orientation: "portrait" }, DPMM), keys), [1.536, 2.96, 62, 35.92]);
  eq(size(g.paperMM(ENDLESS, { length_mm: 30, orientation: "landscape" }, DPMM), keys), [2.96, 1.536, 35.92, 62]);
  eq(size(g.paperMM(DIE_CUT, { orientation: "portrait" }, DPMM), keys), [1.546, 3.048, 29, 90]);
});

test("bounding box of several elements", () => {
  eq(g.bounds([{ x: 2, y: 3, w: 10, h: 4 }, { x: 8, y: 1, w: 10, h: 2 }]), { l: 2, t: 1, r: 18, b: 7 });
});

test("snap lines: the label and every element not being dragged", () => {
  const els = [{ x: 1, y: 1, w: 2, h: 2 }, { x: 8, y: 1, w: 10, h: 2 }];
  eq(g.snapTargets(els, new Set([0]), { w: 60, h: 30 }), { xs: [0, 30, 60, 8, 13, 18], ys: [0, 15, 30, 1, 2, 3] });
  eq(g.snapTargets(els, new Set([0, 1]), { w: 60, h: 30 }), LABEL);
});

test("the nearest line within reach", () => {
  eq(g.nearest([10], [9.5, 10.25], NEAR), { d: 0.25, at: 10.25 });
  eq(g.nearest([10], [11], NEAR), null);
  eq(g.nearest([10], [9.75, 10.25], NEAR), { d: -0.25, at: 9.75 });   // a tie goes to the first
  eq(g.nearest([1, 29.75], [0, 30], NEAR), { d: 0.25, at: 30 });      // any of the points may be the one
});

const BOX = { l: 10, t: 5, r: 20, b: 9 };   // 10 x 4 mm

test("a dragged box snaps its left edge, centre or right edge", () => {
  eq(g.moveBox(BOX, -9.75, 0, LABEL, NEAR), { x: 0, y: 5, gx: [0], gy: [] });
  eq(g.moveBox(BOX, 14.75, 0, LABEL, NEAR), { x: 25, y: 5, gx: [30], gy: [] });
  eq(g.moveBox(BOX, 40.25, 0, LABEL, NEAR), { x: 50, y: 5, gx: [60], gy: [] });
});

test("a dragged box snaps down the page too", () => {
  eq(g.moveBox(BOX, 0, 7.75, LABEL, NEAR), { x: 10, y: 13, gx: [], gy: [15] });   // its middle on the label's
  eq(g.moveBox(BOX, 0, 21.25, LABEL, NEAR), { x: 10, y: 26, gx: [], gy: [30] });   // its bottom on the label's
});

test("away from any line a dragged box keeps to the grid", () => {
  eq(g.moveBox(BOX, 3.2, 2.3, LABEL, NEAR), { x: 13, y: 7.5, gx: [], gy: [] });
});

test("with Alt held nothing snaps", () => {
  const m = g.moveBox(BOX, 3.2, -4.9, LABEL, 0);
  near(m.x, 13.2); near(m.y, 0.1);
  eq([m.gx, m.gy], [[], []]);
});

test("resizing moves only the dragged edge", () => {
  eq(g.resizeBox(BOX, "e", 9.8, 50, LABEL, NEAR), { l: 10, t: 5, r: 30, b: 9, gx: [30], gy: [] });
  eq(g.resizeBox(BOX, "e", 3.3, 0, LABEL, NEAR), { l: 10, t: 5, r: 23.5, b: 9, gx: [], gy: [] });
  eq(g.resizeBox(BOX, "se", 10, 6, LABEL, NEAR), { l: 10, t: 5, r: 30, b: 15, gx: [30], gy: [15] });
  near(g.resizeBox(BOX, "e", 3.3, 0, LABEL, 0).r, 23.3);
});

test("a box can't be resized to nothing", () => {
  eq(g.resizeBox(BOX, "e", -50, 0, LABEL, NEAR).r, 11);    // 1 mm wide
  eq(g.resizeBox(BOX, "w", 50, 0, LABEL, NEAR).l, 19);
  eq(g.resizeBox(BOX, "n", 0, 100, LABEL, NEAR).t, 8.5);   // 0.5 mm tall
  eq(g.resizeBox(BOX, "s", 0, -100, LABEL, NEAR).b, 5.5);
});

test("a QR code stays square, held at the opposite corner", () => {
  const QR = { l: 10, t: 10, r: 20, b: 20 };
  eq(g.resizeBox(QR, "se", 5, 2, LABEL, 0, true), { l: 10, t: 10, r: 25, b: 25, gx: [], gy: [] });
  eq(g.resizeBox(QR, "nw", -4, -1, LABEL, 0, true), { l: 6, t: 6, r: 20, b: 20, gx: [], gy: [] });
});

test("a QR code's guides are only those its edges end up on", () => {
  const QR = { l: 10, t: 10, r: 20, b: 20 };
  // The right edge reaches the label's centre line and the bottom follows it down
  eq(g.resizeBox(QR, "se", 10, 5.1, LABEL, NEAR, true), { l: 10, t: 10, r: 30, b: 30, gx: [30], gy: [] });
  // The bottom edge found the line at 15, but the square then grew past it
  eq(g.resizeBox(QR, "se", 2, -5.2, LABEL, NEAR, true), { l: 10, t: 10, r: 22, b: 22, gx: [], gy: [] });
});

test("align within a box", () => {
  const R = { l: 0, t: 0, r: 60, b: 30 }, [left, hcenter, right, gap, top, vcenter, bottom] = g.ALIGN;
  const at = (entry) => { const e = { x: 5, y: 5, w: 10, h: 4 }; g.alignEls([e], entry, R); return [e.x, e.y]; };
  eq(gap, null);
  eq([left, hcenter, right].map(at), [[0, 5], [25, 5], [50, 5]]);
  eq([top, vcenter, bottom].map(at), [[5, 0], [5, 13], [5, 26]]);
});

test("distribute leaves equal gaps and the outermost where they are", () => {
  const a = { x: 0, y: 0, w: 10, h: 2 }, b = { x: 12, y: 3, w: 10, h: 2 }, c = { x: 50, y: 20, w: 10, h: 2 };
  g.distribute([c, a, b], false);
  eq([a.x, b.x, c.x], [0, 25, 50]);
  g.distribute([c, a, b], true);
  eq([a.y, b.y, c.y], [0, 10, 20]);
});

test("distribute needs three", () => {
  const a = { x: 0, w: 10 }, b = { x: 12, w: 10 };
  g.distribute([a, b], false);
  eq([a.x, b.x], [0, 12]);
});

test("nudge", () => {
  const e = { x: 1, y: 1 };
  g.nudge([e], 0.5, -2);
  eq(e, { x: 1.5, y: -1 });
});

test("resizing from the keyboard moves the right and bottom edges", () => {
  const box = { type: "text", x: 2, y: 2, w: 10, h: 4 }, qr = { type: "qr", x: 0, y: 0, w: 10, h: 10 };
  g.resizeBy([box, qr], 0.5, 0);
  eq([box.x, box.y, box.w, box.h], [2, 2, 10.5, 4]);
  eq([qr.w, qr.h], [10.5, 10.5]);   // a QR code stays square
  g.resizeBy([box, qr], 0, -2);
  eq([box.w, box.h], [10.5, 2]);
  eq([qr.w, qr.h], [8.5, 8.5]);
});

test("the keyboard can't resize a box to nothing either", () => {
  const box = { type: "rect", x: 0, y: 0, w: 1.2, h: 0.6 }, qr = { type: "qr", x: 0, y: 0, w: 2, h: 2 };
  g.resizeBy([box, qr], -2, -2);
  eq([box.w, box.h, qr.w, qr.h], [g.MIN_W, g.MIN_H, g.MIN_W, g.MIN_W]);
});

test("a new label shape scales the layout, and QR codes stay square", () => {
  const text = { type: "text", x: 10, y: 10, w: 20, h: 10 }, qr = { type: "qr", x: 0, y: 0, w: 10, h: 10 };
  g.rescale([text, qr], 2, 1);
  eq(text, { type: "text", x: 20, y: 10, w: 40, h: 10 });
  eq(qr, { type: "qr", x: 5, y: 0, w: 10, h: 10 });   // centred in the space it had
  g.rescale([text], 1, 1);
  eq(text.w, 40);
});
