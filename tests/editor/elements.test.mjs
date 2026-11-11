import { eq, ok, suite, test } from "./harness.mjs";
import * as el from "../../app/static/elements.mjs";

suite("elements");

const LENGTHS = [5, 1000];

test("what isn't a layout is refused", () => {
  eq([null, undefined, "x", 7, []].map((l) => el.tidyLayout(l, LENGTHS)), [null, null, null, null, null]);
});

test("an empty layout gets the defaults", () => {
  eq(el.tidyLayout({}, LENGTHS), { tape: "62red", length_mm: 30, orientation: "portrait", elements: [] });
});

test("a layout's length is held to the limits", () => {
  const len = (v) => el.tidyLayout({ length_mm: v }, LENGTHS).length_mm;
  eq([5000, 1, "40", "abc", null, " "].map(len), [1000, 5, 40, 30, 30, 30]);
});

test("pieces missing from a layout are filled in, and the rest kept", () => {
  const l = el.tidyLayout({ tape: 62, orientation: "sideways", v: 2,
    elements: [{ type: "text", x: "3", w: null }, 7, null, [1], { type: "qr", x: 1, y: 2, w: 3, h: 4, data: "d" }] }, LENGTHS);
  eq(l, { tape: "62red", orientation: "portrait", length_mm: 30, v: 2, elements: [
    { type: "text", x: 3, y: 0, w: 10, h: 10, text: "" },
    { type: "qr", x: 1, y: 2, w: 3, h: 4, data: "d" }] });
});

test("a text element's text is always text", () => {
  eq(el.tidyLayout({ elements: [{ type: "text", text: 42 }] }, LENGTHS).elements[0].text, "42");
});

test("remove", () => {
  eq(el.removeEls(["a", "b", "c", "d"], [3, 1]), ["a", "c"]);
});

test("move one place forward or back, but not off the end", () => {
  const els = ["a", "b", "c"];
  eq(el.moveEl(els, 0, 1), 1);
  eq(els, ["b", "a", "c"]);
  eq([el.moveEl(els, 0, -1), el.moveEl(els, 2, 1)], [-1, -1]);
  eq(els, ["b", "a", "c"]);
});

test("each copy sits just above its original, a little right and down", () => {
  const els = [{ n: "a", x: 1, y: 1, o: { deep: 1 } }, { n: "b", x: 5, y: 5 }, { n: "c", x: 9, y: 9 }];
  eq(el.duplicateEls(els, [2, 0]), new Set([1, 4]));
  eq(els.map((e) => [e.n, e.x, e.y]), [["a", 1, 1], ["a", 3, 3], ["b", 5, 5], ["c", 9, 9], ["c", 11, 11]]);
  ok(els[0].o !== els[1].o, "a copy shares nothing with its original");
});

test("a list of elements is tidied on its own too", () => {
  eq(el.tidyElements([{ type: "rect" }, "junk"]), [{ type: "rect", x: 0, y: 0, w: 10, h: 10 }]);
  eq([el.tidyElements(null), el.tidyElements({ 0: {} })], [[], []]);
});

test("copies are taken in list order and share nothing with the originals", () => {
  const els = [{ n: "a", o: { deep: 1 } }, { n: "b" }, { n: "c" }];
  const clip = el.copyEls(els, [2, 0]);
  eq(clip.map((e) => e.n), ["a", "c"]);
  ok(clip[0].o !== els[0].o);
});

const CANVAS = { w: 60, h: 30 };

test("pasted elements go on top, shifted from where they were copied", () => {
  const els = [{ n: "under", x: 0, y: 0, w: 5, h: 5 }];
  const clip = [{ n: "a", x: 10, y: 4, w: 20, h: 6, color: "red" }, { n: "b", x: 1, y: 1, w: 2, h: 2 }];
  eq(el.pasteEls(els, clip, CANVAS, { shift: 2 }), new Set([1, 2]));
  eq(els.map((e) => [e.n, e.x, e.y]), [["under", 0, 0], ["a", 12, 6], ["b", 3, 3]]);
  eq(els[1].color, "red");
  eq(clip[0].x, 10, "what was copied can be pasted again");
});

test("a paste never lands off the label", () => {
  const els = [];
  el.pasteEls(els, [{ x: 55, y: 28, w: 10, h: 4 }], CANVAS, { shift: 4 });
  eq([els[0].x, els[0].y], [50, 26]);
});

test("an element larger than the label is cut down to it", () => {
  const els = [];
  el.pasteEls(els, [{ type: "text", x: 5, y: 5, w: 80, h: 10 }, { type: "qr", x: 0, y: 0, w: 40, h: 40 }], CANVAS, { shift: 2 });
  eq(els.map((e) => [e.x, e.y, e.w, e.h]), [[0, 7, 60, 10], [2, 0, 30, 30]]);   // the QR code stays square
});

test("red elements pasted onto black-only tape turn black", () => {
  const els = [];
  el.pasteEls(els, [{ x: 0, y: 0, w: 5, h: 5, color: "red" }], CANVAS, { red: false });
  eq(els[0].color, "black");
});
