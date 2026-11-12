import { eq, suite, test } from "./harness.mjs";
import { chipState, tapeWords } from "../../app/static/printerstate.mjs";

suite("printer chip");

const CFG = { printer_host: "192.168.1.50", model: "QL-820NWB" };
const TAPE = { kind: "continuous", width_mm: 62, length_mm: 0, two_colour: true, name: "Continuous length tape" };
// /api/status's answer, as the server gives it
const info = (status, reachable = null) => ({ status, reachable });
const ready = (tape = TAPE) => ({ state: "ready", errors: [], tape, display: "READY" });
const chip = (i) => { const c = chipState(CFG, i); return [c.dot, c.text, c.detail, c.trouble]; };

test("the tape, short", () => {
  eq(tapeWords(TAPE), "62 mm black/red");
  eq(tapeWords({ ...TAPE, two_colour: false }), "62 mm");
  eq(tapeWords({ kind: "die-cut", width_mm: 29, length_mm: 90 }), "29 × 90 mm labels");
  eq(tapeWords({ kind: "other", name: "Laminated tape" }), "Laminated tape");
});

test("no printer set, and before the first answer", () => {
  eq(chipState({ printer_host: "", model: "QL-820NWB" }, null),
    { dot: "", text: "No printer set", detail: "", trouble: false, title: "" });
  eq(chip(null), ["hollow", "Checking the printer…", "", false]);
});

test("ready, with the tape", () => {
  eq(chip(info(ready())), ["ok", "Ready", "62 mm black/red", false]);
  eq(chip(info(ready({ kind: "die-cut", width_mm: 29, length_mm: 90 }))), ["ok", "Ready", "29 × 90 mm labels", false]);
});

test("printing", () => {
  eq(chip(info({ ...ready(), state: "printing" })), ["ok", "Printing", "", false]);
});

test("trouble is red, in words", () => {
  eq(chip(info({ ...ready(), state: "error", errors: ["Cover open", "The cutter is jammed"] })), ["bad", "Cover open", "", true]);
  eq(chip(info({ ...ready(), state: "error", errors: [] })), ["bad", "Printer error", "", true]);
  eq(chip(info(ready(null))), ["bad", "No tape", "", true]);
});

test("a printer that gives no status", () => {
  eq(chip(info(null, true)), ["ok", "Connected", "no status", false]);
  eq(chip(info(null, false)), ["bad", "Not answering", "", true]);
});

test("the tooltip names the printer, and what its display says", () => {
  eq(chipState(CFG, info(ready())).title, "QL-820NWB at 192.168.1.50 · display: READY");
  eq(chipState(CFG, info(null, true)).title, "QL-820NWB at 192.168.1.50");
});
