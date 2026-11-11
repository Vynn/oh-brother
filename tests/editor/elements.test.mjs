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
