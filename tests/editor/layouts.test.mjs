import { eq, ok, suite, test } from "./harness.mjs";
import * as L from "../../app/static/layouts.mjs";
import { setUnits } from "../../app/static/units.mjs";

suite("layouts");

// Every printable size among the tapes the server offers for the QL-820NWB,
// in dots at 300 dpi; a length of 0 is continuous tape
const TAPES = [[696, 0], [106, 0], [234, 0], [306, 0], [413, 0], [554, 0], [590, 0],
  [94, 94], [165, 566], [165, 956], [202, 202], [236, 236], [306, 425], [306, 991], [413, 991],
  [425, 495], [578, 271], [598, 271], [618, 618], [672, 954], [696, 271], [696, 1109]];
const DPMM = 300 / 25.4;

// Each tape's printable area in mm, across and along the tape; continuous
// tape at several lengths
const SIZES = TAPES.flatMap(([w, len]) => (len ? [len / DPMM] : [12, 30, 62, 100, 300])
  .flatMap((h) => [[w / DPMM, h], [h, w / DPMM]]));

// Why a layout isn't offered at a size, as the editor works it out ("" = it is)
const refusal = (p, W, H) => p.fits ? p.fits(W, H, true) : L.checkEls(p.make(W, H));

test("every layout has a name of its own and a category in the panel", () => {
  const names = L.PRESETS.map((p) => p.name), cats = L.CATS.map(([id]) => id);
  eq(new Set(names).size, names.length);
  ok(L.PRESETS.every((p) => cats.includes(p.cat)));
  ok(cats.every((id) => L.PRESETS.some((p) => p.cat === id)), "no category is empty");
  ok(names.includes("Red header"), "the layout a first run opens with");
});

test("every layout offered at a size fits that label", () => {
  // On each tape, across and along: nothing off the label, nothing with no
  // size, and no code or text too small to use
  let offered = 0;
  for (const [W, H] of SIZES) for (const p of L.PRESETS) {
    if (refusal(p, W, H)) continue;
    offered++;
    const at = `${p.name} at ${W.toFixed(1)} × ${H.toFixed(1)} mm`;
    const els = L.roundAll(p.make(W, H));
    ok(els.length > 0, at);
    for (const e of els) {
      ok([e.x, e.y, e.w, e.h].every(Number.isFinite), `${at}: a ${e.type} without a size`);
      ok(e.w > 0 && e.h > 0, `${at}: a ${e.type} of ${e.w} × ${e.h}`);
      ok(e.x >= -0.011 && e.y >= -0.011 && e.x + e.w <= W + 0.011 && e.y + e.h <= H + 0.011,
        `${at}: a ${e.type} off the label at ${e.x}, ${e.y}, ${e.w} × ${e.h}`);
    }
    eq(L.checkEls(els), "", at);
  }
  ok(offered > 1000, `only ${offered} offered`);
});

test("a layout that isn't offered says why", () => {
  for (const [W, H] of SIZES) for (const p of L.PRESETS) {
    const why = refusal(p, W, H);
    ok(why === "" || /^(Needs|Too small)/.test(why), `${p.name}: ${why}`);
  }
});

test("every layout is offered on some tape, and the plain ones on all", () => {
  for (const p of L.PRESETS) ok(SIZES.some(([W, H]) => !refusal(p, W, H)), p.name);
  const single = L.PRESETS.find((p) => p.name === "Single line");
  ok(SIZES.every(([W, H]) => !refusal(single, W, H)));
});

test("sale tags need black and red tape", () => {
  const sale = L.PRESETS.filter((p) => p.name.startsWith("Sale tag"));
  eq(sale.length, 2);
  for (const p of sale) {
    eq(p.fits(58.9, 30, false), "Needs black and red tape (DK-2251)");
    eq(p.fits(58.9, 30, true), "");
    ok(p.make(58.9, 30).some((e) => e.color === "red"));
  }
});

test("a size given in a reason follows the units", () => {
  const flag = L.PRESETS.find((p) => p.name === "Cable flag");
  eq(flag.fits(30, 20), "Needs a label at least 45 mm long");
  setUnits("in");
  try { eq(flag.fits(30, 20), "Needs a label at least 1.77 in long"); } finally { setUnits("mm"); }
});

test("label shapes: thin strips, tall labels and the rest", () => {
  eq([L.shapeOf(84, 30), L.shapeOf(83, 30)], ["thin", "normal"]);
  eq([L.shapeOf(30, 42), L.shapeOf(30, 41)], ["tall", "normal"]);
});

test("the margin follows the label's short side", () => {
  eq([L.marginFor(58.9, 30), L.marginFor(12, 12), L.marginFor(9, 100)], [2, 1, 0.5]);
});

test("a new element fits the label it's added to", () => {
  const c = { w: 58.9, h: 30 }, box = (type) => { const e = L.newElement(type, c); return [e.x, e.y, e.w, e.h]; };
  eq(box("text"), [2, 2, 54.9, 12]);
  eq(box("qr"), [2, 2, 26, 26]);
  eq(box("barcode"), [2, 2, 50, 12]);
  eq(box("image"), [2, 2, 20, 20]);
  eq(box("rect"), [2, 2, 54.9, 1]);
  eq(L.newElement("text", c).text, "Text");
  eq(L.newElement("hologram", c), undefined);
});

test("a new element on a small label is smaller", () => {
  const e = L.newElement("qr", { w: 8, h: 8 });
  eq([e.w, e.h], [4, 4]);
});

test("positions are stored to a hundredth of a millimetre", () => {
  eq(L.roundAll([{ type: "text", x: 1.234, y: 5.678, w: 58.928, h: 0.3 }]), [{ type: "text", x: 1.23, y: 5.68, w: 58.93, h: 0.3 }]);
});

test("codes and text too small to use are named", () => {
  eq(L.checkEls([{ type: "qr", w: 6.9, h: 6.9 }]), "Too small for a scannable QR code");
  eq(L.checkEls([{ type: "barcode", w: 19, h: 10 }]), "Needs a longer label for a barcode");
  eq(L.checkEls([{ type: "barcode", w: 30, h: 4 }]), "Needs a taller label for a barcode");
  eq(L.checkEls([{ type: "text", w: 4, h: 5 }]), "Needs a larger label");
  eq(L.checkEls([{ type: "qr", w: 7, h: 7 }, { type: "barcode", w: 20, h: 5 }, { type: "text", w: 5, h: 2 }, { type: "rect", w: 0.3, h: 0.3 }]), "");
});

test("an element's image settings, with defaults for those it lacks", () => {
  eq(L.imageOf({ type: "image", x: 1, src: "data:,x", name: "logo.png", mode: "dither" }),
    { src: "data:,x", name: "logo.png", url: "", mode: "dither", threshold: 50, invert: false });
});
